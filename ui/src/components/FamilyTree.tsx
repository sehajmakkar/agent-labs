import { api, type FamilyNode, type RunSummary } from "../api";
import { useLoad } from "../lib/hooks";

/**
 * A run's family, from its root: the original, its replays (↺) and its forks (⑂), each fork with
 * its runs. Forks of fork runs nest inside them.
 */
export function FamilyTree({ runId, currentId }: { runId: string; currentId: string }) {
  const family = useLoad(() => api.family(runId), `family-${runId}`);
  const root = family.data;
  if (!root || (root.replays.length === 0 && root.forks.length === 0)) return null;
  return (
    <details className="family" open>
      <summary>Run family</summary>
      <ul className="tree-list">
        <Node node={root} currentId={currentId} />
      </ul>
    </details>
  );
}

function Node({ node, currentId }: { node: FamilyNode; currentId: string }) {
  return (
    <li>
      <RunLink run={node.run} currentId={currentId} />
      {(node.replays.length > 0 || node.forks.length > 0) && (
        <ul>
          {node.replays.map((r) => (
            <li key={r.id}>
              <RunLink run={r} currentId={currentId} />
            </li>
          ))}
          {node.forks.map(({ fork, runs }) => {
            const s = fork.summary;
            const rate = (g?: { passed: number | null; n: number } | null) =>
              g && g.passed != null ? `${g.passed}/${g.n}` : "–";
            return (
              <li key={fork.id}>
                <a href={`#/forks/${fork.id}`}>
                  ⑂ fork at {fork.label}
                  {s ? ` · ${rate(s.fork)} with the change, ${rate(s.control)} without` : ` · ${fork.status}`}
                </a>
                {runs.length > 0 && (
                  // Folded unless the run being viewed is in it: a fork can hold 2N runs.
                  <details open={runs.some((c) => c.run.id === currentId)}>
                    <summary className="muted">{runs.length} runs</summary>
                    <ul>
                      {runs.map((child) => (
                        <Node key={child.run.id} node={child} currentId={currentId} />
                      ))}
                    </ul>
                  </details>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

function RunLink({ run, currentId }: { run: RunSummary; currentId: string }) {
  const icon = run.mode === "replay" ? "↺" : run.mode === "fork" ? (run.fork_override ? "⑂" : "○") : "●";
  const outcome = run.mode === "replay"
    ? run.replay_report?.identical ? "identical" : "diverged"
    : run.eval ? (run.eval.passed ? "passed" : run.eval.failure_category ?? "failed") : run.status;
  return (
    <a href={`#/runs/${run.id}`} className={run.id === currentId ? "current" : undefined}>
      {icon} <span className="mono">{run.id.slice(0, 8)}</span> {outcome}
      {run.mode === "fork" && !run.fork_override && " (control)"}
    </a>
  );
}
