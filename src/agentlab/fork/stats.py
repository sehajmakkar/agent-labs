"""Is a fork's pass rate really better than the control's, or is it luck?

The live part of a fork is random (the model samples), so one passing run proves little. We run
the fork N times *and* a control N times (same fork point, no change), then ask how likely a gap
this large would be if the change did nothing. Fisher's exact test answers that for two small
groups of pass/fail results, exactly, with no large-sample approximation.
"""

from math import comb


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided p-value for the 2×2 table [[a, b], [c, d]].

    Rows are groups (fork, control); columns are pass, fail. With the row and column totals fixed,
    each possible table has a hypergeometric probability. The p-value sums the probabilities of
    every table at most as likely as the one observed.
    """
    row1, col1, total = a + b, a + c, a + b + c + d

    def probability(x: int) -> float:
        return comb(row1, x) * comb(total - row1, col1 - x) / comb(total, col1)

    observed = probability(a)
    low, high = max(0, col1 - (total - row1)), min(row1, col1)
    # The small tolerance stops float rounding from leaving out a table exactly as likely.
    return min(
        1.0, sum(p for x in range(low, high + 1) if (p := probability(x)) <= observed * (1 + 1e-9))
    )


def verdict(fork_passed: int, n: int, control_passed: int | None, p_value: float | None) -> str:
    if control_passed is None:
        return f"{fork_passed}/{n} fork runs pass (no control to compare with)"
    if fork_passed > control_passed and p_value is not None and p_value < 0.05:
        return "The change fixes it: significantly more passes than without it"
    if fork_passed > control_passed:
        return f"Better than without the change, but not significant with N={n}: try a larger N"
    if fork_passed == control_passed:
        return "No difference: the change doesn't affect the outcome"
    return "Worse than without the change"
