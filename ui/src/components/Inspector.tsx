import { useState, type ReactNode } from "react";

import { api, type Recording, type RunSummary, type Span } from "../api";
import { money, tokens } from "../lib/format";
import { useLoad } from "../lib/hooks";
import { ForkDialog } from "./ForkDialog";

/** Everything recorded about one span. For a model call, that is the exact prompt and reply. */
export function Inspector({
  span,
  spans,
  run,
  openFork = false,
  onClose,
}: {
  span: Span;
  spans: Span[];
  run: RunSummary;
  openFork?: boolean;
  onClose: () => void;
}) {
  const [forking, setForking] = useState(openFork);
  const forkable = span.kind !== "agent" && run.mode !== "replay";
  const recordings = useLoad(
    () => (span.kind === "llm" || span.kind === "tool" ? api.recordings(span.id) : Promise.resolve([])),
    span.id,
  );
  const recording = recordings.data?.[0];

  return (
    <aside className="inspector">
      <header className="inspector-head">
        <div>
          <div className="eyebrow">{span.kind}</div>
          <h2>{span.name}</h2>
          <div className="muted">
            {(span.duration_ms / 1000).toFixed(2)}s
            {span.kind === "llm" &&
              ` · ${tokens(span.input_tokens)} in · ${tokens(span.output_tokens)} out` +
                (span.thinking_tokens ? ` · ${tokens(span.thinking_tokens)} thinking` : "") +
                ` · ${money(span.cost_usd)}`}
            {span.status === "error" && <span className="pill pill-error">error</span>}
          </div>
        </div>
        <button className="icon-button" onClick={onClose} aria-label="Close inspector">
          ×
        </button>
      </header>

      {forkable && (
        <button className="fork-button" onClick={() => setForking(true)}>
          ⑂ Fork from here
        </button>
      )}
      {forking && (
        <ForkDialog run={run} span={span} spans={spans} onClose={() => setForking(false)} />
      )}

      {span.error && (
        <Section title="Error">
          <pre className="error-text">{span.error}</pre>
        </Section>
      )}

      {span.kind === "llm" && recording && <ModelCall recording={recording} />}
      {span.kind === "llm" && !recording && !recordings.loading && !span.error && (
        <p className="muted">No recording for this call.</p>
      )}

      {span.kind === "tool" && (
        <>
          <Section title="Arguments (written by the model)">
            <Json value={span.input} />
          </Section>
          {!span.error && (
            <Section title="Result (sent back to the model)">
              <Json value={span.output} />
            </Section>
          )}
        </>
      )}

      {span.kind === "agent" && (
        <>
          <Section title="Input">
            <Json value={span.input} />
          </Section>
          <Section title="Output">
            <Json value={span.output} />
          </Section>
        </>
      )}

      {span.kind === "step" && (
        <p className="muted">
          A step is one model decision plus the tool calls it asked for. Forking here replays
          everything before it and lets the model decide this step again, with your change.
        </p>
      )}

      <details>
        <summary>Attributes</summary>
        <table className="attributes">
          <tbody>
            {Object.entries(span.attributes).map(([key, value]) => (
              <tr key={key}>
                <th>{key}</th>
                <td>{typeof value === "object" ? JSON.stringify(value) : String(value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      {recording && (
        <details>
          <summary>Raw recording · hash {recording.request_hash.slice(0, 12)}…</summary>
          <p className="muted">
            The exact request and response. Replay (Phase 3) finds this recording by the request's
            hash.
          </p>
          <Json value={{ request: recording.request, response: recording.response }} />
        </details>
      )}
    </aside>
  );
}

function ModelCall({ recording }: { recording: Recording }) {
  const config = recording.request?.config ?? {};
  const contents: any[] = recording.request?.contents ?? [];
  const declarations: any[] = (config.tools ?? []).flatMap((t: any) => t.function_declarations ?? []);
  const candidate = recording.response?.candidates?.[0];
  const replyParts: any[] = candidate?.content?.parts ?? [];

  return (
    <>
      <Section title="System instruction">
        <pre className="prose">{systemText(config.system_instruction)}</pre>
      </Section>
      {declarations.length > 0 && (
        <Section title={`Tools offered (${declarations.length})`}>
          <ul className="tool-list">
            {declarations.map((d) => (
              <li key={d.name}>
                <code>{d.name}</code> <span className="muted">{d.description}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      <Section title={`Conversation sent (${contents.length} turns)`}>
        {contents.map((content, i) => (
          <Turn key={i} role={roleOf(content)} parts={content.parts ?? []} />
        ))}
      </Section>
      <Section title={`Model reply${candidate?.finish_reason ? ` · ${candidate.finish_reason}` : ""}`}>
        <Turn role="model" parts={replyParts} />
      </Section>
    </>
  );
}

function roleOf(content: any): string {
  const parts: any[] = content.parts ?? [];
  if (content.role === "user" && parts.some((p) => p.function_response)) return "tool results";
  return content.role ?? "?";
}

function Turn({ role, parts }: { role: string; parts: any[] }) {
  const visible = parts.filter((p) => p.text || p.function_call || p.function_response);
  return (
    <div className={`turn turn-${role.replace(" ", "-")}`}>
      <div className="turn-role">{role}</div>
      {visible.length === 0 && <div className="muted">(no visible content)</div>}
      {visible.map((part, i) => {
        if (part.function_call) {
          const call = part.function_call;
          return (
            <div key={i} className="part part-call">
              → <code>{call.name}</code>({JSON.stringify(call.args)})
            </div>
          );
        }
        if (part.function_response) {
          const r = part.function_response;
          return (
            <div key={i} className="part part-result">
              ← <code>{r.name}</code> <Json value={r.response} inline />
            </div>
          );
        }
        return (
          <div key={i} className={part.thought ? "part part-thought" : "part"}>
            {part.thought && <span className="pill">thinking</span>}
            {part.text}
          </div>
        );
      })}
    </div>
  );
}

function systemText(instruction: unknown): string {
  if (typeof instruction === "string") return instruction;
  const parts = (instruction as any)?.parts;
  if (Array.isArray(parts)) return parts.map((p: any) => p.text ?? "").join("\n");
  return instruction == null ? "(none)" : JSON.stringify(instruction, null, 2);
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="inspector-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function Json({ value, inline = false }: { value: unknown; inline?: boolean }) {
  return <pre className={inline ? "json json-inline" : "json"}>{JSON.stringify(value, null, 2)}</pre>;
}
