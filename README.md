# Agent Reliability Lab
### Build, evaluate, and improve reliable AI agents.

Agent Reliability Lab is a framework for testing AI agents under real-world conditions. It runs agents against repeatable tasks, records execution traces, tracks tool calls and failures, and benchmarks different implementations using task success, latency, and cost. The goal is to move beyond agents that *seem* to work toward agents whose reliability can be measured and improved.

## Core Features

- **Agent Runner:** Execute multi-step agents with tool calling, structured outputs, retries, and timeouts.
- **Execution Tracing:** Record prompts, model responses, tool calls, execution steps, errors, and token usage.
- **Evaluation Dataset:** Run agents against a repeatable collection of tasks with expected outcomes.
- **Reliability Testing:** Categorize failures such as incorrect tool use, invalid outputs, timeouts, and incomplete tasks.
- **Experiment Comparison:** Compare baseline and improved agent versions on the same evaluation dataset.
- **Observability Dashboard:** Inspect traces, task outcomes, failure patterns, latency, and cost.
- **Regression Testing:** Detect when a code, prompt, model, or tool change makes agent performance worse.

## How It Works

1. **Define tasks:** Create an evaluation dataset with expected outcomes.
2. **Run agents:** Execute each task using a selected agent configuration.
3. **Capture traces:** Record every important step, tool call, error, and model interaction.
4. **Evaluate results:** Determine task success and classify failures.
5. **Compare experiments:** Measure the impact of changes to prompts, models, tools, or agent logic.
6. **Improve reliability:** Use the results to identify bottlenecks and prevent regressions.

## Initial Tech Stack

- **Backend:** TypeScript + Node.js
- **Database:** PostgreSQL
- **Agent Integration:** Model-provider abstraction with tool calling
- **Observability:** OpenTelemetry-inspired traces and structured logs
- **Dashboard:** React + Vite
- **Deployment:** Docker

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

## Potential Target Companies

Companies to study, learn from, or approach for relevant engineering opportunities. This list does **not** imply they are currently hiring or that every role is suitable.

**Agent evaluation & reliability:** Ressl AI, Agnost AI, Maxim AI, Cekura, BentoLabs, DrDroid, Raga AI, Athina AI.

**AI developer tools & code quality:** CodeAnt AI, TestMu AI, Composio, Metorial, Dexto.

**AI infrastructure & platforms:** TrueFoundry, Portkey, Scalekit, UnifyApps, Lyzr.

**AI applications & media agents:** Cardboard, Clueso, Trupeer, InVideo, Spyne.ai.

## Guiding Principles

- Reproducible evaluations over anecdotal demos.
- Every failure should be inspectable and diagnosable.
- Compare changes against a consistent baseline.
- Measure reliability, latency, and cost together.
- Keep evaluation results actionable for developers.

## Project Status

Early-stage project. Initial focus: a working agent runner, trace storage, a small evaluation dataset, baseline-versus-improved experiments, and a dashboard showing reliability, latency, cost, and failure patterns.
