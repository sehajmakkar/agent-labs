# Agent Reliability Lab

### Build, evaluate, and improve reliable AI agents — then find exactly where they went wrong, fork the run, and prove the fix.

Agent Reliability Lab is a framework for testing AI agents under real-world conditions. It runs agents against repeatable tasks, records every decision as an execution tree, and benchmarks implementations on task success, latency, and cost.

Most agent tools stop at **"here is what happened."** This project goes further:

> **Fork, Blame & Diff.** Point at the step where an agent went wrong, fork the run from that step with a change, replay it, and see side by side whether the fix worked.

The goal is to move beyond agents that *seem* to work toward agents whose reliability can be measured, debugged, and improved in one place.

## What Makes It Different

All four features run on one engine: **deterministic replay**. Every model response and tool result is recorded, so any run can be replayed exactly, without calling the model again.

- **Fork & Replay:** Click any node in a run's decision tree and change the prompt, the model, or a tool's output. Steps before the fork are replayed from the recording, and steps after it run live. The result is a new branch of the same run, not a new run started from scratch.
- **Auto-Blame:** For a failed run, find the *first step that went wrong*, not just the final error. Candidate steps are proposed by an LLM judge and then **verified by forking**: if correcting that step makes the run succeed, the blame is confirmed.
- **Trajectory Diff:** Align two runs (original vs. fork, or v1 vs. v2 of an agent) and highlight exactly where their paths diverged and what changed downstream.
- **Chaos Testing** *(stretch)*: Replay runs with injected tool faults (timeouts, malformed JSON, rate limits, prompt-injected tool output) and score how robust the agent is.

Some tools already let you rerun from a step (Laminar's debugger, LangGraph's time travel). The difference here is the loop: **Blame** tells you *where* to fork, **statistical forks** (N reruns → a pass rate) *prove* the fix, and **Diff** shows *what changed*.

## How Teams Use It

The lab never hosts your agent. Your agent keeps running in your own code. The lab records it and gives you a control panel.

```
  Your repo / your servers                          Agent Reliability Lab
 ┌───────────────────────────────┐   traces   ┌──────────────────────────────┐
 │ your agent  +  lab SDK         │ ─────────► │ server + trace store          │
 │                                │            │ UI: tree · blame · fork · diff│
 │ lab worker  (executes forks)   │ ◄───────── │                               │
 └───────────────────────────────┘  fork jobs └──────────────────────────────┘
```

1. **Instrument once.** Install the SDK, wrap your LLM client, and mark your tools and entry point:

   ```python
   import agentlab as lab
   from google import genai

   lab.init(".agentlab/lab.db")          # where runs are saved
   client = lab.wrap(genai.Client())     # every model call is traced and recorded

   @lab.tool(kind="read")                # safe to call again during a fork
   def get_payments(order_id: str): ...

   @lab.tool(kind="write")               # never re-executed; served from a recording or a simulator
   def refund(payment_id: str): ...

   @lab.agent("support")                 # each call becomes a run
   def support_agent(message: str): ...
   ```

   Recording, replay and fork work today. `lab replay <run>` re-runs your agent with every model call, tool call, clock read and random number served from the recording: no network, no cost, and a `write` tool never runs twice. `lab fork <run> --step N` reruns from step N with one change, N times next to a control. A `write` tool runs in a fork only through a simulator you register (`@refund.simulator`). Read time and randomness through `lab.now()` and `lab.random()` so they replay too. To send runs to a lab server instead of a local file, use `lab.init("http://lab:8000")`. [`examples/customer_app.py`](examples/customer_app.py) is a complete agent with its own loop, traced with just these lines.

2. **Run it where you already do.** Local development, a CI eval suite (`lab eval tasks.jsonl`), or production with sampling. Every run becomes a replayable trace.
3. **Debug in the UI.** Open a failed run, then **Blame** → **Fork** from the blamed step with a fix → **Diff** the branches. Forks are run by `lab worker`, a process inside your repo, so they use your real agent code.
4. **Lock it in.** Save the verified failure as a regression test; CI blocks future changes that bring it back.

Agents already traced with OpenTelemetry (for example from LangGraph) can be imported to view, diff and get blame suggestions. Forking needs the SDK, because the lab has to re-run your code.

## Core Features

- **Agent Runner:** Execute multi-step agents with tool calling, structured outputs, retries, and timeouts.
- **Execution Tracing:** Record prompts, model responses, tool calls, execution steps, errors, and token usage as a tree of spans, aligned with the OpenTelemetry GenAI conventions.
- **Decision Tree View:** Inspect any run as an interactive tree of the agent's path.
- **Evaluation Dataset:** Run agents against a repeatable collection of tasks with expected outcomes.
- **Reliability Testing:** Categorize failures such as incorrect tool use, invalid outputs, timeouts, and incomplete tasks.
- **Experiment Comparison:** Compare baseline and improved agent versions on the same evaluation dataset.
- **Observability Dashboard:** Inspect traces, task outcomes, failure patterns, latency, and cost.
- **Regression Testing:** Detect when a code, prompt, model, or tool change makes agent performance worse, and turn any failed run into a regression test.

## How It Works

1. **Define tasks:** Create an evaluation dataset with expected outcomes.
2. **Run agents:** Execute each task using a selected agent configuration.
3. **Capture traces:** Record every step, tool call, error, and model interaction as a replayable tree.
4. **Evaluate results:** Determine task success and classify failures.
5. **Blame:** For each failure, locate the first step that went wrong.
6. **Fork & verify:** Fork from the blamed step with a fix, replay, and diff the branches.
7. **Compare experiments:** Measure the impact of changes to prompts, models, tools, or agent logic.
8. **Prevent regressions:** Turn verified failures into tests that run on every change.

## Evaluation Metrics

- **Task Success Rate:** Percentage of tasks completed correctly.
- **Failure Rate:** Percentage of tasks that fail, grouped by failure category.
- **Latency:** p50 and p95 end-to-end task duration, plus individual model/tool-call latency.
- **Cost per Task:** Estimated model and tool execution cost per task.
- **Token Usage:** Input/output tokens per task and across experiments.
- **Tool Reliability:** Tool-call success rate, invalid arguments, retries, and timeouts.
- **Regression Rate:** Number of previously passing tasks that fail after a change.
- **Retry Rate:** Percentage of tasks requiring retries and their recovery success.
- **Evaluation Consistency:** Whether repeated runs produce consistent outcomes.
- **Trace Completeness:** Percentage of runs with sufficient traces to diagnose failures.
- **Replay Fidelity:** Percentage of recorded runs that replay to an identical tree.
- **Blame Accuracy:** How often Auto-Blame finds the correct step on runs with known, deliberately injected failures.
- **Fork Fix Rate:** Percentage of forks from a blamed step that turn a failure into a success.
- **Robustness Score** *(stretch)*: Task success under injected tool faults, relative to the clean baseline.

## Guiding Principles

- Reproducible evaluations over anecdotal demos.
- Every failure should be inspectable, diagnosable, and **replayable**.
- A root cause is a hypothesis until a fork proves it.
- Compare changes against a consistent baseline.
- Measure reliability, latency, and cost together.
- Keep evaluation results actionable for developers.

## Quickstart

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+ (for the UI) and a Gemini API key.

```bash
uv sync
cp .env.example .env          # then add GEMINI_API_KEY
uv run lab models             # check which Gemini Flash models your key can use

uv run lab run support "Was I charged twice for order 4417?"   # one run, printed as a tree
uv run lab run triage "ALR-101 is firing. What's going on?"     # the incident-triage agent

uv run lab eval datasets/support.jsonl datasets/triage.jsonl   # 20 tasks, scored, with a report
uv run lab evals              # past eval runs; `lab report <id>` prints one again

uv run lab replay <run-id>    # re-run a recorded run offline and check it reproduces exactly
uv run lab fidelity           # replay recent runs: what share reproduce exactly?
uv run lab fork <run-id> --step 3 --append-prompt "Always give the refund ID." -n 5
                              # rerun from step 3 with the change, 5× vs 5 controls, p-value
uv run lab worker --entry app.py:my_agent [--server http://lab:8000]
                              # run fork jobs queued from the UI, with your agent's code
uv run lab diff <run-a> <run-b>   # align two runs step by step: first divergence, effects

(cd ui && npm install && npm run build)
uv run lab ui                 # web UI at http://127.0.0.1:8000: runs, evals, decision trees

uv run pytest                 # offline tests, no API key needed
```

### Evals

A dataset is a JSONL file, one task per line: an input, the expected outcome in words, and checks.

```json
{"id": "support-double-charge", "agent": "support", "input": "Was I charged twice for order 4417?",
 "expected": "Confirms two captured payments and says billing will refund one; no refund claimed.",
 "checks": [{"type": "tool_called", "tool": "get_payments", "args": {"order_id": "4417"}},
            {"type": "answer_excludes", "any_of": ["has been refunded"]},
            {"type": "judge"}]}
```

Checks are programmatic (`tool_called`, `tool_not_called`, `answer_contains`, `answer_excludes`, `grounded` (IDs in the answer must come from tool results), `max_steps`) or an LLM judge with structured output. Every failed task gets a **failure category** (`wrong_tool`, `invalid_arguments`, `ignored_tool_error`, `false_claim`, `incomplete`, `timeout`, …), and each eval run reports success rate, p50/p95 latency and cost per task.

The demo datasets include deliberate traps: a prompt injection hidden in an order's item name, a voided authorization hold that looks like a double charge, and incidents whose obvious suspect (a recent deploy) is not the cause.

## Project Status

Early-stage project, built in phases. Done so far: tool-calling agents on Gemini, tracing of every run into a local or remote trace store, evals with programmatic and LLM-judge checks, a web UI with an interactive decision tree, **deterministic replay** (offline, verified span by span against the original run), **Fork & Replay** (rerun from any step with a changed prompt, model or tool result; N runs against a control; Fisher's exact test; fork jobs run by workers in your own repo), and **Trajectory Diff** (two runs aligned step by step, with the first divergence and its effect on outcome, tokens, cost and time). Order: runner and tracing → evals and tree view → deterministic replay → Fork → Trajectory Diff → Auto-Blame → regression gates → chaos testing.
