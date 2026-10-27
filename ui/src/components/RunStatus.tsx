import type { RunSummary } from "../api";

/** The outcome of a run: its eval verdict if it was scored, otherwise how the loop ended. */
export function Outcome({ run }: { run: RunSummary }) {
  if (run.mode === "replay") {
    const report = run.replay_report;
    if (!report) return <span className="pill">↺ replaying</span>;
    return report.identical ? (
      <span className="pill pill-pass">↺ identical</span>
    ) : (
      <span className="pill pill-fail" title={report.differences[0]}>
        ↺ diverged
      </span>
    );
  }
  if (run.eval) {
    return run.eval.passed ? (
      <span className="pill pill-pass">✓ passed</span>
    ) : (
      <span className="pill pill-fail" title={firstFailure(run)}>
        ✗ {run.eval.failure_category ?? "failed"}
      </span>
    );
  }
  if (run.status === "completed") return <span className="pill">completed</span>;
  return <span className="pill pill-fail">{run.status}</span>;
}

export function firstFailure(run: RunSummary): string {
  const check = run.eval?.checks.find((c) => !c.passed);
  return check ? `${check.type}: ${check.detail}` : (run.error ?? "");
}
