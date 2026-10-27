import { api, type EvalRun } from "../api";
import { Outcome, firstFailure } from "../components/RunStatus";
import { activeSeconds, localTime, money, percent, seconds, truncate } from "../lib/format";
import { navigate, useLoad } from "../lib/hooks";

export function Evals() {
  const evals = useLoad(api.evals, "evals");
  return (
    <div className="page">
      <div className="page-head">
        <h1>Eval runs</h1>
        <button onClick={evals.reload}>Refresh</button>
      </div>
      {evals.error && <p className="error-text">Could not load evals: {evals.error}</p>}
      {evals.data?.length === 0 && (
        <p className="empty">
          No eval runs yet. Try <code>lab eval datasets/support.jsonl datasets/triage.jsonl</code>
        </p>
      )}
      {!!evals.data?.length && (
        <table className="table">
          <thead>
            <tr>
              <th>Success</th>
              <th>Datasets</th>
              <th>Model · judge</th>
              <th className="num">p50</th>
              <th className="num">p95</th>
              <th className="num">Cost / task</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {evals.data.map((e) => (
              <tr key={e.id} className="clickable" onClick={() => navigate(`#/evals/${e.id}`)}>
                <td>
                  <Score run={e} />
                </td>
                <td>{e.datasets.map((d) => d.split("/").pop()).join(", ")}</td>
                <td className="muted">
                  {e.model} · {e.judge_model ?? "no judge"}
                </td>
                <td className="num">{seconds(e.metrics?.latency_p50_s)}</td>
                <td className="num">{seconds(e.metrics?.latency_p95_s)}</td>
                <td className="num">{money(e.metrics?.cost_per_task_usd)}</td>
                <td className="muted nowrap">{localTime(e.started_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function EvalView({ id }: { id: string }) {
  const detail = useLoad(() => api.eval(id), id);
  const categories = useLoad(api.failureCategories, "categories");
  if (detail.error) return <p className="page error-text">Could not load eval: {detail.error}</p>;
  if (!detail.data) return <p className="page muted">Loading…</p>;

  const { eval: e, runs } = detail.data;
  const m = e.metrics;
  // Failures first: that's what you open an eval report for.
  const ordered = [...runs].sort((a, b) => Number(a.eval?.passed) - Number(b.eval?.passed));
  const failures = Object.entries(m?.failure_categories ?? {});
  const maxCount = Math.max(1, ...failures.map(([, n]) => n));

  return (
    <div className="page">
      <a href="#/evals" className="back">
        ← Eval runs
      </a>
      <div className="page-head">
        <h1>Eval {e.id.slice(0, 8)}</h1>
        <span className="muted">
          {e.model} · judge {e.judge_model ?? "off"} · {localTime(e.started_at)}
        </span>
      </div>

      {m && (
        <div className="cards">
          <Card label="Success rate" value={percent(m.success_rate)} note={`${m.passed} of ${m.tasks} tasks`} />
          <Card label="Latency p50" value={seconds(m.latency_p50_s)} note="the typical run" />
          <Card label="Latency p95" value={seconds(m.latency_p95_s)} note="the slow tail" />
          <Card
            label="Cost per task"
            value={money(m.cost_per_task_usd)}
            note={`judge ${money(m.judge_cost_usd)} total`}
          />
        </div>
      )}

      {failures.length > 0 && (
        <section className="panel">
          <h2>How tasks failed</h2>
          {failures.map(([name, count]) => (
            <div key={name} className="bar-row" title={categories.data?.[name]}>
              <span className="bar-label">{name}</span>
              <span className="bar">
                <span style={{ width: `${(count / maxCount) * 100}%` }} />
              </span>
              <span className="bar-count">{count}</span>
              <span className="muted bar-note">{categories.data?.[name]}</span>
            </div>
          ))}
        </section>
      )}

      <table className="table">
        <thead>
          <tr>
            <th>Outcome</th>
            <th>Task</th>
            <th>Why</th>
            <th className="num">Time</th>
            <th className="num">Cost</th>
          </tr>
        </thead>
        <tbody>
          {ordered.map((run) => (
            <tr key={run.id} className="clickable" onClick={() => navigate(`#/runs/${run.id}`)}>
              <td>
                <Outcome run={run} />
              </td>
              <td>
                <div className="task-id">{run.task_id}</div>
                <div className="muted">{truncate(run.message, 70)}</div>
              </td>
              <td className="muted">{run.eval?.passed ? "" : truncate(firstFailure(run), 120)}</td>
              <td className="num">{seconds(activeSeconds(run))}</td>
              <td className="num">{money(run.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Score({ run }: { run: EvalRun }) {
  const m = run.metrics;
  if (!m) return <span className="pill">{run.status}</span>;
  const tone = m.passed === m.tasks ? "pill-pass" : "pill-fail";
  return (
    <span className={`pill ${tone}`}>
      {m.passed}/{m.tasks} · {percent(m.success_rate)}
    </span>
  );
}

function Card({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="card">
      <div className="eyebrow">{label}</div>
      <div className="card-value">{value}</div>
      <div className="muted">{note}</div>
    </div>
  );
}
