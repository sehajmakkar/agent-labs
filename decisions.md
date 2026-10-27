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

## D-022 — Demo agents live in `agentlab.demo`

- **Date:** 2026-10-27
- **Status:** Accepted (Claude, flagged to the author at the end of Phase 1)
- **Context:** The wheel shipped a top-level `agents` package, which clashes with the OpenAI
  Agents SDK (C-011).
- **Options:**
  - (a) move the demo agents to `agentlab.demo`;
  - (b) leave them out of the wheel and load them only from the repo;
  - (c) rename the top-level package.
- **Decision:** (a). `src/agentlab/demo/` holds `support.py` and `triage.py`, and
  `demo_agents()` lists them.
- **Trade-offs:** About 15 KB of demo code ships inside the SDK. We accept it because the CLI's
  `lab run` and `lab eval` then work from an installed wheel, not only from the repo.
- **Rationale:** It is the only option with no name clash that still works when installed.

## D-023 — Eval datasets are JSONL with typed checks, scored from stored runs

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Options:** YAML files, Python files, or JSONL.
- **Decision:**
  - One JSON task per line: `id`, `agent`, `input`, `expected` (the outcome in words) and
    `checks`.
  - Checks are a pydantic *discriminated union* on `type`, so a typo in a dataset fails loudly
    with the file and line.
  - Checks read the run back from the trace store (`Trajectory.from_store`), never the agent's
    in-memory result.
- **Trade-offs:**
  - JSONL is harder to read and edit by hand than YAML, and it has no comments.
  - Scoring from the store costs a few queries per task.
  - We accept both: JSONL is the de facto format for eval datasets, appends cleanly and needs no
    new dependency. Scoring from the store means the same checks work on *any* recorded run,
    including a customer's own agent (`examples/customer_app.py`).
- **Rationale:** Datasets should be data, not code. Scoring from traces makes evals a property of
  the trace store, not of our loop.

## D-024 — The LLM judge: Flash-Lite, reasoning first, failures kept separate

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:**
  - The judge is a Gemini call with structured output (`response_json_schema` from a pydantic
    `Verdict`). `reasoning` comes before `passed` in the schema, so the model explains before it
    decides.
  - The judge grades against the task's written `expected` outcome and treats the tool results in
    the transcript as ground truth.
  - It defaults to Flash-Lite (`--judge-model flash` is available).
  - If the judge call itself fails, the check reports `eval_error`, not an agent failure.
- **Trade-offs:**
  - The judge is the same model family as the agent, so it may favour answers that sound like its
    own (self-preference bias).
  - Every task costs one more model call. In the first eval the judge cost about 35% of the agent.
  - We accept both: Flash is sometimes unavailable (D-014), and the cost is fractions of a cent.
    Programmatic checks sit alongside the judge on every task, so one biased verdict can't pass a
    run on its own.
- **Rationale:** Some outcomes can't be checked by code ("didn't promise a refund"). Structured
  output turns the judge's reply into validated data instead of text to scrape.

## D-025 — Failure categories: each check names one, with run status first

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:**
  - Each check type has a default failure category (for example `answer_excludes` →
    `false_claim`), and a dataset can override it per check.
  - A task's category is the highest-precedence one among its failed checks and its run status:
    `crash` > `timeout` > `max_steps` > `wrong_tool` > … > `eval_error`.
- **Trade-offs:** One category per task hides secondary failures. We accept it because every
  check's result is still stored and shown, and one category per task is what makes the
  "how tasks failed" chart readable.
- **Rationale:** The person writing a check knows which failure it is meant to catch. If the agent
  never answered, judging the answer adds nothing, so run status comes first.

## D-026 — A client-side rate limiter, and latency that leaves out its waiting

- **Date:** 2026-10-27
- **Status:** Accepted (Claude), after the first full eval hit the free-tier quota (C-012)
- **Decision:**
  - `GeminiClient` takes `requests_per_minute`. It is a sliding-window limiter shared by all
    threads, set by `AGENTLAB_RPM` (default 15, the free-tier limit; 0 turns it off).
  - Retries wait at least as long as the server's `RetryInfo` hint asks.
  - Time spent waiting on the limiter is stored on the run (`agentlab.rate_limit.wait_s`) and left
    out of latency metrics.
- **Trade-offs:**
  - Paid keys are slowed to 15 requests per minute until `AGENTLAB_RPM` is raised.
  - Reported latency is the agent's own time, not wall time.
  - We accept both: a default that never fails on a free key is better for a demo, and throttling
    is the eval harness's doing, not the agent's.
- **Rationale:** Retrying after a 429 handles bursts, not sustained load. Waiting before sending
  is cheaper than being refused.

## D-027 — The Phase 2 server is a read-only API over the local store

- **Date:** 2026-10-27
- **Status:** Accepted (Claude). This moves HTTP trace ingestion, which Phase 1's "known gaps"
  said would come in Phase 2, to Phase 4.
- **Decision:**
  - `src/agentlab/server.py` (FastAPI) reads the SQLite store and serves the built UI.
  - The SDK keeps writing straight to SQLite. Sending traces over HTTP moves to Phase 4, next to
    `lab worker`, since both are about the lab talking to the customer's machine.
- **Trade-offs:** `lab ui` must run on the machine that holds `.agentlab/lab.db`. We accept it
  because Phase 2's demo is local, and an ingestion API needs auth and batching design that
  belongs with the worker.
- **Rationale:** It keeps Phase 2 to its checklist (evals and the tree UI).

## D-028 — UI: React Flow with our own tree layout, hash routes, no state library

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:**
  - React 19, TypeScript and Vite in `ui/`, with `@xyflow/react` (React Flow) for the tree.
  - Node positions come from a 50-line tidy-tree layout (`ui/src/lib/layout.ts`), not dagre or
    ELK.
  - Routing is by URL hash.
  - Data is fetched with a small `useLoad` hook, with no Redux or React Query.
  - In development, Vite proxies `/api` to `lab ui`; for the demo, FastAPI serves `ui/dist`.
- **Trade-offs:**
  - Our layout only handles trees; Phase 5's diff view may need a real graph layout.
  - Hash URLs look less clean.
  - We accept both: a span tree *is* a tree, and the layout is short enough to read and test
    (5 vitest tests). Hash routing needs no server-side routing at all.
- **Rationale:** It uses the fewest moving parts that do the job, which helps the author follow
  the code.

## D-029 — A customer-style example agent

- **Date:** 2026-10-27
- **Status:** Accepted (Claude recommended it after the author asked how customers plug in)
- **Decision:** `examples/customer_app.py` is an agent with its own loop over raw `google-genai`,
  traced with `lab.init`, `lab.wrap`, `@lab.tool` and `@lab.agent`.
- **Trade-offs:** It is one more file to keep working as the SDK changes, and it is not covered by
  offline tests because it calls Gemini. We accept it because it is the clearest proof of the
  integration model (D-009), and it was verified live.
- **Rationale:** It makes "we plug into their agent" concrete in a demo.

## D-030 — Replay re-runs the agent's code, with every call served from recordings

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Options:**
  - (a) Re-execute the agent's code, with the interceptors serving recorded responses (the
    record/replay or "VCR" pattern).
  - (b) Only re-render the stored trace, executing nothing.
  - (c) Re-execute, falling back to live calls when a request isn't recorded.
- **Decision:** (a), strict.
  - The wrapped model client, `Tool.invoke` and the clock/random functions ask a `ReplaySession`
    for each response, by the hash of the exact request.
  - Recordings that share a hash are served in recording order.
  - An unrecorded request raises `ReplayDivergence`, naming the JSON paths where it differs from
    the next recorded call.
- **Trade-offs:**
  - A replay needs the same agent code: any change to prompts, tools or code makes it diverge.
    All Phase 2 support runs now diverge, because the support agent changed.
  - Option (b) would never break, but it proves nothing.
  - We accept this, because divergence is information: it pinpoints what changed, and the
    fidelity check found a real bug on its first day (C-016). Live fallback (c) is exactly what a
    fork needs *after* its fork point, so it arrives in Phase 4 as a separate mode.
- **Rationale:** Only re-execution shows that the code really produces the recorded behaviour, and
  fork is defined as "replay up to step N, then go live".

## D-031 — An additive schema migration on startup (partly supersedes D-020)

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:** On startup, `Store` adds any column that the models define but the database lacks
  (`ALTER TABLE … ADD COLUMN`). Renames, type changes and removals still need a fresh database.
- **Trade-offs:** It is home-grown and only adds columns. A real migration tool (Alembic) would
  version every change. We accept it because Phase 3 only added columns, and deleting the database
  would have thrown away 56 live runs that the fidelity check then used as test data.
- **Rationale:** It is the least machinery that keeps your data across schema changes. It is
  tested.

## D-032 — Failed calls are recorded, and a run's limits are stored on the run

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:**
  - The model wrapper records failures too (`{"error": {code, details}}`), and a replay raises the
    same error again. So a 429 followed by a retry replays as the same 429 and retry, without the
    backoff waits.
  - `run_agent` stores `max_steps`, `timeout_s` and the retry limit on the root span, and the
    replay uses them.
- **Trade-offs:** Each failed attempt adds a recording. Runs from before Phase 3 lack these, so a
  replay of an old run that had retries shows fewer attempts. We accept this because otherwise a
  replay of any run that hit a rate limit could never be identical.
- **Rationale:** The aim is for a replay to reproduce the run, failures included.

## D-033 — Clock and randomness go through the interceptor

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:**
  - `lab.now()`, `lab.monotonic()` and `lab.random()` record their values while recording and
    return them, in order, while replaying.
  - The loop's timeout clock defaults to `lab.monotonic`, so a run that timed out at step 3
    replays as a timeout at step 3.
  - If the source run recorded no reads of that kind (it predates Phase 3), the replay uses live
    values and says so in its report.
- **Trade-offs:**
  - Agent code must call `lab.now()` instead of `datetime.now()` to be replayable, and nothing
    enforces that.
  - The lenient fallback for old runs means "identical" can carry a caveat.
  - We accept both: patching the standard library globally would be invisible and fragile, and the
    caveat is printed whenever it applies.
- **Rationale:** This is CLAUDE.md's core rule, "every clock read and random number goes through
  the interceptor layer". `examples/customer_app.py` puts today's date in its prompt to show why.

## D-034 — A per-run simulated backend for the demo; customer write-tool simulators in Phase 4

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:**
  - The support agent gains a write tool, `refund_payment`, which runs against `SupportBackend`:
    a fresh copy of the seed data for every run, keyed by run ID.
  - A refund-policy prompt allows refunding only a requested duplicate.
  - During replay, no tool function runs, read or write.
  - An SDK hook for customers to register a simulator for their own write tools moves to Phase 4,
    because forks are the first time a write tool would run without a recording.
- **Trade-offs:**
  - The demo's "real" refund is itself simulated, so "writes never reach anything real" is
    demonstrated for replay, not yet for a customer's live tools.
  - The policy change invalidated Phase 2 support runs for replay, and changed 5 eval tasks.
  - We accept both: C-003 called for exactly this backend, and Phase 4 is where simulators are
    exercised.
- **Rationale:** Per-run state keeps parallel eval tasks and repeated runs independent. A write tool
  gives the evals something sharper to catch: money moved when it shouldn't have been.

## D-035 — Tool results are snapshots

- **Date:** 2026-10-27
- **Status:** Accepted (Claude), after the bug in C-016
- **Decision:** `Tool.invoke` returns `copy.deepcopy` of what the function returned.
- **Trade-offs:** It costs a copy per call, and results that can't be deep-copied would fail. We
  accept it because tool results are small JSON-like data, and an aliased result silently rewrites
  conversation history.
- **Rationale:** A tool result is a fact *at the time of the call*. The boundary is the one place
  that can guarantee that for every tool, including customers' tools.

## D-036 — The API's first write: `POST /api/runs/{id}/replay` (amends D-027)

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:**
  - The server replays demo-agent runs on request; the UI's Replay button uses this.
  - Runs of other agents return 400, pointing to `lab replay <run> --entry FILE.py:FUNCTION`,
    because only their own code can replay them.
- **Trade-offs:** The server is no longer read-only. We accept it because a replay reaches nothing
  outside the process (no network, no tools), so there's nothing unsafe to guard yet.
- **Rationale:** It makes replay visible in the demo, and it is the endpoint that fork extends in
  Phase 4.

## D-037 — A fork replays by position up to the fork point, then goes live with the override applied at the boundary

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Options:**
  - (a) Match the prefix by request hash, as replay does.
  - (b) Match by position: the i-th model call gets the i-th recorded response.
  - (c) Snapshot the agent's in-memory state at the fork point and restart from it.
- **Decision:** (b).
  - `ForkSession` serves recordings with `seq` before the fork point in call order: model calls by
    position, tool calls by position with the tool name checked, clock and random reads by
    source.
  - Past the fork point it returns `LIVE`, and the boundaries make real calls.
  - The override is applied *at the boundary*: the wrapped Gemini client swaps the system
    instruction or model on live calls, and `Tool.invoke` swaps the forked tool's result.
- **Trade-offs:**
  - Positional matching assumes the agent makes the same calls in the same order up to the fork
    point. A code change there goes unnoticed, except that tool names are checked.
  - A changed prompt is sent only on live calls; the prefix's recorded responses were produced
    under the old prompt.
  - We accept both: (a) breaks as soon as the override changes the requests, which a prompt change
    always does, and (c) is impossible in general, because an agent's state lives in arbitrary
    Python objects. Freezing history and changing the future is exactly the question a fork asks.
- **Rationale:** It works for any agent, ours or a customer's, without knowing its internals.

## D-038 — The live part sees the world the original left: writes re-applied, the clock continued

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:**
  - A recorded write before the fork point is served from the recording *and* re-applied to its
    simulator (result discarded). This is event sourcing: state is rebuilt by replaying the
    events that changed it.
  - Live clock reads continue the recorded timeline: the first one is pinned to the last recorded
    value, and later ones move forward from there.
- **Trade-offs:**
  - It needs a simulator that accepts the same calls; a simulator that disagrees is silently
    ignored.
  - Wall time in a fork is the recorded time plus elapsed time, not today's date.
  - We accept both. Without re-applying writes, a fork after a refund would see the payment as
    still captured and could refund it again. Without continuing the clock, a recorded
    `monotonic()` deadline compared with a fresh reading from another process would time out
    instantly or never (C-017).
- **Rationale:** A counterfactual is only meaningful if everything except the change is the same.

## D-039 — Write tools in forks: simulated or simulator, otherwise the fork stops (closes D-034)

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:**
  - Live in a fork, a read tool runs normally.
  - A write tool runs only if it is marked `@tool(kind="write", simulated=True)` (its function
    only touches simulated state, like the demo backend), or has a simulator registered with
    `@my_tool.simulator`.
  - Otherwise `ForkBlocked` stops the run. Like `ReplayDivergence`, it is an `InterceptorStop`,
    so the loop re-raises it instead of telling the model "tool error".
- **Trade-offs:**
  - Customers must write simulators for the write tools they want forks to reach.
  - A blocked fork tells you nothing about the steps after the write.
  - We accept both: the alternative is a debugging tool that can issue real refunds.
- **Rationale:** "Writes never reach anything real" must hold in every mode, not just replay.

## D-040 — Forks run N times next to N controls, scored by the source's task, compared with Fisher's exact test

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:**
  - A fork job runs N forks with the change and, by default, N controls: the same fork point,
    no change.
  - If the source run came from an eval task, every run is scored with that task's checks, and
    the results are stored as eval results under the fork's ID.
  - The two pass counts are compared with a two-sided Fisher's exact test, and the verdict says
    "fixes it" only for more passes with p < 0.05.
- **Trade-offs:**
  - Controls double the cost.
  - With N=5, only large effects can be significant: 5/5 vs 0/5 gives p = 0.008, but 5/5 vs 3/5
    gives p = 0.44.
  - Runs that aren't from a task can't be scored; their answers are shown to compare by eye.
  - We accept all three: without a control, "4/5 pass" is meaningless if it would have been 4/5
    anyway. That happened live: the ALR-999 run's control passed 3/5, so the original failure was
    partly luck.
- **Rationale:** The live part is sampled (C-001). A claim that a fix works must be a comparison of
  two distributions, not of two runs.

## D-041 — Fork jobs are queued in the database and run by workers, never by the API server

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:**
  - `POST /api/forks` only inserts a row into `forks` (status `queued`).
  - Workers claim jobs with a compare-and-set UPDATE (`… WHERE status = 'queued'`; whoever
    updates the row first owns the job) and run them with real agent code.
  - `lab ui` starts an in-process worker thread for the demo agents (`--no-worker` turns it off).
  - Customers run `lab worker --entry app.py:agent` in their own repo.
- **Trade-offs:**
  - The UI has to poll for progress.
  - With no worker running, forks just wait (the UI says why).
  - A crashed worker leaves its job "running"; there is no lease timeout yet.
  - We accept these because the server can't run customer code safely or at all (D-009).
- **Rationale:** A database queue needs no extra infrastructure (no Redis or Celery), and the
  atomic claim is enough for a few workers.

## D-042 — Traces and fork jobs travel over a narrow store RPC (`RemoteStore`), guarded by a token

- **Date:** 2026-10-27
- **Status:** Accepted (Claude). This carries out D-027's move of HTTP ingestion into Phase 4.
- **Options:** REST endpoints per resource; OTLP export; or an RPC mirroring the store methods
  that tracing, replay, forks and the worker use.
- **Decision:**
  - The RPC. `RemoteStore` has the same method names as `Store` and POSTs each call to
    `/api/store/<method>`, with rows as JSON.
  - `lab.init("http://lab:8000")` and `lab worker --server URL` use it.
  - If `AGENTLAB_TOKEN` is set on the server, requests must send it as a bearer token.
- **Trade-offs:**
  - It ties the wire format to our store's method names.
  - One HTTP request per span is slow over a real network (no batching).
  - A single shared token is minimal security.
  - OTLP would let other tools send traces, but can't carry our recordings or fork jobs.
  - We accept all of this for now: eleven small handlers made the whole SDK and worker work
    remotely with no other code changes, which a test shows by replaying and forking entirely
    through HTTP.
- **Rationale:** It is the smallest step from "the lab and the agent share one SQLite file" to "the
  agent runs in the customer's repo and reports to a lab server".

## D-043 — STORY.md: the narrative companion to the walkthrough

- **Date:** 2026-10-27
- **Status:** Accepted (raised by the author)
- **Decision:** `STORY.md` tells the project as one story, with tree diagrams: what was built, how,
  why, and what comes next. CLAUDE.md requires it to be updated at the end of every phase.
- **Trade-offs:** It is a third document to keep in sync, after WALKTHROUGH.md and PLAN.md's "How we
  built it". We accept this because each has its own job: the walkthrough is for reading the code,
  the PLAN sections for engineering detail, and the story for retelling.
- **Rationale:** The author asked for a way to explain the whole project to someone from start to
  finish.

## D-044 — A diff compares steps: one model decision plus the tool calls it caused

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Options:**
  - (a) Diff the raw span trees (tree edit distance).
  - (b) Diff the model calls only.
  - (c) Diff *steps*: each model decision with its tool calls, results and words.
- **Decision:** (c). `extract_steps` builds them from stored spans: from step spans for our loop,
  or, for an agent with its own loop, by starting a new step at each successful model call.
  Retried attempts that failed are folded into their step (shown as "N attempts").
- **Trade-offs:**
  - Tree edit distance would also see structural differences inside a step, such as span nesting.
    Steps flatten that away.
  - A step's parallel tool calls are compared as a multiset, so a different order isn't a change.
  - We accept both because a step is how people reason about an agent ("at step 3 it answered
    instead of checking"), and it is the unit that forks start from (D-015).
- **Rationale:** The diff should answer "what did the agent decide differently?", not "which span
  moved".

## D-045 — Alignment: shared prefix, then Needleman–Wunsch with a weighted step similarity

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Options:**
  - LCS on exact step equality;
  - Needleman–Wunsch (global alignment with a similarity score);
  - embedding similarity of step texts.
- **Decision:**
  - Identical steps from the start are matched first.
  - The rest are aligned with Needleman–Wunsch: a pair scores `2·similarity − 1`, and a gap
    costs −0.6.
  - Similarity:
    - steps that call tools: 0.6 × multiset Jaccard of tool names, 0.3 × the share of arguments
      that are equal, and 0.1 × the share of results that are equal;
    - answers: the share of words in common (difflib);
    - steps of different kinds: 0.
  - Each changed pair gets notes in words (`get_order: order_id '4417' → '4471'`).
- **Trade-offs:**
  - The weights and gap penalty are hand-picked, not learned.
  - Word overlap can't tell that two differently worded answers mean the same thing.
  - With exact-match LCS, every slightly different step would show as removed plus added.
  - We accept these: the alignment is explainable, has no dependencies, is tested on insertions,
    deletions and substitutions, and is fast for runs of tens of steps. An embedding model could
    replace `text_similarity` later.
- **Rationale:** "Same tool, different arguments" must show as a change, and an extra step must
  show as an insertion without shifting every later step.

## D-046 — Diffs are computed on demand and show downstream effects, not just the steps

- **Date:** 2026-10-27
- **Status:** Accepted (Claude)
- **Decision:**
  - `GET /api/diff?a=&b=` and `lab diff A B` compute the diff from the store each time.
  - Each run's outcome (its eval result if scored), steps, tokens, cost and time are shown side by
    side, with a word-level diff of the final answers.
  - The cost of a replay or fork is labelled as covering live calls only.
  - Every run page has "Compare with": its source, or other runs of the same task. Fork pages
    link each run to a diff against the source.
- **Trade-offs:** Nothing is cached, so a diff of two 50-step runs is recomputed each time
  (milliseconds at this size). Comparing a fork's cost with its source's is apples to oranges, so
  we label it rather than hide it.
- **Rationale:** "Where did it diverge?" is half the question; "and what did that change?" is the
  other half.
