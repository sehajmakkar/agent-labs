# Walkthrough

How to read this codebase in an order where each file only needs what you've already read. It
covers what has been built, how a run and an eval flow through the code, how tool calling works,
and what to show in an interview.

Claude updates this file at the end of every phase: new files go into the reading order, and each
phase gets a short recap. Last updated: **Phase 2 (2026-10-27)**.

---

## 1. What exists so far

**In one sentence:** two demo agents (customer support and incident triage) answer questions by
calling tools. Every model and tool call is recorded to a local database. A dataset of 20 tasks
scores the agents automatically, and a web UI shows any run as a clickable decision tree.

| Phase | What it added | Try it |
|---|---|---|
| 0 | An agent loop, `@tool`, a Gemini adapter, a demo support agent, the CLI | `uv run lab run support "Was I charged twice for order 4417?"` |
| 1 | Tracing: every run saved to SQLite as a tree of spans, with the exact request and response of every call; tokens, cost, latency, retries, timeouts | `uv run lab runs`, then `uv run lab show <id>` |
| 2 | Evals (datasets, checks, LLM judge, failure categories, metrics), the triage agent, a rate limiter, the FastAPI server and the React UI | `uv run lab eval datasets/*.jsonl`, then `uv run lab ui` |

**Not built yet:** replay from recordings (Phase 3), then fork, diff and blame (Phases 4 to 6).

The lab has **two halves**, and the split matters in interviews:

- **The agent** (`loop.py`, `tools.py`, `llm/`, `demo/`): the thing being observed. In real use
  this is the customer's code, not ours. [examples/customer_app.py](examples/customer_app.py) is
  such an agent: it uses none of our loop.
- **The lab** (`tracing.py`, `store.py`, the wrapper in `gemini.py`, `evals/`, `server.py`,
  `ui/`): what observes and scores it. It only touches the agent at two **boundaries**, the model
  client and the tool functions (decisions.md D-004, D-016).

---

## 2. How data flows

### 2a. One run

Here is everything that happens when you type
`uv run lab run support "Was I charged twice for order 4417?"`.

```
cli.main()                                         cli.py
 ├─ load_settings()             key, model IDs, rate limit   config.py
 ├─ GeminiClient(...)           wraps genai.Client, owns the rate limiter   llm/gemini.py
 ├─ tracing.init(".agentlab/lab.db")   recording on tracing.py → store.py
 └─ run_agent(AGENT, llm, model, message)          loop.py
     └─ agent_run(...)          new row in `runs`, opens span "invoke_agent support"
         └─ _loop()
             │  messages = [user: "Was I charged twice…"]
             ├─ step 1          span "step 1"
             │   ├─ call_with_retries(llm.generate)             retry.py
             │   │    └─ GeminiClient.generate                  llm/gemini.py
             │   │        ├─ limiter.acquire()     wait if over 15 requests/min   llm/ratelimit.py
             │   │        ├─ to_contents(messages)    our types → Gemini's types
             │   │        ├─ TracedModels.generate_content      span "chat gemini-…"
             │   │        │    ├─ real HTTP call to Gemini
             │   │        │    └─ record(request, response), tokens, cost
             │   │        └─ from_response()          Gemini's types → our types
             │   │   model said: call get_payments(order_id="4417")
             │   └─ _execute(call)
             │        └─ Tool.invoke(args)            span "execute_tool get_payments"   tools.py
             │             validate args → run the Python function → record
             │   messages += [model turn, tool results]
             ├─ step 2 …        model calls get_order
             └─ step 3          model replies with text and no tool calls → stop, "completed"
 then: store.spans(run_id) → render_run() → print the tree                      render.py
```

Each span is saved to SQLite **when it ends**, which is why spans carry a `seq` number for their
start order (challenges.md C-008).

### 2b. One eval

Here is what happens for `uv run lab eval datasets/support.jsonl datasets/triage.jsonl`.

```
cli._eval
 ├─ load_dataset(path)          each JSONL line → Task (input, expected, checks)   evals/tasks.py
 ├─ LLMJudge(llm, flash-lite)                                                     evals/judge.py
 └─ run_eval(tasks, …)                                                            evals/runner.py
     ├─ store.create_eval_run()                 row in `eval_runs`
     ├─ ThreadPoolExecutor(4): for each task, in parallel:
     │    ├─ run_agent(agent, task.input, task_id=…, run_id=…)   = section 2a, a normal traced run
     │    ├─ Trajectory.from_store(run_id)      read the run BACK from the store   evals/trajectory.py
     │    ├─ score(task, trajectory, judge)
     │    │    ├─ each check.evaluate()         tool_called / answer_contains / … → CheckResult
     │    │    ├─ judge check → LLMJudge()      Gemini with response_json_schema → Verdict
     │    │    └─ pick_category(status, failed) one failure category      evals/categories.py
     │    └─ store.save_eval_result()           row in `eval_results` (task, run, checks, category)
     └─ summarize() → finish_eval_run(metrics)  success rate, p50/p95, cost   evals/metrics.py
 then: render_eval() prints the report                                           render.py
```

### 2c. The UI

`uv run lab ui` starts FastAPI (`server.py`), which serves `ui/dist` and the `/api/*` endpoints.

```
browser  #/evals/<id>       → GET /api/evals/<id>             → eval run + run summaries
         #/runs/<id>        → GET /api/runs/<id>              → run + flat list of spans
                              ui: layoutTree(spans) → React Flow draws nodes and edges
         click a node       → URL becomes #/runs/<id>?span=<span-id>
                            → GET /api/spans/<span-id>/recordings → exact prompt and reply
```

---

## 3. Reading order

★★★ means it's core: know it well enough to explain without looking. ★★ means understand what it
does and why. ★ means skim. The times are for a careful first read. **New in Phase 2** is marked 🆕.

### Step 0: orient (10 min)

1. **[README.md](README.md)**: what the product is for. Skim it.
2. **[PLAN.md](PLAN.md)**: the Progress table and each finished phase's **How we built it**.
3. Run the demo once: `uv run lab run support "Was I charged twice for order 4417?"`. Keep the
   tree output open while you read the code.

### Step 1: the agent from the outside

4. **[src/agentlab/demo/support.py](src/agentlab/demo/support.py)** ★★ (108 lines, 5 min)
   This is what a *user* of the lab writes: fake data, three functions marked `@tool`, a system
   prompt, and an `Agent(...)`. Don't worry about how `@tool` works yet; Section 4 covers it. The
   docstrings are written for the **model** to read. The docstring at the top lists the four traps
   built in for evals.
   *Check yourself:* why does order 4523 *look* double-charged but isn't?

### Step 2: the vocabulary

5. **[src/agentlab/llm/base.py](src/agentlab/llm/base.py)** ★★★ (91 lines, 10 min)
   These are the nouns everything else uses: `Message`, `ToolCall`, `ToolResult`, `Usage`,
   `LLMResponse`, `TransientLLMError` (which can carry the server's `retry_after_s`), and the
   `LLMClient` protocol.
   - A conversation is a `list[Message]`. Each message's role is `user`, `model` or `tool`.
   - `LLMClient` is a `Protocol`: any object with a matching `generate(...)` counts, which is how
     tests swap in a fake. 🆕 `response_schema` asks for structured output; the judge uses it.
   - `raw` keeps Gemini's original response so it can be sent back unchanged (D-012, C-005).

### Step 3: the heart

6. **[src/agentlab/loop.py](src/agentlab/loop.py)** ★★★ (147 lines, 20 min). **This is the most
   important file.**
   An agent is this loop: send the conversation to the model, run any tools it asks for, append the
   results, and repeat until it answers in plain text. On this first read, treat `span(...)` and
   `agent_run(...)` as "a stopwatch box that gets saved", and `call_with_retries` as "try again if
   Gemini is busy".
   - `_loop` (lines 87–123): the loop itself. The stopping rule is on line 119: no tool calls means
     a final answer.
   - `_execute` (lines 126–147): a tool error becomes **data** sent back to the model, and never
     crashes the loop (D-013).
   - 🆕 `run_agent(task_id=…, run_id=…)`: the eval runner chooses the run's ID up front, so it can
     score a run even if it crashes.

### Step 4: tools

7. **[src/agentlab/tools.py](src/agentlab/tools.py)** ★★★ (100 lines, 20 min)
   Read [Section 4](#4-how-tool-calling-works) first, then this file.
   - `tool()` / `decorate()`: turn a function into a `Tool` object.
   - `_args_model`: type hints → a pydantic model → a JSON Schema.
   - `invoke` (lines 40–63): validate → call → record. Every call becomes an `execute_tool` span.

### Step 5: talking to Gemini (first half)

8. **[src/agentlab/llm/gemini.py](src/agentlab/llm/gemini.py)**, **lines 1–160 only** ★★ (15 min)
   - `GeminiClient.generate`: builds the config (system prompt, tool declarations, automatic
     function calling **off**, 🆕 optional JSON schema). It waits on the rate limiter, then
     converts errors (429/503 → `TransientLLMError`).
   - 🆕 `_retry_delay`: reads the server's "retry in 3.6s" hint (`RetryInfo`).
   - `_declaration`: a `Tool` → a Gemini `FunctionDeclaration`.
   - `to_contents`: our messages → Gemini contents. Tool results go back as `function_response`
     parts in a **user** turn (lines 114–124).
   - `from_response`: Gemini's response → our `LLMResponse`.

### Step 6: small helpers

9. **[src/agentlab/config.py](src/agentlab/config.py)** ★ (5 min): model IDs, prices, and
   🆕 `AGENTLAB_RPM`.
10. **[src/agentlab/retry.py](src/agentlab/retry.py)** ★★ (39 lines, 5 min): exponential backoff
    with jitter; 🆕 never waits less than the server asked.
11. 🆕 **[src/agentlab/llm/ratelimit.py](src/agentlab/llm/ratelimit.py)** ★★ (48 lines, 5 min): a
    sliding-window limiter shared by threads. Note the lock, and the sleep that happens *outside*
    it.
12. **[src/agentlab/cost.py](src/agentlab/cost.py)** ★ (15 lines, 2 min): tokens × price.

### Step 7: tracing (the "lab" half)

13. **[src/agentlab/semconv.py](src/agentlab/semconv.py)** ★ (3 min): attribute names.
14. **[src/agentlab/store.py](src/agentlab/store.py)** ★★ (302 lines, 15 min): five tables.
    - `runs`, `spans` and `recordings` came in Phase 1.
    - 🆕 `eval_runs` and `eval_results`.
    - 🆕 WAL mode and `check_same_thread=False`, so threads can write while the UI reads.
    - 🆕 `run_totals` sums tokens and cost per run in one `GROUP BY` query.
    - 🆕 `run_message` / `run_answer` read runs from both our loop and `@lab.agent`.
15. **[src/agentlab/tracing.py](src/agentlab/tracing.py)** ★★★ (231 lines, 25 min). **The second
    most important file.** Read [Section 5](#5-tracing-in-five-minutes) first.
    - `span()` (lines 106–131): open a span, make it current, save it on exit.
    - `agent_run()`: also creates the run row. 🆕 It records rate-limit waiting on the root span.
    - `Span.record()`, `@agent`, 🆕 `note_wait()`.

### Step 8: close the loop

16. **[src/agentlab/llm/gemini.py](src/agentlab/llm/gemini.py)**, **lines 162–230** ★★★ (10 min).
    `TracedGenAIClient` is the **model-call boundary**: a stand-in for `genai.Client` that turns
    each `generate_content` into a recorded `chat` span.
17. **Re-read `Tool.invoke`** in [tools.py](src/agentlab/tools.py). It is the **tool-call
    boundary**, and it works the same way.
18. **[src/agentlab/\_\_init\_\_.py](src/agentlab/__init__.py)** ★★ (3 min): the public SDK.
19. 🆕 **[examples/customer_app.py](examples/customer_app.py)** ★★★ (86 lines, 10 min): someone
    else's agent, with its own loop over raw `google-genai`, traced by lines 1, 2 and 3 only. This
    is the integration story in one file.

### Step 9: the demo agents and the CLI

20. 🆕 **[src/agentlab/demo/triage.py](src/agentlab/demo/triage.py)** ★★ (212 lines, 10 min): an
    on-call assistant over simulated alerts, metrics, logs and deploys. Read the top docstring for
    each incident's real cause and its distraction.
21. **[src/agentlab/render.py](src/agentlab/render.py)** ★ (5 min): the terminal tree, and
    🆕 `render_eval` for the report.
22. **[src/agentlab/cli.py](src/agentlab/cli.py)** ★★ (260 lines, 10 min): `run`, `runs`, `show`,
    🆕 `eval`, `evals`, `report` and `ui`.

### Step 10: evals 🆕

Read these in this order; each one uses the ones before it.

23. **[datasets/support.jsonl](datasets/support.jsonl)** ★★ (5 min): look at two or three tasks:
    input, expected outcome, checks.
24. **[src/agentlab/evals/categories.py](src/agentlab/evals/categories.py)** ★★ (49 lines, 5 min):
    the failure categories and `pick_category`.
25. **[src/agentlab/evals/trajectory.py](src/agentlab/evals/trajectory.py)** ★★★ (79 lines,
    10 min): a stored run flattened for checks, and `transcript()` for the judge. Scoring from
    the *store* is why evals work on any agent (D-023).
26. **[src/agentlab/evals/judge.py](src/agentlab/evals/judge.py)** ★★★ (80 lines, 10 min):
    structured output with a pydantic `Verdict`, reasoning before verdict, and the judge prompt.
27. **[src/agentlab/evals/tasks.py](src/agentlab/evals/tasks.py)** ★★★ (191 lines, 20 min): the
    check classes, the discriminated union `Check`, `Task` and `load_dataset`.
28. **[src/agentlab/evals/metrics.py](src/agentlab/evals/metrics.py)** ★★ (65 lines, 5 min):
    `percentile` and `summarize`.
29. **[src/agentlab/evals/runner.py](src/agentlab/evals/runner.py)** ★★★ (119 lines, 15 min): the
    batch runner, which uses threads and scores and saves each task. Trace it against Section 2b.

### Step 11: the server and the UI 🆕

30. **[src/agentlab/server.py](src/agentlab/server.py)** ★★ (202 lines, 10 min): the response
    models, then the routes in `create_app`. Open http://127.0.0.1:8000/docs while `lab ui` runs.
31. **[ui/src/api.ts](ui/src/api.ts)** ★★ (5 min): the same shapes in TypeScript, plus fetchers.
32. **[ui/src/lib/layout.ts](ui/src/lib/layout.ts)** ★★★ (50 lines, 10 min) and its test,
    [layout.test.ts](ui/src/lib/layout.test.ts): the tree layout.
33. **[ui/src/lib/hooks.ts](ui/src/lib/hooks.ts)** ★ (5 min): the hash router and `useLoad`.
34. **[ui/src/components/SpanNode.tsx](ui/src/components/SpanNode.tsx)** →
    **[TraceTree.tsx](ui/src/components/TraceTree.tsx)** ★★★ (15 min): one node, then the whole
    tree with its red error path.
35. **[ui/src/components/Inspector.tsx](ui/src/components/Inspector.tsx)** ★★ (10 min): rebuilds
    the exact prompt from a recording.
36. **[ui/src/pages/](ui/src/pages/)** ★ (10 min): `Runs.tsx`, `RunView.tsx`, `Evals.tsx`; then
    [App.tsx](ui/src/App.tsx) and [main.tsx](ui/src/main.tsx).

### Step 12: tests (the specification)

37. **[tests/test_loop.py](tests/test_loop.py)** ★★★: `ScriptedLLM`, a fake model.
38. 🆕 **[tests/test_evals.py](tests/test_evals.py)** ★★★: every check type, the judge with a fake
    LLM, categories, percentiles, and the runner end to end.
39. 🆕 **[tests/test_server.py](tests/test_server.py)**, **[test_ratelimit.py](tests/test_ratelimit.py)**,
    **[test_demo.py](tests/test_demo.py)** ★★. `test_demo` checks that every dataset task names a
    real agent and tool, with valid arguments.
40. **[tests/test_tools.py](tests/test_tools.py)**, **[test_tracing.py](tests/test_tracing.py)**,
    **[test_gemini.py](tests/test_gemini.py)**, **[test_render.py](tests/test_render.py)** ★★.

### Step 13: the why

These decisions.md entries come up in interviews: **D-004** (own loop), **D-008** (positioning),
**D-009** (integration), **D-013** (tool errors as data), **D-015** (step spans), **D-016**
(wrapping the SDK), 🆕 **D-023** (evals score traces), **D-024** (the judge), **D-026** (rate
limiting). In [learnings.md](learnings.md), read the Phase 2 sections.

---

## 4. How tool calling works

**The model never runs your code.** It can only write text. Tool calling is an agreement:

1. We tell the model what tools exist: name, description and a JSON Schema for the arguments.
2. The model can reply with a structured *request* instead of an answer: "please call
   `get_payments` with `{"order_id": "4417"}`".
3. **Our code** runs the function and sends the result back in the next message.
4. The model reads the result and either asks for another tool or writes its answer.

Here is what a real run (`0c692454`, from Phase 1) sent and received, taken from
`.agentlab/lab.db`:

**① What we send: the tool list** (built from `support.py` by `@tool`):
```json
{"function_declarations": [{
  "name": "get_payments",
  "description": "List every payment charged for an order, with its amount and status.",
  "parameters_json_schema": {
    "type": "object",
    "properties": {"order_id": {"type": "string", "title": "Order Id"}},
    "required": ["order_id"]}}, … get_order …]}
```
plus the conversation: `[{"role": "user", "parts": [{"text": "Was I charged twice for order 4417?"}]}]`

**② What the model replies.** There's no text, only a function call:
```json
{"role": "model", "parts": [{"function_call":
  {"id": "call_2311547", "name": "get_payments", "args": {"order_id": "4417"}}}]}
```

**③ What our loop does.** `from_response` turns that into `ToolCall(name="get_payments",
args={"order_id": "4417"}, id="call_2311547")`. `_execute` finds the `Tool` by name and calls
`tool.invoke(args)`, which runs your Python function and records:
```json
request:  {"tool": "get_payments", "args": {"order_id": "4417"}}
response: {"output": {"order_id": "4417", "payments": [{"payment_id": "P-901", …}, {"payment_id": "P-902", …}]}}
```

**④ What we send next.** The whole conversation again, now with the model's turn and a
`function_response` part carrying the same `id` (`to_contents`, gemini.py lines 114–124).

The UI shows all of this for any model call: click a `model` node and the inspector lists the
system instruction, the tools offered and every turn of the conversation.

### What `@tool` means

A decorator is a function that takes a function and returns something to use in its place. These
two snippets are identical:

```python
@tool(kind="read")
def get_order(order_id: str) -> dict: ...

# is exactly the same as
def get_order(order_id: str) -> dict: ...
get_order = tool(kind="read")(get_order)
```

So after the decorator, `get_order` is **no longer a function**. It is a `Tool` object:

| Field | Comes from | Used for |
|---|---|---|
| `name` | `fn.__name__` → `"get_order"` | the name the model calls it by |
| `description` | the docstring | how the model decides *when* to call it |
| `args_model` | type hints → pydantic model | validating the model's arguments and building the JSON Schema |
| `kind` | `"read"` or `"write"` | later, replay and fork need to know if a call has side effects (C-002) |
| `fn` | the original function | the code that actually runs |

You can still call it like a function: `get_order("4417")` goes through `Tool.__call__` →
`invoke`. Try it:

```
uv run python -c "from agentlab.demo.support import get_order; print(type(get_order).__name__, get_order.parameters_schema)"
```

### Why validate the arguments

| The model sends | The model receives back |
|---|---|
| `{}` | `Invalid arguments: order_id: Field required` |
| `{"order_id": 4417}` (a number) | `Invalid arguments: order_id: Input should be a valid string` |
| `{"order_id": "9999"}` | `LookupError: No order with ID 9999` (raised by your function) |

All three go back to the model **as data** (D-013). Whether it then tells the user honestly is
exactly what the evals measure. See the `ALR-999` failure in the Phase 2 recap.

### Python ideas used here

- **Decorator**: see above.
- **`@dataclass`**: a class whose `__init__` is generated from its fields. `frozen=True` makes it
  read-only.
- **`Protocol`**: "anything with these methods", checked by shape, not by inheritance.
- **Context manager** (`with … as s:`): code that runs on entry and on exit, even when there is an
  exception.
- **`ContextVar`**: a variable that is "current" for the code running now, including per thread.
- 🆕 **Discriminated union** (pydantic): `Check = Annotated[ToolCalled | AnswerContains | …,
  Field(discriminator="type")]`. The `type` field picks which class to build.

---

## 5. Tracing in five minutes

- **Run**: one execution of the agent on one input.
- **Span**: one timed unit of work inside a run. It has a parent, so spans form a tree.
- **Recording**: the exact request and response of one call, which is enough to replay it.

How `span()` works (tracing.py lines 106–131):

```
with span("tool", "execute_tool get_payments") as s:   # ENTER
    ...                                                 # BODY: fill in s.output, s.error, s.record(...)
                                                        # EXIT
```
- **Enter**: read `_current_span`, which is the parent, and make a new `Span` whose `parent_id`
  is that parent's id. Set `_current_span` to the new span and take the next `seq`.
- **Body**: any `span()` opened inside it automatically becomes a child (**context
  propagation**).
- **Exit**: put the old current span back, store any exception as the span's error, and save the
  span and its recordings. Without `lab.init()`, nothing is saved (D-018).

You can see it in your own database:
```
sqlite3 .agentlab/lab.db "select seq, kind, name, round(duration_ms) from spans where run_id like '0c692454%' order by seq"
```

**Why record the exact request and hash it?** In Phase 3, replay will rerun the agent and, instead
of calling Gemini, look up the request's hash and return the saved response. A fork is then a
replay that changes one thing at one step.

**A fake LLM leaves no `chat` spans.** Those come from the wrapped Gemini client. A test's
`ScriptedLLM` bypasses that client, so its runs show `agent → step → tool` only. That shows the
boundary is the SDK client, not our loop.

---

## 6. For interviews and demos

**The demo:**
1. `uv run lab ui`, then open the Evals tab and the latest eval.
2. Point at the success rate, the p50/p95 latencies and the failure-category chart.
3. Click the failed task. The tree shows the red path to the tool call that failed, and the
   checks at the top say why the task failed.
4. Click the failing tool node: the error and the arguments the model wrote. Click the next
   model node: the exact prompt it saw, including that error.

**Files to have open:** [loop.py](src/agentlab/loop.py), [tools.py](src/agentlab/tools.py),
[tracing.py](src/agentlab/tracing.py), the wrapper in [gemini.py](src/agentlab/llm/gemini.py),
[examples/customer_app.py](examples/customer_app.py) and
[evals/runner.py](src/agentlab/evals/runner.py).

**A 60-second explanation:**
> "An agent is a loop: call the model, run the tools it asks for, feed results back. I intercept
> at exactly two boundaries — the model client and the tool functions — so any agent, even one
> with its own loop, gets traced with three lines. Every call becomes a span in a tree with the
> exact request and response recorded. On top of the traces I built evals: a JSONL dataset,
> programmatic checks plus an LLM judge with structured output, failure categories, and p50/p95
> and cost metrics, all scored from the stored traces. The UI shows any run as a decision tree with
> the path to the failure highlighted. Next: deterministic replay from the recordings, then fork,
> diff and auto-blame."

**Questions you should be able to answer:**

| Question | Short answer | Where |
|---|---|---|
| Why not LangGraph? | Tracing needs control of every call. Companies in this space build framework-agnostic SDKs. | D-004 |
| How do you intercept calls? | Wrap the SDK client (a stand-in object), and tools record themselves. | D-016 |
| What happens when a tool fails? | The error goes back to the model as data, and the span is marked as an error. | D-013 |
| How do spans find their parent? | A `ContextVar` holds the current span, and each thread has its own. | tracing.py |
| 🆕 How do you score an agent? | Programmatic checks for facts, an LLM judge for meaning, both run on the stored trace. | D-023, D-024 |
| 🆕 How do you trust the judge? | Structured output, reasoning first, tool results as ground truth, code checks beside it. We know its biases, and its reasoning is shown. | learnings.md |
| 🆕 Why p95, not the average? | Averages hide the slow tail that users notice. | metrics.py |
| 🆕 What broke? | The free tier's 15 RPM failed half the first eval. We added a client-side limiter, honoured `RetryInfo`, and kept throttle time out of latency. | C-012, D-026 |
| 🆕 An interesting failure? | ALR-999: the tool said "no such alert", and the agent silently investigated a different alert. The answer looked expert; only the trace shows it. | learnings.md |
| 🆕 Why is the UI's tree layout your own? | A trace is a tree; 50 lines, unit-tested, no graph library needed. | D-028 |

---

## 7. Staying in the loop

### A review routine after each phase (about an hour)

1. **Run it first.** Do the phase's demo before reading code.
2. **See what changed.** Run `git diff --stat <last-phase-commit>`, then read the phase recap
   below and the phase's **How we built it** in PLAN.md.
3. **Read the code in order.** New files are marked 🆕 in Section 3.
4. **Break something on purpose.** Each recap lists experiments. Predict the result before you run
   it.
5. **Explain it back.** Write 3–5 lines in your own words, or ask Claude to check your
   explanation.
6. **Write the commit message yourself.**

### Theory and practice side by side

| Concept | In the code | Experiment |
|---|---|---|
| The agent loop | `loop.py` `_loop` | Put `breakpoint()` after `messages.append(response.message)` and print `messages`. |
| Tool descriptions steer the model | `demo/support.py` docstrings | Delete the status explanation from `get_payments`'s docstring and run `lab eval datasets/support.jsonl --tasks support-voided-hold`. |
| Tool errors as data | `loop.py` `_execute` | `lab run triage "Can you look into ALR-999?"` and check whether it tells you the alert doesn't exist. |
| Context propagation | `tracing.py` `span` | Read `test_spans_nest_under_the_span_open_around_them`. |
| 🆕 Checks | `evals/tasks.py` | Add a task to `datasets/support.jsonl` and run it with `--tasks <id> --no-judge`. |
| 🆕 The judge | `evals/judge.py` | Change a task's `expected` to something wrong and watch the judge fail a good answer. |
| 🆕 Percentiles | `evals/metrics.py` | `percentile([1,2,3,4,100], 50)` vs. the mean, in a Python shell. |
| 🆕 Rate limiting | `llm/ratelimit.py` | `AGENTLAB_RPM=5 uv run lab eval datasets/triage.jsonl --tasks triage-db-pool` and look at the "wait left out" line. |
| 🆕 The tree layout | `ui/src/lib/layout.ts` | Change `GAP_Y` and rebuild; or break the centring and see which test fails (`npm test`). |
| 🆕 The API | `server.py` | Open http://127.0.0.1:8000/docs and call `/api/runs?status=error`. |

### Ways to work with Claude so you don't get lost

- Ask for smaller slices: "implement only X, then stop and explain it".
- Ask for the plan before the code: which files will change, and why.
- Write one piece yourself each phase and ask Claude to review it. In Phase 3, try the replay
  fidelity check (`replayed tree == original tree`).
- Ask "where does this value come from?" about any field in the UI, and follow it from the model's
  response to the database to the screen.

---

## Phase recaps

### Phase 0: a first agent
- **Added:** `loop.py`, `tools.py`, `llm/base.py`, `llm/gemini.py` (the adapter half),
  `config.py`, `cli.py` and the support agent.
- **Key ideas:** the agent loop; tool schemas built from type hints; tool errors as data; raw
  responses resent for thought signatures; Flash-Lite as the default.

### Phase 1: tracing and the trace store
- **Added:** `tracing.py`, `store.py`, `semconv.py`, `retry.py`, `cost.py` and `render.py`; the
  `TracedGenAIClient` wrapper; spans in `Tool.invoke`; step spans, retries and timeouts; `lab runs`
  and `lab show`.
- **Key ideas:** spans and context propagation; OTel GenAI names; recordings keyed by request hash;
  backoff with jitter; cost estimation.

### Phase 2: evals and the decision-tree UI
- **Added:**
  - `evals/` (tasks, trajectory, judge, categories, metrics, runner) and `datasets/` (20 tasks);
  - `demo/triage.py` and a bigger `demo/support.py`;
  - `llm/ratelimit.py`;
  - `server.py`;
  - `ui/`;
  - `examples/customer_app.py`;
  - `lab eval`, `evals`, `report` and `ui`.
- **Key ideas:**
  - programmatic checks vs. an LLM judge;
  - structured output;
  - judge biases;
  - failure categories;
  - p50/p95;
  - client-side rate limiting and `RetryInfo`;
  - threads with `contextvars` and SQLite WAL;
  - FastAPI response models;
  - React Flow with our own tree layout.
- **Things that went wrong, and are worth retelling:**
  - The free-tier quota failed half of the first eval (C-012).
  - A check over-specified the path (C-013).
  - The triage agent ignored "no alert ALR-999" and investigated ALR-101 instead (learnings.md).
- **Experiments:**
  - Open the ALR-999 run in the UI and find the step where it went wrong.
  - Make `get_payments`'s docstring vague and rerun `support-voided-hold`.
  - Run `examples/customer_app.py` and find its run in the UI.
  - Change a task's `expected` and see whether the judge follows it.
