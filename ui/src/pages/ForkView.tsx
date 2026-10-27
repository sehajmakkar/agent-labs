import { useEffect } from "react";

import { api, type ForkGroup, type RunSummary } from "../api";
import { Outcome } from "../components/RunStatus";
import { localTime, money, truncate } from "../lib/format";
import { navigate, useLoad } from "../lib/hooks";

/** One fork job: what changed, where, and whether it helped compared with the control. */
export function ForkView({ id }: { id: string }) {
  const detail = useLoad(() => api.fork(id), id);
  const status = detail.data?.fork.status;

  // Poll while a worker is on it.
  useEffect(() => {
    if (status !== "queued" && status !== "running") return;
    const timer = window.setInterval(detail.reload, 2000);
    return () => window.clearInterval(timer);
  }, [status, detail.reload]);

  if (detail.error) return <p className="page error-text">Could not load fork: {detail.error}</p>;
  if (!detail.data) return <p className="page muted">Loading…</p>;

  const { fork, source, runs } = detail.data;
  const summary = fork.summary;
  const total = fork.n * (fork.control ? 2 : 1);
  const withChange = runs.filter((r) => r.fork_override);
  const without = runs.filter((r) => !r.fork_override);

  return (
    <div className="page">
      <a href={`#/runs/${source.id}`} className="back">
        ← Source run
      </a>
      <div className="page-head">
        <h1>
          ⑂ Fork of {source.task_id ?? source.agent_name} at {fork.label}
        </h1>
        <span className={`pill ${fork.status === "error" ? "pill-fail" : ""}`}>{fork.status}</span>
      </div>

      <section className="panel">
        <h2>The change</h2>
        <Change override={fork.override ?? {}} />
        <p className="muted">
          Everything before {fork.label} was replayed from run{" "}
          <a href={`#/runs/${source.id}`} className="mono">
            {source.id.slice(0, 8)}
          </a>
          ; from there the agent ran live, {fork.n}× with the change
          {fork.control ? ` and ${fork.n}× without it` : ""}.
        </p>
      </section>

      {fork.status === "queued" && (
        <p className="panel">
          Waiting for a worker. <code>lab ui</code> runs forks of the demo agents itself; for your
          own agent, run <code>lab worker --entry your_app.py:your_agent</code> in its repo.
        </p>
      )}
      {fork.status === "running" && (
        <p className="panel">
          Running: {runs.length} of {total} runs done…
        </p>
      )}
      {fork.status === "error" && <p className="panel error-text">{fork.error}</p>}

      {summary && (
        <div className="cards">
          <Rate label="With the change" group={summary.fork} good />
          {summary.control && <Rate label="Without it (control)" group={summary.control} />}
          {summary.p_value != null && (
            <div className="card">
              <div className="eyebrow">How sure</div>
              <div className="card-value">p = {summary.p_value.toFixed(4)}</div>
              <div className="muted">Fisher's exact test: below 0.05 is unlikely to be luck</div>
            </div>
          )}
        </div>
      )}
      {summary && <p className="verdict">{summary.verdict}</p>}

      <div className="fork-groups">
        <RunList title="With the change" runs={withChange} />
        {fork.control && <RunList title="Without it (control)" runs={without} />}
      </div>
      <p className="muted">
        Queued {localTime(fork.created_at)}
        {fork.worker ? ` · run by ${fork.worker}` : ""}
      </p>
    </div>
  );
}

function Change({ override }: { override: Record<string, unknown> }) {
  const entries = Object.entries(override);
  if (entries.length === 0) return <p>No change: every run is a control.</p>;
  return (
    <dl className="change">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key.replace("_", " ")}</dt>
          <dd>
            <pre className={key === "system_prompt" ? "prose" : "json"}>
              {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
            </pre>
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Rate({ label, group, good = false }: { label: string; group: ForkGroup; good?: boolean }) {
  const scored = group.passed != null;
  return (
    <div className={`card ${good ? "card-accent" : ""}`}>
      <div className="eyebrow">{label}</div>
      <div className="card-value">{scored ? `${group.passed}/${group.n}` : `${group.n} runs`}</div>
      <div className="muted">{scored ? "runs passed the task's checks" : "not scored"}</div>
    </div>
  );
}

function RunList({ title, runs }: { title: string; runs: RunSummary[] }) {
  return (
    <section>
      <h2>{title}</h2>
      {runs.length === 0 && <p className="muted">No runs yet.</p>}
      <table className="table">
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className="clickable" onClick={() => navigate(`#/runs/${run.id}`)}>
              <td>
                <Outcome run={run} />
              </td>
              <td className="muted">{truncate(run.answer ?? run.error ?? "", 110)}</td>
              <td className="num">{money(run.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
