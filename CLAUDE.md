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
- Update these files in the same change that causes the entry, not afterwards.
- Work in phases from [PLAN.md](PLAN.md). Each phase must end in something demoable, with its
  learnings written up. Update PLAN.md if scope changes, and record why in decisions.md.
- **PLAN.md is a checklist.** Tick `[x]` an item as soon as it is done and verified, and keep the
  Progress table at the top in sync. Never tick something that wasn't actually run or tested.
- Ask before choosing between options that change scope or architecture; record the answer in
  decisions.md.

## Layout and commands

- `src/agentlab/`: SDK and core. `loop.py` (agent loop), `tools.py` (`@tool`), `llm/` (neutral
  types plus the Gemini adapter), `config.py` (model IDs, the only place they live), `cli.py`.
- `agents/`: demo agents that play the customer's role (`support.py`).
- `tests/`: pytest. Tests never call the network; use a scripted fake LLM.

```
uv sync                                   # install
uv run pytest                             # tests
uv run ruff check . && uv run ruff format .   # lint and format
uv run lab models                         # check Gemini model IDs (needs GEMINI_API_KEY in .env)
uv run lab run support "Was I charged twice for order 4417?"   # Flash-Lite by default
```

## Current status

- **Phase 0 done** (2026-10-27): the agent loop, `@tool`, the Gemini adapter, the CLI and the
  support agent with two read tools; 14 offline tests; live runs on Flash-Lite verified.
- Next: Phase 1 (tracing SDK and trace store). See the checklist in PLAN.md.
- Stack accepted (D-003 to D-006, D-011):
  - Python 3.12 with uv, FastAPI, SQLite/SQLModel, React + React Flow.
  - Our own agent loop with interception at the LLM client and tool functions. No LangGraph in the
    core.
  - Gemini via `google-genai`. **Flash-Lite is the default model** for inference because Flash is
    sometimes unavailable (D-014). Model IDs live in `config.py` and `.env` only.
- Focus: Fork & Replay, Trajectory Diff, Auto-Blame. Chaos testing comes only after those.
- Positioning: "Others let you rerun; we tell you where and prove it" (D-008).
- Integration model: SDK in the user's code plus `lab worker` to run forks (D-009).
- The target company list is in PLAN.md and must never go into the README (D-010).
