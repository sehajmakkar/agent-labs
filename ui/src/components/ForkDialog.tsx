import { useState } from "react";

import { api, type Override, type RunSummary, type Span } from "../api";
import { navigate, useLoad } from "../lib/hooks";

/**
 * The override editor. Everything before the chosen span is replayed from the recording; from
 * there the agent runs live with the change, N times, next to N controls without it.
 */
export function ForkDialog({
  run,
  span,
  spans,
  onClose,
}: {
  run: RunSummary;
  span: Span;
  spans: Span[];
  onClose: () => void;
}) {
  const modelCall = modelCallFor(span, spans);
  const recorded = useLoad(
    () => (modelCall ? api.recordings(modelCall.id) : Promise.resolve([])),
    `fork-${modelCall?.id}`,
  );
  const models = useLoad(api.models, "models");
  const recordedPrompt = systemText(recorded.data?.[0]?.request?.config?.system_instruction);

  const [changePrompt, setChangePrompt] = useState(span.kind !== "tool");
  const [prompt, setPrompt] = useState<string>();
  const [model, setModel] = useState("");
  const [toolOutput, setToolOutput] = useState(
    span.kind === "tool" ? JSON.stringify(span.output, null, 2) : "",
  );
  const [n, setN] = useState(5);
  const [control, setControl] = useState(true);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const promptText = prompt ?? recordedPrompt;
  const where =
    span.kind === "tool"
      ? `the ${span.attributes["gen_ai.tool.name"]} call: its result is replaced, then the next model call runs live`
      : "this step: its model call runs again, live";

  async function submit() {
    setError(undefined);
    const override: Override = {};
    if (changePrompt && promptText !== recordedPrompt) override.system_prompt = promptText;
    if (model) override.model = model;
    if (span.kind === "tool") {
      try {
        const parsed = JSON.parse(toolOutput);
        if (JSON.stringify(parsed) !== JSON.stringify(span.output)) override.tool_output = parsed;
      } catch {
        setError("The tool output isn't valid JSON");
        return;
      }
    }
    setBusy(true);
    try {
      const fork = await api.createFork({ run_id: run.id, span_id: span.id, override, n, control });
      navigate(`#/forks/${fork.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <h2>⑂ Fork from here</h2>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <p className="muted">
          Steps before this point are replayed from the recording, exactly. The fork starts at{" "}
          {where}.
        </p>

        {span.kind === "tool" && (
          <label className="field">
            <span>Tool result (JSON)</span>
            <textarea
              rows={7}
              className="mono"
              value={toolOutput}
              onChange={(e) => setToolOutput(e.target.value)}
            />
          </label>
        )}

        <label className="checkbox">
          <input
            type="checkbox"
            checked={changePrompt}
            onChange={(e) => setChangePrompt(e.target.checked)}
          />
          Change the system prompt
        </label>
        {changePrompt && (
          <textarea
            rows={9}
            value={promptText}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={recorded.loading ? "Loading the recorded prompt…" : "System prompt"}
          />
        )}

        <div className="field-row">
          <label className="field">
            <span>Model for the live part</span>
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">Same as the run ({run.model})</option>
              {Object.entries(models.data ?? {}).map(([tier, id]) => (
                <option key={id} value={id}>
                  {tier}: {id}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Runs (N)</span>
            <input
              type="number"
              min={1}
              max={20}
              value={n}
              onChange={(e) => setN(Number(e.target.value))}
            />
          </label>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={control} onChange={(e) => setControl(e.target.checked)} />
          Also run N times without the change (a control), to prove the change is what helped
        </label>

        {error && <p className="error-text">{error}</p>}
        <footer className="modal-foot">
          <span className="muted">
            {control ? 2 * n : n} live runs; the model is called only from the fork point on.
          </span>
          <button onClick={submit} disabled={busy}>
            {busy ? "Queuing…" : `Fork ${n}×`}
          </button>
        </footer>
      </div>
    </div>
  );
}

/** The model call whose prompt a fork at `span` would change. */
function modelCallFor(span: Span, spans: Span[]): Span | undefined {
  if (span.kind === "llm") return span;
  const parentId = span.kind === "step" ? span.id : span.parent_span_id;
  return spans.find((s) => s.kind === "llm" && s.parent_span_id === parentId);
}

function systemText(instruction: unknown): string {
  if (typeof instruction === "string") return instruction;
  const parts = (instruction as { parts?: { text?: string }[] })?.parts;
  return Array.isArray(parts) ? parts.map((p) => p.text ?? "").join("\n") : "";
}
