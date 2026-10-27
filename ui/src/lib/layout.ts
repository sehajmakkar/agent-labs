// Tree layout: where to draw each span.
//
// The API sends spans as a flat list with parent IDs. We rebuild the tree and lay it out left to
// right: depth sets the column (agent → steps → calls), and each leaf takes the next free row.
// A parent sits level with the middle of its children. This is the simplest "tidy tree" layout,
// and it never overlaps, because every leaf gets a row of its own.

export type TreeInput = { id: string; parent_span_id: string | null; seq: number };

export type Placed = { id: string; x: number; y: number; depth: number };

export const NODE_WIDTH = 280;
export const NODE_HEIGHT = 84;
const GAP_X = 70;
const GAP_Y = 18;

export function layoutTree(spans: TreeInput[]): Placed[] {
  const ids = new Set(spans.map((s) => s.id));
  const children = new Map<string | null, TreeInput[]>();
  for (const span of [...spans].sort((a, b) => a.seq - b.seq)) {
    // A span whose parent is missing (not saved, or from another run) is drawn as a root.
    const parent = span.parent_span_id && ids.has(span.parent_span_id) ? span.parent_span_id : null;
    children.set(parent, [...(children.get(parent) ?? []), span]);
  }

  const placed: Placed[] = [];
  let nextRow = 0;

  // Returns the row this node was placed on (a fractional row for parents).
  function place(span: TreeInput, depth: number): number {
    const kids = children.get(span.id) ?? [];
    let row: number;
    if (kids.length === 0) {
      row = nextRow++;
    } else {
      const rows = kids.map((kid) => place(kid, depth + 1));
      row = (rows[0] + rows[rows.length - 1]) / 2;
    }
    placed.push({
      id: span.id,
      depth,
      x: depth * (NODE_WIDTH + GAP_X),
      y: row * (NODE_HEIGHT + GAP_Y),
    });
    return row;
  }

  for (const root of children.get(null) ?? []) place(root, 0);
  return placed;
}
