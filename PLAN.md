# Implementation Plan

This project has two jobs: **teach the concepts** behind agent reliability tooling, and produce a
**demo that pitches** to the companies listed under "Target Companies" below ("I can build what you build, plus Fork, Blame &
Diff"). Every phase therefore ends with three things:

- **Demo:** something you can show in under two minutes.
- **Learn:** the concepts the phase teaches (write them up in `learnings.md` as you go).
- **Pitch:** which companies the demo speaks to.

Sizes are relative (S / M / L), not calendar estimates.

## Progress

`[x]` done · `[ ]` not done. Every phase ends with its demo working and its learnings written up.

| Phase | Name | Status |
|---|---|---|
| 0 | Setup and a first agent | ✅ Done |
| 1 | Tracing SDK and trace store | ✅ Done |
| 2 | Evals and the decision tree UI | ✅ Done |
| 3 | Deterministic replay | ⏭️ Next |
| 4 | Fork & Replay | ⬜ Not started |
| 5 | Trajectory Diff | ⬜ Not started |
| 6 | Auto-Blame | ⬜ Not started |
| 7 | Experiments, regressions and CI gate | ⬜ Not started |
| 8 | Chaos testing *(stretch)* | ⬜ Not started |
| 9 | Pitch kit | ⬜ Not started |

---

## The one idea everything depends on

**The agent is replayable by construction.** Every source of nondeterminism (LLM calls, tool calls,
the clock, random numbers) goes through one *interceptor* layer. When recording, the interceptor
saves each request and response. When replaying, it returns the saved response instead of calling out.

```
            ┌──────────── Agent loop ────────────┐
            │  think → call LLM → call tool → …  │
            └───────┬───────────────┬────────────┘
                    │               │
              ┌─────▼───────────────▼─────┐
              │       Interceptor         │   mode = record | replay | fork | chaos
              └─────┬───────────────┬─────┘
                    │               │
              LLM provider    Tool simulator  ──►  Trace store (runs, spans, recordings)
```

Fork = replay up to step N, apply an override at N, then record live from N onward.
Chaos = replay, with the interceptor corrupting chosen tool responses.
Blame = an LLM judge proposes a step; a fork from that step confirms or rejects it.

Get this layer right in Phases 1–3 and the differentiators are mostly UI and orchestration on top of it.

---

## Architecture (accepted — see decisions.md D-003 to D-006, D-009)

| Layer | Choice | Why |
|---|---|---|
| Agent runner, SDK, replay engine | Python 3.12 | Most target companies' SDKs and agent frameworks are Python-first |
| API | FastAPI | Small, typed, easy to learn |
| Storage | SQLite (via SQLModel) → Postgres later | Zero setup; same schema later |
| UI | React + TypeScript (Vite) + React Flow | React Flow draws interactive node trees out of the box |
| Agent loop | Our own, with interception at the boundaries (LLM client and tool functions) | Replay needs control over every call; boundaries work under any framework (D-004) |
| LLM access | Gemini via `google-genai`, behind our own thin interface. **Flash-Lite by default**; Flash selectable | Provider chosen by Sehaj (D-005); Flash is sometimes unavailable (D-014) |
| Trace format | Own schema, field names aligned to OTel GenAI conventions (pinned version) | Interoperable later without depending on a draft spec now |

### Core data model (first draft)

- **Run:** `id, task_id, agent_version, status, parent_run_id, fork_span_id, fork_override, created_at`
- **Span:** `id, run_id, parent_span_id, kind (agent | llm | tool | eval), name, input, output, error, start, end, tokens_in, tokens_out, cost, attributes`
- **Recording:** `span_id, request_hash, response` (the data replay serves from)
- **Task:** `id, input, expected, checker` · **Eval result:** `run_id, passed, failure_category, notes`

Forks are runs with a `parent_run_id`, so the runs of one task form a tree too.

### Demo agents (the "patients")

Real-looking agents with a **deterministic simulated backend**, so writes are safe and results repeat:

1. **Support agent:** orders, refunds, account lookup. Chat-shaped, for Agnost, Cekura, Maxim, Coval.
2. **Incident triage agent:** reads simulated logs, metrics and deploy history. For DrDroid and Sentrial.
3. *(optional)* **Research / browsing agent:** long trajectories. For Browser Use, OpenHands, Laminar.

**Seeded failure catalog:** known bugs injected on purpose (wrong tool, wrong arguments, hallucinated
ID, ignored tool error, infinite loop, giving up too early, prompt injection in tool output). These
give every later feature *ground truth*: we know which step is really at fault.

---

## Phases

### Phase 0 — Setup and a first agent · S · ✅ Done

- [x] Repo layout: `src/agentlab/` (core), `agents/`, `tests/` (D-011)
- [x] Environment with uv and Python 3.12
- [x] Lint (ruff) and tests (pytest) set up
- [x] Agent loop with tool calling (`src/agentlab/loop.py`)
- [x] `@tool` decorator that builds schemas from type hints
- [x] Gemini adapter behind a provider-neutral interface (D-012)
- [x] Support agent with two read-only tools (`agents/support.py`)
- [x] CLI: `lab run` and `lab models`
- [x] Model IDs confirmed with `lab models` (C-006)
- [x] Flash-Lite made the default model (D-014)
- [x] **Demo:** a live run on Flash-Lite answers by calling tools
- [x] **Learnings** written up
- Moved: structured outputs → Phase 2 (the LLM judge needs them).
- **Learn:** what an "agent" is mechanically (a loop of model call → tool call → result →
model call), tool and function calling.
- **Pitch:** none yet.

#### How we built it

**The approach:** build the smallest agent that works, before tracing anything. You can't design
a recorder until you know what an agent actually does.

1. **A Python package from day one.**
   - `pyproject.toml` is the package's ID card: its name (`agentlab`), version, dependencies, and a
     console command (`lab = "agentlab.cli:main"`, which is why `lab` works in a terminal).
   - `hatchling`, the build backend, turns the code into a **wheel**: a zip file that `pip` or
     `uv` installs into any project.
   - `uv` manages the virtual environment, and `uv.lock` pins every dependency version so installs
     are repeatable.
   - The code lives in `src/agentlab/`. Tests import the *installed* package, as a customer would,
     not loose files that happen to be nearby (D-011).
2. **Our own types first** (`llm/base.py`).
   - `Message`, `ToolCall`, `ToolResult` and `Usage` are plain dataclasses, and the loop speaks only
     these. Gemini's SDK is hidden behind an **adapter** (`GeminiClient`) that translates both ways.
     That keeps the loop provider-neutral and lets tests swap in a fake model (D-005, D-012).
   - `LLMClient` is a `Protocol` (a type defined by its methods, not by inheritance), so any object
     with a matching `generate()` fits.
3. **`@tool` by introspection.**
   - The decorator reads the function's signature and type hints with `inspect` and
     `get_type_hints`, and builds a pydantic model from them with `create_model`.
   - That model provides both the JSON Schema sent to the model and the validation of the
     arguments the model sends back. FastAPI uses the same trick for request bodies.
   - Developers write an ordinary typed function and never write a schema by hand.
4. **The loop.** Call the model. If it asked for tools, run them, append the results and go round
   again; otherwise return its text. A tool error is returned to the model as data, never raised
   (D-013).
5. **Read the real SDK, not memory.** The `google-genai` 2.33 types decided the details:
   - function calls carry an `id`;
   - tool results go back as `function_response` parts;
   - automatic function calling is turned off;
   - responses carry thought signatures, which is why `raw` exists (C-005).
6. **Tests before live calls, then live verification.**
   - `ScriptedLLM` replays prewritten model replies, so the loop is tested offline.
   - `lab models` confirmed the real model IDs (C-006), and live runs on Flash-Lite confirmed the
     whole path.

### Phase 1 — Tracing SDK and trace store · M · ✅ Done

- [x] Run and Span models, with attribute names from the OTel GenAI conventions v1.41.0 (`semconv.py`)
- [x] Context propagation: each span knows its parent (`tracing.py`, context variables)
- [x] Interceptor in *record* mode at the LLM client and tool boundaries (D-016)
- [x] Recordings store Gemini's raw request and response; thought signatures round-trip (C-005)
- [x] SQLite trace store (SQLModel, `store.py`)
- [x] Token accounting and cost per span, from Google's published prices (D-019)
- [x] Retries with exponential backoff, a per-request timeout and a whole-run timeout (D-017)
- [x] SDK surface: `lab.init`, `lab.wrap(client)`, `@lab.tool(kind="read" | "write")`, `@lab.agent(name)`
- [x] CLI prints a run as an indented tree with tokens, cost and latency; `lab runs`, `lab show`
- [x] Step spans group each model decision with its tool calls (D-015)
- [x] **Demo:** `lab run support "..."` → tree printed in the terminal (live, Flash-Lite)
- [x] **Learnings** written up
- **Learn:** traces vs. spans vs. logs, parent/child context, OTel GenAI conventions, token
accounting and cost calculation.
- **Pitch:** none yet. This is the foundation.

#### How we built it

**The question:** how do we see every model call and tool call an agent makes, without changing
how the customer writes their agent?

1. **Studied how existing tools plug in** (learnings.md, "Three integration patterns"):
   - wrapping the model client;
   - decorators on the customer's functions;
   - OpenTelemetry auto-instrumentation, which patches libraries at import time.

   We chose a client wrapper plus decorators. It is explicit, needs no monkeypatching, and costs
   the customer about three lines (D-016).
2. **Data model before code:**
   - a run is one execution;
   - a span is one timed unit of work, with a parent, so spans form a tree;
   - a recording is the exact request and response of one call.

   The model and the attribute names (`gen_ai.*`) were borrowed from the OpenTelemetry GenAI
   conventions, read from the spec and pinned to v1.41.0, so traces can later be exported to
   standard tools (D-006).
3. **Context propagation with `ContextVar`.** The span currently open is stored in a context
   variable, and each new span makes it its parent. Nobody passes a parent through the customer's
   code. OpenTelemetry's Python SDK does the same, and it also works with threads and async code.
4. **The interceptor is a proxy object.**
   - `TracedGenAIClient` has the same shape as `genai.Client`
     (`client.models.generate_content(...)`). It intercepts that one method, which opens a `chat`
     span, makes the real call and records it, and passes every other method through with
     `__getattr__`.
   - The customer changes one line: `client = lab.wrap(genai.Client())`.
   - Tools record themselves inside `Tool.invoke`, so a call is traced whether our loop or the
     customer's code makes it.
5. **Recordings built for replay.** Each request is serialised as canonical JSON (sorted keys) and
   hashed with SHA-256, so Phase 3 can find "this exact call" again. Bytes such as thought
   signatures are stored as base64 and survive the round trip; a test checks this.
6. **Storage: SQLite via SQLModel**, in a local file. There's no server to run, and the schema is
   readable with `sqlite3`.
   - Spans are written when they end, so a `seq` number keeps their start order (C-008).
   - Times are stored in UTC and shown in local time (C-009).
7. **Safe to import into someone else's app.**
   - Until `lab.init()` is called, tracing is a no-op (D-018).
   - Retries are ours (backoff with jitter, with the SDK's own retries switched off), so every
     attempt is visible (D-017).
   - Errors are recorded and then re-raised, never swallowed.
8. **A small public API.** `agentlab/__init__.py` exports four things: `lab.init`, `lab.wrap`,
   `@lab.tool` and `@lab.agent`. Everything else is internal and can change.
9. **Verified like a customer would use it:**
   - 30 offline tests, using a fake `genai` client and `ScriptedLLM`;
   - a live run on Flash-Lite;
   - a forced 404, to check that failures are saved correctly;
   - the wheel built (`uv build`), installed into a fresh virtualenv, and confirmed that
     `import agentlab` and `lab --help` work.

**Not done yet, and worth saying in an interview:**
- Traces go to a SQLite file on the customer's machine. Sending them to a lab server over HTTP
  moves to Phase 4, next to `lab worker` (D-027).
- The package isn't on PyPI, and the name `agentlab` is already taken there.
- The wheel also ships the demo `agents/` package, which clashes with the OpenAI Agents SDK
  (C-011). *Fixed at the start of Phase 2 (D-022).*

### Phase 2 — Evals and the decision tree UI · M–L · *parity milestone* · ✅ Done

- [x] Demo agents moved into `agentlab.demo`, so the wheel no longer clashes with other packages (C-011, D-022)
- [x] Task dataset format: JSONL with input, expected outcome and checks (`evals/tasks.py`, D-023)
- [x] Programmatic checkers: `tool_called`, `tool_not_called`, `answer_contains`, `answer_excludes`, `max_steps`
- [x] LLM-as-judge checker with structured output (`evals/judge.py`, D-024)
- [x] Failure categories (crash, timeout, max_steps, wrong_tool, invalid_arguments, ignored_tool_error, false_claim, incomplete, inefficient, eval_error; D-025)
- [x] Batch runner over a dataset, tasks in parallel (`evals/runner.py`, `lab eval`)
- [x] Metrics: success rate, p50/p95 latency, cost per task, failures by category (`evals/metrics.py`)
- [x] Incident triage demo agent (`demo/triage.py`); support agent grown to six orders, three tools and four traps
- [x] 20-task dataset: `datasets/support.jsonl` (12) and `datasets/triage.jsonl` (8)
- [x] Client-side rate limiter and server retry hints, after the free tier's 15 RPM broke the first eval (C-012, D-026)
- [x] FastAPI server, read-only over the store (`src/agentlab/server.py`, `lab ui`; D-027)
- [x] UI: run list (filters: agent, failures only)
- [x] UI: **interactive decision tree** (React Flow, own tree layout, red path to errors; D-028)
- [x] UI: node inspector: exact prompt (system instruction, tools offered, conversation), reply, tool input and output, raw recording
- [x] UI: eval report (metric cards, failure-category chart, tasks with the reason each one failed)
- [x] `examples/customer_app.py`: an agent with its own loop, traced with three SDK lines (D-029)
- [x] **Demo:** run 20 tasks, open a failed one, click through its tree to the bad tool call. Live on Flash-Lite: **19/20 (95%)**, p50 2.76s, p95 5.84s, $0.001 per task. The failure is `triage-unknown-alert`: `get_alert` → "No alert ALR-999", and the agent silently investigated ALR-101 instead (`ignored_tool_error`).
- [x] **Learnings** written up
- Moved: HTTP trace ingestion → Phase 4, next to `lab worker` (D-027).
- **Learn:** eval design, programmatic vs. LLM-judge scoring, judge bias, percentiles, frontend tree
layout.
- **Pitch:** "I can build your core product." Parity with Laminar, Raga AI, Langfuse and Maxim's
tracing view. **Not enough to pitch on its own.**

#### How we built it

**The question:** given recorded runs, how do we say *how well* an agent works and *how* it fails,
and let someone see a failure instead of reading logs?

1. **Evals score traces, not the agent's return value.**
   - `Trajectory.from_store` flattens a stored run into what checks need: the question, every tool
     call with its arguments and result, the answer, the step count and the status.
   - So the same checks work on any recorded run, including `examples/customer_app.py`, which
     never touches our loop (D-023).
2. **A typed dataset format.**
   - Tasks are JSONL.
   - Checks are a pydantic **discriminated union**: the `type` field picks the class, so
     `{"type": "tool_called", ...}` becomes a `ToolCalled` object, and a typo fails with the file
     and line.
   - Each check class has an `evaluate()` method (the strategy pattern) and a default failure
     category.
3. **An LLM judge with structured output** (D-024).
   - A pydantic `Verdict` becomes a JSON Schema, and Gemini's `response_json_schema` makes the
     reply match it. The reply is validated, not parsed with regexes.
   - `reasoning` comes first, so the model argues before it decides.
   - If the judge call itself fails, the check reports `eval_error`, never an agent failure.
4. **Categories and metrics.**
   - Each task gets one failure category: run status first, then the highest-precedence failed
     check (D-025).
   - Metrics: success rate, p50/p95 latency (percentiles with linear interpolation), cost per task
     (summed from `llm` spans in one SQL `GROUP BY`), and judge cost kept separate.
5. **A concurrent batch runner.**
   - A `ThreadPoolExecutor` runs tasks in parallel. Each thread has its own `contextvars` context,
     so traces don't mix.
   - Run IDs are chosen up front (`run_agent(run_id=...)`), so a run that crashes is still scored
     and linked.
   - SQLite got WAL mode and cross-thread connections.
6. **The first live eval failed, and that changed the design** (C-012).
   - 10 of 20 tasks hit the free tier's 15 requests per minute.
   - Fix: a **sliding-window rate limiter** shared by all threads, retries that honour the
     server's `RetryInfo` delay, and rate-limit waiting recorded on the run and left out of
     latency (D-026).
   - The eval itself labelled those failures `crash` / `eval_error` rather than blaming the agent,
     which validated the category design.
7. **Fixing the eval as well as the agent.** One failure was the dataset's fault: a check required
   `get_order` when `get_shipment` was an equally valid way to answer (C-013). We loosened the
   check and wrote the lesson down: test outcomes, not paths.
8. **A thin API.**
   - FastAPI endpoints return pydantic response models, so they are validated and documented at
     `/docs` for free.
   - Run summaries use two aggregate queries in total, not one per run (avoiding N+1).
   - `TestClient` tests the API in-process.
9. **The UI.**
   - React and TypeScript on Vite. A typed API client mirrors the response models.
   - The tree: a 50-line tidy-tree layout (depth → column, leaf → row, parent centred on its
     children), drawn by React Flow with a custom node per span. Ancestors of a failed span are
     drawn red.
   - Clicking a node opens the inspector, which rebuilds the exact prompt from the recording.
   - Hash URLs carry the selected span, so a link can point at the failing call.
   - Vite proxies `/api` in development, and FastAPI serves the built files for the demo.
10. **Verified:**
    - 64 Python tests (checks, judge, categories, percentiles, runner, rate limiter, API) and 5
      layout tests;
    - `tsc` type check and production build;
    - live evals on Flash-Lite;
    - headless-Chrome screenshots of the eval report, the failed run's tree and the inspector;
    - the customer example run live.

**Not done yet, and worth saying in an interview:**
- The judge is the same model as the agent, so it is open to self-preference bias. We haven't
  measured how often the judge agrees with a human.
- Each task runs once. Pass rates over N repeats arrive with Fork (Phase 4) and Experiments
  (Phase 7).
- `lab ui` serves the UI from the repo's `ui/dist`; a pip-installed wheel doesn't include it yet.
- The trace store is still local (D-027).
- In the tree, step and agent nodes show wall time, including rate-limit waiting. The header and
  the eval metrics leave that wait out. Waits are recorded per run, not per step.

### Phase 3 — Deterministic replay · M · ⏭️ Next

- [ ] Interceptor *replay* mode
- [ ] Request hashing to match each call to its recording
- [ ] Tool simulator with read/write classification; writes never reach anything real (C-002, C-003)
- [ ] Support agent gains write tools (refund) against the simulator
- [ ] Clock and random seeding
- [ ] Gemini thinking and function-call parts replayed byte-for-byte (C-005)
- [ ] **Replay fidelity** check: replayed tree == original tree
- [ ] **Demo:** replay a recorded run with the network off; identical tree, zero API cost
- [ ] **Learnings** written up
- **Learn:** determinism, the record/replay ("VCR") pattern, content hashing, idempotency, side
effects.
- **Pitch:** a strong engineering talking point; still invisible to non-engineers.

### Phase 4 — Fork & Replay · L · *first pitchable demo*

- [ ] "Fork from here" on any node (API and UI)
- [ ] Override editor: change the prompt, the model, or a tool's output
- [ ] Replay up to the fork point, then run live
- [ ] Forks stored as child runs (`parent_run_id`, `fork_span_id`)
- [ ] Each fork runs **N times** and reports a pass rate (C-001)
- [ ] UI: the run family shown as a tree
- [ ] `lab worker`: runs fork jobs inside the user's repo (D-009)
- [ ] HTTP trace ingestion: the SDK can send runs to a lab server instead of local SQLite (D-027)
- [ ] **Demo:** a failed support run, forked at the bad step with a fix, now passes 5/5
- [ ] **Learnings** written up
- [ ] **Start Tier 1 outreach**
- **Learn:** state snapshots, copy-on-write, counterfactual reasoning, comparing distributions
(pass rate across N samples) instead of single runs.
- **Pitch:** Maxim (simulation → verified fix), Agnost (the "why" next to their "what"), Laminar,
Raga AI.

### Phase 5 — Trajectory Diff · M

- [ ] Step alignment: shared prefix, then sequence alignment on step type, tool name and argument
similarity
- [ ] Divergence point detection
- [ ] Side-by-side diff view: matched, changed, added and removed steps
- [ ] Downstream effect summary (tokens, cost, outcome)
- [ ] **Demo:** original vs. fork, and Flash vs. Flash-Lite on the same task ("the cheaper model
skips the verification step on refunds")
- [ ] **Learnings** written up
- **Learn:** sequence alignment (LCS, Needleman–Wunsch), similarity measures, tree edit distance,
designing a diff view.
- **Pitch:** Braintrust, Raga AI, Arize: experiments become explainable, not just scored.

### Phase 6 — Auto-Blame · L · *headline differentiator*

- [ ] Seeded failure catalog: known bugs planted on purpose, as ground truth (C-004)
- [ ] LLM judge ranks candidate "first wrong steps", with reasons
- [ ] Top-k candidates verified by forking with a corrected step
- [ ] Report: confirmed blame plus confidence
- [ ] Blame Accuracy benchmark; compare Flash-Lite and Flash as the judge (D-014)
- [ ] **Demo:** one click on a failed run → "Step 4 is at fault … verified 5/5", plus the accuracy
chart on 50 seeded failures
- [ ] **Learnings** written up
- **Learn:** failure attribution (research such as the Who&When benchmark), LLM-judge calibration,
precision and recall at k, the cost trade-off of verifying by replay.
- **Pitch:** BentoLabs, Sentrial, DrDroid, Galileo, Future AGI. A root cause you have *proved*, not
just a guess.

### Phase 7 — Experiments, regressions and CI gate · M

- [ ] Version comparison: success, cost, latency, regression rate
- [ ] "Turn this failure into a regression test" (recorded tools frozen as fixtures, expected
outcome stored)
- [ ] GitHub Action that fails a PR when the regression rate goes up
- [ ] **Demo:** a prompt change → CI blocks it because 2 tasks regressed → the diff shows why
- [ ] **Learnings** written up
- **Learn:** regression testing for nondeterministic systems, flakiness and pass-rate thresholds,
CI pipelines.
- **Pitch:** Athina, LangWatch, TestMu AI, CodeAnt AI, Lyzr and UnifyApps (enterprise reliability gates).

### Phase 8 — Chaos testing · M · *stretch, only after Phases 4–6 are solid*

- [ ] Interceptor *chaos* mode
- [ ] Fault library: timeout, 429, malformed JSON, empty result, wrong-but-valid data, prompt
injection in tool output
- [ ] Robustness score for each fault type
- [ ] Report: which faults the agent handles and which it doesn't
- [ ] **Demo:** "survives timeouts, but follows instructions injected into a tool's output 40% of
the time"
- [ ] **Learnings** written up
- **Learn:** chaos engineering, resilience patterns (retries, backoff, circuit breakers), prompt
injection through tool output.
- **Pitch:** Composio, Metorial, Cekura, TestMu AI, Portkey, TrueFoundry.

### Phase 9 — Pitch kit · S–M

- [ ] Import OTel GenAI traces from other frameworks (view, diff and blame suggestions; no fork)
- [ ] LangGraph adapter, so LangGraph agents can be forked too
- [ ] Hosted read-only demo with seeded data
- [ ] 2-minute video
- [ ] One-page demo script per Tier 1 company
- [ ] Technical write-up built from `learnings.md` and `challenges.md`
- [ ] **Learnings** written up
- **Learn:** OTLP ingestion, product storytelling.
- **Pitch:** everyone. Each message links the demo that fits that company's product.

---

## Target Companies

_Private: this list lives here, not in the README, because the README is shown to these companies._

Companies to study, learn from, or approach for relevant engineering opportunities. This list does **not** imply they are currently hiring or that every role is suitable. Tiers show how directly this project relates to what each company builds.

### Tier 1 — Agent evaluation, observability & reliability (direct fit)

| Company | What they do | Pitch angle |
|---|---|---|
| Maxim AI | Simulation, evals, and observability | Simulation finds failures; Fork & Blame verifies the fix |
| Agnost AI | Conversation analytics: intents, sentiment, frustration | They show *what users felt*; this shows *why the agent failed* |
| BentoLabs | Silent-failure detection, root cause, suggested fixes | Auto-Blame with fork-based verification of the suggested fix |
| Sentrial | Production monitoring for agent reliability | Go from a reliability alert to the blamed step and a verified fix |
| Laminar | Open-source agent tracing; debugger reruns from a span | They let you rerun; this says *where* (Blame), proves it (pass rate over N forks), and diffs the result |
| Raga AI | Agent tracing and evaluation (Catalyst) | Trajectory diff and fork-from-step |
| Athina AI | LLM monitoring and evals | Turn monitored failures into blamed, replayable tests |
| Cekura | Testing and monitoring for voice and chat agents | Chaos testing for tools; replay of failed conversations |
| Coval | Simulation and evals for voice agents | Fork a simulated conversation from the turn that failed |
| Future AGI | Evals and observability | Blame Accuracy as a measurable eval metric |
| Langfuse | Open-source LLM observability | OTel-compatible traces plus replay and fork |
| Braintrust | Evals and experiment tracking | Trajectory diff between experiment versions |
| Arize (Phoenix) | LLM tracing and evals | OTel GenAI traces in, Fork & Blame out |
| Galileo | Agent evaluation and guardrails | Verified root cause instead of a score |
| LangWatch | Agent monitoring and evals | Regression tests generated from blamed failures |

### Tier 2 — Agent builders & agent tooling (they need this)

| Company | What they do | Pitch angle |
|---|---|---|
| DrDroid | AI SRE agent for production incidents | Root-cause analysis, applied to the agent itself |
| TestMu AI | KaneAI testing agent, agent-to-agent testing | Chaos and regression testing for agents |
| Composio | Managed tool and integration layer | How agents behave when tools fail (chaos testing) |
| Metorial | MCP gateway and integrations | Tool-reliability metrics and fault injection at the MCP layer |
| Dexto | Open agent harness | Plug-in tracing and replay for harness users |
| Lyzr | Enterprise agent platform | Debuggability and regression gates for enterprise agents |
| UnifyApps | Enterprise agentic platform | Same as above |
| Ressl AI | Custom enterprise agents | Prove reliability of delivered agents to clients |
| CodeAnt AI | AI code review | Regression gates for AI-driven pipelines |
| Browser Use | Browser agents | Fork a long browser run from the step that failed |
| All Hands AI (OpenHands) | Coding agents | Blame and diff for long coding trajectories |

### Tier 3 — AI infrastructure & platforms

| Company | What they do | Pitch angle |
|---|---|---|
| Portkey | AI gateway, observability, guardrails | Cost and latency analysis per step; gateway-level tracing |
| TrueFoundry | AI and MCP gateway, self-hosted platform | MCP-level tracing, self-hostable replay |
| Scalekit | Auth for agents and apps | Tracing of auth and tool-permission failures |

### Tier 4 — AI applications & media agents

Cardboard, Clueso, Trupeer, InVideo, Spyne.ai — teams running agent pipelines in production. Pitch angle: make multi-step generation pipelines debuggable and regression-tested.

---

## Milestones at a glance

| After phase | You can say | Who to approach |
|---|---|---|
| 2 | "I built the core of an agent observability platform." | Practice only |
| 4 | "…and you can fork any run from any step and test the fix." | Tier 1 |
| 6 | "…and it finds the failing step and *proves* it." | Tier 1 and Tier 2 |
| 7 | "…and it blocks regressions in CI." | Tier 2 and enterprise platforms |
| 8 | "…and it tests how agents handle broken tools." | Tool, gateway and voice companies |

## Out of scope (for now)

- Multi-tenant auth and billing, a real production SaaS deployment.
- Voice and audio pipelines (simulate conversations as text instead).
- Supporting every agent framework (our SDK plus OTel import is enough to demo).
