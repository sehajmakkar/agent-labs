"""Verifying a blame candidate by forking.

A judge's "step 3 went wrong" is a hypothesis. Two forks test it:

1. **Does correcting step c fix the run?** Fork at step c with the correction added to the prompt,
   N times, next to N controls without it (Phase 4). If the correction passes and the control
   doesn't, step c is where the outcome is decided, and the correction is what changes it.
2. **Is step c the point of no return?** Fork once more at step c+1 with the *same* correction, so
   step c's original decision is kept. If that fails, the run was already lost at step c:
   *decisive*. If it still passes, the mistake at c could have been recovered later: *recoverable*,
   so c may be too early and the real damage is done afterwards.
"""

from dataclasses import asdict, dataclass
from typing import Any

from agentlab.diff.steps import StepView
from agentlab.fork.point import recorded_system_prompt
from agentlab.fork.runner import execute_fork
from agentlab.store import Store

CONFIRM_RATE = 0.6  # the corrected forks must pass at least this often…
CONFIRM_GAP = 0.5  # …and beat the control by at least this much
REJECT_RATE = 0.2  # at or below this the correction plainly doesn't help


@dataclass
class Verification:
    step: int
    fork_id: str
    n: int
    passed: int  # corrected forks that passed
    control_passed: int  # controls (no correction) that passed
    p_value: float | None
    status: str  # confirmed | rejected | inconclusive
    later_fork_id: str | None = None
    later_passed: int | None = None  # the same correction applied one step later
    decisive: bool | None = None  # None when not confirmed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify(passed: int, control_passed: int, n: int) -> str:
    rate, gap = passed / n, (passed - control_passed) / n
    if rate >= CONFIRM_RATE and gap >= CONFIRM_GAP:
        return "confirmed"
    if rate <= REJECT_RATE or gap <= 0.1:
        return "rejected"
    return "inconclusive"


def verify_candidate(
    store: Store,
    source_run_id: str,
    steps: list[StepView],
    step: int,
    correction: str,
    *,
    n: int,
    fork_context: dict[str, Any],
) -> Verification:
    """Fork at `step` with the correction (and a control), then one step later if confirmed."""
    base_prompt = recorded_system_prompt(store, source_run_id) or ""
    override = {"system_prompt": f"{base_prompt}\n{correction}"}

    summary, fork_id = _fork(store, source_run_id, steps[step - 1], override, n, True, fork_context)
    passed, control_passed = summary["fork"]["passed"], summary["control"]["passed"]
    result = Verification(
        step=step,
        fork_id=fork_id,
        n=n,
        passed=passed,
        control_passed=control_passed,
        p_value=summary["p_value"],
        status=classify(passed, control_passed, n),
    )
    if result.status != "confirmed":
        return result
    if step == len(steps):
        result.decisive = True  # nothing comes after it that could have saved the run
        return result
    later, later_id = _fork(store, source_run_id, steps[step], override, n, False, fork_context)
    result.later_fork_id, result.later_passed = later_id, later["fork"]["passed"]
    result.decisive = later["fork"]["passed"] / n < CONFIRM_RATE
    return result


def _fork(
    store: Store,
    source_run_id: str,
    step: StepView,
    override: dict[str, Any],
    n: int,
    control: bool,
    fork_context: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    from agentlab.fork.point import resolve_fork_point

    point = resolve_fork_point(store, source_run_id, step.span_id)
    fork_id = store.create_fork(
        source_run_id=source_run_id,
        span_id=point.span_id,
        label=point.label,
        override=override,
        n=n,
        control=control,
        status="running",
        worker="blame",
    )
    summary = execute_fork(store, store.get_fork(fork_id), **fork_context)
    if summary["fork"]["passed"] is None:
        raise ValueError("Blame needs the source run's eval task, to score the forks")
    store.finish_fork(fork_id, summary=summary)
    return summary, fork_id
