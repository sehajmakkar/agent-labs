import { useState } from "react";

import { api, type RunSummary } from "../api";
import { navigate } from "../lib/hooks";

/** For a recorded run: a Replay button and its past replays. For a replay: how faithful it was. */
export function ReplayPanel({ run, replays }: { run: RunSummary; replays: RunSummary[] }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  if (run.mode === "replay") {
    const report = run.replay_report;
    return (
      <div className="replay-panel">
        <span>
          ↺ Replay of{" "}
          <a href={`#/runs/${run.parent_run_id}`} className="mono">
            {run.parent_run_id?.slice(0, 8)}
          </a>
          , served entirely from its recordings: no model or tool was called.
        </span>
        {report && (
          <span className={report.identical ? "replay-ok" : "replay-bad"}>
            {report.identical
              ? `Identical: all ${report.spans_compared} spans match.`
              : `${report.differences.length} differences.`}
          </span>
        )}
        {report && Object.keys(report.fallbacks).length > 0 && (
          <span className="muted">
            The source recorded no clock reads (it predates Phase 3), so live time was used.
          </span>
        )}
        {report && !report.identical && (
          <ul className="differences">
            {report.differences.slice(0, 8).map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  async function replay() {
    setBusy(true);
    setError(undefined);
    try {
      const result = await api.replay(run.id);
      navigate(`#/runs/${result.run_id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="replay-panel">
      <button onClick={replay} disabled={busy}>
        {busy ? "Replaying…" : "↺ Replay"}
      </button>
      <span className="muted">
        Re-run this agent from its recordings: offline, free, and checked against this run.
      </span>
      {replays.length > 0 && (
        <span>
          Replays:{" "}
          {replays.slice(0, 5).map((r) => (
            <a key={r.id} href={`#/runs/${r.id}`} className="replay-link">
              {r.id.slice(0, 8)} {r.replay_report?.identical ? "✓" : "✗"}
            </a>
          ))}
        </span>
      )}
      {error && <span className="error-text">{error}</span>}
    </div>
  );
}
