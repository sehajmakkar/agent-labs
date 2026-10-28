import { useState } from "react";

import { api } from "../api";
import { FamilyTree } from "../components/FamilyTree";
import { Inspector } from "../components/Inspector";
import { RunActions, RunBanner } from "../components/RunActions";
import { Outcome } from "../components/RunStatus";
import { TraceTree } from "../components/TraceTree";
import { activeSeconds, money, seconds, tokens } from "../lib/format";
import { navigate, useLoad } from "../lib/hooks";

type Tab = "tree" | "conversation" | "family";

export function RunView({
  id,
  spanId,
  openFork = false,
}: {
  id: string;
  spanId?: string;
  openFork?: boolean;
}) {
  const detail = useLoad(() => api.run(id), id);
  const [tab, setTab] = useState<Tab>("tree");
  if (detail.error) return <p className="page error-text">Could not load run: {detail.error}</p>;
  if (!detail.data) return <p className="page muted">Loading…</p>;

  const { run, spans, replays, forks, blames } = detail.data;
  const blamedSpan = blames.find((b) => b.report?.blamed)?.report?.blamed?.span_id;
  const selected = spans.find((s) => s.id === spanId);
  const select = (span?: string) =>
    navigate(span ? `#/runs/${id}?span=${span}` : `#/runs/${id}`, true);
  const back = run.eval ? { href: `#/evals/${run.eval.eval_run_id}`, label: "Eval" } : { href: "#/runs", label: "Runs" };
  const failedChecks = run.eval?.checks.filter((c) => !c.passed).length ?? 0;
  const family = replays.length + forks.length;

  return (
    <div className="run-view">
      <header className="run-head">
        <a href={back.href} className="back">
          ← {back.label}
        </a>
        <div className="run-title-row">
          <div className="run-title">
            <h1>{run.task_id ?? run.agent_name}</h1>
            <Outcome run={run} />
          </div>
          <RunActions run={run} blames={blames} />
        </div>
        <div className="run-meta">
          {run.agent_name} · {run.model} · {seconds(activeSeconds(run))} · {tokens(run.tokens)} tokens ·{" "}
          {money(run.cost_usd)} · <span className="mono">run {run.id.slice(0, 8)}</span>
        </div>
        <RunBanner run={run} blames={blames} />
        <nav className="tabs">
          <TabButton current={tab} value="tree" onClick={setTab}>
            Decision tree
          </TabButton>
          <TabButton current={tab} value="conversation" onClick={setTab}>
            Conversation & checks{failedChecks ? ` (${failedChecks} failed)` : ""}
          </TabButton>
          <TabButton current={tab} value="family" onClick={setTab}>
            Replays & forks{family ? ` (${family})` : ""}
          </TabButton>
        </nav>
      </header>

      {tab === "tree" && (
        <div className={selected ? "tree-area with-inspector" : "tree-area"}>
          <div className="tree">
            <TraceTree spans={spans} selectedId={spanId} blamedId={blamedSpan} onSelect={(s) => select(s)} />
            {!selected && <p className="tree-hint">Click any step, model call or tool call to see exactly what it saw and did.</p>}
          </div>
          {selected && (
            <Inspector key={selected.id} span={selected} spans={spans} run={run} openFork={openFork} onClose={() => select()} />
          )}
        </div>
      )}

      {tab === "conversation" && (
        <div className="page conversation">
          <section className="panel">
            <div className="eyebrow">User</div>
            <p>{run.message}</p>
          </section>
          <section className="panel">
            <div className="eyebrow">Agent answer</div>
            <p className={run.answer ? "answer" : "muted"}>{run.answer ?? run.error ?? "(no answer)"}</p>
          </section>
          {run.eval && (
            <section className="panel">
              <div className="eyebrow">Checks</div>
              <ul className="checks">
                {run.eval.checks.map((check, i) => (
                  <li key={i} className={check.passed ? "check-pass" : "check-fail"}>
                    <span>{check.passed ? "✓" : "✗"}</span>
                    <code>{check.type}</code>
                    {!check.passed && check.category && <span className="pill pill-fail">{check.category}</span>}
                    <span className="check-detail">{check.detail}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      {tab === "family" && (
        <div className="page">
          {family || run.parent_run_id ? (
            <FamilyTree runId={run.id} currentId={run.id} />
          ) : (
            <p className="empty">No replays or forks of this run yet. Try ↺ Replay, or open a step in the tree and fork it.</p>
          )}
        </div>
      )}
    </div>
  );
}

function TabButton({
  current,
  value,
  onClick,
  children,
}: {
  current: Tab;
  value: Tab;
  onClick: (tab: Tab) => void;
  children: React.ReactNode;
}) {
  return (
    <button className={`tab ${current === value ? "tab-active" : ""}`} onClick={() => onClick(value)}>
      {children}
    </button>
  );
}
