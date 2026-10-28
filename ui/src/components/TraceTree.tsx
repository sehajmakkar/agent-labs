import { Background, Controls, ReactFlow, type Edge } from "@xyflow/react";
import { useMemo } from "react";

import type { Span } from "../api";
import { layoutTree } from "../lib/layout";
import { SpanNode, type SpanFlowNode } from "./SpanNode";

const nodeTypes = { span: SpanNode };

/** The run as an interactive tree. Click a node to inspect it. */
export function TraceTree({
  spans,
  selectedId,
  blamedId,
  onSelect,
}: {
  spans: Span[];
  selectedId?: string;
  blamedId?: string;
  onSelect: (id: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const byId = new Map(spans.map((s) => [s.id, s]));
    // Ancestors of a failed span are drawn with a red edge, so the path to an error stands out.
    const onErrorPath = new Set<string>();
    for (const s of spans) {
      if (s.status !== "error") continue;
      let parent = s.parent_span_id;
      while (parent && byId.has(parent)) {
        onErrorPath.add(parent);
        parent = byId.get(parent)!.parent_span_id;
      }
    }
    const nodes: SpanFlowNode[] = layoutTree(spans).map((p) => {
      const span = byId.get(p.id)!;
      return {
        id: p.id,
        type: "span",
        position: { x: p.x, y: p.y },
        data: {
          span,
          selected: p.id === selectedId,
          onError: onErrorPath.has(p.id),
          blamed: p.id === blamedId,
          decision: span.kind === "step" ? decision(span.id, spans) : undefined,
        },
      };
    });
    const edges: Edge[] = spans
      .filter((s) => s.parent_span_id && byId.has(s.parent_span_id))
      .map((s) => ({
        id: `${s.parent_span_id}-${s.id}`,
        source: s.parent_span_id!,
        target: s.id,
        type: "smoothstep",
        className: s.status === "error" || onErrorPath.has(s.id) ? "edge-error" : undefined,
      }));
    return { nodes, edges };
  }, [spans, selectedId, blamedId]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, node) => onSelect(node.id)}
      nodesDraggable={false}
      nodesConnectable={false}
      fitView
      fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
      minZoom={0.2}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={24} size={1} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

/** What a step decided: the tools its model call asked for, or that it answered. */
function decision(stepId: string, spans: Span[]): string {
  const children = spans.filter((s) => s.parent_span_id === stepId);
  const tools = children.filter((s) => s.kind === "tool");
  if (tools.length) {
    const failed = tools.filter((s) => s.status === "error").length;
    const names = tools.map((s) => s.attributes["gen_ai.tool.name"] ?? s.name).join(", ");
    return `→ ${names}` + (failed ? `  (${failed} failed)` : "");
  }
  const llm = children.find((s) => s.kind === "llm");
  if (llm?.error) return "✗ model call failed";
  return llm?.output?.text ? "✓ final answer" : "no tool calls";
}
