"""Print a stored run as an indented tree, with tokens, cost and latency on each line."""

import json
from typing import Any

from agentlab import semconv
from agentlab.store import RunRow, SpanRow

MAX_DETAIL = 90


def render_run(run: RunRow, spans: list[SpanRow]) -> str:
    llm_spans = [s for s in spans if s.kind == "llm"]
    tokens = sum(s.input_tokens + s.output_tokens + s.thinking_tokens for s in llm_spans)
    costs = [s.cost_usd for s in llm_spans if s.cost_usd is not None]
    duration = (
        f"{(run.ended_at - run.started_at).total_seconds():.2f}s" if run.ended_at else "running"
    )
    header = [
        f"run {run.id[:8]}",
        run.agent_name,
        run.model or "",
        run.status,
        duration,
        f"{tokens:,} tokens",
        _money(sum(costs)) if costs else "cost unknown",
    ]
    lines = [" · ".join(part for part in header if part)]
    if run.error:
        lines.append(f"error: {run.error}")

    ids = {s.id for s in spans}
    children: dict[str | None, list[SpanRow]] = {}
    for s in spans:
        parent = s.parent_span_id if s.parent_span_id in ids else None
        children.setdefault(parent, []).append(s)

    def walk(parent_id: str | None, prefix: str) -> None:
        kids = children.get(parent_id, [])
        for i, s in enumerate(kids):
            last = i == len(kids) - 1
            lines.append(f"{prefix}{'└─ ' if last else '├─ '}{_label(s)}")
            child_prefix = prefix + ("   " if last else "│  ")
            for detail in _details(s):
                lines.append(f"{child_prefix}    {detail}")
            walk(s.id, child_prefix)

    walk(None, "")
    return "\n".join(lines)


def _label(s: SpanRow) -> str:
    parts = [s.name, f"{s.duration_ms / 1000:.2f}s"]
    if s.kind == "llm":
        tokens = f"in {s.input_tokens:,} · out {s.output_tokens:,}"
        if s.thinking_tokens:
            tokens += f" · thinking {s.thinking_tokens:,}"
        parts.append(tokens)
        if s.cost_usd is not None:
            parts.append(_money(s.cost_usd))
    attempts = s.attributes.get(semconv.LLM_ATTEMPTS, 1)
    if s.kind == "step" and attempts > 1:
        parts.append(f"{attempts} attempts")
    if s.status == "error":
        parts.append("✗")
    return "  ".join(parts)


def _details(s: SpanRow) -> list[str]:
    if s.kind == "llm" and s.output:
        details = [f"→ {c['name']}({_short(c['args'])})" for c in s.output.get("tool_calls", [])]
        if s.output.get("text"):
            details.append(f'"{_truncate(s.output["text"])}"')
        return details
    if s.kind == "llm" and s.error:
        return [f"✗ {_truncate(s.error)}"]
    if s.kind == "tool":
        result = f"✗ {s.error}" if s.error else f"← {_short(s.output)}"
        return [f"args {_short(s.input)}", _truncate(result)]
    return []


def _short(value: Any) -> str:
    return _truncate(json.dumps(value, ensure_ascii=False))


def _truncate(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_DETAIL else text[: MAX_DETAIL - 1] + "…"


def _money(usd: float) -> str:
    return f"${usd:.6f}"
