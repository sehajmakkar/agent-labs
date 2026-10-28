"""The trace store: runs, spans, recordings and eval results in SQLite (decisions.md D-003, D-006).

- A **run** is one execution of an agent on one input.
- A **span** is one timed piece of work inside a run. `parent_span_id` makes the spans a tree, and
  `seq` keeps their start order (spans are saved when they *end*, so children land before parents).
- A **recording** is the exact request and response of one model or tool call. Phase 3 replays
  runs from these, matching calls by `request_hash`.
- An **eval run** is one pass of a dataset through an agent; each task in it gets an **eval
  result** pointing to the run it produced.
- A **replay** is a run re-executed from another run's recordings (`mode="replay"`,
  `parent_run_id` = the source). Its `replay_report` says whether it reproduced the source exactly.
- A **fork** is a job: "rerun this run from that span, with this change, N times". It is queued
  here, claimed by a worker, and produces N fork runs (and N control runs without the change),
  each with `mode="fork"` and `fork_id` pointing back to it.

`fork_span_id` and `fork_override` stay empty until Phase 4.

Schema changes that only *add* nullable columns are applied to an existing database on startup
(`_add_missing_columns`). Anything bigger still means deleting `.agentlab/lab.db` (D-020, D-031).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column, event, func, update
from sqlmodel import Field, Session, SQLModel, create_engine, select

from agentlab.semconv import RATE_LIMIT_WAIT_S


class RunRow(SQLModel, table=True):
    __tablename__ = "runs"

    id: str = Field(primary_key=True)
    agent_name: str
    model: str | None = None
    task_id: str | None = Field(default=None, index=True)
    status: str = "running"  # running | completed | max_steps | timeout | error
    input: Any = Field(default=None, sa_column=Column(JSON))
    output: Any = Field(default=None, sa_column=Column(JSON))
    error: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    mode: str | None = None  # record (or None, for runs before Phase 3) | replay | fork
    parent_run_id: str | None = Field(default=None, index=True)
    fork_id: str | None = Field(default=None, index=True)  # the fork job this run belongs to
    fork_span_id: str | None = None
    fork_override: Any = Field(default=None, sa_column=Column(JSON))
    replay_report: Any = Field(default=None, sa_column=Column(JSON))


class SpanRow(SQLModel, table=True):
    __tablename__ = "spans"

    id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    parent_span_id: str | None = None
    seq: int
    kind: str  # agent | step | llm | tool
    name: str
    status: str  # ok | error
    started_at: datetime
    duration_ms: float
    input: Any = Field(default=None, sa_column=Column(JSON))
    output: Any = Field(default=None, sa_column=Column(JSON))
    error: str | None = None
    attributes: dict = Field(default_factory=dict, sa_column=Column(JSON))
    input_tokens: int = 0
    output_tokens: int = 0  # excludes thinking tokens, which are counted separately
    thinking_tokens: int = 0
    cost_usd: float | None = None


class RecordingRow(SQLModel, table=True):
    __tablename__ = "recordings"

    id: int | None = Field(default=None, primary_key=True)
    span_id: str = Field(index=True)
    # The order of the call within its run, shared with span `seq`. None for runs before Phase 3.
    seq: int | None = None
    kind: str  # llm | tool | clock | random
    request_hash: str = Field(index=True)
    request: Any = Field(default=None, sa_column=Column(JSON))
    response: Any = Field(default=None, sa_column=Column(JSON))


class EvalRunRow(SQLModel, table=True):
    __tablename__ = "eval_runs"

    id: str = Field(primary_key=True)
    datasets: list = Field(default_factory=list, sa_column=Column(JSON))
    model: str
    judge_model: str | None = None  # None when the LLM judge was switched off
    status: str = "running"  # running | done
    task_count: int = 0
    started_at: datetime
    ended_at: datetime | None = None
    metrics: Any = Field(default=None, sa_column=Column(JSON))


class EvalResultRow(SQLModel, table=True):
    __tablename__ = "eval_results"

    id: int | None = Field(default=None, primary_key=True)
    eval_run_id: str = Field(index=True)
    task_id: str
    run_id: str = Field(index=True)
    passed: bool
    failure_category: str | None = None
    checks: list = Field(default_factory=list, sa_column=Column(JSON))
    judge_cost_usd: float | None = None


class ForkRow(SQLModel, table=True):
    __tablename__ = "forks"

    id: str = Field(primary_key=True)
    source_run_id: str = Field(index=True)
    span_id: str  # where the fork starts: a step or a tool call of the source run
    label: str = ""  # e.g. "step 3" or "get_alert in step 1", for display
    override: Any = Field(default=None, sa_column=Column(JSON))
    n: int = 5
    control: bool = True  # also run N times with no change, to compare against
    status: str = "queued"  # queued | running | done | error
    worker: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: Any = Field(default=None, sa_column=Column(JSON))
    error: str | None = None


class BlameRow(SQLModel, table=True):
    """A blame job: find and verify the step that made a failed run fail."""

    __tablename__ = "blames"

    id: str = Field(primary_key=True)
    source_run_id: str = Field(index=True)
    judge_model: str
    n: int = 5  # runs per verification fork (and per control)
    max_candidates: int = 2  # how many of the judge's candidates to verify, at most
    status: str = "queued"  # queued | running | done | error
    worker: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report: Any = Field(default=None, sa_column=Column(JSON))
    error: str | None = None


class BenchmarkRow(SQLModel, table=True):
    """Results of a benchmark, such as blame accuracy on seeded failures."""

    __tablename__ = "benchmarks"

    id: str = Field(primary_key=True)
    kind: str = Field(index=True)  # blame
    created_at: datetime
    results: Any = Field(default=None, sa_column=Column(JSON))


@dataclass
class RunTotals:
    """Per-run sums over its model calls."""

    tokens: int = 0
    cost_usd: float | None = None
    wait_s: float = 0.0  # time spent waiting for the client-side rate limiter


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # The eval runner writes from several threads, and the UI reads while it does.
        self.engine = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30}
        )
        event.listen(self.engine, "connect", _use_wal)
        SQLModel.metadata.create_all(self.engine)
        _add_missing_columns(self.engine)

    # Runs and spans

    def create_run(
        self,
        *,
        agent_name: str,
        input: Any,
        model: str | None,
        task_id: str | None,
        run_id: str | None = None,
        mode: str = "record",
        parent_run_id: str | None = None,
        fork_id: str | None = None,
        fork_span_id: str | None = None,
        fork_override: Any = None,
    ) -> str:
        run = RunRow(
            id=run_id or uuid.uuid4().hex,
            agent_name=agent_name,
            model=model,
            task_id=task_id,
            input=input,
            started_at=datetime.now(UTC),
            mode=mode,
            parent_run_id=parent_run_id,
            fork_id=fork_id,
            fork_span_id=fork_span_id,
            fork_override=fork_override,
        )
        with Session(self.engine) as session:
            session.add(run)
            session.commit()
            return run.id

    def finish_run(self, run_id: str, *, status: str, output: Any, error: str | None) -> None:
        with Session(self.engine) as session:
            run = session.get(RunRow, run_id)
            run.status, run.output, run.error = status, output, error
            run.ended_at = datetime.now(UTC)
            session.add(run)
            session.commit()

    def set_replay_report(self, run_id: str, report: Any) -> None:
        with Session(self.engine) as session:
            run = session.get(RunRow, run_id)
            run.replay_report = report
            session.add(run)
            session.commit()

    def save_span(self, span: SpanRow, recordings: list[RecordingRow]) -> None:
        with Session(self.engine) as session:
            session.add(span)
            session.add_all(recordings)
            session.commit()

    def runs(
        self,
        limit: int = 20,
        *,
        status: str | None = None,
        agent_name: str | None = None,
        task_id: str | None = None,
    ) -> list[RunRow]:
        with Session(self.engine) as session:
            query = select(RunRow)
            if status:
                query = query.where(RunRow.status == status)
            if agent_name:
                query = query.where(RunRow.agent_name == agent_name)
            if task_id:
                query = query.where(RunRow.task_id == task_id)
            query = query.order_by(RunRow.started_at.desc()).limit(limit)
            return list(session.exec(query))

    def get_run(self, run_id: str) -> RunRow | None:
        with Session(self.engine) as session:
            return session.get(RunRow, run_id)

    def find_run(self, id_prefix: str) -> RunRow:
        """Look a run up by the start of its ID, as printed by `lab runs`."""
        return _find_by_prefix(self.engine, RunRow, id_prefix, "run")

    def spans(self, run_id: str) -> list[SpanRow]:
        with Session(self.engine) as session:
            query = select(SpanRow).where(SpanRow.run_id == run_id).order_by(SpanRow.seq)
            return list(session.exec(query))

    def get_span(self, span_id: str) -> SpanRow | None:
        with Session(self.engine) as session:
            return session.get(SpanRow, span_id)

    def recordings(self, span_id: str) -> list[RecordingRow]:
        with Session(self.engine) as session:
            return list(session.exec(select(RecordingRow).where(RecordingRow.span_id == span_id)))

    def run_recordings(self, run_id: str) -> list[RecordingRow]:
        """Every recording of a run, in the order the calls were made."""
        query = (
            select(RecordingRow)
            .join(SpanRow, SpanRow.id == RecordingRow.span_id)
            .where(SpanRow.run_id == run_id)
            # Runs before Phase 3 have no recording seq; their span's start order is the next best.
            .order_by(RecordingRow.seq, SpanRow.seq, RecordingRow.id)
        )
        with Session(self.engine) as session:
            return list(session.exec(query))

    def replays_of(self, run_id: str) -> list[RunRow]:
        with Session(self.engine) as session:
            query = (
                select(RunRow)
                .where(RunRow.parent_run_id == run_id, RunRow.mode == "replay")
                .order_by(RunRow.started_at.desc())
            )
            return list(session.exec(query))

    def run_totals(self, run_ids: list[str]) -> dict[str, RunTotals]:
        """Tokens and cost of each run's model calls, in one query."""
        tokens = SpanRow.input_tokens + SpanRow.output_tokens + SpanRow.thinking_tokens
        query = (
            select(SpanRow.run_id, func.sum(tokens), func.sum(SpanRow.cost_usd))
            .where(SpanRow.kind == "llm", SpanRow.run_id.in_(run_ids))
            .group_by(SpanRow.run_id)
        )
        with Session(self.engine) as session:
            rows = session.exec(query).all()
        roots = select(SpanRow.run_id, SpanRow.attributes).where(
            SpanRow.kind == "agent", SpanRow.parent_span_id.is_(None), SpanRow.run_id.in_(run_ids)
        )
        with Session(self.engine) as session:
            waits = {
                run_id: (attrs or {}).get(RATE_LIMIT_WAIT_S, 0)
                for run_id, attrs in session.exec(roots)
            }
        totals = {run_id: RunTotals(wait_s=waits.get(run_id, 0)) for run_id in run_ids}
        for run_id, token_sum, cost_sum in rows:
            totals[run_id].tokens, totals[run_id].cost_usd = token_sum or 0, cost_sum
        return totals

    # Evals

    def create_eval_run(
        self, *, datasets: list[str], model: str, judge_model: str | None, task_count: int
    ) -> str:
        row = EvalRunRow(
            id=uuid.uuid4().hex,
            datasets=datasets,
            model=model,
            judge_model=judge_model,
            task_count=task_count,
            started_at=datetime.now(UTC),
        )
        with Session(self.engine) as session:
            session.add(row)
            session.commit()
            return row.id

    def finish_eval_run(self, eval_run_id: str, *, metrics: Any) -> None:
        with Session(self.engine) as session:
            row = session.get(EvalRunRow, eval_run_id)
            row.status, row.metrics, row.ended_at = "done", metrics, datetime.now(UTC)
            session.add(row)
            session.commit()

    def save_eval_result(self, result: EvalResultRow) -> None:
        with Session(self.engine) as session:
            session.add(result)
            session.commit()

    def eval_runs(self, limit: int = 20) -> list[EvalRunRow]:
        with Session(self.engine) as session:
            query = select(EvalRunRow).order_by(EvalRunRow.started_at.desc()).limit(limit)
            return list(session.exec(query))

    def find_eval_run(self, id_prefix: str) -> EvalRunRow:
        return _find_by_prefix(self.engine, EvalRunRow, id_prefix, "eval run")

    def eval_results(self, eval_run_id: str) -> list[EvalResultRow]:
        with Session(self.engine) as session:
            query = (
                select(EvalResultRow)
                .where(EvalResultRow.eval_run_id == eval_run_id)
                .order_by(EvalResultRow.id)
            )
            return list(session.exec(query))

    # Forks (the job queue)

    def create_fork(
        self,
        *,
        source_run_id: str,
        span_id: str,
        label: str,
        override: Any,
        n: int,
        control: bool,
        status: str = "queued",
        worker: str | None = None,
    ) -> str:
        """Queue a fork job. Pass status="running" to run it yourself (`lab fork`) instead."""
        now = datetime.now(UTC)
        row = ForkRow(
            id=uuid.uuid4().hex,
            source_run_id=source_run_id,
            span_id=span_id,
            label=label,
            override=override,
            n=n,
            control=control,
            status=status,
            worker=worker,
            created_at=now,
            started_at=now if status == "running" else None,
        )
        with Session(self.engine) as session:
            session.add(row)
            session.commit()
            return row.id

    def get_fork(self, fork_id: str) -> ForkRow | None:
        with Session(self.engine) as session:
            return session.get(ForkRow, fork_id)

    def find_fork(self, id_prefix: str) -> ForkRow:
        return _find_by_prefix(self.engine, ForkRow, id_prefix, "fork")

    def forks_of(self, run_id: str) -> list[ForkRow]:
        with Session(self.engine) as session:
            query = (
                select(ForkRow)
                .where(ForkRow.source_run_id == run_id)
                .order_by(ForkRow.created_at.desc())
            )
            return list(session.exec(query))

    def fork_runs(self, fork_id: str) -> list[RunRow]:
        with Session(self.engine) as session:
            query = select(RunRow).where(RunRow.fork_id == fork_id).order_by(RunRow.started_at)
            return list(session.exec(query))

    def claim_fork(self, agent_names: list[str], worker: str) -> ForkRow | None:
        """Take the oldest queued fork whose agent this worker can run, or None."""
        return self._claim(ForkRow, agent_names, worker)

    def _claim(self, table: Any, agent_names: list[str], worker: str) -> Any:
        """Claim the oldest queued job in `table` (forks or blames) for an agent we can run.

        Two workers may poll at once, so the claim is a compare-and-set: the UPDATE only succeeds
        while the row is still "queued", and whoever changes it first owns the job.
        """
        with Session(self.engine) as session:
            candidates = session.exec(
                select(table.id)
                .join(RunRow, RunRow.id == table.source_run_id)
                .where(table.status == "queued", RunRow.agent_name.in_(agent_names))
                .order_by(table.created_at)
            ).all()
            for job_id in candidates:
                claimed = session.execute(
                    update(table)
                    .where(table.id == job_id, table.status == "queued")
                    .values(status="running", worker=worker, started_at=datetime.now(UTC))
                )
                session.commit()
                if claimed.rowcount == 1:
                    return session.get(table, job_id)
        return None

    # Blames

    def create_blame(
        self,
        *,
        source_run_id: str,
        judge_model: str,
        n: int,
        max_candidates: int,
        status: str = "queued",
        worker: str | None = None,
    ) -> str:
        now = datetime.now(UTC)
        row = BlameRow(
            id=uuid.uuid4().hex,
            source_run_id=source_run_id,
            judge_model=judge_model,
            n=n,
            max_candidates=max_candidates,
            status=status,
            worker=worker,
            created_at=now,
            started_at=now if status == "running" else None,
        )
        with Session(self.engine) as session:
            session.add(row)
            session.commit()
            return row.id

    def claim_blame(self, agent_names: list[str], worker: str) -> BlameRow | None:
        return self._claim(BlameRow, agent_names, worker)

    def get_blame(self, blame_id: str) -> BlameRow | None:
        with Session(self.engine) as session:
            return session.get(BlameRow, blame_id)

    def find_blame(self, id_prefix: str) -> BlameRow:
        return _find_by_prefix(self.engine, BlameRow, id_prefix, "blame")

    def blames_of(self, run_id: str) -> list[BlameRow]:
        with Session(self.engine) as session:
            query = (
                select(BlameRow)
                .where(BlameRow.source_run_id == run_id)
                .order_by(BlameRow.created_at.desc())
            )
            return list(session.exec(query))

    def update_blame(self, blame_id: str, *, report: Any) -> None:
        """Save a partial report while the blame is still running, so the UI can show progress."""
        with Session(self.engine) as session:
            row = session.get(BlameRow, blame_id)
            row.report = report
            session.add(row)
            session.commit()

    def finish_blame(self, blame_id: str, *, report: Any = None, error: str | None = None) -> None:
        with Session(self.engine) as session:
            row = session.get(BlameRow, blame_id)
            row.status = "error" if error else "done"
            row.report = report if report is not None else row.report
            row.error, row.finished_at = error, datetime.now(UTC)
            session.add(row)
            session.commit()

    # Benchmarks

    def save_benchmark(self, kind: str, results: Any) -> str:
        row = BenchmarkRow(
            id=uuid.uuid4().hex, kind=kind, created_at=datetime.now(UTC), results=results
        )
        with Session(self.engine) as session:
            session.add(row)
            session.commit()
            return row.id

    def benchmarks(self, kind: str, limit: int = 10) -> list[BenchmarkRow]:
        with Session(self.engine) as session:
            query = (
                select(BenchmarkRow)
                .where(BenchmarkRow.kind == kind)
                .order_by(BenchmarkRow.created_at.desc())
                .limit(limit)
            )
            return list(session.exec(query))

    def latest_benchmark(self, kind: str) -> BenchmarkRow | None:
        with Session(self.engine) as session:
            query = (
                select(BenchmarkRow)
                .where(BenchmarkRow.kind == kind)
                .order_by(BenchmarkRow.created_at.desc())
                .limit(1)
            )
            return session.exec(query).first()

    def finish_fork(self, fork_id: str, *, summary: Any = None, error: str | None = None) -> None:
        with Session(self.engine) as session:
            row = session.get(ForkRow, fork_id)
            row.status = "error" if error else "done"
            row.summary, row.error, row.finished_at = summary, error, datetime.now(UTC)
            session.add(row)
            session.commit()

    def eval_results_for_runs(self, run_ids: list[str]) -> dict[str, EvalResultRow]:
        """The eval result of each run that was scored, keyed by run ID."""
        with Session(self.engine) as session:
            query = select(EvalResultRow).where(EvalResultRow.run_id.in_(run_ids))
            return {r.run_id: r for r in session.exec(query)}


def run_message(run: RunRow) -> str:
    """The user's message for a run. Our loop records it as {"message": ...}; `@lab.agent` records
    the entry point's arguments, so fall back to the first text argument."""
    value = run.input
    if isinstance(value, dict):
        if "message" in value:
            return str(value["message"])
        value = next((v for v in value.values() if isinstance(v, str)), "")
    return value if isinstance(value, str) else ""


def run_answer(run: RunRow) -> str | None:
    """The final answer: {"answer": ...} from our loop, or whatever `@lab.agent` returned."""
    if isinstance(run.output, dict):
        return run.output.get("answer")
    return None if run.output is None else str(run.output)


def _add_missing_columns(engine: Any) -> None:
    """Add columns that the models define but an older database lacks.

    This is the smallest useful migration: it only ever adds nullable columns, so existing rows
    stay valid. Renames, type changes or removals still need a fresh database.
    """
    with engine.begin() as connection:
        for table in SQLModel.metadata.sorted_tables:
            existing = {
                row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table.name})")
            }
            for column in table.columns:
                if column.name not in existing:
                    kind = column.type.compile(dialect=engine.dialect)
                    connection.exec_driver_sql(
                        f"ALTER TABLE {table.name} ADD COLUMN {column.name} {kind}"
                    )


def _use_wal(connection: Any, _record: Any) -> None:
    # Write-ahead logging lets readers (the UI) see the database while a writer is busy.
    connection.execute("PRAGMA journal_mode=WAL")


def _find_by_prefix(engine: Any, table: Any, id_prefix: str, label: str) -> Any:
    with Session(engine) as session:
        matches = list(session.exec(select(table).where(table.id.startswith(id_prefix))))
    if len(matches) != 1:
        problem = f"No {label}" if not matches else f"{len(matches)} {label}s"
        raise LookupError(f"{problem} with an ID starting {id_prefix!r}")
    return matches[0]
