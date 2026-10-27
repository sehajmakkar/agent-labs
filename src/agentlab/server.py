"""The lab's HTTP API, read by the web UI (`lab ui`).

A thin layer over the trace store. Every endpoint reads, except `POST /api/runs/{id}/replay`, which
is safe to offer because a replay calls nothing outside the process: no model, no tools.

Response models are pydantic classes, so FastAPI validates what we send and documents every
endpoint at /docs (OpenAPI) for free.

The built UI (`ui/dist`, from `npm run build`) is served at `/` when it exists. During UI
development, Vite serves the UI instead and forwards `/api` requests here.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agentlab.evals.categories import DESCRIPTIONS
from agentlab.store import (
    EvalResultRow,
    EvalRunRow,
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
    mode: str  # record | replay
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


class RunDetail(BaseModel):
    run: RunSummary
    spans: list[Span]
    replays: list[RunSummary]  # replays of this run, newest first


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
    def list_runs(limit: int = 100, status: str | None = None, agent: str | None = None):
        return _summaries(store, store.runs(limit, status=status, agent_name=agent))

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
        )

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
