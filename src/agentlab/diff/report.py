"""The full diff of two runs: aligned steps, where they first diverge, what changed downstream."""

import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any

from agentlab.diff.align import Row, align, text_similarity
from agentlab.diff.steps import StepView, extract_steps
from agentlab.store import RunRow, Store, run_answer


@dataclass
class RunSide:
    """One run's outcome and totals: the downstream effects being compared."""

    run_id: str
    agent: str
    model: str | None
    mode: str
    status: str
    passed: bool | None  # its eval verdict, if it was scored
    category: str | None
    steps: int
    tokens: int
    cost_usd: float | None
    duration_s: float | None  # the agent's own time, rate-limit waiting left out
    answer: str | None


@dataclass
class Divergence:
    row: int  # index into `rows`
    a_step: int | None
    b_step: int | None
    summary: str


@dataclass
class TrajectoryDiff:
    a: RunSide
    b: RunSide
    rows: list[Row]
    divergence: Divergence | None
    answer_diff: list[dict[str, str]] = field(default_factory=list)  # [{op, text}], word level
    answer_similarity: float = 1.0

    @property
    def identical(self) -> bool:
        return self.divergence is None

    def effects(self) -> list[str]:
        """The downstream differences, in words."""
        a, b = self.a, self.b
        lines = []
        if a.steps != b.steps:
            lines.append(f"steps {a.steps} → {b.steps}")
        if a.tokens != b.tokens:
            lines.append(f"tokens {a.tokens:,} → {b.tokens:,} ({b.tokens - a.tokens:+,})")
        if a.cost_usd is not None and b.cost_usd is not None and a.cost_usd != b.cost_usd:
            replayed = [
                side for side, run in (("A", a), ("B", b)) if run.mode in ("replay", "fork")
            ]
            note = f" ({' and '.join(replayed)}: live calls only)" if replayed else ""
            lines.append(f"cost ${a.cost_usd:.6f} → ${b.cost_usd:.6f}{note}")
        if a.duration_s is not None and b.duration_s is not None:
            lines.append(f"time {a.duration_s:.2f}s → {b.duration_s:.2f}s")
        outcome_a, outcome_b = _outcome(a), _outcome(b)
        if outcome_a != outcome_b:
            lines.append(f"outcome {outcome_a} → {outcome_b}")
        if a.answer != b.answer:
            lines.append(f"final answers share {self.answer_similarity:.0%} of their words")
        return lines

    def to_dict(self) -> dict[str, Any]:
        return {
            "a": asdict(self.a),
            "b": asdict(self.b),
            "rows": [asdict(r) | {"a": _step(r.a), "b": _step(r.b)} for r in self.rows],
            "divergence": asdict(self.divergence) if self.divergence else None,
            "answer_diff": self.answer_diff,
            "answer_similarity": self.answer_similarity,
            "effects": self.effects(),
        }


def diff_runs(store: Store, a_id: str, b_id: str) -> TrajectoryDiff:
    runs = [store.get_run(a_id), store.get_run(b_id)]
    if None in runs:
        raise LookupError(f"No run {a_id if runs[0] is None else b_id}")
    a_run, b_run = runs
    a_steps, b_steps = extract_steps(store.spans(a_id)), extract_steps(store.spans(b_id))
    rows = align(a_steps, b_steps)
    a_answer, b_answer = run_answer(a_run), run_answer(b_run)
    return TrajectoryDiff(
        a=_side(store, a_run, a_steps),
        b=_side(store, b_run, b_steps),
        rows=rows,
        divergence=_divergence(rows),
        answer_diff=word_diff(a_answer or "", b_answer or ""),
        answer_similarity=round(text_similarity(a_answer, b_answer), 3),
    )


def word_diff(a: str, b: str) -> list[dict[str, str]]:
    """The two texts as runs of equal, deleted and inserted words (whitespace kept)."""
    a_words, b_words = re.split(r"(\s+)", a), re.split(r"(\s+)", b)
    parts = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a_words, b_words, autojunk=False).get_opcodes():
        if op in ("delete", "replace"):
            parts.append({"op": "delete", "text": "".join(a_words[i1:i2])})
        if op in ("insert", "replace"):
            parts.append({"op": "insert", "text": "".join(b_words[j1:j2])})
        if op == "equal":
            parts.append({"op": "equal", "text": "".join(a_words[i1:i2])})
    return parts


def _divergence(rows: list[Row]) -> Divergence | None:
    for index, row in enumerate(rows):
        if row.status == "same":
            continue
        a_step = row.a.index if row.a else None
        b_step = row.b.index if row.b else None
        where = (
            f"step {a_step or b_step}"
            if a_step == b_step or None in (a_step, b_step)
            else (f"step {a_step} of A / step {b_step} of B")
        )
        return Divergence(index, a_step, b_step, f"{where}: {'; '.join(row.notes)}")
    return None


def _side(store: Store, run: RunRow, steps: list[StepView]) -> RunSide:
    totals = store.run_totals([run.id])[run.id]
    result = store.eval_results_for_runs([run.id]).get(run.id)
    duration = (
        (run.ended_at - run.started_at).total_seconds() - totals.wait_s if run.ended_at else None
    )
    return RunSide(
        run_id=run.id,
        agent=run.agent_name,
        model=run.model,
        mode=run.mode or "record",
        status=run.status,
        passed=result.passed if result else None,
        category=result.failure_category if result else None,
        steps=len(steps),
        tokens=totals.tokens,
        cost_usd=totals.cost_usd,
        duration_s=round(duration, 3) if duration is not None else None,
        answer=run_answer(run),
    )


def _outcome(side: RunSide) -> str:
    if side.passed is None:
        return side.status
    return "✓ passed" if side.passed else f"✗ {side.category}"


def _step(step: StepView | None) -> dict[str, Any] | None:
    return None if step is None else asdict(step) | {"kind": step.kind, "label": step.label()}
