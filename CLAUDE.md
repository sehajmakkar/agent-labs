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
- **STORY.md**: the project told as one narrative, with tree diagrams: what was built, how it
  works, why each piece exists, and what comes next. At the end of every phase:
  - turn the phase's "what comes next" section into a chapter about what was actually built and
    seen, with real numbers and real runs;
  - update "What comes next", the platform map and the "Last updated" line;
  - write it so the author can retell it in an interview or a demo.
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
  - `store.py`: SQLite tables (runs, spans, recordings, eval runs and results); an additive
    migration adds new columns on startup (D-031).
  - `replay/`: the replay session (record/replay by request hash), `ForkSession` (replay by
    position up to a fork point, then live), the fidelity check, and the runner.
  - `fork/`: fork points, Fisher's exact test, the fork runner (N forks plus N controls, scored),
    and the worker loop.
  - `remote.py`: `RemoteStore`, the store over HTTP (`lab.init("http://…")`, `lab worker --server`).
  - `diff/`: runs as steps, Needleman–Wunsch step alignment with a weighted similarity, and the diff
    report (divergence, effects, answer word diff).
  - `determinism.py`: `lab.now()`, `lab.monotonic()`, `lab.random()`, which are replayable.
  - `semconv.py`: span attribute names (OTel GenAI v1.41.0 plus our `agentlab.*`).
  - `llm/`: neutral types, the Gemini adapter, `wrap_genai_client` (the model-call boundary) and
    `ratelimit.py`.
  - `evals/`: datasets and checks (`tasks.py`), the LLM judge, failure categories, metrics, and
    the batch runner.
  - `demo/`: demo agents that play the customer's role (`support.py`, `triage.py`).
  - `server.py`: the read-only FastAPI app behind the UI.
  - `retry.py`, `cost.py`, `render.py` (terminal output), `config.py` (model IDs and prices, the
    only place they live), `cli.py`.
- `datasets/`: eval tasks as JSONL (20 tasks).
- `ui/`: React + TypeScript + Vite + React Flow. `npm run build` → `ui/dist`, served by `lab ui`.
- `examples/customer_app.py`: an agent with its own loop, traced with the SDK alone.
- `tests/`: pytest. Tests never call the network: use a scripted fake LLM (`tests/fakes.py`), or
  a fake `genai` client wrapped with `wrap_genai_client`. The `store` fixture gives a fresh trace
  store. A fake LLM produces no `llm` spans, because those come from the wrapped Gemini client.

```
uv sync                                   # install
uv run pytest                             # tests
uv run ruff check . && uv run ruff format .   # lint and format
uv run lab models                         # check Gemini model IDs (needs GEMINI_API_KEY in .env)
uv run lab run support "Was I charged twice for order 4417?"   # Flash-Lite by default; prints the tree
uv run lab runs                           # recent runs
uv run lab show <run-id-prefix>           # a saved run's tree
uv run lab eval datasets/support.jsonl datasets/triage.jsonl   # score 20 tasks (needs API key)
uv run lab evals / lab report <id>        # past eval runs
uv run lab replay <run-id> [--entry FILE.py:FUNCTION]   # offline replay + fidelity (no API key needed)
uv run lab fidelity                       # replay recent demo runs, share that reproduce exactly
uv run lab fork <run> --step N --append-prompt "…" -n 5   # fork with a control; needs API key
uv run lab worker [--entry FILE.py:FN] [--server URL] [--once]   # run queued fork jobs
uv run lab diff <run-a> <run-b>           # trajectory diff in the terminal (UI: #/diff/A/B)
(cd ui && npm install && npm run build && npm test)   # UI build and layout tests
uv run lab ui                             # API + UI on http://127.0.0.1:8000 (Vite dev: cd ui && npm run dev)
```

`AGENTLAB_RPM` (default 15, the free-tier limit) caps Gemini requests per minute (D-026).

Runs are saved to `.agentlab/lab.db` (git-ignored). New nullable columns are added automatically
(D-031); renames or type changes still mean deleting that file.

Replay rules (D-030 to D-035): any new source of nondeterminism in agent code must go through an
interceptor (`lab.now()`, `lab.random()`, a wrapped client or `@tool`). Tool results are deep-copied
snapshots. During replay no tool or model is ever called.

Fork rules (D-037 to D-042): overrides are applied at the boundaries, never inside agent code. A
live write tool in a fork runs only through a simulator (`simulated=True` or `@tool.simulator`),
otherwise `ForkBlocked`. The API server never executes agent code: it queues fork jobs, and
workers run them. `AGENTLAB_TOKEN` guards `/api/store/*` when set.

## Current status

- **Phase 0 done** (2026-10-27): the agent loop, `@tool`, the Gemini adapter, the CLI and the
  support agent.
- **Phase 1 done** (2026-10-27): every run is traced as `invoke_agent` → `step N` → `chat` /
  `execute_tool`, saved to SQLite with recordings of every model and tool call; cost, tokens,
  latency, retries and timeouts; `lab run` / `runs` / `show`. 30 offline tests; verified live on
  Flash-Lite.
- **Phase 2 done** (2026-10-27): JSONL datasets with programmatic and LLM-judge checks, failure
  categories, a concurrent batch runner, metrics, the triage agent, a rate limiter, a FastAPI API,
  and the React UI (run list, eval report, decision tree, inspector). 64 Python tests and 5 UI
  tests; verified live.
- **Phase 3 done** (2026-10-27): deterministic replay at both boundaries plus the clock and
  randomness, recorded failures, a fidelity check, `lab replay` / `lab fidelity`, a Replay button
  in the UI, and the support agent's `refund_payment` write tool on a per-run simulated backend.
  79 Python tests; verified offline on real runs.
- **Phase 4 done** (2026-10-27): forks from any step, model call or tool call, with prompt, model
  or tool-output overrides; N forks plus N controls scored by the task, with Fisher's exact test;
  write-tool simulators; a fork job queue with `lab worker` (local or over HTTP via
  `RemoteStore`); the UI's fork dialog, fork page and run family; the `grounded` eval check;
  STORY.md. 97 Python tests; verified live (refund fix 5/5 vs 0/5, p = 0.008).
- **Phase 5 done** (2026-10-27): Trajectory Diff. Runs become steps, aligned with a shared prefix
  plus Needleman–Wunsch on a weighted step similarity; the first divergence in words; downstream
  effects and an answer word diff; `lab diff`, `/api/diff`, the diff page, and "Compare with". 111
  Python tests; verified on the refund fork and on Flash vs Flash-Lite over 8 tasks.
- Next: Phase 6 (Auto-Blame). See the checklist in PLAN.md. Tier 1 outreach can start (the
  author's step).
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
