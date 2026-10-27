"""Print a stored run as an indented tree, with tokens, cost and latency on each line."""

import json
from typing import Any

from agentlab import semconv
from agentlab.store import EvalResultRow, EvalRunRow, RunRow, RunTotals, SpanRow

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
    if run.mode == "replay" and run.parent_run_id:
        header.insert(1, f"replay of {run.parent_run_id[:8]}")
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


def render_eval(
    eval_run: EvalRunRow,
    results: list[EvalResultRow],
    runs: dict[str, RunRow],
    totals: dict[str, RunTotals],
) -> str:
    """An eval run's summary metrics, then one line per task."""
    m = eval_run.metrics or {}
    judge = eval_run.judge_model or "off"
    lines = [f"eval {eval_run.id[:8]} · {eval_run.model} · judge {judge} · {eval_run.status}"]
    if m:
        rate = f"  ({m['success_rate']:.0%})" if m.get("success_rate") is not None else ""
        lines += [
            f"success   {m['passed']}/{m['tasks']}{rate}",
            f"latency   p50 {_seconds(m.get('latency_p50_s'))} · "
            f"p95 {_seconds(m.get('latency_p95_s'))}"
            + (
                f" · {m['rate_limit_wait_s']:.0f}s rate-limit wait left out"
                if m.get("rate_limit_wait_s")
                else ""
            ),
            f"cost      {_maybe_money(m.get('cost_per_task_usd'))} per task · "
            f"{_maybe_money(m.get('total_cost_usd'))} total · "
            f"judge {_maybe_money(m.get('judge_cost_usd'))}",
        ]
        if m.get("failure_categories"):
            counts = ", ".join(f"{name} {n}" for name, n in m["failure_categories"].items())
            lines.append(f"failures  {counts}")
    lines.append("")
    for r in results:
        run = runs.get(r.run_id)
        total = totals.get(r.run_id, RunTotals())
        # Leave out time spent waiting for our rate limiter, as p50 and p95 do.
        end = run.ended_at if run else None
        duration = (end - run.started_at).total_seconds() - total.wait_s if end else None
        mark = "✓" if r.passed else "✗"
        cost = total.cost_usd
        line = f"{mark} {r.task_id:28} {_seconds(duration):>7}  {_maybe_money(cost):>10}"
        line += f"  run {r.run_id[:8]}"
        if not r.passed:
            failed = next((c for c in r.checks if not c["passed"]), None)
            line += f"  {r.failure_category}"
            if failed:
                lines.append(line)
                line = f"    {failed['type']}: {_truncate(failed['detail'])}"
        lines.append(line)
    return "\n".join(lines)


def _seconds(value: float | None) -> str:
    return f"{value:.2f}s" if value is not None else "–"


def _maybe_money(usd: float | None) -> str:
    return _money(usd) if usd is not None else "–"


DIFF_MARK = {"same": "=", "changed": "≠", "added": "+", "removed": "-"}
COLUMN = 44


def render_diff(diff: Any) -> str:
    """Two runs side by side, one aligned step per line, then the divergence and its effects."""
    a, b = diff.a, diff.b
    lines = [
        f"A {a.run_id[:8]} · {a.agent} · {a.model or ''} · {a.mode}",
        f"B {b.run_id[:8]} · {b.agent} · {b.model or ''} · {b.mode}",
        "",
        f"    {'A':{COLUMN}}   B",
    ]
    for row in diff.rows:
        left = _cell(row.a)
        right = _cell(row.b)
        lines.append(f"{DIFF_MARK[row.status]} {left:{COLUMN}} │ {right}")
        if row.status == "changed":
            for note in row.notes:
                lines.append(f"    ↳ {_truncate(note)}")
    lines.append("")
    if diff.divergence is None:
        lines.append("no divergence: the two runs made the same decisions")
    else:
        lines.append(f"first divergence: {_truncate(diff.divergence.summary)}")
    for effect in diff.effects():
        lines.append(f"  {effect}")
    if a.answer != b.answer and diff.answer_diff:
        marked = "".join(
            p["text"]
            if p["op"] == "equal"
            else f"[-{p['text']}-]"
            if p["op"] == "delete"
            else f"{{+{p['text']}+}}"
            for p in diff.answer_diff
        )
        lines += ["", "answer (A → B):", " ".join(marked.split())[:600]]
    return "\n".join(lines)


def _cell(step: Any) -> str:
    if step is None:
        return ""
    text = f"{step.index}. {'↺ ' if step.replayed else ''}{step.label()}"
    text = " ".join(text.split())
    return text if len(text) <= COLUMN else text[: COLUMN - 1] + "…"
