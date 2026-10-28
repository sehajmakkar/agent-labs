"""Seeding failures with known causes, and measuring how often blame finds them.

`seed_failures` runs each seeded bug's task several times with the bugged agent, through the normal
eval runner, so every run is scored. `seeded_failures` then collects the runs that failed *and*
show the bug's signature: those are the test cases, each with its known guilty step.
"""

from collections.abc import Callable
from dataclasses import dataclass

from agentlab.blame.catalog import BUGS, BUGS_BY_ID, SeededBug
from agentlab.blame.propose import BlameJudge
from agentlab.diff.steps import extract_steps
from agentlab.evals.judge import LLMJudge
from agentlab.evals.runner import TaskOutcome, run_eval
from agentlab.evals.tasks import Task
from agentlab.fork.point import recorded_system_prompt
from agentlab.llm.base import LLMClient
from agentlab.loop import Agent
from agentlab.store import Store, run_message

SEED_PREFIX = "seeded:"


@dataclass
class SeededFailure:
    run_id: str
    bug: SeededBug
    guilty_step: int  # ground truth: the first step showing the planted bug
    steps: int


def seed_failures(
    store: Store,
    *,
    llm: LLMClient,
    model: str,
    agents: dict[str, Agent],
    tasks: dict[str, Task],
    judge: LLMJudge | None,
    runs: int = 5,
    bugs: list[SeededBug] | None = None,
    on_result: Callable[[SeededBug, TaskOutcome], None] | None = None,
) -> list[str]:
    """Run every bug's task `runs` times with the bugged agent. Returns the eval run IDs."""
    eval_ids = []
    for bug in bugs or BUGS:
        task = tasks[bug.task_id]
        eval_ids.append(
            run_eval(
                [task] * runs,
                agents={task.agent: agents[bug.agent_name]},
                llm=llm,
                model=model,
                store=store,
                judge=judge,
                datasets=[SEED_PREFIX + bug.id],
                on_result=(lambda o, b=bug: on_result(b, o)) if on_result else None,
            )
        )
    return eval_ids


def seeded_failures(store: Store, limit: int | None = None) -> list[SeededFailure]:
    """Every seeded run that failed and shows its bug, newest seeding first."""
    failures = []
    for eval_run in store.eval_runs(500):
        dataset = (eval_run.datasets or [""])[0]
        if not dataset.startswith(SEED_PREFIX) or dataset[len(SEED_PREFIX) :] not in BUGS_BY_ID:
            continue
        bug = BUGS_BY_ID[dataset[len(SEED_PREFIX) :]]
        for result in store.eval_results(eval_run.id):
            if result.passed:
                continue
            steps = extract_steps(store.spans(result.run_id))
            guilty = bug.guilty_step(steps)
            if guilty is not None:
                failures.append(SeededFailure(result.run_id, bug, guilty, len(steps)))
    return failures[:limit] if limit else failures


def benchmark_proposals(
    store: Store,
    failures: list[SeededFailure],
    *,
    judges: dict[str, BlameJudge],
    tasks: dict[str, Task],
    with_prompt: bool = True,
    on_result: Callable[[str, SeededFailure, int | None], None] | None = None,
) -> dict:
    """How often each judge's ranked candidates contain the planted step.

    - top-1: the first candidate is the guilty step;
    - top-3: any of the (up to three) candidates is;
    - within 1: the first candidate is at most one step off.
    Proposals only: no forks, so this is cheap enough to run on every seeded failure.
    """
    results: dict = {}
    for name, judge in judges.items():
        cases = []
        for failure in failures:
            run = store.get_run(failure.run_id)
            steps = extract_steps(store.spans(failure.run_id))
            result = store.eval_results_for_runs([failure.run_id]).get(failure.run_id)
            failed = [
                f"{c['type']}: {c['detail']}"
                for c in (result.checks if result else [])
                if not c["passed"]
            ]
            try:
                proposal = judge(
                    request=run_message(run),
                    expected=tasks[failure.bug.task_id].expected,
                    failures=failed,
                    steps=steps,
                    system_prompt=recorded_system_prompt(store, failure.run_id)
                    if with_prompt
                    else None,
                )
                ranked = [c.step for c in proposal.proposal.candidates]
                cost = proposal.cost_usd
            except Exception as e:  # a judge failure counts as a miss, and is recorded
                ranked, cost = [], None
                print(f"  judge error on {failure.run_id[:8]}: {type(e).__name__}: {e}")
            rank = ranked.index(failure.guilty_step) + 1 if failure.guilty_step in ranked else None
            cases.append(
                {
                    "run_id": failure.run_id,
                    "bug": failure.bug.id,
                    "guilty_step": failure.guilty_step,
                    "steps": failure.steps,
                    "ranked": ranked,
                    "rank": rank,
                    "cost_usd": cost,
                }
            )
            if on_result:
                on_result(name, failure, rank)
        results[name] = _summarise(cases)
    return results


def _summarise(cases: list[dict]) -> dict:
    n = len(cases)

    def share(predicate: Callable[[dict], bool]) -> float | None:
        return round(sum(1 for c in cases if predicate(c)) / n, 3) if n else None

    by_bug: dict[str, dict] = {}
    for c in cases:
        bug = by_bug.setdefault(c["bug"], {"cases": 0, "top1": 0, "top3": 0})
        bug["cases"] += 1
        bug["top1"] += c["rank"] == 1
        bug["top3"] += c["rank"] is not None
    costs = [c["cost_usd"] for c in cases if c["cost_usd"] is not None]
    return {
        "cases": n,
        "top1": share(lambda c: c["rank"] == 1),
        "top3": share(lambda c: c["rank"] is not None),
        "within1": share(
            lambda c: bool(c["ranked"]) and abs(c["ranked"][0] - c["guilty_step"]) <= 1
        ),
        # A naive baseline: always blame the last step (where the answer is).
        "last_step_baseline": share(lambda c: c["guilty_step"] == c["steps"]),
        "cost_per_case_usd": sum(costs) / len(costs) if costs else None,
        "by_bug": by_bug,
        "cases_detail": cases,
    }


def benchmark_verification(
    store: Store,
    failures: list[SeededFailure],
    *,
    judge_model: str,
    n: int,
    max_candidates: int,
    run_blame: Callable[[str], dict],
    on_result: Callable[[SeededFailure, dict], None] | None = None,
) -> dict:
    """Full blame (propose, then verify by forking) on some seeded failures.

    Forks cost real model calls (about 3N runs per candidate), so this runs on a sample, usually one
    failure per bug. It measures what the proposal benchmark can't: does verification keep right
    answers, reject wrong ones, and abstain instead of guessing?
    """
    cases = []
    for failure in failures:
        blame_id = store.create_blame(
            source_run_id=failure.run_id,
            judge_model=judge_model,
            n=n,
            max_candidates=max_candidates,
            status="running",
            worker="bench",
        )
        try:
            report = run_blame(blame_id)
            store.finish_blame(blame_id, report=report)
        except Exception as e:
            store.finish_blame(blame_id, error=f"{type(e).__name__}: {e}")
            report = {"blamed": None, "candidates": [], "confidence": None}
        blamed = report["blamed"]
        case = {
            "run_id": failure.run_id,
            "blame_id": blame_id,
            "bug": failure.bug.id,
            "guilty_step": failure.guilty_step,
            "proposed": report["candidates"][0]["step"] if report["candidates"] else None,
            "blamed": blamed["step"] if blamed else None,
            "decisive": blamed["verification"]["decisive"] if blamed else None,
            "confidence": report["confidence"],
        }
        cases.append(case)
        if on_result:
            on_result(failure, case)

    total = len(cases)
    blamed = [c for c in cases if c["blamed"] is not None]
    right = [c for c in blamed if c["blamed"] == c["guilty_step"]]
    return {
        "cases": total,
        "judge_model": judge_model,
        "n": n,
        "proposed_top1": round(sum(c["proposed"] == c["guilty_step"] for c in cases) / total, 3)
        if total
        else None,
        "verified_accuracy": round(len(right) / total, 3) if total else None,
        # Of the blames verification confirmed, how many were right?
        "precision": round(len(right) / len(blamed), 3) if blamed else None,
        "abstained": round((total - len(blamed)) / total, 3) if total else None,
        "cases_detail": cases,
    }
