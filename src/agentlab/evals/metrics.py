"""Summary metrics for an eval run: success rate, latency percentiles, cost per task.

Latency is reported as percentiles, not an average. One 40-second run among nineteen 3-second ones
barely moves the mean but is exactly what users notice. p50 (the median) is the typical run; p95 is
the slow tail, which only 1 in 20 runs exceeds.
"""

import math
from collections import Counter
from typing import Any

from agentlab.store import EvalResultRow, RunRow, RunTotals


def percentile(values: list[float], q: float) -> float | None:
    """The q-th percentile (0–100), interpolating linearly between the two nearest ranks.

    This is the "linear" method that numpy and most spreadsheets use by default. With few values the
    tail estimate is rough: p95 of 20 runs sits between the two slowest.
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q / 100
    low, high = math.floor(rank), math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize(
    results: list[EvalResultRow], runs: dict[str, RunRow], totals: dict[str, RunTotals]
) -> dict[str, Any]:
    # Time spent waiting for our own rate limiter is the eval's doing, not the agent's.
    durations = [
        (run.ended_at - run.started_at).total_seconds() - totals.get(r.run_id, RunTotals()).wait_s
        for r in results
        if (run := runs.get(r.run_id)) and run.ended_at
    ]
    costs = [t.cost_usd for r in results if (t := totals.get(r.run_id)) and t.cost_usd is not None]
    tokens = [totals[r.run_id].tokens for r in results if r.run_id in totals]
    judge_costs = [r.judge_cost_usd for r in results if r.judge_cost_usd is not None]
    passed = sum(r.passed for r in results)

    by_agent: dict[str, dict[str, int]] = {}
    for r in results:
        agent = runs[r.run_id].agent_name if r.run_id in runs else "?"
        counts = by_agent.setdefault(agent, {"tasks": 0, "passed": 0})
        counts["tasks"] += 1
        counts["passed"] += r.passed

    return {
        "tasks": len(results),
        "passed": passed,
        "success_rate": passed / len(results) if results else None,
        "latency_p50_s": percentile(durations, 50),
        "latency_p95_s": percentile(durations, 95),
        "rate_limit_wait_s": sum(t.wait_s for t in totals.values()),
        "cost_per_task_usd": sum(costs) / len(costs) if costs else None,
        "total_cost_usd": sum(costs) if costs else None,
        "judge_cost_usd": sum(judge_costs) if judge_costs else None,
        "tokens_per_task": sum(tokens) / len(tokens) if tokens else None,
        "failure_categories": dict(
            Counter(r.failure_category for r in results if r.failure_category).most_common()
        ),
        "by_agent": by_agent,
    }
