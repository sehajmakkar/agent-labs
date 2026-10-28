"""Eval tasks and their checks, loaded from JSONL datasets (one JSON task per line).

A task is an input plus a way to tell whether the agent handled it:

    {"id": "support-double-charge", "agent": "support",
     "input": "Was I charged twice for order 4417?",
     "expected": "Confirms two captured payments of 2499 INR and says billing will refund one.",
     "checks": [{"type": "tool_called", "tool": "get_payments", "args": {"order_id": "4417"}},
                {"type": "answer_contains", "any_of": ["twice", "two"]},
                {"type": "judge"}]}

`expected` is the outcome in words: people read it, and the LLM judge grades against it. `checks`
are the tests. Each check type knows which failure category to report when it fails.
"""

import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, ValidationError

from agentlab.evals.categories import FailureCategory
from agentlab.evals.judge import LLMJudge
from agentlab.evals.trajectory import Trajectory


class CheckResult(BaseModel):
    type: str
    passed: bool
    category: str | None = None  # set when the check failed
    detail: str = ""
    cost_usd: float | None = None  # only the judge costs anything


class _Check(BaseModel):
    category: FailureCategory  # reported when this check fails; each type has a sensible default

    def evaluate(self, traj: Trajectory, task: "Task", judge: LLMJudge | None) -> CheckResult:
        raise NotImplementedError

    def _result(self, passed: bool, detail: str, category: str | None = None) -> CheckResult:
        failed_category = None if passed else (category or self.category)
        return CheckResult(type=self.type, passed=passed, category=failed_category, detail=detail)


class ToolCalled(_Check):
    """The agent called `tool`, optionally with arguments that include `args`."""

    type: Literal["tool_called"] = "tool_called"
    tool: str
    args: dict[str, Any] | None = None
    category: FailureCategory = "wrong_tool"

    def evaluate(self, traj, task, judge):
        calls = [c for c in traj.tool_calls if c.name == self.tool]
        if not calls:
            called = ", ".join(c.name for c in traj.tool_calls) or "no tools"
            return self._result(False, f"{self.tool} was never called (called: {called})")
        if self.args is None:
            return self._result(True, f"{self.tool} called {len(calls)}×")
        if any(_includes(c.args, self.args) for c in calls):
            return self._result(True, f"{self.tool} called with {json.dumps(self.args)}")
        seen = "; ".join(json.dumps(c.args) for c in calls)
        return self._result(
            False,
            f"{self.tool} called, but never with {json.dumps(self.args)} (got {seen})",
            category="invalid_arguments",
        )


class ToolNotCalled(_Check):
    """The agent did not call `tool`."""

    type: Literal["tool_not_called"] = "tool_not_called"
    tool: str
    category: FailureCategory = "wrong_tool"

    def evaluate(self, traj, task, judge):
        count = sum(1 for c in traj.tool_calls if c.name == self.tool)
        return self._result(count == 0, f"{self.tool} called {count}×")


class AnswerContains(_Check):
    """The answer mentions at least one of `any_of` and every one of `all_of` (case-insensitive)."""

    type: Literal["answer_contains"] = "answer_contains"
    any_of: list[str] = Field(default_factory=list)
    all_of: list[str] = Field(default_factory=list)
    category: FailureCategory = "incomplete"

    def evaluate(self, traj, task, judge):
        answer = (traj.answer or "").lower()
        missing = [s for s in self.all_of if s.lower() not in answer]
        if self.any_of and not any(s.lower() in answer for s in self.any_of):
            missing.append(" or ".join(repr(s) for s in self.any_of))
        if missing:
            return self._result(False, f"answer is missing {', '.join(missing)}")
        return self._result(True, "answer has the expected content")


class AnswerExcludes(_Check):
    """The answer mentions none of `any_of` (case-insensitive). Catches claims that are wrong."""

    type: Literal["answer_excludes"] = "answer_excludes"
    any_of: list[str]
    category: FailureCategory = "false_claim"

    def evaluate(self, traj, task, judge):
        answer = (traj.answer or "").lower()
        found = [s for s in self.any_of if s.lower() in answer]
        if found:
            return self._result(False, f"answer says {', '.join(repr(s) for s in found)}")
        return self._result(True, "answer avoids the excluded phrases")


class Grounded(_Check):
    """Every identifier in the answer matching `pattern` (e.g. `ALR-\\d+`) must appear in the user's
    message or in some tool result. It catches invented IDs, which a judge reading prose misses."""

    type: Literal["grounded"] = "grounded"
    pattern: str
    category: FailureCategory = "false_claim"

    def evaluate(self, traj, task, judge):
        seen = (
            traj.message
            + " "
            + " ".join(
                json.dumps(c.output, default=str) for c in traj.tool_calls if c.error is None
            )
        )
        mentioned = sorted(set(re.findall(self.pattern, traj.answer or "")))
        invented = [m for m in mentioned if m not in seen]
        if invented:
            return self._result(
                False, f"answer mentions {', '.join(invented)}, which no tool returned"
            )
        return self._result(True, f"all {len(mentioned)} IDs in the answer came from the tools")


class MaxSteps(_Check):
    """The run used at most `limit` steps (model calls)."""

    type: Literal["max_steps"] = "max_steps"
    limit: int
    category: FailureCategory = "inefficient"

    def evaluate(self, traj, task, judge):
        return self._result(traj.steps <= self.limit, f"{traj.steps} steps (limit {self.limit})")


class Judge(_Check):
    """An LLM grades the run against the task's `expected` outcome, plus an optional `rubric`."""

    type: Literal["judge"] = "judge"
    rubric: str | None = None
    # Used only if the judge fails a run without naming a category.
    category: FailureCategory = "incomplete"

    def evaluate(self, traj, task, judge):
        if judge is None:
            raise ValueError("A judge check needs an LLM judge")
        expected = task.expected + (f"\n{self.rubric}" if self.rubric else "")
        try:
            judgement = judge(request=task.input, expected=expected, transcript=traj.transcript())
        except Exception as e:  # a judge failure (API error, bad JSON) is the eval's fault
            return self._result(False, f"judge failed: {type(e).__name__}: {e}", "eval_error")
        verdict = judgement.verdict
        result = self._result(verdict.passed, verdict.reasoning, verdict.failure_category)
        result.cost_usd = judgement.cost_usd
        return result


Check = Annotated[
    ToolCalled | ToolNotCalled | AnswerContains | AnswerExcludes | Grounded | MaxSteps | Judge,
    Field(discriminator="type"),
]


class Task(BaseModel):
    id: str
    agent: str
    input: str
    expected: str
    checks: list[Check] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    # For a regression test: the run, blame and correction it was made from (evals/regressions.py).
    origin: dict[str, Any] | None = None

    @property
    def needs_judge(self) -> bool:
        return any(isinstance(c, Judge) for c in self.checks)


def load_dataset(path: str | Path) -> list[Task]:
    """Read a JSONL dataset. Blank lines are skipped; errors name the file and line."""
    tasks = []
    for number, line in enumerate(Path(path).read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            tasks.append(Task.model_validate_json(line))
        except ValidationError as e:
            raise ValueError(f"{path}:{number}: invalid task: {e}") from e
    ids = [t.id for t in tasks]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"{path}: duplicate task IDs: {', '.join(duplicates)}")
    return tasks


def load_tasks(directory: str | Path) -> dict[str, Task]:
    """Every task in every `*.jsonl` file of a directory, by ID. Forks use it to score their runs
    with the source run's task."""
    tasks: dict[str, Task] = {}
    for path in sorted(Path(directory).glob("*.jsonl")):
        tasks |= {t.id: t for t in load_dataset(path)}
    return tasks


def _includes(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    """True if every expected key is in `actual` with an equal value (compared as text)."""
    return all(_text(actual.get(k)) == _text(v) for k, v in expected.items())


def _text(value: Any) -> str:
    return str(value).strip().lower()
