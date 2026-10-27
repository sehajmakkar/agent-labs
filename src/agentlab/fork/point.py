"""Where a fork starts.

A fork keeps everything the source run did *before* a point and runs live from there. The point is
expressed as a position in the run's recordings (their `seq`, the call order):

- fork at a **step**: replay everything before the step; its model call is the first live call,
  so the model decides that step again, with the change;
- fork at a **tool call**: replay the step's model decision and tool calls, replacing that one
  tool's result with the override; the *next* model call is the first live one.

A model-call span counts as its step. For an agent with its own loop (no step spans), a model
call is the unit instead.
"""

from dataclasses import dataclass

from agentlab import semconv
from agentlab.store import RecordingRow, SpanRow, Store


@dataclass
class ForkPoint:
    span_id: str  # the step, tool or model-call span the fork starts at
    kind: str  # step | tool | llm
    label: str  # "step 3", "get_alert in step 1", "model call 2"
    live_from_seq: float  # the first recording at or after this seq is made live
    tool_override_seq: int | None = None  # for tool forks: the recording whose result changes


def resolve_fork_point(store: Store, run_id: str, span_id: str) -> ForkPoint:
    spans = {s.id: s for s in store.spans(run_id)}
    span = spans.get(span_id)
    if span is None:
        raise LookupError(f"Run {run_id[:8]} has no span {span_id}")
    recordings = store.run_recordings(run_id)
    if any(r.seq is None for r in recordings):
        raise ValueError(
            "This run was recorded before Phase 3, without call order, so it can't be forked"
        )

    by_span: dict[str, list[RecordingRow]] = {}
    for r in recordings:
        by_span.setdefault(r.span_id, []).append(r)

    if span.kind == "agent":
        steps = sorted((s for s in spans.values() if s.kind == "step"), key=lambda s: s.seq)
        span = steps[0] if steps else span
    if span.kind == "llm" and span.parent_span_id in spans:
        parent = spans[span.parent_span_id]
        span = parent if parent.kind == "step" else span

    if span.kind == "step":
        model_calls = [
            r.seq
            for child in spans.values()
            if child.parent_span_id == span.id and child.kind == "llm"
            for r in by_span.get(child.id, [])
        ]
        if not model_calls:
            raise ValueError(f"Step {_step(span)} has no recorded model call to fork from")
        return ForkPoint(span.id, "step", f"step {_step(span)}", min(model_calls))

    if span.kind == "llm":
        calls = sorted((s for s in spans.values() if s.kind == "llm"), key=lambda s: s.seq)
        index = calls.index(span) + 1
        return ForkPoint(
            span.id, "llm", f"model call {index}", min(r.seq for r in by_span[span.id])
        )

    if span.kind == "tool":
        (tool_recording,) = by_span[span.id][:1] or (None,)
        if tool_recording is None:
            raise ValueError("This tool call has no recording")
        later_model_calls = [
            r.seq for r in recordings if r.kind == "llm" and r.seq > tool_recording.seq
        ]
        name = span.attributes.get(semconv.TOOL_NAME, span.name)
        parent = spans.get(span.parent_span_id)
        where = f" in step {_step(parent)}" if parent and parent.kind == "step" else ""
        return ForkPoint(
            span.id,
            "tool",
            f"{name}{where}",
            min(later_model_calls, default=float("inf")),
            tool_override_seq=tool_recording.seq,
        )

    raise ValueError(f"Can't fork at a {span.kind} span")


def _step(span: SpanRow) -> str:
    return str(span.attributes.get(semconv.STEP_INDEX, "?"))
