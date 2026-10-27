"""Failure categories: a name for *how* a task failed, not just *that* it failed.

A 60% success rate says little on its own. "Most failures are false claims" tells you where to look.
The categories below follow the failure modes from PLAN.md's seeded failure catalog.
"""

from typing import Literal

FailureCategory = Literal[
    "crash",
    "timeout",
    "max_steps",
    "wrong_tool",
    "invalid_arguments",
    "ignored_tool_error",
    "false_claim",
    "incomplete",
    "inefficient",
    "eval_error",
]

DESCRIPTIONS: dict[str, str] = {
    "crash": "the run stopped with an error (for example the model API failed after retries)",
    "timeout": "the run hit its time limit",
    "max_steps": "the run hit its step limit without answering, often a loop",
    "wrong_tool": "a needed tool was not called, or a tool that shouldn't be was",
    "invalid_arguments": "a tool was called with wrong or malformed arguments",
    "ignored_tool_error": "a tool returned an error and the answer ignored or hid it",
    "false_claim": "the answer states something the tool results don't support",
    "incomplete": "the answer leaves out something the user needed",
    "inefficient": "the right answer, but with far more steps than needed",
    "eval_error": "the evaluation itself failed (for example the judge call), not the agent",
}

# When several checks fail, the task gets the first category in this order. Run-level failures come
# first: if the agent never answered, judging the answer adds nothing.
PRECEDENCE: list[str] = list(DESCRIPTIONS)

# Run statuses that are failures in themselves.
STATUS_CATEGORIES = {"error": "crash", "timeout": "timeout", "max_steps": "max_steps"}


def pick_category(status: str, failed: list[str]) -> str | None:
    """The one category that best describes a task, given its run's status and the categories of
    its failed checks. None means the task passed."""
    candidates = list(failed)
    if status in STATUS_CATEGORIES:
        candidates.append(STATUS_CATEGORIES[status])
    return min(candidates, key=PRECEDENCE.index) if candidates else None
