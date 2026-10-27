import { useState } from "react";

import { api, type RunSummary } from "../api";
import { Outcome } from "../components/RunStatus";
import { activeSeconds, localTime, money, seconds, tokens, truncate } from "../lib/format";
import { navigate, useLoad } from "../lib/hooks";

export function Runs() {
  const [agent, setAgent] = useState("");
  const [failedOnly, setFailedOnly] = useState(false);
  const [showReplays, setShowReplays] = useState(false);
  const runs = useLoad(() => api.runs(), "runs");

  const rows = (runs.data ?? []).filter(
    (r) =>
      (!agent || r.agent_name === agent) &&
      (!failedOnly || isFailure(r)) &&
      (showReplays || r.mode !== "replay"),
  );
  const agents = [...new Set((runs.data ?? []).map((r) => r.agent_name))].sort();

  return (
    <div className="page">
      <div className="page-head">
        <h1>Runs</h1>
        <div className="toolbar">
          <select value={agent} onChange={(e) => setAgent(e.target.value)} aria-label="Agent">
            <option value="">All agents</option>
            {agents.map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={failedOnly}
              onChange={(e) => setFailedOnly(e.target.checked)}
            />
            Failures only
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={showReplays}
              onChange={(e) => setShowReplays(e.target.checked)}
            />
            Show replays
          </label>
          <button onClick={runs.reload}>Refresh</button>
        </div>
      </div>

      {runs.error && <p className="error-text">Could not load runs: {runs.error}</p>}
      {runs.data && rows.length === 0 && (
        <p className="empty">
          No runs yet. Try <code>lab run support "Was I charged twice for order 4417?"</code>
        </p>
      )}
      {rows.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Outcome</th>
              <th>Task / message</th>
              <th>Agent</th>
              <th className="num">Time</th>
              <th className="num">Tokens</th>
              <th className="num">Cost</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((run) => (
              <tr key={run.id} className="clickable" onClick={() => navigate(`#/runs/${run.id}`)}>
                <td>
                  <Outcome run={run} />
                </td>
                <td>
                  {run.task_id && <div className="task-id">{run.task_id}</div>}
                  <div className="muted">{truncate(run.message, 90)}</div>
                </td>
                <td>{run.agent_name}</td>
                <td className="num">{seconds(activeSeconds(run))}</td>
                <td className="num">{tokens(run.tokens)}</td>
                <td className="num">{money(run.cost_usd)}</td>
                <td className="muted nowrap">{localTime(run.started_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function isFailure(run: RunSummary): boolean {
  if (run.mode === "replay") return !run.replay_report?.identical;
  return run.eval ? !run.eval.passed : run.status !== "completed";
}
