import { api } from "../api";
import { Inspector } from "../components/Inspector";
import { ReplayPanel } from "../components/ReplayPanel";
import { Outcome } from "../components/RunStatus";
import { TraceTree } from "../components/TraceTree";
import { activeSeconds, money, seconds, tokens } from "../lib/format";
import { navigate, useLoad } from "../lib/hooks";

export function RunView({ id, spanId }: { id: string; spanId?: string }) {
  const detail = useLoad(() => api.run(id), id);
  if (detail.error) return <p className="page error-text">Could not load run: {detail.error}</p>;
  if (!detail.data) return <p className="page muted">Loading…</p>;

  const { run, spans, replays } = detail.data;
  const selected = spans.find((s) => s.id === spanId);
  const select = (span?: string) =>
    navigate(span ? `#/runs/${id}?span=${span}` : `#/runs/${id}`, true);
  const evalLink = run.eval ? `#/evals/${run.eval.eval_run_id}` : null;

  return (
    <div className="run-view">
      <header className="run-head">
        <div className="run-title">
          <a href={evalLink ?? "#/"} className="back">
            ← {evalLink ? "Eval" : "Runs"}
          </a>
          <h1>{run.task_id ?? run.agent_name}</h1>
          <Outcome run={run} />
        </div>
        <div className="run-stats">
          <Stat label="Agent" value={run.agent_name} />
          <Stat label="Model" value={run.model ?? "–"} />
          <Stat label="Status" value={run.status} />
          <Stat label="Time" value={seconds(activeSeconds(run))} />
          <Stat label="Tokens" value={tokens(run.tokens)} />
          <Stat label="Cost" value={money(run.cost_usd)} />
          <Stat label="Run" value={run.id.slice(0, 8)} mono />
        </div>
        <ReplayPanel run={run} replays={replays} />
        <div className="run-io">
          <div>
            <div className="eyebrow">User</div>
            <p>{run.message}</p>
          </div>
          <div>
            <div className="eyebrow">Agent answer</div>
            <p className={run.answer ? "answer" : "muted"}>
              {run.answer ?? run.error ?? "(no answer)"}
            </p>
          </div>
        </div>
        {run.eval && (
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
        )}
      </header>
      <div className={selected ? "tree-area with-inspector" : "tree-area"}>
        <div className="tree">
          <TraceTree spans={spans} selectedId={spanId} onSelect={(s) => select(s)} />
        </div>
        {selected && <Inspector span={selected} onClose={() => select()} />}
      </div>
    </div>
  );
}

function Stat({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="stat">
      <div className="eyebrow">{label}</div>
      <div className={mono ? "mono" : undefined}>{value}</div>
    </div>
  );
}
