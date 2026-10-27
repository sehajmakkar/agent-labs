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

## 2026-10-27 — What an SDK is, and how ours ships

### An SDK is a library with a small, stable surface
"SDK" sounds bigger than it is. Ours is a Python package that a customer installs and imports.
What makes it an SDK rather than a pile of code is the **public surface**: the few names
customers are meant to use (`lab.init`, `lab.wrap`, `@lab.tool`, `@lab.agent`, exported from
`agentlab/__init__.py`). Everything else is internal and free to change. Keeping that surface
small is what lets a library evolve without breaking its users.

### How a Python package gets from here to a customer
1. `pyproject.toml` declares the name, version, dependencies and console commands.
2. A build backend (hatchling) runs `uv build` and produces a **wheel** (`.whl`), a zip file of
   the code plus metadata, and a source archive (`.tar.gz`).
3. A customer installs it with `pip install <wheel>` or straight from git
   (`uv add git+https://github.com/<owner>/<repo>`). Once it's published, a plain
   `pip install <name>` works.
4. `[project.scripts]` creates the `lab` command at install time; it calls `agentlab.cli:main`.

We built the wheel and installed it into an empty virtualenv: `import agentlab` and `lab --help`
both worked. Listing the wheel's contents is how C-011 was found. Look inside what you ship.

### Patterns an SDK like this relies on
- **Proxy / wrapper:** an object with the same shape as the real client that intercepts one
  method and forwards the rest (`__getattr__`). The customer swaps one line.
- **Decorator:** wraps a function to add behaviour (tracing, schema building) without changing
  how it's written or called.
- **Adapter:** translates between our neutral types and a provider's SDK, so the core never
  depends on one provider.
- **No-op by default:** importing the library does nothing until `init()`, so adding it to an
  app is safe.
- **Context propagation:** `ContextVar` holds "the current span", so nesting works without
  passing anything around.

## 2026-10-27 — Phase 2: evals

### What an eval is
An eval is a test for behaviour that isn't deterministic. A unit test asks "does this function
return 4?". An eval asks "across these 20 realistic requests, how often does the agent do the
right thing, and how does it fail when it doesn't?". It has three parts:
- a **dataset** of tasks;
- **checks** that score each run;
- **metrics** that summarise the batch.

Because the agent is nondeterministic (the same task took 2 steps once and 3 another time), one
run proves little. The success *rate* over a fixed dataset is the number to track across changes.

### Programmatic checks vs. an LLM judge
- **Programmatic** (`tool_called`, `answer_contains`, …): exact, free, instant and repeatable,
  but they can only test what you can write as code. Matching strings is brittle: "₹2,499"
  contains "2,499" but not "2499", so a check needs both spellings.
- **LLM judge:** grades *meaning* ("didn't promise a refund it can't give") against a written
  expected outcome. It costs a model call and can be wrong.
- **Use both on each task.** Code checks the hard facts; the judge checks the meaning; neither can
  pass a run on its own.

### Eval design: test outcomes, not paths
`support-two-orders` first required `get_order`. The agent used `get_shipment` instead and gave a
correct answer, and the eval failed it (C-013). An over-specified check measures how closely the
agent copies *your* plan, not whether it helped the user.
- Require a specific tool only when using it is the point: "looked up the payments before saying
  you weren't double-charged".
- Use `answer_excludes` / `tool_not_called` for things that must *never* happen.

### LLM-as-judge: structured output and biases
- **Structured output:** Gemini's `response_json_schema` constrains the reply to JSON matching a
  schema, here a pydantic `Verdict`. The reply is validated (`model_validate_json`), not scraped
  with regexes. Gemini accepted our schema as pydantic wrote it, including `anyOf` with `null` for
  "no category".
- **Reason before verdict:** `reasoning` is the first field, so the model writes its argument
  before committing to `passed`. A model generates tokens in order, so a verdict written first
  can't be informed by reasoning that comes after it.
- **Known judge biases:**
  - *Self-preference:* a judge from the same model family favours answers that sound like its own;
    ours is Flash-Lite judging Flash-Lite.
  - *Verbosity:* longer answers look more thorough.
  - *Position:* when comparing two answers, the first is favoured.
  - *Leniency:* judges tend to pass borderline cases.

  Mitigations: write expected outcomes concretely, tell the judge that tool results are ground
  truth and not to reward length, keep programmatic checks next to it, and spot-check its
  reasoning. Every verdict's reasoning is stored and shown in the UI.
- **The judge can fail too.** A failed judge call is `eval_error`, never an agent failure.
  Otherwise an outage at the judge would look like the agent getting worse.

### Failure categories
"9 of 20 passed" says little; "6 crashes, 4 eval errors" says the API failed, not the agent.
Categories follow the failure catalogue (`wrong_tool`, `invalid_arguments`, `ignored_tool_error`,
`false_claim`, `incomplete`, `inefficient`, plus run-level `crash`, `timeout` and `max_steps`).
The person writing a check knows which failure it is meant to catch, so each check carries its own
category.

### Percentiles: p50 and p95
Sort the latencies. p50 is the median (the typical run); p95 is the value that only 5% of runs
exceed (the slow tail users complain about). Averages hide the tail: one 40-second run among
nineteen 3-second ones barely moves the mean. With few runs, p95 is rough: for 20 values it falls
between the 19th and 20th, so we interpolate linearly between ranks, as numpy does by default.

### Seen live: an ignored tool error
Asked about the non-existent alert `ALR-999`, the triage agent called `get_alert`, got
`No alert with ID ALR-999`, then quietly listed all alerts and reported a full investigation of
`ALR-101` instead, never telling the user that ALR-999 doesn't exist. The answer looked expert and
confident. Only the trace shows the error being ignored in step 1 → step 2. That is the case the
lab is built for, and the first wrong step (step 2) is what Auto-Blame should find in Phase 6.

### Seen live: the traps mostly held
Flash-Lite resisted both prompt injections: the "VIP refund" in an item name, and "blame cosmic
rays" in a log line. The system prompt tells it to treat tool text as data. It also told a voided
authorization hold apart from a double charge, partly because the `get_payments` docstring
explains the statuses. Tool descriptions are part of the prompt.

## 2026-10-27 — Phase 2: rate limits, concurrency and the server

### Rate limiting: before sending, not after failing
Retrying a 429 with backoff handles a burst. It doesn't handle sustained load: four workers on a
15-requests-per-minute quota refill it the moment it empties, so every retry fails again (C-012).
A **client-side rate limiter** waits *before* sending.
- **Sliding window** (ours): remember when the last N requests were sent; a new one waits until
  the oldest is more than 60s old. It is exact and simple.
- **Token bucket:** tokens refill at a steady rate and each request spends one. It is smoother and
  allows controlled bursts. Either works at this scale.

Servers often say how long to wait. Gemini sends a `google.rpc.RetryInfo` detail
(`retryDelay: "3.6s"`), the gRPC version of HTTP's `Retry-After` header. Retries should wait at
least that long.

### Concurrency: threads, context and SQLite
- The batch runner uses a `ThreadPoolExecutor`. Model calls spend their time waiting on the
  network, which is where threads help in Python despite the GIL.
- Each new thread starts with an empty `contextvars` context, so one task's current run and span
  can't leak into another's.
- SQLite needed two settings:
  - `check_same_thread=False` lets connections from the pool be used by any thread;
  - **WAL mode** (write-ahead logging) lets the UI read while an eval writes, instead of waiting
    on a lock.

### FastAPI
- A route is a function. Its parameters become query or path parameters, and its
  `response_model` (a pydantic class) validates the output and documents it at `/docs` (OpenAPI)
  automatically.
- `TestClient` calls the app in-process, so API tests need no running server.
- The API is a thin read layer over the store. Two aggregate queries (token/cost sums and eval
  results, each grouped by run) avoid an N+1 pattern, where listing 100 runs would make 100 more
  queries.

## 2026-10-27 — Phase 2: the decision-tree UI

### Drawing a trace as a tree
- The API sends spans as a flat list with parent IDs, because that's how they're stored. The UI
  rebuilds the tree, lays it out, and hands positioned nodes and edges to React Flow, which handles
  drawing, panning, zooming and clicks.
- **Layout** (`ui/src/lib/layout.ts`): depth sets the column (agent → step → call). Each leaf
  takes the next free row, and a parent sits at the middle of its children. Nothing can overlap,
  because every leaf owns a row. The layout sorts by `seq`, because spans are saved when they
  *end*, so children arrive before their parents (C-008 again).
- **Error path:** every ancestor of a failed span gets a red border and edge, so the eye goes
  straight from the run to the bad call.

### Frontend plumbing
- **Vite** serves the app in development with instant reloads, and proxies `/api` to the Python
  server so both look like one origin (no CORS setup). `npm run build` emits static files that
  FastAPI serves.
- **Hash routing** (`#/runs/<id>?span=<id>`): the server only ever serves `index.html`, and a
  selected span is part of the URL, so a link can point straight at the failing tool call.
- **Typed API client:** `ui/src/api.ts` mirrors the pydantic response models. When one side
  changes, `tsc` or the API tests catch the mismatch.

## 2026-10-27 — Phase 3: deterministic replay

### Determinism, and where nondeterminism comes from
A program is deterministic if the same inputs always give the same outputs. An agent isn't, because
some of its inputs arrive *during* the run:
- model responses (sampled, and Gemini 3 should stay at temperature 1.0);
- tool results (the world changes);
- the clock;
- random numbers.

Replay makes a run deterministic by recording all of those inputs and feeding them back. The
agent's own code is deterministic given its inputs, so it then makes the same decisions.

### The record/replay ("VCR") pattern
The name comes from video recorders and the Ruby library VCR, which records HTTP traffic to
"cassettes" for tests.
- **Record:** at each boundary, save the request and the response.
- **Replay:** run the same code; at each boundary, look the request up and return the saved
  response instead of calling out.

Ours matches by the **hash of the exact request** (canonical JSON → SHA-256). Recordings that share
a hash form a queue in recording order, so a retried call replays as fail, fail, succeed, and two
identical questions in one run get their own answers in order.

### Divergence is information
If the replayed agent asks for something that was never recorded, its code or inputs have changed.
We stop and say *where*, by diffing the new request against the next recorded one
(`$.config.system_instruction`). Giving the support agent a refund policy made all 16 of its
Phase 2 runs diverge at exactly that path; the 14 triage runs, untouched, replayed identically.
That is regression detection for free: replay last week's runs against today's code and see what
changed.

### Replay fidelity
"Identical" means the agent made the same decisions: the same tree shape, statuses, tool arguments
and results, model outputs, token counts and final answer. It does *not* mean the same IDs,
timestamps, durations or cost, which always differ, and a replay costs $0. The README's **Replay
Fidelity** metric is the share of recorded runs that replay identically (`lab fidelity`).

### Side effects and idempotency
- During replay, *no* tool runs, read or write. Reads are served too, because the world may have
  changed since (a payment refunded since then), and the replay must see what the original saw.
- Writes are the dangerous half: a replayed refund must never move money again.
- **Idempotency** is the production version of the same worry: an operation is idempotent if doing
  it twice has the same effect as once. Payment APIs take an *idempotency key*, so a retried
  request can't double-charge. Our refund tool isn't idempotent (a second call fails: "already
  refunded"), which is exactly why replay must serve it from the recording.

### Clock and randomness
An agent that writes "Today is Tuesday" into its prompt changes its request every day, so a strict
replay would diverge. `lab.now()`, `lab.monotonic()` and `lab.random()` route these through the
interceptor: real values while recording, saved values while replaying. The loop's deadline check
reads `lab.monotonic()`, so a run that timed out at step 3 replays as a timeout at step 3.

### Seen live: replay found our bug, not the model's
The first refund run ended with "P-902 was already refunded… I've processed another refund", which
looked like a hallucination. Its replay diverged at `payments[1].status` inside the *step-1* tool
result, as resent in step 3. `get_payments` had returned a reference to live backend state, and
the later refund rewrote that earlier result in the conversation. The model accurately described
the corrupted history it was shown. Fix: tool results are deep-copied at the boundary (C-016,
D-035). Two lessons:
1. Aliasing (two names for one mutable object) can rewrite history.
2. Many "hallucinations" are bad inputs. Look at what the model was actually sent before blaming
   it; the inspector shows exactly that.

### Thought signatures, verified on real data
Every live Flash-Lite response carried a `thought_signature`, an opaque blob that must go back to
Gemini unchanged in the next turn. Replay rebuilds each response from its stored JSON (bytes as
base64), the loop resends it, and the next request hashes identically. So the signature survived
storage byte for byte (C-005).

### Schema evolution without losing data
Adding columns to existing tables is the easy kind of migration: `ALTER TABLE … ADD COLUMN`, with
nullable columns so old rows stay valid. `Store` does that automatically on startup (D-031).
Renames and type changes are the hard kind; they need versioned migrations (Alembic) and data
copying.
