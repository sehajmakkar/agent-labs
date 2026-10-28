import { useEffect } from "react";

import { api, type BlameCandidate, type ProposalStats } from "../api";
import { LockInButton } from "../components/LockInButton";
import { localTime, money } from "../lib/format";
import { useLoad } from "../lib/hooks";

/** One blame: the judge's candidates, how each fared when tested by forking, and the verdict. */
export function BlameView({ id }: { id: string }) {
  const detail = useLoad(() => api.blame(id), id);
  const status = detail.data?.blame.status;

  useEffect(() => {
    if (status !== "queued" && status !== "running") return;
    const timer = window.setInterval(detail.reload, 2500);
    return () => window.clearInterval(timer);
  }, [status, detail.reload]);

  if (detail.error) return <p className="page error-text">Could not load blame: {detail.error}</p>;
  if (!detail.data) return <p className="page muted">Loading…</p>;
  const { blame, source } = detail.data;
  const report = blame.report;

  return (
    <div className="page">
      <a href={`#/runs/${source.id}`} className="back">
        ← Failed run
      </a>
      <div className="page-head">
        <h1>🔍 Blame: {source.task_id ?? source.agent_name}</h1>
        <span className="pill">{blame.status}</span>
      </div>

      {blame.status === "queued" && (
        <p className="panel">
          Waiting for a worker. <code>lab ui</code> runs blames of the demo agents itself; for your
          own agent, run <code>lab worker --entry your_app.py:your_agent</code>.
        </p>
      )}
      {blame.status === "error" && <p className="panel error-text">{blame.error}</p>}

      {report && (
        <>
          <section className={`panel verdict-panel ${report.blamed ? "verdict-found" : ""}`}>
            <div className="eyebrow">
              Verdict
              {report.confidence && <span className={`pill confidence-${report.confidence}`}>{report.confidence} confidence</span>}
            </div>
            <p className="verdict">{report.verdict}</p>
            {report.blamed && (
              <p className="verdict-actions">
                <a href={`#/runs/${source.id}?span=${report.blamed.span_id}`}>
                  See step {report.blamed.step} in the run →
                </a>
                <LockInButton runId={source.id} />
              </p>
            )}
          </section>

          <section className="panel">
            <h2>What the judge saw</h2>
            <p>{report.analysis}</p>
            <p className="muted">
              Judge {report.judge_model} · {money(report.judge_cost_usd)} · each candidate is tested by
              forking {blame.n}× with its correction and {blame.n}× without
            </p>
          </section>

          <h2>Candidates, most likely first</h2>
          <div className="candidates">
            {report.candidates.map((c) => (
              <Candidate key={c.rank} c={c} sourceId={source.id} isBlamed={report.blamed?.rank === c.rank} />
            ))}
          </div>
        </>
      )}
      <p className="muted">Started {localTime(blame.created_at)}</p>
    </div>
  );
}

function Candidate({ c, sourceId, isBlamed }: { c: BlameCandidate; sourceId: string; isBlamed: boolean }) {
  const v = c.verification;
  return (
    <div className={`card candidate ${isBlamed ? "card-accent" : ""}`}>
      <div className="candidate-head">
        <span className="eyebrow">#{c.rank}</span>
        <a href={`#/runs/${sourceId}?span=${c.span_id}`}>
          <strong>Step {c.step}</strong>
        </a>
        {v ? (
          <span className={`pill ${v.status === "confirmed" ? "pill-pass" : v.status === "rejected" ? "pill-fail" : ""}`}>
            {v.status}
          </span>
        ) : (
          <span className="pill">not tested</span>
        )}
        {v?.decisive === true && <span className="pill">decisive</span>}
        {v?.decisive === false && <span className="pill">recoverable</span>}
      </div>
      <p>{c.reasoning}</p>
      <p className="correction">
        <span className="eyebrow">Correction tried</span> {c.correction}
      </p>
      {v && (
        <div className="evidence">
          <a href={`#/forks/${v.fork_id}`}>
            corrected {v.passed}/{v.n} vs control {v.control_passed}/{v.n}
            {v.p_value != null && ` · p = ${v.p_value.toFixed(3)}`}
          </a>
          {v.later_fork_id && (
            <a href={`#/forks/${v.later_fork_id}`}>
              same correction one step later: {v.later_passed}/{v.n}
            </a>
          )}
        </div>
      )}
    </div>
  );
}

/** How often blame finds the planted step, on the seeded failures. */
export function BlameBench() {
  const bench = useLoad(api.blameBenchmark, "blame-bench");
  if (bench.error)
    return (
      <p className="page empty">
        No benchmark yet. Run <code>lab seed-failures</code>, then <code>lab blame-bench</code>.
      </p>
    );
  if (!bench.data) return <p className="page muted">Loading…</p>;
  const { results } = bench.data;
  const judges = Object.entries(results.proposals);
  const v = results.verification;
  const bugs = [...new Set(judges.flatMap(([, s]) => Object.keys(s.by_bug)))].sort();

  return (
    <div className="page">
      <div className="page-head">
        <h1>Blame accuracy</h1>
        <span className="muted">
          {results.failures} seeded failures · {localTime(bench.data.created_at)}
        </span>
      </div>
      <p className="muted">
        Each seeded failure comes from a bug planted on purpose, so its guilty step is known. The
        judge's job: name that step. In this run the judge{" "}
        {results.judge_sees_prompt ? "saw" : "did not see"} the agent's system prompt.
      </p>

      <section className="panel">
        <h2>Does the judge rank the guilty step?</h2>
        {judges.map(([model, s]) => (
          <JudgeBars key={model} model={model} stats={s} />
        ))}
      </section>

      {v && (
        <section className="panel">
          <h2>After verifying by forking</h2>
          <div className="cards">
            <Stat label="Proposed top-1" value={v.proposed_top1} note={`${v.judge_model}, before forking`} />
            <Stat label="Verified accuracy" value={v.verified_accuracy} note="confirmed and right" />
            <Stat label="Precision" value={v.precision} note="of confirmed blames, share right" />
            <Stat label="Abstained" value={v.abstained} note="nothing confirmed, so no blame" />
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Bug</th>
                <th>Guilty step</th>
                <th>Judge's first guess</th>
                <th>Confirmed blame</th>
              </tr>
            </thead>
            <tbody>
              {v.cases_detail.map((c) => (
                <tr key={c.blame_id}>
                  <td className="mono">{c.bug}</td>
                  <td>{c.guilty_step}</td>
                  <td className={c.proposed === c.guilty_step ? "ok-text" : "bad-text"}>{c.proposed ?? "–"}</td>
                  <td>
                    <a href={`#/blames/${c.blame_id}`} className={c.blamed === c.guilty_step ? "ok-text" : c.blamed == null ? "muted" : "bad-text"}>
                      {c.blamed ?? "none"}
                      {c.confidence ? ` (${c.confidence}${c.decisive === false ? ", recoverable" : ""})` : ""}
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {bench.data.history.length > 1 && (
        <section className="panel">
          <h2>Benchmark history</h2>
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Judge saw the prompt</th>
                <th>Top-1 by judge</th>
                <th>Verified accuracy</th>
                <th>Precision</th>
              </tr>
            </thead>
            <tbody>
              {bench.data.history.map((h) => (
                <tr key={h.id}>
                  <td className="nowrap">{localTime(h.created_at)}</td>
                  <td>{h.judge_sees_prompt ? "yes" : "no"}</td>
                  <td>
                    {Object.entries(h.top1)
                      .map(([m, v]) => `${m}: ${pct(v)}`)
                      .join(" · ")}
                  </td>
                  <td>{pct(h.verified_accuracy)}</td>
                  <td>{pct(h.precision)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="panel">
        <h2>By bug: top-1 hits / cases</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Bug</th>
              {judges.map(([model]) => (
                <th key={model}>{model}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bugs.map((bug) => (
              <tr key={bug}>
                <td className="mono">{bug}</td>
                {judges.map(([model, s]) => {
                  const b = s.by_bug[bug];
                  return <td key={model}>{b ? `${b.top1}/${b.cases}` : "–"}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function JudgeBars({ model, stats }: { model: string; stats: ProposalStats }) {
  const bars: [string, number | null][] = [
    ["Top-1", stats.top1],
    ["Top-3", stats.top3],
    ["Within one step", stats.within1],
    ["Baseline: always the last step", stats.last_step_baseline],
  ];
  return (
    <div className="judge-bars">
      <div className="judge-name">
        <strong className="mono">{model}</strong>
        <span className="muted"> · {stats.cases} cases · {money(stats.cost_per_case_usd)} per case</span>
      </div>
      {bars.map(([label, value]) => (
        <div key={label} className={`bar-row ${label.startsWith("Baseline") ? "baseline" : ""}`}>
          <span className="bar-label">{label}</span>
          <span className="bar">
            <span style={{ width: `${(value ?? 0) * 100}%` }} />
          </span>
          <span className="bar-count">{value == null ? "–" : `${Math.round(value * 100)}%`}</span>
          <span />
        </div>
      ))}
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: number | null; note: string }) {
  return (
    <div className="card">
      <div className="eyebrow">{label}</div>
      <div className="card-value">{value == null ? "–" : `${Math.round(value * 100)}%`}</div>
      <div className="muted">{note}</div>
    </div>
  );
}

function pct(value: number | null | undefined): string {
  return value == null ? "–" : `${Math.round(value * 100)}%`;
}
