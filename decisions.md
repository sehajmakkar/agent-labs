# Decisions

Append-only log. Each entry records: ID, date, status, who raised it, context, options, the
decision, its **trade-offs** (what we give up, and why we accept that), and the rationale.
To change a decision, add a new entry that supersedes the old one, and point to it from the old
entry's status line.

---

## D-001 — Project tracking documents

- **Date:** 2026-10-27
- **Status:** Accepted
- **Raised by:** Sehaj
- **Decision:** Maintain `CLAUDE.md`, `decisions.md`, `learnings.md` and `challenges.md` at the repo
  root for the whole life of the project.
- **Trade-offs:** Writing docs takes time away from code, and docs go stale if nobody updates them.
  Accepted because the docs *are* part of the output (study material, interview stories). Going
  stale is handled by the rule that docs are updated in the same change that causes the entry.
- **Rationale:** The project is a learning vehicle as much as a demo; recording decisions, learnings
  and challenges as they happen produces study material and interview talking points.

## D-002 — Differentiator on top of the base trace/replay platform

- **Date:** 2026-10-27
- **Status:** Accepted (2026-10-27)
- **Raised by:** Sehaj (asked Claude to propose options and recommend one)
- **Context:** The base project (trace capture, tree view of the agent's path, evals, dashboard)
  overlaps with Agnost AI, Maxim AI, Laminar, Raga AI, Langfuse and others. A differentiator is
  needed so the demo is more than a clone.
- **Options proposed:**
  1. Fork & Replay from any node (counterfactual debugging)
  2. Automatic blame: find the first step that went wrong
  3. Trajectory diff between two runs or versions
  4. Chaos testing for tools (fault injection)
  5. Failure → regression test in one click
  6. Cost/latency waste profiler
- **Claude's recommendation:** Combine 1 + 2 + 3 ("Fork, Blame & Diff"), keeping 4 as a stretch
  phase, because all four sit on one engine (deterministic replay with recorded tool responses).
- **Decision:** Build **Fork & Replay + Auto-Blame + Trajectory Diff** as the differentiator, with
  **Chaos Testing** as a stretch phase. Failure → regression test (5) is folded into the regression
  phase. The cost profiler (6) is dropped for now.
- **Trade-offs:**
  - Three features plus a stretch goal is a big scope, with a risk of finishing none of them well.
    The phase order (D-007) handles this: Phase 4 (Fork) is pitchable on its own.
  - Dropping the cost profiler weakens the pitch to gateway companies (Portkey, TrueFoundry).
  - Fork alone is not unique (see D-008), so the value rests on the combination.
- **Rationale:** It finishes the original "find where the agent goes wrong in one click" idea. All
  four features share one replay engine. Fork-to-verify is missing from the main platforms (Maxim,
  Agnost, Raga AI, Langfuse). Learning value is high.

## D-003 — Tech stack

- **Date:** 2026-10-27
- **Status:** Accepted (2026-10-27, Sehaj)
- **Raised by:** Claude (in PLAN.md)
- **Options:** (a) Python backend + React/TypeScript UI; (b) TypeScript end to end.
- **Decision:** (a) Python 3.12, FastAPI, SQLite via SQLModel (Postgres later), React + Vite +
  React Flow for the tree UI. **No LangGraph/LangChain in the core** (see D-004).
- **Trade-offs:**
  - Two languages and two toolchains instead of one; TypeScript end to end would share types
    between the API and the UI.
  - Python is slower than Rust (which Laminar uses) for high-volume trace ingestion. That doesn't
    matter at demo scale.
  - SQLite allows only one writer at a time, so many parallel fork runs will queue. Fine locally;
    Postgres is the way out.
  - React Flow is a dependency with its own layout limits, but it saves building a tree renderer.
  - Without LangGraph we build retries and state handling ourselves, and the demo doesn't run on
    the framework many customers use until the Phase 9 adapter.
- **Rationale:**
  - *Python:* the SDKs of the target companies (Langfuse, Raga AI, Agnost, Maxim) and most agent
    frameworks are Python-first, so our SDK looks familiar to them. Gemini's `google-genai` SDK is
    first-class in Python.
  - *FastAPI:* small, typed and async; it serves both the UI's API and trace ingestion.
  - *SQLite → Postgres:* zero setup while learning. SQLModel keeps the schema portable.
  - *React Flow:* draws interactive, zoomable node trees, which is our main UI.
  - *Why not LangGraph:* (1) Replay needs us to serve every model and tool response from a
    recording. LangGraph's own time travel *re-executes* nodes, so LLM calls fire again. (2) A
    reliability tool pitched to many companies must work with any framework; building on one makes
    it look tied to that framework. (3) Writing the loop ourselves is the best way to learn what
    frameworks hide. LangGraph returns later as an *adapter* (Phase 9), because many customer
    agents use it.

## D-004 — Own agent loop vs. an agent framework

- **Date:** 2026-10-27
- **Status:** Accepted (2026-10-27, Sehaj)
- **Raised by:** Claude
- **Options:** (a) write a minimal agent loop ourselves; (b) build on LangGraph, the OpenAI Agents
  SDK, or similar.
- **Decision:** (a) for our demo agents. The SDK intercepts at the **boundaries** (the LLM client
  and the tool functions), not inside the loop, so the same interception works under any framework.
  A LangGraph adapter and OTel trace import come in Phase 9.
- **What the market does (researched 2026-10-27):** It is mixed, and no reliable survey splits
  custom loops from frameworks. The evidence is in how observability vendors integrate:
  - Langfuse ships a LangChain/LangGraph callback, a Google ADK instrumentor (OpenTelemetry), and an
    `@observe()` decorator for custom code.
  - Laminar auto-instruments the Claude Agent SDK and the AI SDK.
  - Agnost wraps MCP servers and offers plain SDK calls.

  Vendors therefore support *both* framework users and custom-loop users. Frameworks commonly seen:
  LangGraph, the OpenAI Agents SDK, Google ADK, the Claude Agent SDK, Vercel AI SDK, CrewAI and
  Pydantic AI.
- **Trade-offs:**
  - More code to own and maintain.
  - Our loop is simpler than real production agents (no multi-agent setups or human approval
    steps yet), so the demo may look like a toy to some reviewers.
  - Boundary interception only sees what crosses the model and tool boundaries, not a framework's
    internal state (for example LangGraph's graph state). Forks rebuild state by replaying calls,
    not by restoring snapshots.
- **Rationale:** Replay needs control over every LLM and tool call. Boundary interception keeps us
  framework-agnostic, like the vendors above. Writing the loop is the best way to learn.

## D-005 — LLM provider

- **Date:** 2026-10-27
- **Status:** Accepted (2026-10-27, Sehaj). **Default model tier changed by D-014.**
- **Raised by:** Claude; provider chosen by Sehaj
- **Decision:** **Gemini** through the `google-genai` Python SDK, behind a thin provider interface
  of our own.
  - **Flash** runs the main agent and the blame judge. *(Superseded by D-014: Flash-Lite is now
    the default for inference.)*
  - **Flash-Lite** runs bulk eval sweeps and cheap fork samples.
  - Model IDs live in config, never in code. Confirmed on 2026-10-27 with `lab models`:
    `gemini-3.8-flash` and `gemini-3.5-flash-lite` (challenges.md C-006).
- **Trade-offs:** With a single provider the demo can't compare providers (Gemini vs. Claude vs.
  GPT), which some eval companies care about. The neutral interface (D-012) keeps a second provider
  cheap to add later.
- **Rationale:** The interface keeps recordings independent of the provider. Having two tiers of the
  same family gives a ready-made demo: diff Flash against Flash-Lite on the same task to show what
  the cheaper model skips.

## D-006 — Trace schema

- **Date:** 2026-10-27
- **Status:** Accepted (2026-10-27, Sehaj)
- **Raised by:** Claude
- **Decision:** Our own schema (Run, Span, Recording) with field names aligned to the OTel GenAI
  semantic conventions at a pinned version. OTLP export/import later.
- **Trade-offs:** We will have to write a converter to and from OTLP later. Pinned attribute names
  may drift from the spec as it changes, so we re-check them when we build the converter.
- **Rationale:** The GenAI conventions are still in Development status. Aligning names now and
  depending on the spec later avoids churn while staying interoperable.

## D-007 — Phase order

- **Date:** 2026-10-27
- **Status:** Accepted
- **Raised by:** Claude (PLAN.md), approved by Sehaj with the plan
- **Decision:** Replay (3) → Fork (4) → Diff (5) → Blame (6), and outreach starts after Phase 4.
- **Trade-offs:** The headline feature (Blame) comes last of the three. If time runs out, the most
  impressive part is missing. Accepted because Blame can't be built without forks, and Phase 4 is
  already a demo worth pitching.
- **Rationale:** Fork needs replay. Blame verifies its guesses with forks and is clearer to show
  alongside a diff, so it comes last of the three. Phase 4 is the first demo that differs from what
  the target companies already ship.

## D-008 — Positioning against existing fork and rerun features

- **Date:** 2026-10-27
- **Status:** Accepted
- **Raised by:** Claude, after research
- **Context:** Fork-from-a-step is not unique on its own:
  - **Laminar's debugger** reruns from a chosen span, with earlier LLM calls mocked from their
    original responses. You can change the prompt or tool definitions first.
  - **LangGraph time travel** forks from a checkpoint, but re-executes the nodes.

  Neither offers automatic blame, a trajectory diff, or repeated reruns to compare pass rates.
- **Decision:** Pitch the **loop**, not fork alone:
  1. **Blame** says where to fork.
  2. **Statistical forks** (N samples → a pass rate) prove whether the fix works.
  3. **Diff** shows what changed.

  Supporting points: overrides can change a tool's *output*, not just prompts; it works with any
  framework through boundary interception; and Blame Accuracy is measured on planted bugs.
  Chaos testing stays a stretch phase after these three.
- **Trade-offs:**
  - "Blame, prove, diff" takes longer to explain than "we fork".
  - The full claim only holds once Phases 4–6 exist.
  - Statements about competitors go stale, so re-check them before each pitch.
- **Rationale:** An honest pitch survives a technical interviewer who knows Laminar. "They let you
  rerun; we tell you where and prove it" is a clear upgrade.

## D-009 — How users integrate with the lab

- **Date:** 2026-10-27
- **Status:** Accepted
- **Raised by:** Sehaj asked how a user would actually use the app
- **Decision:** The lab never hosts the user's agent.
  - The user adds our SDK to their own code: they wrap the LLM client, mark tools as read or write,
    and mark the agent's entry point.
  - Traces flow to the lab server from development, CI or production.
  - Forks run through `lab worker`, a process inside the user's repo that receives fork jobs from
    the server and runs the user's agent in fork mode.
  - Traces imported from other tools (OTel) can be viewed, diffed and blame-suggested, but not
    forked, because forking needs to re-run the user's code.

  Our demo ships its own agents (support, incident triage), which play the customer's role.
- **Trade-offs:**
  - Running a worker process is more setup than a hosted sandbox where you just paste your agent.
  - Imported traces can't be forked.
  - A worker that runs code when the server tells it to is a security surface: fork jobs will need
    authentication before anything leaves localhost.
- **Rationale:** This is how Sentry, Langfuse and Laminar fit into a team's workflow. The agent stays
  where it already runs, and the lab adds recording and a control panel.

## D-010 — Target company list lives in PLAN.md, not the README

- **Date:** 2026-10-27
- **Status:** Accepted (Sehaj confirmed keeping it in PLAN.md, 2026-10-27)
- **Raised by:** Sehaj
- **Decision:** The tiered company list and pitch angles moved from README.md to PLAN.md
  ("Target Companies"). The README no longer links to PLAN.md.
- **Trade-offs:** If the repository is public, PLAN.md can still be found by anyone who browses it.
  Sehaj accepted this.
- **Rationale:** The README is shown to the companies themselves. A list of other targets and pitch
  angles doesn't belong in front of them.

## D-011 — Phase 0 tooling and layout

- **Date:** 2026-10-27
- **Status:** Accepted (Claude, within the approved stack; open to change)
- **Decision:**
  - `uv` for environments and dependencies (Python 3.12 pinned in `.python-version`).
  - `ruff` for lint and formatting; `pytest` for tests.
  - `argparse` for the CLI (no extra dependency).
  - `pydantic` to build tool schemas from type hints. It is already a dependency of `google-genai`.
  - Layout: `src/agentlab/` is the SDK and core (PLAN.md's `core/`), `agents/` holds the demo
    agents, `tests/` holds the tests. `api/` and `ui/` are created in the phases that need them.
- **Trade-offs:**
  - `argparse` is wordier than Typer or Click, and its help output is plainer.
  - `uv` is less familiar to some reviewers than plain pip, but `pip install -e .` still works
    because everything is in `pyproject.toml`.
  - The `src/` layout needs an install step, which `uv sync` handles.
- **Rationale:** Standard, fast and few dependencies. The `src/` layout keeps tests honest: they
  import the installed package, not files that happen to sit next to them.

## D-012 — Provider-neutral messages that carry the raw provider response

- **Date:** 2026-10-27
- **Status:** Accepted (Claude; flagged for Sehaj's review)
- **Options:** (a) the loop works on Gemini's own `Content` objects; (b) our own `Message`,
  `ToolCall` and `ToolResult` types, with each model message keeping the original response in `raw`.
- **Decision:** (b). When building the next request, the Gemini adapter resends `raw` unchanged and
  only rebuilds a model turn from our fields when no raw response exists.
- **Trade-offs:**
  - Every model turn exists twice (our fields and `raw`), and the two could disagree if someone
    edits one but not the other. Fork overrides must therefore edit through one function that
    updates both.
  - The `raw` part of a recording is Gemini-specific, so a recording can't simply be replayed on
    another provider.
  - Each provider needs its own conversion code.
- **Rationale:** The loop, and later the trace store and replay, stay independent of the provider.
  Resending the raw response preserves Gemini's thought signatures exactly (challenges.md C-005).

## D-013 — Tool failures are returned to the model, never raised

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:** An unknown tool, invalid arguments, or an exception inside a tool becomes a result
  like `{"error": "..."}` marked `is_error`, and goes back to the model. The loop never crashes on a
  tool failure.
- **Trade-offs:**
  - A genuine bug in our own tool code also looks like an ordinary tool error to the agent, so
    traces must show `is_error` and the error type clearly or the bug gets lost.
  - A model can keep retrying a broken tool; `max_steps` puts a ceiling on that.
- **Rationale:** Handling tool errors is part of the agent's job. An agent that ignores them is the
  failure this lab is built to catch (see the worked example in learnings.md), so the errors must
  stay visible inside the run.

## D-014 — Flash-Lite is the default model for inference

- **Date:** 2026-10-27
- **Status:** Accepted
- **Raised by:** Sehaj
- **Context:** In Sehaj's experience Gemini Flash is sometimes unavailable, which would break demos
  and long eval runs halfway through.
- **Options:** (a) keep Flash as the default; (b) make Flash-Lite the default and keep Flash
  selectable; (c) default to Flash and fall back to Flash-Lite automatically when it is unavailable.
- **Decision:** (b). `lab run` defaults to `--model flash-lite`; `--model flash` still works.
  Partly supersedes D-005.
- **Trade-offs:**
  - Flash-Lite is less capable, so the agent will make more mistakes and the blame judge may be
    weaker. For a reliability lab, more natural failures are useful material, not only a cost.
  - It is cheaper and faster, which matters when every fork runs N times.
  - Option (c) was not chosen: a silent fallback would mix two models inside one experiment and
    make results hard to compare. If we ever add a fallback, it must be recorded on the span.
  - Revisit for the blame judge in Phase 6: measure Blame Accuracy with both models before
    choosing.
- **Rationale:** A demo that fails because the model is unavailable is worse than one running a
  slightly weaker model. Reliability of the lab itself comes first.

## D-015 — A "step" span between the agent and its calls

- **Date:** 2026-10-27
- **Status:** Accepted (Claude; flagged for Sehaj's review)
- **Context:** In the OTel conventions, model calls (`chat`) and tool calls (`execute_tool`) are
  siblings under the agent span. That gives a flat list, not the decision tree this project is
  about.
- **Options:** (a) follow OTel exactly: flat children under `invoke_agent`; (b) make tool spans
  children of the `chat` span that asked for them; (c) add a `step N` span that wraps one model
  call and the tool calls it requested.
- **Decision:** (c). The tree is `invoke_agent` → `step N` → (`chat`, `execute_tool`…). Step spans
  carry `agentlab.step.index` and `agentlab.llm.attempts`.
- **Trade-offs:**
  - Step spans aren't part of the OTel conventions, so other tools that read our traces will show
    an extra layer they don't recognise. They appear as ordinary internal spans, so nothing breaks.
  - Only our loop creates steps. A customer's own loop traced through `lab.wrap` and `@lab.tool`
    gets the flat OTel shape, so the tree view must handle both shapes.
  - (b) was rejected: a tool span would hang under a `chat` span that has already ended, which is
    allowed but confusing to read.
- **Rationale:** A step is one decision by the model plus its consequences, which is exactly what
  Fork starts from (Phase 4) and what Blame points at (Phase 6).

## D-016 — Interception wraps the provider SDK client, and tools record themselves

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Options:** (a) trace at our own `LLMClient.generate`; (b) wrap the provider SDK client
  (`genai.Client`) so every `models.generate_content` call is traced.
- **Decision:** (b) for model calls: `lab.wrap(genai.Client())` returns a stand-in that traces and
  records each call and passes everything else through. For tool calls, `Tool.invoke` opens the
  span, so a tool is traced whether our loop or a customer's code calls it. Recordings hold the
  exact request (model, contents, config) and the raw response, keyed by a SHA-256 `request_hash`
  of the request's canonical JSON.
- **Trade-offs:**
  - The wrapper only covers `models.generate_content`. Streaming, async (`client.aio`) and chats
    pass through untraced for now.
  - Recordings are Gemini-shaped, so each new provider needs its own wrapper.
  - Every request is stored in full, conversation history included, so the database grows roughly
    with the square of the number of steps. Fine at demo scale; deduplication can come later.
- **Rationale:** The SDK client is the boundary every Gemini user has, whatever loop or framework
  they run (D-004, D-009). Recording at that level captures exactly what Gemini received and
  returned, which is what replay needs (Phase 3).

## D-017 — Our own retries, with the SDK's retries switched off

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:** Model calls are retried in the loop (`retry.py`): up to 4 attempts, exponential
  backoff (1s, 2s, 4s, capped at 16s) with jitter, only for transient failures (HTTP 408, 429,
  500, 502, 503, 504 and network or timeout errors). The SDK client is created with
  `HttpRetryOptions(attempts=1)`. Each request has a 60s timeout, and a whole run has a time limit
  (`--timeout`, default 120s) checked before each step.
- **Trade-offs:**
  - More code than turning on the SDK's built-in retries.
  - The run time limit is only checked between steps: one slow model call can overrun it by up
    to the 60s request timeout.
  - Jitter uses `random`, which Phase 3 will have to seed for exact replay.
- **Rationale:** With the SDK retrying silently, failed attempts would never reach our traces, and
  the README's Retry Rate metric couldn't be measured. It also covers the open part of C-007: when
  Flash-Lite is overloaded, the run retries instead of failing.

## D-018 — Tracing does nothing until `lab.init()` is called

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:** Spans are always created, but they are saved only when a store has been set up
  with `lab.init(path)`. Without it, the same code runs and records nothing.
- **Trade-offs:** Forgetting `lab.init()` silently records nothing, with no warning. A later phase
  may add a warning, or an environment variable that switches recording on.
- **Rationale:** Tests and plain library use need no database, and instrumented code never has to
  check whether tracing is on. OpenTelemetry's no-op tracer works the same way.

## D-019 — Cost is estimated from a price table in config

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:** `config.PRICES_PER_MILLION` holds paid-tier Standard prices from Google's pricing
  page (checked 2026-10-27). Cost = input tokens × input price + (output + thinking tokens) ×
  output price, because Google bills thinking tokens at the output price. Models without a price
  show "cost unknown" instead of $0.
- **Trade-offs:**
  - Prices change: 3.8 Flash doubles on 2027-01-01, and the table must be updated by hand.
  - A run's cost is computed when it is recorded and never recalculated.
  - Free-tier keys pay nothing, so on the free tier the figure is what the run *would* cost.
  - Cached-input discounts are ignored; we don't use context caching yet.
- **Rationale:** Cost per task is a headline README metric and has to work offline from the
  recorded usage. A hand-checked table is simple and honest about what it knows.

## D-020 — Fork columns exist in the schema from the start

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:** `runs` already has `parent_run_id`, `fork_span_id` and `fork_override`, unused until
  Phase 4. Tables are created with SQLModel's `create_all`, with no migration tool.
- **Trade-offs:** Unused columns now. Without migrations, any later schema change means deleting
  `.agentlab/lab.db` (losing local runs) or adding a migration tool such as Alembic at that point.
- **Rationale:** Adding the known Phase 4 columns now avoids the first migration. A migration tool
  would be one more thing to learn before it is needed.

## D-021 — A reading guide, updated every phase

- **Date:** 2026-10-27
- **Status:** Accepted (raised by the author)
- **Context:** Claude writes most of the code, and the author kept losing track of how the files
  fit together. learnings.md explains concepts but not the order in which to read the code.
- **Decision:** [WALKTHROUGH.md](WALKTHROUGH.md) holds:
  - a dependency-ordered reading list of every file, with importance ratings;
  - the end-to-end flow of one run;
  - deep dives on tool calling and tracing;
  - interview prep and a review routine.
  It is updated at the end of every phase, and each phase gets a short recap with experiments to
  try.
- **Trade-offs:** One more document to keep in sync, and line references in it go stale as code
  changes. We accept that because the author can't explain a demo they haven't read in order. The
  file is checked at each phase end.
- **Rationale:** Learning is the first goal (CLAUDE.md). Reading files in dependency order is the
  fastest way to understand code someone else wrote.
