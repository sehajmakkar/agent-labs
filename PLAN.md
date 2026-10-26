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
| 1 | Tracing SDK and trace store | ⏭️ Next |
| 2 | Evals and the decision tree UI | ⬜ Not started |
| 3 | Deterministic replay | ⬜ Not started |
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

### Phase 1 — Tracing SDK and trace store · M · ⏭️ Next

- [ ] Run and Span models, with field names aligned to the OTel GenAI conventions (pinned version)
- [ ] Context propagation: each span knows its parent
- [ ] Interceptor in *record* mode at the LLM client and tool boundaries
- [ ] Recordings store Gemini's raw response content (C-005)
- [ ] SQLite trace store (SQLModel)
- [ ] Token accounting and cost per span
- [ ] Retries and timeouts in the runner
- [ ] SDK surface: `lab.wrap(client)`, `@lab.tool(kind="read" | "write")`, `@lab.agent(name)`
- [ ] CLI prints a run as an indented tree with tokens, cost and latency
- [ ] **Demo:** `lab run support "..."` → tree printed in the terminal
- [ ] **Learnings** written up
- **Learn:** traces vs. spans vs. logs, parent/child context, OTel GenAI conventions, token
accounting and cost calculation.
- **Pitch:** none yet. This is the foundation.

### Phase 2 — Evals and the decision tree UI · M–L · *parity milestone*

- [ ] Task dataset format (input, expected outcome, checker)
- [ ] Programmatic checkers
- [ ] LLM-as-judge checker with structured output
- [ ] Failure categories (wrong tool, invalid arguments, timeout, incomplete, false claim, …)
- [ ] Batch runner over a dataset
- [ ] Metrics: success rate, p50/p95 latency, cost per task
- [ ] Incident triage demo agent
- [ ] FastAPI server (`api/`)
- [ ] UI: run list
- [ ] UI: **interactive decision tree** (React Flow)
- [ ] UI: node inspector (prompt, response, tool input and output)
- [ ] **Demo:** run 20 tasks, open a failed one, click through its tree to the bad tool call
- [ ] **Learnings** written up
- **Learn:** eval design, programmatic vs. LLM-judge scoring, judge bias, percentiles, frontend tree
layout.
- **Pitch:** "I can build your core product." Parity with Laminar, Raga AI, Langfuse and Maxim's
tracing view. **Not enough to pitch on its own.**

### Phase 3 — Deterministic replay · M

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
