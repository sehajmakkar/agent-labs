"""The trace store: runs, spans and recordings in SQLite (decisions.md D-003, D-006).

- A **run** is one execution of an agent on one input.
- A **span** is one timed piece of work inside a run. `parent_span_id` makes the spans a tree, and
  `seq` keeps their start order (spans are saved when they *end*, so children land before parents).
- A **recording** is the exact request and response of one model or tool call. Phase 3 replays
  runs from these, matching calls by `request_hash`.

The fork columns on runs (`parent_run_id`, `fork_span_id`, `fork_override`) stay empty until
Phase 4. They exist now because SQLite has no migrations here yet.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, Session, SQLModel, create_engine, select


class RunRow(SQLModel, table=True):
    __tablename__ = "runs"

    id: str = Field(primary_key=True)
    agent_name: str
    model: str | None = None
    task_id: str | None = None
    status: str = "running"  # running | completed | max_steps | timeout | error
    input: Any = Field(default=None, sa_column=Column(JSON))
    output: Any = Field(default=None, sa_column=Column(JSON))
    error: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    parent_run_id: str | None = Field(default=None, index=True)
    fork_span_id: str | None = None
    fork_override: Any = Field(default=None, sa_column=Column(JSON))


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
    kind: str  # llm | tool
    request_hash: str = Field(index=True)
    request: Any = Field(default=None, sa_column=Column(JSON))
    response: Any = Field(default=None, sa_column=Column(JSON))


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}")
        SQLModel.metadata.create_all(self.engine)

    def create_run(
        self, *, agent_name: str, input: Any, model: str | None, task_id: str | None
    ) -> str:
        run = RunRow(
            id=uuid.uuid4().hex,
            agent_name=agent_name,
            model=model,
            task_id=task_id,
            input=input,
            started_at=datetime.now(UTC),
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

    def save_span(self, span: SpanRow, recordings: list[RecordingRow]) -> None:
        with Session(self.engine) as session:
            session.add(span)
            session.add_all(recordings)
            session.commit()

    def runs(self, limit: int = 20) -> list[RunRow]:
        with Session(self.engine) as session:
            query = select(RunRow).order_by(RunRow.started_at.desc()).limit(limit)
            return list(session.exec(query))

    def find_run(self, id_prefix: str) -> RunRow:
        """Look a run up by the start of its ID, as printed by `lab runs`."""
        with Session(self.engine) as session:
            matches = list(session.exec(select(RunRow).where(RunRow.id.startswith(id_prefix))))
        if len(matches) != 1:
            problem = "No run" if not matches else f"{len(matches)} runs"
            raise LookupError(f"{problem} with an ID starting {id_prefix!r}")
        return matches[0]

    def spans(self, run_id: str) -> list[SpanRow]:
        with Session(self.engine) as session:
            query = select(SpanRow).where(SpanRow.run_id == run_id).order_by(SpanRow.seq)
            return list(session.exec(query))

    def recordings(self, span_id: str) -> list[RecordingRow]:
        with Session(self.engine) as session:
            return list(session.exec(select(RecordingRow).where(RecordingRow.span_id == span_id)))
