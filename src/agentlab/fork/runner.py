"""Run one fork job: N forks with the change and N controls without it, scored and compared.

Each run is a `ForkSession` over the source run's recordings: everything before the fork point is
served from the recording, then the agent runs live with the override applied. If the source run
came from an eval task, every run is scored with that task's checks, so a fork reports a pass rate
rather than a feeling.
"""

import time
import uuid
from collections.abc import Callable
from typing import Any

from agentlab.evals.judge import LLMJudge
from agentlab.evals.runner import score
from agentlab.evals.tasks import Task
from agentlab.evals.trajectory import Trajectory
from agentlab.fork.point import recorded_system_prompt, resolve_fork_point
from agentlab.fork.stats import fisher_exact, verdict
from agentlab.llm.gemini import GeminiClient
from agentlab.loop import Agent
from agentlab.replay.runner import run_in_session
from agentlab.replay.session import ForkSession, Override
from agentlab.store import EvalResultRow, ForkRow, Store, run_answer


def execute_fork(
    store: Store,
    fork: ForkRow,
    *,
    llm: GeminiClient,
    agents: dict[str, Agent] | None = None,
    entry: Callable[..., Any] | None = None,
    judge: LLMJudge | None = None,
    tasks: dict[str, Task] | None = None,
    on_run: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the fork job and return its summary. The store must be the active one."""
    source = store.get_run(fork.source_run_id)
    if source is None:
        raise LookupError(f"No run {fork.source_run_id}")
    point = resolve_fork_point(store, source.id, fork.span_id)
    recordings = store.run_recordings(source.id)
    override = Override.model_validate(fork.override or {})
    recorded_prompt = recorded_system_prompt(store, source.id)
    task = (tasks or {}).get(source.task_id or "")

    groups: dict[str, list[dict[str, Any]]] = {"fork": [], "control": []}
    roles = [("fork", override)] + ([("control", Override())] if fork.control else [])
    for role, role_override in roles:
        for _ in range(fork.n):
            run_id = uuid.uuid4().hex
            session = ForkSession.for_fork(
                source.id,
                recordings,
                live_from_seq=point.live_from_seq,
                override=role_override,
                run_id=run_id,
                fork_id=fork.id,
                fork_span_id=point.span_id,
                tool_override_seq=point.tool_override_seq
                if role_override.tool_output is not None
                else None,
                recorded_prompt=recorded_prompt,
            )
            error = run_in_session(
                store,
                source,
                session,
                agents=agents,
                entry=entry,
                llm=llm,
                # Recorded failures before the fork point are replayed instantly; live ones wait.
                sleep=lambda seconds, s=session: time.sleep(seconds) if s.live else None,
            )
            result = _outcome(store, run_id, task, judge, fork.id, error)
            groups[role].append(result)
            if on_run:
                on_run(role, result)

    return _summary(fork, point.label, override, task is not None, groups)


def _outcome(
    store: Store,
    run_id: str,
    task: Task | None,
    judge: LLMJudge | None,
    fork_id: str,
    error: Exception | None,
) -> dict[str, Any]:
    run = store.get_run(run_id)
    result: dict[str, Any] = {
        "run_id": run_id,
        "status": run.status,
        "answer": run_answer(run),
        "error": f"{type(error).__name__}: {error}" if error else None,
        "passed": None,
        "category": None,
    }
    if task is None:
        return result
    outcome = score(task, Trajectory.from_store(store, run_id), judge)
    store.save_eval_result(
        EvalResultRow(
            eval_run_id=fork_id,  # fork runs' results are grouped under their fork job
            task_id=task.id,
            run_id=run_id,
            passed=outcome.passed,
            failure_category=outcome.category,
            checks=[c.model_dump() for c in outcome.checks],
            judge_cost_usd=sum(c.cost_usd or 0 for c in outcome.checks) or None,
        )
    )
    return result | {"passed": outcome.passed, "category": outcome.category}


def _summary(
    fork: ForkRow,
    label: str,
    override: Override,
    scored: bool,
    groups: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    def group(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not runs:
            return None
        passed = sum(1 for r in runs if r["passed"]) if scored else None
        return {"n": len(runs), "passed": passed, "runs": runs}

    forked, control = group(groups["fork"]), group(groups["control"])
    p_value = None
    if scored and forked and control:
        n = forked["n"]
        p_value = fisher_exact(
            forked["passed"],
            n - forked["passed"],
            control["passed"],
            control["n"] - control["passed"],
        )
    return {
        "label": label,
        "override": override.model_dump(exclude_none=True),
        "scored": scored,
        "fork": forked,
        "control": control,
        "p_value": p_value,
        "verdict": verdict(
            forked["passed"], forked["n"], control["passed"] if control else None, p_value
        )
        if scored
        else "Not scored: the source run isn't from an eval task, so compare the answers by eye",
    }
