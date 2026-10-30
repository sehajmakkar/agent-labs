import { useState } from "react";

import { api, type BlameInfo, type RunSummary } from "../api";
import { useAction, useConfig } from "../lib/config";
import { navigate } from "../lib/hooks";
import { ComparePanel } from "./ComparePanel";
import { LockInButton } from "./LockInButton";

/** The run page's actions, in one row: replay, compare, blame, lock in. */
export function RunActions({
  run,
  blames,
  replays,
}: {
  run: RunSummary;
  blames: BlameInfo[];
  replays: RunSummary[];
}) {
  const config = useConfig();
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const blameAction = useAction("blame");
  const lockIn = useAction("lock_in");
  const failed = run.eval ? !run.eval.passed : run.status !== "completed";
  const canBlame = failed && !!run.task_id && run.mode !== "replay";
  const blamed = blames.some((b) => b.report?.blamed);

  async function act(name: string, call: () => Promise<{ id?: string; run_id?: string }>, to: (r: any) => string) {
    setBusy(name);
    setError(undefined);
    try {
      navigate(to(await call()));
    } catch (e) {
      setError((e as Error).message);
      setBusy(undefined);
    }
  }

  return (
    <div className="run-actions">
      {run.mode !== "replay" && !config.actions.replay && replays.length > 0 && (
        // Read-only demo: nothing can run, but a replay made earlier can still be opened.
        <a className="button-link" href={`#/runs/${replays[0].id}`} title="This run replayed from its recordings">
          ↺ See its replay
        </a>
      )}
      {run.mode !== "replay" && config.actions.replay && (
        <button
          onClick={() => act("replay", () => api.replay(run.id), (r) => `#/runs/${r.run_id}`)}
          disabled={!!busy}
          title="Re-run from the recordings: offline, free, checked against this run"
        >
          {busy === "replay" ? "Replaying…" : "↺ Replay"}
        </button>
      )}
      <ComparePanel key={run.id} run={run} />
      {canBlame && !config.static && (
        <button
          className="primary"
          onClick={() => act("blame", () => api.createBlame(run.id), (r) => `#/blames/${r.id}`)}
          disabled={!!busy || !blameAction.allowed}
          title={blameAction.why ?? "Find the step at fault, and prove it by forking"}
        >
          {busy === "blame" ? "Starting…" : "🔍 Blame"}
        </button>
      )}
      {blamed && lockIn.allowed && <LockInButton runId={run.id} />}
      {error && <span className="error-text">{error}</span>}
    </div>
  );
}

/** One line saying what this run is: a blamed failure, a replay, or a fork. */
export function RunBanner({ run, blames }: { run: RunSummary; blames: BlameInfo[] }) {
  const blame = blames.find((b) => b.report?.blamed) ?? blames[0];
  if (run.mode === "replay") {
    const report = run.replay_report;
    return (
      <div className={`banner ${report?.identical ? "banner-ok" : "banner-warn"}`}>
        ↺ Replay of <a href={`#/runs/${run.parent_run_id}`} className="mono">{run.parent_run_id?.slice(0, 8)}</a>,
        served from its recordings with no model or tool calls.{" "}
        {report && (report.identical ? `Identical: all ${report.spans_compared} spans match.` : `${report.differences.length} differences: ${report.differences[0]}`)}
        {report && !report.identical && report.differences[0]?.includes("system_instruction") && (
          <div className="banner-note">
            The agent's prompt has changed since this run was recorded (for example, a fix was
            shipped), so the replay stops at the first model call. That's replay doing its job: it
            only reproduces a run when the code is the same, and otherwise shows what changed.
          </div>
        )}
      </div>
    );
  }
  if (run.mode === "fork") {
    return (
      <div className="banner">
        ⑂ {run.fork_override ? "Fork" : "Control run"} of{" "}
        <a href={`#/runs/${run.parent_run_id}`} className="mono">{run.parent_run_id?.slice(0, 8)}</a>
        {run.fork_override ? ", with a change" : ", with no change"}: steps before the fork point were
        replayed (↺), the rest ran live.{" "}
        {run.fork_id && <a href={`#/forks/${run.fork_id}`}>See the whole fork →</a>}{" "}
        {run.parent_run_id && <a href={`#/diff/${run.parent_run_id}/${run.id}`}>Diff with the original →</a>}
      </div>
    );
  }
  if (blame?.report?.blamed) {
    const b = blame.report.blamed;
    return (
      <div className="banner banner-fault">
        ⚑ <strong>Step {b.step} is at fault</strong>, verified by forking:{" "}
        {b.verification?.passed}/{b.verification?.n} pass with the correction,{" "}
        {b.verification?.control_passed}/{b.verification?.n} without ({blame.report.confidence} confidence).{" "}
        <a href={`#/blames/${blame.id}`}>See the blame →</a>
      </div>
    );
  }
  if (blame) {
    return (
      <div className="banner">
        🔍 Blame {blame.status === "done" ? "finished: not proved" : `${blame.status}…`}{" "}
        <a href={`#/blames/${blame.id}`}>Open →</a>
      </div>
    );
  }
  return null;
}
