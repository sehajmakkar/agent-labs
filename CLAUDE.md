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
   (list in README). It should show that we can build what they build *plus* a differentiator.

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

- **decisions.md** — log every non-trivial decision (who raised it, options considered, choice, why).
  Append-only; supersede old entries instead of editing them.
- **learnings.md** — concepts learned while building, written so the author can revise from it later.
- **challenges.md** — problems hit, what was tried, how it was solved (or that it is still open).
- Update these files in the same change that causes the entry, not afterwards.
- Work in phases from [PLAN.md](PLAN.md). Each phase must end in something demoable, with its
  learnings written up. Update PLAN.md if scope changes, and record why in decisions.md.
- Ask before choosing between options that change scope or architecture; record the answer in
  decisions.md.

## Current status

- Phase: planning done; Phase 0 next.
- Stack accepted (D-003 to D-006):
  - Python 3.12, FastAPI, SQLite/SQLModel, React + React Flow.
  - Our own agent loop with interception at the LLM client and tool functions. No LangGraph in the
    core.
  - Gemini via `google-genai`: Flash for the agent and judge, Flash-Lite for bulk runs. Model IDs
    live in config only.
- Focus: Fork & Replay, Trajectory Diff, Auto-Blame. Chaos testing comes only after those.
- Positioning: "Others let you rerun; we tell you where and prove it" (D-008).
- Integration model: SDK in the user's code plus `lab worker` to run forks (D-009).
- No code yet.
