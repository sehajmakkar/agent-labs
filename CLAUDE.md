# CLAUDE.md

Guidance for Claude when working in this repository.

## What this project is

Agent Reliability Lab: a framework that runs AI agents against repeatable tasks, records every step
(prompts, model responses, tool calls, errors, tokens) as a trace, and lets you inspect, compare and
improve agent behaviour. See [README.md](README.md) for the full feature list and metrics.

It has two goals, in this order of priority:

1. **Learning.** The author is learning the underlying concepts (tracing, evals, replay, agent
   architecture) while building. Explain new concepts when they first appear, prefer clear code over
   clever code, and record what was learned in [learnings.md](learnings.md).
2. **Demo for job applications.** A working demo shown to agent-reliability / AI-infra startups
   (list in PLAN.md, never in the README, which companies see). It should show that we can build what they build *plus* a differentiator.

## Differentiator

**Fork, Blame & Diff** on top of a deterministic replay engine (decisions.md D-002):
- **Fork & Replay:** fork any run from any step with an override.
- **Auto-Blame:** find the first wrong step, verified by forking.
- **Trajectory Diff:** show where two runs diverged.
- **Chaos testing:** a stretch phase.

Core design rule: **the agent is replayable by construction.** Every LLM call, tool call, clock read
and random number goes through the interceptor layer. Never add a code path that calls a model or tool
around it.

## Working agreements

- **decisions.md** — log every non-trivial decision: who raised it, the options, the choice, its
  **trade-offs** (what we give up and why we accept it) and the rationale. Every entry needs a
  trade-offs line, even when the cost is small. Append-only; supersede old entries instead of
  editing them.
- **learnings.md** — concepts learned while building, written so the author can revise from it later.
- **challenges.md** — problems hit, what was tried, how it was solved (or that it is still open).
- **WALKTHROUGH.md**: the author's reading guide (D-021). At the end of every phase:
  - put new files into the reading order, with ★ ratings;
  - update the end-to-end flow and the line references;
  - add a "Phase N recap" with experiments to try.
- Update these files in the same change that causes the entry, not afterwards.
- Work in phases from [PLAN.md](PLAN.md). Each phase must end in something demoable, with its
  learnings written up. Update PLAN.md if scope changes, and record why in decisions.md.
- **Every finished phase in PLAN.md gets a "How we built it" section.** It covers the engineering
  approach, the patterns used, how it was verified, and the known gaps. Write it so the author can
  retell it in a technical interview.
- **PLAN.md is a checklist.** Tick `[x]` an item as soon as it is done and verified, and keep the
  Progress table at the top in sync. Never tick something that wasn't actually run or tested.
- Ask before choosing between options that change scope or architecture; record the answer in
  decisions.md.

## Layout and commands

- `src/agentlab/`: SDK and core.
  - `loop.py`: the agent loop (steps, retries, run time limit).
  - `tools.py`: `@tool`; every tool call is traced and recorded.
  - `tracing.py`: spans, runs, context propagation, `@agent`, `init()`.
  - `store.py`: SQLite tables (runs, spans, recordings).
  - `semconv.py`: span attribute names (OTel GenAI v1.41.0 plus our `agentlab.*`).
  - `llm/`: neutral types, plus the Gemini adapter and `wrap_genai_client` (model-call boundary).
  - `retry.py`, `cost.py`, `render.py` (the terminal tree), `config.py` (model IDs and prices, the
    only place they live), `cli.py`.
- `agents/`: demo agents that play the customer's role (`support.py`).
- `tests/`: pytest. Tests never call the network: use a scripted fake LLM, or a fake `genai`
  client wrapped with `wrap_genai_client`. The `store` fixture gives a fresh trace store.

```
uv sync                                   # install
uv run pytest                             # tests
uv run ruff check . && uv run ruff format .   # lint and format
uv run lab models                         # check Gemini model IDs (needs GEMINI_API_KEY in .env)
uv run lab run support "Was I charged twice for order 4417?"   # Flash-Lite by default; prints the tree
uv run lab runs                           # recent runs
uv run lab show <run-id-prefix>           # a saved run's tree
```

Runs are saved to `.agentlab/lab.db` (git-ignored). There are no migrations (D-020): after a schema
change, delete that file.

## Current status

- **Phase 0 done** (2026-10-27): the agent loop, `@tool`, the Gemini adapter, the CLI and the
  support agent.
- **Phase 1 done** (2026-10-27): every run is traced as `invoke_agent` → `step N` → `chat` /
  `execute_tool`, saved to SQLite with recordings of every model and tool call; cost, tokens,
  latency, retries and timeouts; `lab run` / `runs` / `show`. 30 offline tests; verified live on
  Flash-Lite.
- Next: Phase 2 (evals and the decision tree UI). See the checklist in PLAN.md.
- Stack accepted (D-003 to D-006, D-011):
  - Python 3.12 with uv, FastAPI, SQLite/SQLModel, React + React Flow.
  - Our own agent loop with interception at the LLM client and tool functions. No LangGraph in the
    core.
  - Gemini via `google-genai`. **Flash-Lite is the default model** for inference because Flash is
    sometimes unavailable (D-014). Model IDs and prices live in `config.py` and `.env` only.
- Focus: Fork & Replay, Trajectory Diff, Auto-Blame. Chaos testing comes only after those.
- Positioning: "Others let you rerun; we tell you where and prove it" (D-008).
- Integration model: SDK in the user's code plus `lab worker` to run forks (D-009).
- The target company list is in PLAN.md and must never go into the README (D-010).
