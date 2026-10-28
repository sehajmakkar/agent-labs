"""Locking a fixed failure in: regression tests, and the CI gate that enforces them.

A failure you have blamed and fixed should never come back unnoticed. `lock_in` turns a failed run
into a task in `datasets/regressions.jsonl`: the same input, the original task's checks, and, if a
blame proved a correction, one more LLM-judge check built from that correction, so the exact
failure mode is tested. The task records where it came from.

`check_gate` is what CI runs: an eval passes the gate only if its success rate is at least the
threshold *and* every regression test passes. Regressions are zero-tolerance: they are bugs that
were already paid for once.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from agentlab.evals.tasks import Judge, Task, load_dataset
from agentlab.store import EvalResultRow, Store, run_message

REGRESSIONS_FILE = "regressions.jsonl"
REGRESSION_TAG = "regression"


def lock_in(
    store: Store, run_id: str, *, tasks: dict[str, Task], datasets_dir: str | Path
) -> tuple[Task, bool]:
    """Save a failed run as a regression test. Returns the task and whether it was new."""
    run = store.get_run(run_id)
    if run is None:
        raise LookupError(f"No run {run_id}")
    task = tasks.get(run.task_id or "")
    if task is None:
        raise ValueError("Only runs of an eval task can become regression tests")
    if task.origin is not None:
        raise ValueError("This run is already from a regression test")

    path = Path(datasets_dir) / REGRESSIONS_FILE
    regression_id = f"regression-{task.id}-{run.id[:8]}"
    existing = {t.id: t for t in load_dataset(path)} if path.exists() else {}
    if regression_id in existing:
        return existing[regression_id], False

    blame = next((b for b in store.blames_of(run.id) if (b.report or {}).get("blamed")), None)
    blamed = blame.report["blamed"] if blame else None
    checks = list(task.checks)
    expected = task.expected
    if blamed:
        rule = blamed["correction"]
        expected += f" In particular: {rule}"
        checks.append(
            Judge(
                rubric=f"This exact failure happened before and was fixed. The agent must follow "
                f"this rule: {rule}"
            )
        )
    regression = Task(
        id=regression_id,
        agent=task.agent,  # the real agent, even when the failure came from a seeded variant
        input=run_message(run),
        expected=expected,
        checks=checks,
        tags=sorted(set(task.tags) | {REGRESSION_TAG}),
        origin={
            "run_id": run.id,
            "task_id": task.id,
            "blame_id": blame.id if blame else None,
            "blamed_step": blamed["step"] if blamed else None,
            "correction": blamed["correction"] if blamed else None,
            "locked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(regression.model_dump(mode="json", exclude_none=True)) + "\n")
    return regression, True


@dataclass
class GateResult:
    passed: bool
    success_rate: float
    threshold: float
    reasons: list[str] = field(default_factory=list)


def check_gate(
    results: list[EvalResultRow], tasks: dict[str, Task], threshold: float
) -> GateResult:
    """Pass if the success rate is at least `threshold` and no regression test failed."""
    rate = sum(r.passed for r in results) / len(results) if results else 0.0
    reasons = []
    if rate < threshold:
        reasons.append(f"success rate {rate:.0%} is below the gate's {threshold:.0%}")
    for r in results:
        task = tasks.get(r.task_id)
        if not r.passed and task is not None and REGRESSION_TAG in task.tags:
            failed = next((c for c in r.checks if not c["passed"]), None)
            why = f": {failed['type']}: {failed['detail']}" if failed else ""
            reasons.append(f"regression {r.task_id} failed again{why}")
    return GateResult(not reasons, rate, threshold, reasons)
