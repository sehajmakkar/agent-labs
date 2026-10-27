"""The lab's HTTP API, read by the web UI (`lab ui`).

A thin layer over the trace store. Most endpoints read. The writes:
- `POST /api/runs/{id}/replay`: safe, because a replay calls nothing outside the process;
- `POST /api/forks`: only *queues* a fork job. A worker running the agent's own code executes it
  (`fork/worker.py`), never this server;
- `POST /api/store/{method}`: the narrow RPC that `RemoteStore` uses, so workers and SDKs elsewhere
  can send runs here. Guarded by `AGENTLAB_TOKEN` when that is set.

Response models are pydantic classes, so FastAPI validates what we send and documents every
endpoint at /docs (OpenAPI) for free.

The built UI (`ui/dist`, from `npm run build`) is served at `/` when it exists. During UI
development, Vite serves the UI instead and forwards `/api` requests here.
"""

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agentlab.evals.categories import DESCRIPTIONS
from agentlab.fork.point import resolve_fork_point
from agentlab.replay.session import Override
from agentlab.store import (
    EvalResultRow,
    EvalRunRow,
    ForkRow,
    RecordingRow,
    RunRow,
    RunTotals,
    SpanRow,
    Store,
    run_answer,
    run_message,
)

UI_DIST = Path(__file__).resolve().parents[2] / "ui" / "dist"


class EvalSummary(BaseModel):
    eval_run_id: str
    task_id: str
    passed: bool
    failure_category: str | None
    checks: list[dict[str, Any]]


class RunSummary(BaseModel):
    id: str
    agent_name: str
    model: str | None
    status: str
    task_id: str | None
    started_at: datetime
    duration_s: float | None
    rate_limit_wait_s: float  # part of duration_s spent waiting for our rate limiter
    message: str
    answer: str | None
    error: str | None
    tokens: int
    cost_usd: float | None
    parent_run_id: str | None
    mode: str  # record | replay | fork
    fork_id: str | None
    fork_override: dict[str, Any] | None  # None on a control run
    replay_report: dict[str, Any] | None
    eval: EvalSummary | None


class Span(BaseModel):
    id: str
    parent_span_id: str | None
    seq: int
    kind: str
    name: str
    status: str
    started_at: datetime
    duration_ms: float
    input: Any
    output: Any
    error: str | None
    attributes: dict[str, Any]
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    cost_usd: float | None


class ForkInfo(BaseModel):
    id: str
    source_run_id: str
    span_id: str
    label: str
    override: dict[str, Any] | None
    n: int
    control: bool
    status: str
    worker: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    summary: dict[str, Any] | None
    error: str | None


class RunDetail(BaseModel):
    run: RunSummary
    spans: list[Span]
    replays: list[RunSummary]  # replays of this run, newest first
    forks: list[ForkInfo]  # fork jobs started from this run, newest first


class ForkRequest(BaseModel):
    run_id: str
    span_id: str
    override: Override = Override()
    n: int = 5
    control: bool = True


class ForkDetail(BaseModel):
    fork: ForkInfo
    source: RunSummary
    runs: list[RunSummary]


class FamilyNode(BaseModel):
    """A run, its replays, and the fork jobs started from it (each with its runs)."""

    run: RunSummary
    replays: list[RunSummary]
    forks: list["FamilyFork"]


class FamilyFork(BaseModel):
    fork: ForkInfo
    runs: list[FamilyNode]


FamilyNode.model_rebuild()  # resolve the "FamilyFork" forward reference


class ReplayResponse(BaseModel):
    run_id: str
    identical: bool
    summary: str
    differences: list[str]


class Recording(BaseModel):
    kind: str
    request_hash: str
    request: Any
    response: Any


class EvalRun(BaseModel):
    id: str
    datasets: list[str]
    model: str
    judge_model: str | None
    status: str
    task_count: int
    started_at: datetime
    ended_at: datetime | None
    metrics: dict[str, Any] | None


class EvalDetail(BaseModel):
    eval: EvalRun
    runs: list[RunSummary]


def create_app(store: Store, ui_dist: Path | None = UI_DIST) -> FastAPI:
    app = FastAPI(title="Agent Reliability Lab", version="0.0.1")

    @app.get("/api/runs", response_model=list[RunSummary])
    def list_runs(
        limit: int = 100,
        status: str | None = None,
        agent: str | None = None,
        task_id: str | None = None,
    ):
        runs = store.runs(limit, status=status, agent_name=agent, task_id=task_id)
        return _summaries(store, runs)

    @app.get("/api/diff")
    def diff(a: str, b: str) -> dict[str, Any]:
        """Two runs aligned step by step: rows, the first divergence and downstream effects."""
        from agentlab.diff import diff_runs

        try:
            run_a, run_b = store.find_run(a), store.find_run(b)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e
        result = diff_runs(store, run_a.id, run_b.id).to_dict()
        (result["a_run"],) = _summaries(store, [run_a])
        (result["b_run"],) = _summaries(store, [run_b])
        return result

    @app.get("/api/runs/{run_id}", response_model=RunDetail)
    def get_run(run_id: str):
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(404, f"No run {run_id}")
        (summary,) = _summaries(store, [run])
        return RunDetail(
            run=summary,
            spans=[_span(s) for s in store.spans(run_id)],
            replays=_summaries(store, store.replays_of(run_id)),
            forks=[_fork(f) for f in store.forks_of(run_id)],
        )

    @app.get("/api/runs/{run_id}/family", response_model=FamilyNode)
    def family(run_id: str):
        """The whole family of a run, from its root: replays, forks and their runs."""
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(404, f"No run {run_id}")
        while run.parent_run_id and (parent := store.get_run(run.parent_run_id)):
            run = parent
        return _family(store, run, depth=0)

    @app.post("/api/forks", response_model=ForkInfo)
    def create_fork(request: ForkRequest):
        if store.get_run(request.run_id) is None:
            raise HTTPException(404, f"No run {request.run_id}")
        if not 1 <= request.n <= 20:
            raise HTTPException(400, "n must be between 1 and 20")
        try:
            point = resolve_fork_point(store, request.run_id, request.span_id)
        except (LookupError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        if request.override.tool_output is not None and point.kind != "tool":
            raise HTTPException(
                400, "A tool output can only be changed when forking at a tool call"
            )
        fork_id = store.create_fork(
            source_run_id=request.run_id,
            span_id=point.span_id,
            label=point.label,
            override=request.override.model_dump(exclude_none=True),
            n=request.n,
            control=request.control,
        )
        return _fork(store.get_fork(fork_id))

    @app.get("/api/forks/{fork_id}", response_model=ForkDetail)
    def get_fork(fork_id: str):
        try:
            fork = store.find_fork(fork_id)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e
        (source,) = _summaries(store, [store.get_run(fork.source_run_id)])
        return ForkDetail(
            fork=_fork(fork), source=source, runs=_summaries(store, store.fork_runs(fork.id))
        )

    @app.get("/api/models")
    def models() -> dict[str, str]:
        from agentlab.config import load_settings

        settings = load_settings()
        return {"flash-lite": settings.flash_lite_model, "flash": settings.flash_model}

    rpc = _rpc_handlers(store)

    @app.post("/api/store/{method}")
    def store_rpc(
        method: str,
        args: Annotated[dict[str, Any], Body()],
        authorization: Annotated[str | None, Header()] = None,
    ) -> Any:
        token = os.environ.get("AGENTLAB_TOKEN")
        if token and authorization != f"Bearer {token}":
            raise HTTPException(401, "Missing or wrong AGENTLAB_TOKEN")
        if method not in rpc:
            raise HTTPException(404, f"No store method {method!r}")
        return rpc[method](args)

    @app.post("/api/runs/{run_id}/replay", response_model=ReplayResponse)
    def replay(run_id: str):
        from agentlab import tracing
        from agentlab.demo import demo_agents
        from agentlab.replay.runner import replay_run

        if store.get_run(run_id) is None:
            raise HTTPException(404, f"No run {run_id}")
        tracing.init(store)  # the replay is recorded as a run in this same store
        try:
            result = replay_run(store, run_id, agents=demo_agents())
        except LookupError as e:  # not a demo agent: replay it from its own code with the CLI
            raise HTTPException(400, str(e)) from e
        return ReplayResponse(
            run_id=result.run_id,
            identical=result.report.identical,
            summary=result.report.summary(),
            differences=result.report.differences,
        )

    @app.get("/api/spans/{span_id}/recordings", response_model=list[Recording])
    def get_recordings(span_id: str):
        if store.get_span(span_id) is None:
            raise HTTPException(404, f"No span {span_id}")
        return [Recording(**r.model_dump()) for r in store.recordings(span_id)]

    @app.get("/api/evals", response_model=list[EvalRun])
    def list_evals(limit: int = 50):
        return [_eval_run(e) for e in store.eval_runs(limit)]

    @app.get("/api/evals/{eval_run_id}", response_model=EvalDetail)
    def get_eval(eval_run_id: str):
        try:
            eval_run = store.find_eval_run(eval_run_id)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e
        results = store.eval_results(eval_run.id)
        runs = [run for r in results if (run := store.get_run(r.run_id))]
        return EvalDetail(eval=_eval_run(eval_run), runs=_summaries(store, runs))

    @app.get("/api/failure-categories")
    def failure_categories() -> dict[str, str]:
        return DESCRIPTIONS

    if ui_dist is not None and (ui_dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=ui_dist, html=True), name="ui")

    return app


def _summaries(store: Store, runs: list[RunRow]) -> list[RunSummary]:
    """Run rows plus their token and cost totals and eval results, with two queries in total."""
    ids = [r.id for r in runs]
    totals = store.run_totals(ids)
    evals = store.eval_results_for_runs(ids)
    return [_summary(run, totals.get(run.id, RunTotals()), evals.get(run.id)) for run in runs]


def _summary(run: RunRow, totals: RunTotals, result: EvalResultRow | None) -> RunSummary:
    return RunSummary(
        id=run.id,
        agent_name=run.agent_name,
        model=run.model,
        status=run.status,
        task_id=run.task_id,
        started_at=_utc(run.started_at),
        duration_s=(run.ended_at - run.started_at).total_seconds() if run.ended_at else None,
        rate_limit_wait_s=totals.wait_s,
        message=run_message(run),
        answer=run_answer(run),
        error=run.error,
        tokens=totals.tokens,
        cost_usd=totals.cost_usd,
        parent_run_id=run.parent_run_id,
        mode=run.mode or "record",
        fork_id=run.fork_id,
        fork_override=run.fork_override,
        replay_report=run.replay_report,
        eval=EvalSummary(
            eval_run_id=result.eval_run_id,
            task_id=result.task_id,
            passed=result.passed,
            failure_category=result.failure_category,
            checks=result.checks,
        )
        if result
        else None,
    )


def _fork(f: ForkRow) -> ForkInfo:
    return ForkInfo(
        **f.model_dump(exclude={"created_at", "started_at", "finished_at"}),
        created_at=_utc(f.created_at),
        started_at=_utc(f.started_at) if f.started_at else None,
        finished_at=_utc(f.finished_at) if f.finished_at else None,
    )


def _family(store: Store, run: RunRow, depth: int) -> FamilyNode:
    forks = store.forks_of(run.id) if depth < 3 else []
    (summary,) = _summaries(store, [run])
    return FamilyNode(
        run=summary,
        replays=_summaries(store, store.replays_of(run.id)),
        forks=[
            FamilyFork(
                fork=_fork(f), runs=[_family(store, r, depth + 1) for r in store.fork_runs(f.id)]
            )
            for f in forks
        ],
    )


def _rpc_handlers(store: Store) -> dict[str, Callable[[dict[str, Any]], Any]]:
    """The store methods a `RemoteStore` may call, with their arguments rebuilt from JSON."""

    def dump(row: Any) -> Any:
        return row.model_dump(mode="json") if row is not None else None

    return {
        "create_run": lambda a: store.create_run(**a),
        "finish_run": lambda a: store.finish_run(
            a["run_id"], status=a["status"], output=a["output"], error=a["error"]
        ),
        "save_span": lambda a: store.save_span(
            SpanRow.model_validate(a["span"]),
            [RecordingRow.model_validate(r) for r in a["recordings"]],
        ),
        "set_replay_report": lambda a: store.set_replay_report(a["run_id"], a["report"]),
        "save_eval_result": lambda a: store.save_eval_result(
            EvalResultRow.model_validate(a["result"])
        ),
        "get_run": lambda a: dump(store.get_run(a["run_id"])),
        "spans": lambda a: [dump(s) for s in store.spans(a["run_id"])],
        "run_recordings": lambda a: [dump(r) for r in store.run_recordings(a["run_id"])],
        "claim_fork": lambda a: dump(store.claim_fork(a["agent_names"], a["worker"])),
        "get_fork": lambda a: dump(store.get_fork(a["fork_id"])),
        "finish_fork": lambda a: store.finish_fork(
            a["fork_id"], summary=a["summary"], error=a["error"]
        ),
    }


def _span(s: SpanRow) -> Span:
    return Span(**s.model_dump(exclude={"run_id", "started_at"}), started_at=_utc(s.started_at))


def _eval_run(e: EvalRunRow) -> EvalRun:
    return EvalRun(
        **e.model_dump(exclude={"started_at", "ended_at"}),
        started_at=_utc(e.started_at),
        ended_at=_utc(e.ended_at) if e.ended_at else None,
    )


def _utc(value: datetime) -> datetime:
    # SQLite drops the timezone (challenges.md C-009); stored times are UTC, so say so in the JSON.
    return value.replace(tzinfo=UTC)
