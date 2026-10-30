import { api, type Preset, type RunSummary } from "../api";
import { useConfig } from "../lib/config";
import { localTime } from "../lib/format";
import { navigate, useLoad } from "../lib/hooks";

/**
 * The read-only demo's fork dialog (D-057). Nothing can run live here, so it offers forks that
 * were run ahead of time on this run, each with its real result, and says so.
 */
export function PresetForkDialog({ run, onClose }: { run: RunSummary; onClose: () => void }) {
  const presets = useLoad(api.presets, "presets");
  const config = useConfig();
  const here = (presets.data ?? []).filter((p) => p.run_id === run.id);
  const elsewhere = (presets.data ?? []).find((p) => p.run_id !== run.id);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <h2>⑂ Fork from here</h2>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        {here.length > 0 ? (
          <>
            <p className="muted">
              A fork replays everything before {here[0].label} from the recording, makes one
              change, and runs the rest live: {here[0].n} times with the change and{" "}
              {here[0].n} without. This is a read-only copy of the lab, so these forks were run
              ahead of time. Pick a change to see what really happened.
            </p>
            <div className="preset-list">
              {here.map((p) => (
                <PresetCard key={p.fork_id} preset={p} />
              ))}
            </div>
          </>
        ) : (
          <p className="muted">
            Forks make live model calls, so they're off in this read-only copy of the lab.{" "}
            {elsewhere && (
              <a href={`#/runs/${elsewhere.run_id}?span=${elsewhere.span_id}&fork=1`} onClick={onClose}>
                Try the forks that were run ahead of time on the refund run →
              </a>
            )}
          </p>
        )}
        <footer className="modal-foot">
          <span className="muted">
            To fork anything yourself, run the lab locally: <a href={config.repo}>source on GitHub</a>
          </span>
        </footer>
      </div>
    </div>
  );
}

function PresetCard({ preset: p }: { preset: Preset }) {
  const result =
    p.passed === null
      ? p.verdict
      : `${p.passed}/${p.n} pass with it · ${p.control_passed ?? "–"}/${p.n} without` +
        (p.p_value !== null ? ` · p = ${p.p_value.toFixed(3)}` : "");
  return (
    <button className="preset" onClick={() => navigate(`#/forks/${p.fork_id}`)}>
      <strong>{p.title}</strong>
      <span className="preset-change">{p.change}</span>
      <span className="preset-result">{result}</span>
      <span className="muted">Run on {localTime(p.created_at)} →</span>
    </button>
  );
}
