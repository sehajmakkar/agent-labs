"""One blame job: propose candidate steps, verify them by forking, and write the report.

Candidates are verified in the judge's order, and the first one confirmed is the blame. Its
confidence is high when the correction beat the control with p < 0.05 *and* the step was decisive;
medium when it was confirmed but the evidence is weaker (a small N, or a recoverable step); and
there is no blame at all when no candidate is confirmed. Then the report says so, and gives the
judge's best guess as unproven.
"""

from collections.abc import Callable
from typing import Any

from agentlab.blame.propose import BlameJudge
from agentlab.blame.verify import verify_candidate
from agentlab.diff.steps import extract_steps
from agentlab.evals.tasks import Task
from agentlab.fork.point import recorded_system_prompt
from agentlab.store import BlameRow, Store, run_message


def execute_blame(
    store: Store,
    blame: BlameRow,
    *,
    blame_judge: BlameJudge,
    tasks: dict[str, Task],
    fork_context: dict[str, Any],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    source = store.get_run(blame.source_run_id)
    task = tasks.get(source.task_id or "") if source else None
    if source is None or task is None:
        raise ValueError(
            "Blame needs a failed run from an eval task: the task's checks score the forks"
        )
    steps = extract_steps(store.spans(source.id))
    result = store.eval_results_for_runs([source.id]).get(source.id)
    failures = [
        f"{c['type']}: {c['detail']}" for c in (result.checks if result else []) if not c["passed"]
    ]

    proposal = blame_judge(
        request=run_message(source),
        expected=task.expected,
        failures=failures,
        steps=steps,
        system_prompt=recorded_system_prompt(store, source.id),
    )
    report: dict[str, Any] = {
        "judge_model": proposal.model,
        "judge_cost_usd": proposal.cost_usd,
        "analysis": proposal.proposal.analysis,
        "candidates": [
            {
                "rank": rank,
                **c.model_dump(),
                "span_id": steps[c.step - 1].span_id,
                "verification": None,
            }
            for rank, c in enumerate(proposal.proposal.candidates, start=1)
        ],
        "blamed": None,
        "confidence": None,
        "verdict": "Verifying…",
    }
    _progress(store, blame.id, report, on_progress)

    for candidate in report["candidates"][: blame.max_candidates]:
        verification = verify_candidate(
            store,
            source.id,
            steps,
            candidate["step"],
            candidate["correction"],
            n=blame.n,
            fork_context=fork_context,
        )
        candidate["verification"] = verification.to_dict()
        _progress(store, blame.id, report, on_progress)
        if verification.status == "confirmed":
            report["blamed"] = candidate
            break

    report["confidence"] = _confidence(report["blamed"])
    report["verdict"] = _verdict(report)
    return report


def _confidence(blamed: dict[str, Any] | None) -> str | None:
    if blamed is None:
        return None
    v = blamed["verification"]
    strong = v["p_value"] is not None and v["p_value"] < 0.05
    return "high" if strong and v["decisive"] else "medium"


def _verdict(report: dict[str, Any]) -> str:
    blamed = report["blamed"]
    if blamed is None:
        guess = report["candidates"][0]["step"] if report["candidates"] else None
        tested = sum(1 for c in report["candidates"] if c["verification"])
        return f"Not proved: none of the {tested} candidates tested was confirmed by forking." + (
            f" The judge's best guess, unproven, is step {guess}." if guess else ""
        )
    v = blamed["verification"]
    text = (
        f"Step {blamed['step']} is at fault. Verified: with the correction {v['passed']}/{v['n']} "
        f"runs pass, without it {v['control_passed']}/{v['n']}"
        + (f" (p = {v['p_value']:.3f})." if v["p_value"] is not None else ".")
    )
    if v["later_passed"] is None:
        return text + " It is the last step, so it is decisive."
    if v["decisive"]:
        return text + (
            f" The same correction one step later saves only {v['later_passed']}/{v['n']}: "
            f"the run was lost at step {blamed['step']}."
        )
    return text + (
        f" But the same correction one step later still saves {v['later_passed']}/{v['n']}: the "
        "mistake was recoverable, so the damage may really be done later."
    )


def _progress(
    store: Store, blame_id: str, report: dict[str, Any], on_progress: Callable | None
) -> None:
    store.update_blame(blame_id, report=report)
    if on_progress:
        on_progress(report)
