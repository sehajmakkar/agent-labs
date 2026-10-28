import { useState } from "react";

import { api } from "../api";

/** Save a failed run as a regression test, so CI catches the failure if it ever comes back. */
export function LockInButton({ runId }: { runId: string }) {
  const [state, setState] = useState<{ busy?: boolean; done?: string; error?: string }>({});

  async function lockIn() {
    setState({ busy: true });
    try {
      const result = await api.lockIn(runId);
      setState({ done: `${result.created ? "Saved" : "Already saved"} as ${result.task_id}` });
    } catch (e) {
      setState({ error: (e as Error).message });
    }
  }

  return (
    <span className="lock-in">
      <button onClick={lockIn} disabled={state.busy || !!state.done}>
        🔒 Save as regression test
      </button>
      {state.done && (
        <span className="ok-text">
          {state.done} · CI: <code>lab eval datasets/*.jsonl --gate 0.9</code>
        </span>
      )}
      {state.error && <span className="error-text">{state.error}</span>}
    </span>
  );
}
