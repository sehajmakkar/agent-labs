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

1. **Instrument once.** Install the SDK, wrap your LLM client, and mark your tools and entry point *(planned API)*:

   ```python
   import agentlab as lab
   from google import genai

   client = lab.wrap(genai.Client())        # every model call is recorded

   @lab.tool(kind="read")                   # safe to call again during a fork
   def get_payments(order_id: str): ...

   @lab.tool(kind="write")                  # never re-executed; served from a recording or a simulator
   def refund(payment_id: str): ...

   @lab.agent("support")
   def support_agent(message: str): ...
   ```

2. **Run it where you already do.** Local development, a CI eval suite (`lab eval tasks.yaml`), or production with sampling. Every run becomes a replayable trace.
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

## Potential Target Companies

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

## Guiding Principles

- Reproducible evaluations over anecdotal demos.
- Every failure should be inspectable, diagnosable, and **replayable**.
- A root cause is a hypothesis until a fork proves it.
- Compare changes against a consistent baseline.
- Measure reliability, latency, and cost together.
- Keep evaluation results actionable for developers.

## Project Status

Early-stage project, planned in phases (see [PLAN.md](PLAN.md)). Order: runner and tracing → evals and tree view → deterministic replay → Fork → Trajectory Diff → Auto-Blame → regression gates → chaos testing.
