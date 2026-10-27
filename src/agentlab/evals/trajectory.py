"""A stored run, flattened into what checks need: the question, the tool calls and the answer.

Checks read runs from the trace store, never from the agent's in-memory result. So the same checks
work on any recorded run, including runs from a customer's own agent that never used our loop.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from agentlab import semconv
from agentlab.store import Store, run_answer, run_message

MAX_OUTPUT_CHARS = 1500


@dataclass
class ToolCallRecord:
    name: str
    args: dict[str, Any]
    output: Any = None
    error: str | None = None


@dataclass
class Trajectory:
    run_id: str
    status: str
    message: str
    answer: str | None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    steps: int = 0
    duration_s: float | None = None
    error: str | None = None

    @classmethod
    def from_store(cls, store: Store, run_id: str) -> "Trajectory":
        run = store.get_run(run_id)
        if run is None:
            raise LookupError(f"No run {run_id}")
        spans = store.spans(run_id)
        return cls(
            run_id=run_id,
            status=run.status,
            message=run_message(run),
            answer=run_answer(run),
            tool_calls=[
                ToolCallRecord(
                    name=s.attributes.get(semconv.TOOL_NAME, s.name),
                    args=s.input or {},
                    output=s.output,
                    error=s.error,
                )
                for s in spans
                if s.kind == "tool"
            ],
            steps=sum(1 for s in spans if s.kind == "step"),
            duration_s=(run.ended_at - run.started_at).total_seconds() if run.ended_at else None,
            error=run.error,
        )

    def transcript(self) -> str:
        """The run as plain text, for the LLM judge to read."""
        lines = [f"USER: {self.message}"]
        for call in self.tool_calls:
            lines.append(f"TOOL CALL: {call.name}({json.dumps(call.args)})")
            if call.error:
                lines.append(f"TOOL ERROR: {call.error}")
            else:
                lines.append(f"TOOL RESULT: {_clip(json.dumps(call.output, default=str))}")
        if self.answer:
            lines.append(f"AGENT ANSWER: {self.answer}")
        else:
            lines.append(f"(no answer; the run ended with status {self.status!r})")
        return "\n".join(lines)


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + " …(truncated)"
