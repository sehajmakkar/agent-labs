# Implementation Plan

This project has two jobs: **teach the concepts** behind agent reliability tooling, and produce a
**demo that pitches** to the companies in the README ("I can build what you build, plus Fork, Blame &
Diff"). Every phase therefore ends with three things:

- **Demo:** something you can show in under two minutes.
- **Learn:** the concepts the phase teaches (write them up in `learnings.md` as you go).
- **Pitch:** which companies the demo speaks to.

Sizes are relative (S / M / L), not calendar estimates.

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
| LLM access | Gemini via `google-genai`, behind our own thin interface. Flash for the agent and judge, Flash-Lite for bulk runs | Provider chosen by Sehaj; the interface keeps recordings independent of the provider (D-005) |
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

### Phase 0 — Setup and a first agent · S

- **Build:** repo layout (`core/`, `agents/`, `api/`, `ui/`), environment, lint and test setup, the
smallest possible tool-calling loop with two tools, run from the command line, on Gemini. Confirm
the current Flash and Flash-Lite model IDs with `client.models.list()` and put them in config.
- **Demo:** an agent answers a question by calling a tool.
- **Learn:** what an "agent" is mechanically (a loop of model call → tool call → result →
model call), tool and function calling, structured outputs.
- **Pitch:** none yet.

### Phase 1 — Tracing SDK and trace store · M

- **Build:** span model, context propagation (each span knows its parent), the interceptor in
*record* mode, SQLite store, a CLI that prints a run as an indented tree with tokens, cost and latency.
Retries and timeouts in the runner. First version of the SDK surface: `lab.wrap(client)`,
`@lab.tool(kind="read" | "write")`, `@lab.agent(name)`.
- **Demo:** `lab run support "refund order 123"` → tree printed in the terminal.
- **Learn:** traces vs. spans vs. logs, parent/child context, OTel GenAI conventions, token
accounting and cost calculation.
- **Pitch:** none yet. This is the foundation.

### Phase 2 — Evals and the decision tree UI · M–L · *parity milestone*

- **Build:** task dataset format, programmatic checkers plus an LLM-as-judge checker, failure
categories, batch runner, metrics (success rate, p50/p95 latency, cost per task). Web UI: run list,
**interactive decision tree** (React Flow), node inspector (prompt, response, tool input and output).
- **Demo:** run 20 tasks, open a failed one, click through its tree to the bad tool call.
- **Learn:** eval design, programmatic vs. LLM-judge scoring, judge bias, percentiles, frontend tree
layout.
- **Pitch:** "I can build your core product." Parity with Laminar, Raga AI, Langfuse and Maxim's
tracing view. **Not enough to pitch on its own.**

### Phase 3 — Deterministic replay · M

- **Build:** interceptor *replay* mode, request hashing to match each call to its recording, tool
simulator with read/write classification (writes never reach anything real), a **replay fidelity**
check (replayed tree == original tree), clock and random seeding. Record Gemini's thinking and
function-call parts exactly, so the replayed conversation is byte-for-byte what the model saw.
- **Demo:** replay a recorded run with the network off and get an identical tree with zero API cost.
- **Learn:** determinism, the record/replay ("VCR") pattern, content hashing, idempotency, side
effects.
- **Pitch:** a strong engineering talking point; still invisible to non-engineers.

### Phase 4 — Fork & Replay · L · *first pitchable demo*

- **Build:** "Fork from here" on any node; override editor (change the prompt, model, or tool
output); replay to the fork point, then run live; store the fork as a child run; run each fork
**N times** to tell a real change apart from random variation; show the run family as a tree in the UI.
`lab worker`: a process in the user's repo that takes fork jobs from the server and runs the agent
in fork mode (D-009).
- **Demo:** a support run fails because of a bad tool response. Fork at that step, fix the response,
and the agent now succeeds 5 out of 5 times.
- **Learn:** state snapshots, copy-on-write, counterfactual reasoning, comparing distributions
(pass rate across N samples) instead of single runs.
- **Pitch:** **start outreach to Tier 1 here.** Maxim (simulation → verified fix), Agnost (the "why"
next to their "what"), Laminar, Raga AI.

### Phase 5 — Trajectory Diff · M

- **Build:** align two runs step by step (shared start, then sequence alignment on step type, tool
name and argument similarity), mark the point of divergence, show matched, changed, added and
removed steps side by side; summarize the downstream effect (tokens, cost, outcome).
- **Demo:** original vs. fork, or agent v1 vs. v2 on the same task: "they split at step 4; v2 called
`lookup_order` instead of guessing." Also Flash vs. Flash-Lite: "the cheaper model saves 40% but
skips the verification step on refunds."
- **Learn:** sequence alignment (LCS, Needleman–Wunsch), similarity measures, tree edit distance,
designing a diff view.
- **Pitch:** Braintrust, Raga AI, Arize: experiments become explainable, not just scored.

### Phase 6 — Auto-Blame · L · *headline differentiator*

- **Build:** given a failed run, an LLM judge ranks candidate "first wrong steps" with reasons;
**verify** the top-k by forking each with a corrected step and measuring the pass rate; report
confirmed blame and its confidence. Benchmark against the seeded failure catalog to measure
**Blame Accuracy**.
- **Demo:** one click on a failed run → "Step 3 is at fault: the agent ignored the tool's error.
Verified: correcting it gives 5/5 passes." Then the accuracy chart on 50 seeded failures.
- **Learn:** failure attribution (research such as the Who&When benchmark), LLM-judge calibration,
precision and recall at k, the cost trade-off of verifying by replay.
- **Pitch:** BentoLabs, Sentrial, DrDroid, Galileo, Future AGI. A root cause you have *proved*, not
just a guess.

### Phase 7 — Experiments, regressions and CI gate · M

- **Build:** run comparison across agent versions (success, cost, latency, regression rate); "turn
this failure into a regression test" (freeze the recorded tools as fixtures, store the expected
outcome); a GitHub Action that fails a PR when the regression rate goes up.
- **Demo:** a prompt change opens a PR → CI runs the suite → blocked because 2 tasks regressed → the
diff view shows why.
- **Learn:** regression testing for nondeterministic systems, flakiness and pass-rate thresholds,
CI pipelines.
- **Pitch:** Athina, LangWatch, TestMu AI, CodeAnt AI, Lyzr and UnifyApps (enterprise reliability gates).

### Phase 8 — Chaos testing · M · *stretch, only after Phases 4–6 are solid*

- **Build:** interceptor *chaos* mode with a fault library (timeout, 429, malformed JSON, empty
result, wrong-but-valid data, prompt injection in tool output); a robustness score for each fault
type; a report of which faults the agent handles and which it doesn't.
- **Demo:** "Your agent survives timeouts but follows instructions injected into a tool's output
40% of the time."
- **Learn:** chaos engineering, resilience patterns (retries, backoff, circuit breakers), prompt
injection through tool output.
- **Pitch:** Composio, Metorial, Cekura, TestMu AI, Portkey, TrueFoundry.

### Phase 9 — Pitch kit · S–M

- **Build:** import OTel GenAI traces from outside frameworks (for example LangGraph or the OpenAI
Agents SDK), so companies see their own stack in the viewer (view, diff and blame-suggest work;
fork needs our SDK); a **LangGraph adapter** that applies our interception to LangGraph's model  
and tool nodes, so LangGraph agents can be forked too; a hosted read-only demo with seeded data; a 2-minute video; a one-page demo script per Tier 1 company; a technical write-up built from `learnings.md` and `challenges.md`.
- **Learn:** OTLP ingestion, product storytelling.
- **Pitch:** everyone. Each message links the demo that fits that company's product.

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
