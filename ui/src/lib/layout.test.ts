import { describe, expect, it } from "vitest";

import { layoutTree, NODE_HEIGHT, NODE_WIDTH } from "./layout";

const span = (id: string, parent: string | null, seq: number) => ({
  id,
  parent_span_id: parent,
  seq,
});

// agent → step 1 → (llm, tool), step 2 → (llm)
const RUN = [
  span("agent", null, 0),
  span("step1", "agent", 1),
  span("llm1", "step1", 2),
  span("tool1", "step1", 3),
  span("step2", "agent", 4),
  span("llm2", "step2", 5),
];

describe("layoutTree", () => {
  it("puts each depth in its own column", () => {
    const byId = Object.fromEntries(layoutTree(RUN).map((p) => [p.id, p]));
    expect(byId.agent.depth).toBe(0);
    expect(byId.step1.depth).toBe(1);
    expect(byId.tool1.depth).toBe(2);
    expect(byId.tool1.x).toBeGreaterThan(byId.step1.x + NODE_WIDTH);
  });

  it("gives every leaf its own row, in start order", () => {
    const byId = Object.fromEntries(layoutTree(RUN).map((p) => [p.id, p]));
    const leaves = [byId.llm1, byId.tool1, byId.llm2].map((p) => p.y);
    expect(leaves).toEqual([...leaves].sort((a, b) => a - b));
    expect(new Set(leaves).size).toBe(3);
    expect(leaves[1] - leaves[0]).toBeGreaterThanOrEqual(NODE_HEIGHT);
  });

  it("centres a parent on its children", () => {
    const byId = Object.fromEntries(layoutTree(RUN).map((p) => [p.id, p]));
    expect(byId.step1.y).toBe((byId.llm1.y + byId.tool1.y) / 2);
    expect(byId.agent.y).toBe((byId.step1.y + byId.step2.y) / 2);
  });

  it("does not depend on the order spans arrive in", () => {
    // Spans are saved when they end, so children often arrive before their parents.
    const shuffled = [...RUN].reverse();
    expect(layoutTree(shuffled).sort((a, b) => a.id.localeCompare(b.id))).toEqual(
      layoutTree(RUN).sort((a, b) => a.id.localeCompare(b.id)),
    );
  });

  it("draws orphans as roots instead of dropping them", () => {
    const placed = layoutTree([span("a", null, 0), span("b", "missing", 1)]);
    expect(placed.map((p) => p.depth)).toEqual([0, 0]);
  });
});
