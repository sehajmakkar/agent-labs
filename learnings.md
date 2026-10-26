# Learnings

Concepts learned while building. Each entry: what it is, why it matters here, and a source if any.

---

## 2026-10-27 — Market research

### Agent observability vs. agent analytics are different products
- **Observability / tracing** (Maxim, Laminar, Raga AI, Langfuse) records the *mechanics* of a run:
  every LLM call, tool call, latency, tokens, errors, as nested spans.
- **Analytics** (Agnost AI) reads conversations to find *what users wanted and how they felt*:
  intents, sentiment, frustration patterns. Tool calls are events grouped into sessions.
- Our decision-tree-and-replay idea sits on the observability side.

### OpenTelemetry GenAI semantic conventions
- OpenTelemetry (OTel) is the open standard for traces/metrics/logs. Its "GenAI semantic conventions"
  define standard span names and attributes for model calls, tool execution, retrieval and agent runs.
- As of mid-2026 they are still marked **Development** (not Stable) and moved to their own repo
  (`open-telemetry/semantic-conventions-genai`) in June 2026. Expect renames: pin the version.
- Why it matters: if our traces follow these conventions, other tools can read them and we can ingest
  traces from agents we didn't write.

### Deterministic replay vs. counterfactual replay
- **Deterministic replay:** re-run a recorded trace with every model/tool response served from the
  recording. It explains *what happened* and should reproduce the run exactly.
- **Counterfactual replay:** change something at step N (prompt, tool output, model), serve steps
  before N from the recording, and run live from N onward. It tests *what would have happened*.
- Tools with side effects (sending email, writing to a database) must be mocked during counterfactual
  replay, or the replay would repeat them.
- LLMs are nondeterministic even at temperature 0, so a live replay can differ for reasons other than
  your change. Record sampling parameters and run several samples before trusting a difference.

## 2026-10-27 — How observability tools plug into someone else's agent

### Three integration patterns
1. **Wrap the client:** replace `client` with `wrap(client)`, so every model call passes through the
   tool. Works for custom loops.
2. **Decorators:** `@observe()` (Langfuse) or `@tool` / `@agent` mark functions so each call becomes a
   span. Works for custom loops.
3. **Auto-instrumentation:** an OpenTelemetry instrumentor patches a framework (LangGraph, Google
   ADK, …) once at startup, so users write no tracing code.

Vendors offer all three because their customers use a mix of frameworks and hand-written loops.

### Intercept at the boundaries, not inside the loop
Every agent, whether framework or custom, ends up calling (a) a model client and (b) tool
functions. If recording and replay happen at those two boundaries, the loop in between can be
anything. That is what makes our replay framework-agnostic.

### Fork already exists. The loop around it is what's new.
- Laminar's debugger reruns from a span, with earlier LLM calls mocked from the recording.
- LangGraph time travel forks from a checkpoint, but *re-executes* the nodes, so the LLM is called
  again.
- Neither does automatic blame, diffs, or "rerun N times and compare pass rates." That is our gap
  (decisions.md D-008).

## 2026-10-27 — Worked example: the double-charge refund

Customer: *"I was charged twice for order 4417, please refund the duplicate."*

| Step | What happened |
|---|---|
| 1 | LLM → `get_order("4417")` |
| 2 | Tool → order found |
| 3 | LLM → `get_payments("4417")` → tool returns `{"error": "timeout"}` |
| 4 | LLM ignores the error and calls `refund("P-1001")`, an ID it **made up** |
| 5 | Tool → `{"error": "payment not found"}` |
| 6 | LLM tells the customer: "Your refund is done!" ✗ |

- **Blame:** the visible failure is at step 6 (a false claim), but the *first wrong step* is 4.
  Step 3 is an environment fault. Step 4 is the agent's fault: it should have retried or escalated
  instead of inventing an ID. Blame proposes candidates and checks each one with a fork.
- **Fork:** fork at step 4 with a system-prompt rule ("never invent IDs; on a tool error, retry once,
  then escalate"). Steps 1–3 are replayed from the recording, so the timeout happens again. Step 4
  onward runs live: the agent retries, gets both payments, refunds the duplicate, and passes **5/5**
  times.
- **Diff:** original vs. fork are identical for steps 1–3 and split at step 4 (`refund("P-1001")`
  vs. a retried `get_payments`). The fork has 2 extra steps, about 900 more tokens, and the outcome
  goes from fail to pass.
