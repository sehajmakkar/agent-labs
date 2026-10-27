"""The batch runner: run every task in a dataset through its agent, score it, and save the results.

Each task becomes a normal traced run (so it can be opened in the UI like any other) plus an eval
result linking the task, the run, the checks and the failure category.

Tasks run in parallel threads. Each thread gets its own context, so the current run and span
(tracing.py's context variables) never leak between tasks.
"""

import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from agentlab.evals.categories import pick_category
from agentlab.evals.judge import LLMJudge
from agentlab.evals.metrics import summarize
from agentlab.evals.tasks import CheckResult, Task
from agentlab.evals.trajectory import Trajectory
from agentlab.llm.base import LLMClient
from agentlab.loop import Agent, run_agent
from agentlab.retry import RetryPolicy
from agentlab.store import EvalResultRow, Store

# Batches hit rate limits more than single runs, so they retry longer.
EVAL_RETRY = RetryPolicy(max_attempts=6, max_delay_s=30)


@dataclass
class TaskOutcome:
    task: Task
    run_id: str
    passed: bool
    category: str | None
    checks: list[CheckResult]


def run_eval(
    tasks: list[Task],
    *,
    agents: dict[str, Agent],
    llm: LLMClient,
    model: str,
    store: Store,
    judge: LLMJudge | None,
    datasets: list[str],
    concurrency: int = 4,
    max_steps: int = 10,
    timeout_s: float | None = 120,
    retry: RetryPolicy = EVAL_RETRY,
    on_result: Callable[[TaskOutcome], None] | None = None,
) -> str:
    """Run and score every task; returns the eval run's ID. The store must be the active one
    (`tracing.init`), so the runs are recorded."""
    unknown = sorted({t.agent for t in tasks} - set(agents))
    if unknown:
        raise ValueError(f"Unknown agents in dataset: {', '.join(unknown)}")
    if judge is None and any(t.needs_judge for t in tasks):
        tasks = [_without_judge(t) for t in tasks]

    eval_run_id = store.create_eval_run(
        datasets=datasets,
        model=model,
        judge_model=judge.model if judge else None,
        task_count=len(tasks),
    )

    def run_one(task: Task) -> TaskOutcome:
        run_id = uuid.uuid4().hex
        try:
            run_agent(
                agents[task.agent],
                llm=llm,
                model=model,
                user_message=task.input,
                max_steps=max_steps,
                timeout_s=timeout_s,
                retry=retry,
                task_id=task.id,
                run_id=run_id,
            )
        except Exception:
            pass  # the run is saved with status "error"; the checks below still score it
        outcome = score(task, Trajectory.from_store(store, run_id), judge)
        store.save_eval_result(
            EvalResultRow(
                eval_run_id=eval_run_id,
                task_id=task.id,
                run_id=run_id,
                passed=outcome.passed,
                failure_category=outcome.category,
                checks=[c.model_dump() for c in outcome.checks],
                judge_cost_usd=sum(c.cost_usd or 0 for c in outcome.checks) or None,
            )
        )
        return outcome

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for future in as_completed([pool.submit(run_one, t) for t in tasks]):
            outcome = future.result()
            if on_result:
                on_result(outcome)

    results = store.eval_results(eval_run_id)
    run_ids = [r.run_id for r in results]
    runs = {run_id: store.get_run(run_id) for run_id in run_ids}
    store.finish_eval_run(eval_run_id, metrics=summarize(results, runs, store.run_totals(run_ids)))
    return eval_run_id


def score(task: Task, traj: Trajectory, judge: LLMJudge | None) -> TaskOutcome:
    """Run every check on one trajectory and pick the failure category."""
    checks = [check.evaluate(traj, task, judge) for check in task.checks]
    category = pick_category(traj.status, [c.category for c in checks if not c.passed])
    return TaskOutcome(task, traj.run_id, category is None, category, checks)


def _without_judge(task: Task) -> Task:
    return task.model_copy(update={"checks": [c for c in task.checks if c.type != "judge"]})
