# Decisions

Append-only log. Format: ID, date, status, who raised it, context, options, decision, rationale.
To change a decision, add a new entry that supersedes the old one.

---

## D-001 — Project tracking documents

- **Date:** 2026-10-27
- **Status:** Accepted
- **Raised by:** Sehaj
- **Decision:** Maintain `CLAUDE.md`, `decisions.md`, `learnings.md` and `challenges.md` at the repo
  root for the whole life of the project.
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
- **Rationale:** Replay needs control over every LLM and tool call. Boundary interception keeps us
  framework-agnostic, like the vendors above. Writing the loop is the best way to learn.

## D-005 — LLM provider

- **Date:** 2026-10-27
- **Status:** Accepted (2026-10-27, Sehaj)
- **Raised by:** Claude; provider chosen by Sehaj
- **Decision:** **Gemini** through the `google-genai` Python SDK, behind a thin provider interface
  of our own.
  - **Flash** runs the main agent and the blame judge.
  - **Flash-Lite** runs bulk eval sweeps and cheap fork samples.
  - Model IDs live in config, never in code. Google's docs list `gemini-3.8-flash` and
    `gemini-3.5-flash-lite` as current, and sources disagree, so confirm with `client.models.list()`
    in Phase 0.
- **Rationale:** The interface keeps recordings independent of the provider. Having two tiers of the
  same family gives a ready-made demo: diff Flash against Flash-Lite on the same task to show what
  the cheaper model skips.

## D-006 — Trace schema

- **Date:** 2026-10-27
- **Status:** Accepted (2026-10-27, Sehaj)
- **Raised by:** Claude
- **Decision:** Our own schema (Run, Span, Recording) with field names aligned to the OTel GenAI
  semantic conventions at a pinned version. OTLP export/import later.
- **Rationale:** The GenAI conventions are still in Development status. Aligning names now and
  depending on the spec later avoids churn while staying interoperable.

## D-007 — Phase order

- **Date:** 2026-10-27
- **Status:** Accepted
- **Raised by:** Claude (PLAN.md), approved by Sehaj with the plan
- **Decision:** Replay (3) → Fork (4) → Diff (5) → Blame (6), and outreach starts after Phase 4.
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
- **Rationale:** This is how Sentry, Langfuse and Laminar fit into a team's workflow. The agent stays
  where it already runs, and the lab adds recording and a control panel.
