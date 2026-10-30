import { useState } from "react";

import { api, STATIC, type RunSummary } from "../api";
import { navigate, useLoad } from "../lib/hooks";

/** Pick another run to diff this one against: its source, or other runs of the same task. */
export function ComparePanel({ run }: { run: RunSummary }) {
  const siblings = useLoad(
    () => (run.task_id ? api.runs({ task_id: run.task_id }) : Promise.resolve([])),
    `compare-${run.id}`,
  );
  // The read-only demo has diffs only for the pairs that were exported; offer just those.
  const exported = useLoad(
    () => (STATIC ? api.diffPairs() : Promise.resolve(null)),
    "diff-pairs",
  );
  const pairs = exported.data ? new Set(exported.data) : null;
  const candidates: { id: string; label: string; aFirst: boolean }[] = [];
  if (run.parent_run_id) {
    candidates.push({ id: run.parent_run_id, label: `its source run ${run.parent_run_id.slice(0, 8)}`, aFirst: true });
  }
  // Most useful first: original runs on another model, then on this model, then forks and replays.
  const rank = (r: RunSummary) =>
    (r.mode === "record" ? 0 : 2) + (r.model === run.model ? 1 : 0);
  const others = (siblings.data ?? [])
    .filter((o) => o.id !== run.id && o.id !== run.parent_run_id)
    .sort((x, y) => rank(x) - rank(y));
  for (const other of others) {
    candidates.push({ id: other.id, label: describe(other), aFirst: false });
  }
  const [choice, setChoice] = useState("");
  const offered = pairs ? candidates.filter((c) => pairs.has(`${run.id}/${c.id}`)) : candidates;
  if (offered.length === 0) return null;

  function compare() {
    const picked = offered.find((c) => c.id === (choice || offered[0].id));
    if (!picked) return;
    // The source run goes on the left, so the diff reads "original → this".
    navigate(picked.aFirst ? `#/diff/${picked.id}/${run.id}` : `#/diff/${run.id}/${picked.id}`);
  }

  return (
    <div className="compare-panel">
      <span className="muted">Compare with</span>
      <select value={choice} onChange={(e) => setChoice(e.target.value)} aria-label="Run to compare with">
        {offered.slice(0, 40).map((c) => (
          <option key={c.id} value={c.id}>
            {c.label}
          </option>
        ))}
      </select>
      <button onClick={compare}>⇄ Diff</button>
    </div>
  );
}

function describe(run: RunSummary): string {
  const outcome = run.eval ? (run.eval.passed ? "passed" : run.eval.failure_category) : run.status;
  const kind = run.mode === "record" ? "" : ` · ${run.mode}${run.mode === "fork" && !run.fork_override ? " (control)" : ""}`;
  return `${run.id.slice(0, 8)} · ${run.model ?? ""}${kind} · ${outcome}`;
}
