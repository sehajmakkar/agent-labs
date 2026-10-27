"""A run as a list of steps: one model decision each, plus the tool calls it caused.

For runs of our loop a step is a `step` span. For an agent with its own loop there are no step
spans, so each model call starts a step and the tool calls after it (until the next model call)
belong to it. Retried model calls that failed are skipped: a step is what the model *decided*.
"""

from dataclasses import dataclass, field
from typing import Any

from agentlab import semconv
from agentlab.store import SpanRow


@dataclass
class ToolCallView:
    name: str
    args: dict[str, Any]
    output: Any = None
    error: str | None = None


@dataclass
class StepView:
    index: int  # 1-based position in the run
    span_id: str
    calls: list[ToolCallView] = field(default_factory=list)
    text: str | None = None  # the model's text: the final answer, or words alongside tool calls
    error: str | None = None  # every attempt at the model call failed
    tokens: int = 0
    cost_usd: float | None = None
    duration_ms: float = 0.0
    attempts: int = 1
    replayed: bool = False  # served from a recording (a fork's frozen prefix)

    @property
    def kind(self) -> str:
        if self.error:
            return "error"
        return "tools" if self.calls else "answer"

    def label(self) -> str:
        """A one-line summary of what the step decided."""
        if self.error:
            return f"✗ {self.error}"
        if self.calls:
            return ", ".join(f"{c.name}({_args(c.args)})" for c in self.calls)
        return f'"{(self.text or "").strip()}"'

    def same_as(self, other: "StepView") -> bool:
        """Did both steps decide the same thing, and see the same results?"""
        return (
            self.kind == other.kind
            and self.text == other.text
            and self.error == other.error
            and [(c.name, c.args, c.output, c.error) for c in self.calls]
            == [(c.name, c.args, c.output, c.error) for c in other.calls]
        )


def extract_steps(spans: list[SpanRow]) -> list[StepView]:
    ordered = sorted(spans, key=lambda s: s.seq)
    if any(s.kind == "step" for s in ordered):
        groups = [
            (step, [s for s in ordered if s.parent_span_id == step.id])
            for step in ordered
            if step.kind == "step"
        ]
    else:
        groups = _groups_by_model_call(ordered)
    return [_step(i, anchor, members) for i, (anchor, members) in enumerate(groups, start=1)]


def _groups_by_model_call(ordered: list[SpanRow]) -> list[tuple[SpanRow, list[SpanRow]]]:
    groups: list[tuple[SpanRow, list[SpanRow]]] = []
    for s in ordered:
        if s.kind == "llm":
            if groups and groups[-1][1] and all(m.status == "error" for m in groups[-1][1]):
                groups[-1][1].append(s)  # a retry of a failed call belongs to the same step
            else:
                groups.append((s, [s]))
        elif s.kind == "tool" and groups:
            groups[-1][1].append(s)
    return groups


def _step(index: int, anchor: SpanRow, members: list[SpanRow]) -> StepView:
    model_calls = [m for m in members if m.kind == "llm"]
    decided = next((m for m in reversed(model_calls) if m.status == "ok"), None)
    tools = [m for m in members if m.kind == "tool"]
    output = (decided.output if decided else None) or {}
    costs = [m.cost_usd for m in model_calls if m.cost_usd is not None]
    return StepView(
        index=index,
        span_id=anchor.id,
        calls=[
            ToolCallView(
                name=t.attributes.get(semconv.TOOL_NAME, t.name),
                args=t.input or {},
                output=t.output,
                error=t.error,
            )
            for t in tools
        ],
        text=output.get("text"),
        error=None if decided else (model_calls[-1].error if model_calls else anchor.error),
        tokens=sum(m.input_tokens + m.output_tokens + m.thinking_tokens for m in model_calls),
        cost_usd=sum(costs) if costs else None,
        duration_ms=anchor.duration_ms
        if anchor.kind == "step"
        else sum(m.duration_ms for m in members),
        attempts=len(model_calls) or 1,
        replayed=bool(decided and decided.attributes.get(semconv.REPLAYED)),
    )


def _args(args: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())
