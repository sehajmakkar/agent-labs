import { useState } from "react";

import { api, type DiffResult, type DiffRow, type DiffSide, type DiffStep } from "../api";
import { Outcome } from "../components/RunStatus";
import { compact, money, seconds, tokens, truncate } from "../lib/format";
import { navigate, useLoad } from "../lib/hooks";

const MARK = { same: "=", changed: "≠", added: "+", removed: "−" } as const;

/** Two runs side by side: aligned steps, the first divergence, and what it changed downstream. */
export function DiffView({ a, b }: { a: string; b: string }) {
  const diff = useLoad(() => api.diff(a, b), `${a}-${b}`);
  const [hideSame, setHideSame] = useState(false);
  if (diff.error) return <p className="page error-text">Could not diff: {diff.error}</p>;
  if (!diff.data) return <p className="page muted">Loading…</p>;
  const d = diff.data;

  return (
    <div className="page diff-page">
      <div className="page-head">
        <h1>Trajectory diff</h1>
        <div className="toolbar">
          <label className="checkbox">
            <input type="checkbox" checked={hideSame} onChange={(e) => setHideSame(e.target.checked)} />
            Hide identical steps
          </label>
          <button onClick={() => navigate(`#/diff/${b}/${a}`)}>⇄ Swap</button>
        </div>
      </div>

      <div className="diff-sides">
        <Side label="A" side={d.a} run={d.a_run} />
        <Side label="B" side={d.b} run={d.b_run} />
      </div>

      {d.divergence ? (
        <p className="callout callout-warn">
          <strong>First divergence:</strong> {d.divergence.summary}
        </p>
      ) : (
        <p className="callout callout-ok">No divergence: both runs made the same decisions.</p>
      )}

      <Effects a={d.a} b={d.b} effects={d.effects} />

      <section className="diff-rows">
        <div className="diff-row diff-head">
          <span />
          <span>A · {d.a.run_id.slice(0, 8)}</span>
          <span>B · {d.b.run_id.slice(0, 8)}</span>
        </div>
        {groupRows(d, hideSame).map((item, i) =>
          "hidden" in item ? (
            <div key={i} className="diff-row diff-collapsed">
              <span />
              <span className="muted">{item.hidden} identical steps</span>
              <span />
            </div>
          ) : (
            <RowView key={i} row={item.row} isDivergence={item.index === d.divergence?.row} />
          ),
        )}
      </section>

      {d.a.answer !== d.b.answer && (
        <section className="panel">
          <h2>Final answer, A → B</h2>
          <p className="muted">{Math.round(d.answer_similarity * 100)}% of words shared</p>
          <p className="word-diff">
            {d.answer_diff.map((part, i) =>
              part.op === "equal" ? (
                <span key={i}>{part.text}</span>
              ) : part.op === "delete" ? (
                <del key={i}>{part.text}</del>
              ) : (
                <ins key={i}>{part.text}</ins>
              ),
            )}
          </p>
        </section>
      )}
    </div>
  );
}

function groupRows(d: DiffResult, hideSame: boolean) {
  const items: ({ row: DiffRow; index: number } | { hidden: number })[] = [];
  d.rows.forEach((row, index) => {
    const last = items[items.length - 1];
    if (hideSame && row.status === "same") {
      if (last && "hidden" in last) last.hidden += 1;
      else items.push({ hidden: 1 });
    } else {
      items.push({ row, index });
    }
  });
  return items;
}

function Side({ label, side, run }: { label: string; side: DiffSide; run: DiffResult["a_run"] }) {
  return (
    <a className="diff-side card" href={`#/runs/${side.run_id}`}>
      <div className="eyebrow">
        Run {label} · {side.mode}
      </div>
      <div className="mono">{side.run_id.slice(0, 8)}</div>
      <div>
        {side.agent} · {side.model}
      </div>
      <Outcome run={run} />
    </a>
  );
}

function Effects({ a, b, effects }: { a: DiffSide; b: DiffSide; effects: string[] }) {
  const outcome = (s: DiffSide) =>
    s.passed == null ? s.status : s.passed ? "✓ passed" : `✗ ${s.category}`;
  const rows: [string, string, string][] = [
    ["Outcome", outcome(a), outcome(b)],
    ["Steps", String(a.steps), String(b.steps)],
    ["Tokens", tokens(a.tokens), tokens(b.tokens)],
    ["Cost", money(a.cost_usd), money(b.cost_usd)],
    ["Time", seconds(a.duration_s), seconds(b.duration_s)],
  ];
  return (
    <section className="panel">
      <h2>Downstream effects</h2>
      <table className="effects">
        <thead>
          <tr>
            <th />
            <th>A</th>
            <th>B</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, x, y]) => (
            <tr key={name} className={x !== y ? "effect-changed" : undefined}>
              <th>{name}</th>
              <td>{x}</td>
              <td>{y}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {effects.some((e) => e.includes("live calls only")) && (
        <p className="muted">A replay or fork pays only for its live calls; its replayed steps cost nothing.</p>
      )}
    </section>
  );
}

function RowView({ row, isDivergence }: { row: DiffRow; isDivergence: boolean }) {
  return (
    <div className={`diff-row diff-${row.status} ${isDivergence ? "diff-divergence" : ""}`}>
      <span className="diff-mark" title={row.status}>
        {MARK[row.status]}
      </span>
      <StepCell step={row.a} other={row.b} />
      <StepCell step={row.b} other={row.a} />
      {row.status === "changed" && row.notes.length > 0 && (
        <div className="diff-notes">{row.notes.join(" · ")}</div>
      )}
    </div>
  );
}

function StepCell({ step, other }: { step: DiffStep | null; other: DiffStep | null }) {
  if (!step) return <div className="diff-cell diff-empty" />;
  return (
    <div className="diff-cell">
      <div className="diff-step-head">
        Step {step.index}
        {step.replayed && <span className="pill">↺ recorded</span>}
        {step.attempts > 1 && <span className="pill">{step.attempts} attempts</span>}
      </div>
      {step.error && <div className="error-text">✗ {step.error}</div>}
      {step.calls.map((call, i) => {
        const twin = other?.calls.find((c) => c.name === call.name);
        const sameResult = twin && JSON.stringify(twin.output) === JSON.stringify(call.output);
        return (
          <div key={i} className="diff-call">
            <code>
              → {call.name}({compact(call.args, 60)})
            </code>
            <div className={`diff-result ${twin && !sameResult ? "diff-hl" : ""}`}>
              {call.error ? `✗ ${call.error}` : `← ${compact(call.output, 90)}`}
            </div>
          </div>
        );
      })}
      {step.text && <div className="diff-text">“{truncate(step.text, 260)}”</div>}
    </div>
  );
}
