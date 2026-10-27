import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

import type { Span } from "../api";
import { compact, money, tokens, truncate } from "../lib/format";

export type SpanNodeData = {
  span: Span;
  selected: boolean;
  onError: boolean;
  decision?: string; // for steps: what the step decided
};
export type SpanFlowNode = Node<SpanNodeData, "span">;

const KIND_LABEL = { agent: "agent", step: "step", llm: "model", tool: "tool" } as const;

/** One span in the decision tree: what it was, what it decided or returned, and what it cost. */
export function SpanNode({ data }: NodeProps<SpanFlowNode>) {
  const { span, selected, onError } = data;
  const classes = ["span-node", `kind-${span.kind}`];
  if (span.status === "error") classes.push("is-error");
  else if (onError) classes.push("on-error-path");
  if (selected) classes.push("is-selected");

  return (
    <div className={classes.join(" ")}>
      <Handle type="target" position={Position.Left} />
      <div className="span-node-head">
        <span className="kind-badge">{KIND_LABEL[span.kind]}</span>
        <span className="span-title">{title(span)}</span>
        {span.status === "error" && <span className="error-mark">✗</span>}
      </div>
      <div className="span-node-body">{data.decision ?? summary(span)}</div>
      <div className="span-node-meta">{meta(span)}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function title(span: Span): string {
  if (span.kind === "tool") return span.attributes["gen_ai.tool.name"] ?? span.name;
  if (span.kind === "llm") return span.attributes["gen_ai.request.model"] ?? span.name;
  if (span.kind === "step") return `Step ${span.attributes["agentlab.step.index"] ?? ""}`;
  return span.attributes["gen_ai.agent.name"] ?? span.name;
}

function summary(span: Span): string {
  if (span.kind === "llm") {
    if (span.error) return `✗ ${truncate(span.error, 70)}`;
    const calls: { name: string; args: unknown }[] = span.output?.tool_calls ?? [];
    if (calls.length) return calls.map((c) => `→ ${c.name}(${compact(c.args, 40)})`).join("  ");
    return span.output?.text ? `“${truncate(span.output.text, 70)}”` : "(empty reply)";
  }
  if (span.kind === "tool") {
    return span.error ? `✗ ${truncate(span.error, 70)}` : `← ${compact(span.output, 70)}`;
  }
  if (span.kind === "agent") return compact(span.input, 70);
  return "";
}

function meta(span: Span): string {
  const parts = [`${(span.duration_ms / 1000).toFixed(2)}s`];
  const attempts = span.attributes["agentlab.llm.attempts"];
  if (span.kind === "step" && attempts > 1) parts.push(`${attempts} attempts (retried)`);
  if (span.kind === "llm") {
    parts.push(`${tokens(span.input_tokens)} in · ${tokens(span.output_tokens)} out`);
    if (span.thinking_tokens) parts.push(`${tokens(span.thinking_tokens)} thinking`);
    parts.push(money(span.cost_usd));
  }
  if (span.kind === "tool") parts.push(compact(span.input, 40));
  if (span.attributes["agentlab.replay.served"]) parts.unshift("↺ recorded");
  return parts.join(" · ");
}
