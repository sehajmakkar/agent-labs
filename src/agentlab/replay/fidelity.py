"""Replay fidelity: did the replay reproduce its source run exactly?

Two runs are compared node by node, in start order. For each span we compare what the agent
decided and saw: its kind and name, where it sits in the tree, its status, the model's output
(text and tool calls), its token counts, the tool's arguments and result, and the final answer.
IDs, timestamps, durations and cost are left out: they always differ, and a replayed call costs
nothing.
"""

from dataclasses import dataclass, field
from typing import Any

from agentlab import semconv
from agentlab.store import SpanRow


@dataclass
class FidelityReport:
    identical: bool
    spans_compared: int
    differences: list[str] = field(default_factory=list)
    unused_recordings: int = 0  # calls the source made that the replay never made
    fallbacks: dict[str, int] = field(default_factory=dict)  # unrecorded clock/random reads

    def summary(self) -> str:
        if self.identical:
            text = f"identical: {self.spans_compared} spans match"
        else:
            text = f"{len(self.differences)} differences in {self.spans_compared} spans"
        if self.fallbacks:
            reads = ", ".join(f"{n} {kind}" for kind, n in self.fallbacks.items())
            text += f" ({reads} reads not in the recording; live values used)"
        return text


def signature(spans: list[SpanRow]) -> list[dict[str, Any]]:
    """Each span reduced to what must be the same in a faithful replay."""
    ordered = sorted(spans, key=lambda s: s.seq)
    position = {s.id: i for i, s in enumerate(ordered)}
    nodes = []
    for s in ordered:
        node: dict[str, Any] = {
            "kind": s.kind,
            "name": s.name,
            "parent": position.get(s.parent_span_id),
            "status": s.status,
            "error": s.error,
        }
        if s.kind == "llm":
            node |= {
                "output": s.output,
                "tokens": [s.input_tokens, s.output_tokens, s.thinking_tokens],
            }
        elif s.kind == "tool":
            node |= {"input": s.input, "output": s.output}
        elif s.kind == "agent":
            node |= {"input": s.input, "output": s.output}
        elif s.kind == "step":
            node["attempts"] = s.attributes.get(semconv.LLM_ATTEMPTS)
        nodes.append(node)
    return nodes


def compare(
    source: list[SpanRow],
    replay: list[SpanRow],
    *,
    unused_recordings: int = 0,
    fallbacks: dict[str, int] | None = None,
) -> FidelityReport:
    a, b = signature(source), signature(replay)
    differences = []
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        for key in sorted(set(x) | set(y)):
            if x.get(key) != y.get(key):
                differences.append(f"span {i} ({x['name']}): {key} differs")
    if len(a) != len(b):
        differences.append(f"the source has {len(a)} spans, the replay {len(b)}")
    if unused_recordings:
        differences.append(f"{unused_recordings} recorded calls were never made by the replay")
    return FidelityReport(
        identical=not differences,
        spans_compared=min(len(a), len(b)),
        differences=differences,
        unused_recordings=unused_recordings,
        fallbacks=dict(fallbacks or {}),
    )
