"""How alike are two steps, and which steps of two runs correspond?

Two runs of the same task rarely match step for step: one agent may look something up twice,
skip a check, or answer a step earlier. Lining them up is the same problem as lining up two DNA
sequences or two versions of a file, and we use the classic answer:

1. **Shared prefix.** Steps that are identical from the start are matched as they are.
2. **Needleman–Wunsch** global alignment for the rest. Fill a table where cell (i, j) holds the best
   score for aligning the first i steps of A with the first j steps of B. Each cell takes the best
   of three moves: pair A[i] with B[j] (scored by their similarity), or leave one of them unpaired
   (a gap, with a fixed penalty). Tracing back from the corner gives the alignment.

LCS (longest common subsequence) is the special case where steps either match exactly or not at
all. Needleman–Wunsch can also pair steps that are *similar* (same tool, different arguments),
which is what makes "the same lookup, but for a different order" show up as a change, not as one
step removed and another added.
"""

from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from agentlab.diff.steps import StepView

GAP = (
    -0.6
)  # the cost of leaving a step unpaired; pairing anything with similarity > 0.2 beats two gaps


@dataclass
class Row:
    status: str  # same | changed | removed (only in A) | added (only in B)
    a: StepView | None
    b: StepView | None
    similarity: float
    notes: list[str] = field(default_factory=list)


def similarity(a: StepView, b: StepView) -> float:
    """0 (nothing alike) to 1 (the same decision and the same results)."""
    if a.same_as(b):
        return 1.0
    if a.kind != b.kind:
        return 0.0
    if a.kind == "error":
        return 0.5
    if a.kind == "answer":
        return round(text_similarity(a.text, b.text), 3)
    names_a, names_b = Counter(c.name for c in a.calls), Counter(c.name for c in b.calls)
    name_score = sum((names_a & names_b).values()) / sum((names_a | names_b).values())
    pairs = _pair_calls(a, b)
    arg_score = (
        sum(args_similarity(x.args, y.args) for x, y in pairs) / len(pairs) if pairs else 0.0
    )
    result_score = (
        sum(x.output == y.output and x.error == y.error for x, y in pairs) / len(pairs)
        if pairs
        else 0.0
    )
    return round(0.6 * name_score + 0.3 * arg_score + 0.1 * result_score, 3)


def text_similarity(a: str | None, b: str | None) -> float:
    """Share of words in common, in order (difflib's ratio over word lists)."""
    return SequenceMatcher(None, (a or "").split(), (b or "").split()).ratio()


def args_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    return sum(str(a.get(k)) == str(b.get(k)) for k in keys) / len(keys)


def align(a: list[StepView], b: list[StepView]) -> list[Row]:
    prefix = 0
    while prefix < min(len(a), len(b)) and a[prefix].same_as(b[prefix]):
        prefix += 1
    rows = [Row("same", x, y, 1.0) for x, y in zip(a[:prefix], b[:prefix], strict=True)]
    return rows + _needleman_wunsch(a[prefix:], b[prefix:])


def _needleman_wunsch(a: list[StepView], b: list[StepView]) -> list[Row]:
    n, m = len(a), len(b)
    sim = [[similarity(x, y) for y in b] for x in a]
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = i * GAP
    for j in range(1, m + 1):
        score[0][j] = j * GAP
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            score[i][j] = max(
                score[i - 1][j - 1] + (2 * sim[i - 1][j - 1] - 1),  # pair: +1 if alike, -1 if not
                score[i - 1][j] + GAP,  # A's step has no partner
                score[i][j - 1] + GAP,  # B's step has no partner
            )

    rows: list[Row] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and score[i][j] == score[i - 1][j - 1] + (2 * sim[i - 1][j - 1] - 1):
            x, y, s = a[i - 1], b[j - 1], sim[i - 1][j - 1]
            rows.append(Row("same" if s == 1.0 else "changed", x, y, s, describe(x, y)))
            i, j = i - 1, j - 1
        elif i > 0 and (j == 0 or score[i][j] == score[i - 1][j] + GAP):
            rows.append(Row("removed", a[i - 1], None, 0.0, [f"only in A: {a[i - 1].label()}"]))
            i -= 1
        else:
            rows.append(Row("added", None, b[j - 1], 0.0, [f"only in B: {b[j - 1].label()}"]))
            j -= 1
    return rows[::-1]


def describe(a: StepView, b: StepView) -> list[str]:
    """What differs between two paired steps, in words."""
    if a.same_as(b):
        return []
    if a.kind != b.kind:
        return [f"A {_verb(a)}; B {_verb(b)}"]
    if a.kind == "answer":
        return [f"different answer ({text_similarity(a.text, b.text):.0%} of words shared)"]
    if a.kind == "error":
        return ["both failed, differently"]
    notes = []
    names_a, names_b = [c.name for c in a.calls], [c.name for c in b.calls]
    if Counter(names_a) != Counter(names_b):
        notes.append(f"different tools: {', '.join(names_a)} → {', '.join(names_b)}")
    for x, y in _pair_calls(a, b):
        changed = sorted(
            k for k in set(x.args) | set(y.args) if str(x.args.get(k)) != str(y.args.get(k))
        )
        if changed:
            detail = ", ".join(f"{k} {_value(x.args, k)} → {_value(y.args, k)}" for k in changed)
            notes.append(f"{x.name}: {detail}")
        elif x.output != y.output or x.error != y.error:
            notes.append(f"{x.name}: same call, different result")
    if a.text != b.text and (a.text or b.text):
        notes.append("different words alongside the tool calls")
    return notes or ["same calls in a different order"]


def _value(args: dict[str, Any], key: str) -> str:
    return repr(args[key]) if key in args else "(not given)"


def _verb(step: StepView) -> str:
    if step.kind == "answer":
        return "answers"
    if step.kind == "error":
        return "fails"
    return "calls " + ", ".join(c.name for c in step.calls)


def _pair_calls(a: StepView, b: StepView) -> list[tuple[Any, Any]]:
    """Pair each call in A with the next unused call of the same tool in B."""
    unused = list(b.calls)
    pairs = []
    for x in a.calls:
        match = next((y for y in unused if y.name == x.name), None)
        if match is not None:
            unused.remove(match)
            pairs.append((x, match))
    return pairs
