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

## 2026-10-27 — Phase 0: what an agent loop actually is

### The loop
An agent is a `for` loop (`src/agentlab/loop.py`):
1. Send the conversation so far, plus the list of tools, to the model.
2. If the reply asks for tool calls, run them and append the results to the conversation.
3. Go back to 1. If the reply has no tool calls, that reply is the final answer.
4. Stop after `max_steps` regardless, so a confused agent can't loop forever.

The model never runs anything itself. It only *asks* for a tool by name with arguments, and our
code decides whether and how to run it. That is why every tool call can be traced, replayed or
faked: it all goes through our code.

### Function calling on Gemini (`google-genai` 2.33)
- Tools are described to the model as `FunctionDeclaration(name, description,
  parameters_json_schema)`. The model only sees the name, the description and the JSON Schema, so the
  docstring *is* the tool's documentation for the model.
- A tool request arrives as a `function_call` part (`id`, `name`, `args`) in the model's reply.
- Results go back as `function_response` parts in a **user**-role turn, matched to their call by
  `id`.
- The SDK can call Python functions automatically. We turn that off
  (`AutomaticFunctionCallingConfig(disable=True)`) so the calls go through our loop.
- Parts with `thought=True` are thinking summaries, not the answer. Parts can also carry a
  `thought_signature`, which must be sent back exactly as received. We do that by resending the raw
  `Content` (decisions.md D-012).
- Usage metadata splits tokens into prompt, candidates (output) and thoughts (thinking). Thinking
  tokens cost money too, so we track them separately.

### Tool schemas from type hints
`@tool` reads the function's signature and builds a pydantic model from it. That one model gives the
JSON Schema for the declaration *and* validates the model's arguments before the function runs.
Models do send wrong arguments sometimes, and "invalid arguments" will be one of our failure
categories.

### Testing an agent without calling the model
`tests/test_loop.py` uses a `ScriptedLLM` that returns pre-written replies. Because the loop only
depends on the `LLMClient` interface, a fake can stand in for Gemini, so tests are free, instant and
repeatable. This is the same idea replay is built on in Phase 3: serve a known response instead of
calling the real model.

## 2026-10-27 — Phase 0: first live runs on Flash-Lite

### Parallel function calling
Asked "Was I charged twice for order 4417?", Flash-Lite called `get_order` **and** `get_payments` in
the same reply: one model turn containing two `function_call` parts. Our loop already handles this,
because it runs every call in `tool_calls` and returns all the results together in one turn.
Consequence for later phases: one LLM span can have several tool spans as siblings, so the trace is
a real tree, not a list.

### Watching the agent handle an error
Asked about order 9999, the agent got `{"error": "LookupError: No order with ID 9999"}` and told the
customer it couldn't find the order, instead of making one up. That is the behaviour D-013 is meant
to make visible. The failing version of this (an agent that ignores the error) is what Phase 6's
Blame has to catch.

### Thinking tokens
Both runs reported 0 thinking tokens on Flash-Lite. Thinking is either off or minimal by default for
this model. Token and cost accounting (Phase 1) must still handle thinking tokens, because Flash
and other settings do produce them.

## 2026-10-27 — Phase 1: tracing

### Traces, spans and logs
- A **log** is a line of text about something that happened. It has no structure linking it to
  anything else.
- A **span** is one timed unit of work, with a start, a duration, inputs, outputs, an error if any,
  and a **parent**. Here: the agent, one step, one model call, one tool call.
- A **trace** is all the spans of one request, linked by their parents into a tree. Here, one
  *run* of an agent is one trace.

Logs tell you *that* something happened. A trace tells you *where in the flow* it happened and
what caused it, which is what "find the step that went wrong" needs.

### Context propagation with `contextvars`
Nobody passes a "parent span" argument down through the agent. `tracing.py` keeps the current span
in a `ContextVar`; opening a span reads it as the parent and sets itself as current, and closing it
puts the old value back. So a tool called four levels deep still attaches to the right step.
`ContextVar` rather than a global matters once runs execute in threads or async tasks (parallel
forks in Phase 4): each gets its own current span.

### Spans are saved when they end, so order needs its own column
Children finish before their parents, so the store receives `execute_tool` before `step 1` and
`step 1` before `invoke_agent`. Each span gets a `seq` number when it *starts*, and the tree is
rebuilt by sorting on it.

### OTel GenAI conventions in practice (v1.41.0)
- Operation names: `chat` for model calls, `execute_tool`, `invoke_agent`. Span names follow
  "operation target", e.g. `chat gemini-3.5-flash-lite`.
- The provider value for the Gemini Developer API is `gcp.gemini`; Vertex AI is `gcp.vertex_ai`.
- `gen_ai.usage.output_tokens` should *include* reasoning tokens, and
  `gen_ai.usage.reasoning.output_tokens` reports them separately. Gemini's `candidates_token_count`
  *excludes* thinking, so the wrapper adds the two together for the OTel attribute.
- The registry page now marks these attributes as moved to the new
  `semantic-conventions-genai` repository. The names are the same; the spec is still in
  Development.

### Cost
cost = input × input price + (output + thinking) × output price, per million tokens. Google
bills thinking at the output price. On Flash-Lite ($0.30 in, $2.50 out) the 3-step support run
cost about $0.00055, and output tokens are over 8× more expensive than input. A verbose model
costs more than a long prompt.

### Retries: exponential backoff with jitter
Retry only failures that can pass (429 rate limit, 503 overload, timeouts), never a 400 bad
request or a 404 unknown model, because those fail the same way every time. Wait 1s, 2s, 4s…
(exponential) so an overloaded server gets room to recover. Randomise each wait (jitter) so many
clients that failed together don't all retry at the same instant.

### Recording for replay: request hashing
Each model and tool call stores its exact request and response. The request is serialised to
canonical JSON (sorted keys, fixed separators) and hashed with SHA-256, so the same request always
gives the same hash. In Phase 3, replay answers a call by looking up its hash instead of calling
Gemini. Gemini's `thought_signature` bytes are stored as base64 in JSON mode and decode back to the
exact bytes; a test checks this.

### Seen live: same question, different path
The same message ("Was I charged twice for order 4417?") ran in **2 steps** in Phase 0 (both tools
called in parallel) and in **3 steps** in Phase 1 (`get_payments`, then `get_order`, then the
answer). Both answers were right. That is the nondeterminism from C-001, seen for real: one run
proves little, which is why forks run N times and why Trajectory Diff exists.
