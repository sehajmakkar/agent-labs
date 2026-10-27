# Walkthrough

How to read this codebase in an order where each file only needs what you've already read. It
covers what has been built, how a run flows through the code, how tool calling works, and what to
show in an interview.

Claude updates this file at the end of every phase: new files go into the reading order, and each
phase gets a short recap. Last updated: **Phase 1 (2026-10-27)**.

---

## 1. What exists so far

**In one sentence:** a small agent (a customer support bot) answers questions by calling tools,
and every model call and tool call it makes is recorded to a local database as a tree you can
print.

| Phase | What it added | Try it |
|---|---|---|
| 0 | An agent loop, `@tool`, a Gemini adapter, a demo support agent, the CLI | `uv run lab run support "Was I charged twice for order 4417?"` |
| 1 | Tracing: every run saved to SQLite as a tree of spans, with the exact request and response of every call; tokens, cost, latency, retries, timeouts | `uv run lab runs`, then `uv run lab show <id>` |

**Not built yet:** evals and the web UI (Phase 2), replay from recordings (Phase 3), and then
fork, diff and blame (Phases 4 to 6). The recordings saved in Phase 1 are the raw material for all
of them.

The lab has **two halves**, and the split matters in interviews:

- **The agent** (`loop.py`, `tools.py`, `llm/`, `agents/`): the thing being observed. In real use
  this is the customer's code, not ours.
- **The lab** (`tracing.py`, `store.py`, the wrapper in `gemini.py`, `render.py`): what observes
  it. It only touches the agent at two **boundaries**, the model client and the tool functions
  (decisions.md D-004, D-016).

---

## 2. One run, end to end

Here is everything that happens when you type
`uv run lab run support "Was I charged twice for order 4417?"`. Come back to this after each file;
it will make more sense every time.

```
cli.main()                                         cli.py
 ├─ load_settings()             key, model IDs     config.py
 ├─ GeminiClient(...)           wraps genai.Client  llm/gemini.py
 ├─ tracing.init(".agentlab/lab.db")   recording on tracing.py → store.py
 └─ run_agent(AGENT, llm, model, message)          loop.py
     └─ agent_run(...)          new row in `runs`, opens span "invoke_agent support"
         └─ _loop()
             │  messages = [user: "Was I charged twice…"]
             ├─ step 1          span "step 1"
             │   ├─ call_with_retries(llm.generate)             retry.py
             │   │    └─ GeminiClient.generate                  llm/gemini.py
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

Each `span` is saved to SQLite **when it ends**. That is why spans have a `seq` number for their
start order (challenges.md C-008).

---

## 3. Reading order

★★★ means it's core: know it well enough to explain without looking. ★★ means understand what it
does and why. ★ means skim. The times are for a careful first read.

### Step 0: orient (10 min)

1. **[README.md](README.md)**: what the product is for. Skim it.
2. **[PLAN.md](PLAN.md)**: read the Progress table and the Phase 0 and Phase 1 sections, to see
   what was promised and ticked off.
3. Run the demo once: `uv run lab run support "Was I charged twice for order 4417?"`. Keep the
   tree output open while you read the code.

### Step 1: the agent from the outside

4. **[agents/support.py](agents/support.py)** ★★ (60 lines, 5 min)
   This is what a *user* of the lab writes: some fake data, two functions marked `@tool`, a system
   prompt, and an `Agent(...)`. Don't worry about how `@tool` works yet; Section 4 covers it. Notice
   that the docstrings are written for the **model** to read, not for people.
   *Check yourself:* why does order 4417 have two payments? (The answer is at the top of the file.)

### Step 2: the vocabulary

5. **[src/agentlab/llm/base.py](src/agentlab/llm/base.py)** ★★★ (76 lines, 10 min)
   These are the nouns everything else uses: `Message`, `ToolCall`, `ToolResult`, `Usage`,
   `LLMResponse`, `TransientLLMError`, and the `LLMClient` protocol.
   - A conversation is just a `list[Message]`. Each message's `role` is `user`, `model` or
     `tool`.
   - `LLMClient` is a `Protocol`: any object with a matching `generate(...)` method counts as one.
     That is how the tests swap in a fake model.
   - `raw` keeps Gemini's original response so it can be sent back unchanged on the next turn
     (D-012, C-005).
   *Check yourself:* what is the difference between a `ToolCall` and a `ToolResult`?

### Step 3: the heart

6. **[src/agentlab/loop.py](src/agentlab/loop.py)** ★★★ (142 lines, 20 min). **This is the most
   important file.**
   An agent is this loop: send the conversation to the model, run any tools it asks for, append the
   results, and repeat until it answers in plain text. On this first read, treat `span(...)` and
   `agent_run(...)` as "a stopwatch box that gets saved", and `call_with_retries` as "try again if
   Gemini is busy". You'll read both properly later.
   - `_loop` (lines 82–118): the loop itself. The stopping rule is on line 114: no tool calls means
     a final answer.
   - `_execute` (lines 121–142): a tool error becomes **data** sent back to the model, and never
     crashes the loop (D-013).
   - Three ways a run ends: `completed`, `max_steps` or `timeout`. A model error that is still
     failing after the retries ends it with `error`.
   *Check yourself:* in the demo, how many entries does `messages` have when step 3 starts? (Five:
   the user message, then a model turn and a tool turn for each of steps 1 and 2.)

### Step 4: tools

7. **[src/agentlab/tools.py](src/agentlab/tools.py)** ★★★ (100 lines, 20 min)
   Read [Section 4](#4-how-tool-calling-works) below first, then this file.
   - `tool()` / `decorate()`: turn a function into a `Tool` object.
   - `_args_model`: type hints → a pydantic model → a JSON Schema.
   - `invoke`: validate → call → record. Every call becomes an `execute_tool` span.
   - `describe_error`: the error text the model sees when a call fails.

### Step 5: talking to Gemini (first half)

8. **[src/agentlab/llm/gemini.py](src/agentlab/llm/gemini.py)**, **lines 1–128 only** ★★ (15 min)
   This translates between our neutral types and Google's SDK.
   - `GeminiClient.generate`: builds the config (system prompt, tool declarations, automatic
     function calling **off**) and converts errors (429/503 → `TransientLLMError`).
   - `_declaration`: a `Tool` → a Gemini `FunctionDeclaration`. This is where the schema from
     `tools.py` is sent to the model.
   - `to_contents`: our messages → Gemini contents. Tool results go back as `function_response`
     parts inside a **user** turn, matched to their calls by `id`.
   - `from_response`: Gemini's response → our `LLMResponse`. It skips the "thought" parts and reads
     the token counts.
   Leave `TracedGenAIClient` (line 130 onward) for Step 8.

### Step 6: small helpers

9. **[src/agentlab/config.py](src/agentlab/config.py)** ★ (5 min): model IDs, prices and the
   `.env` loading. This is the only place model names and prices live.
10. **[src/agentlab/retry.py](src/agentlab/retry.py)** ★★ (37 lines, 5 min): exponential backoff
    with jitter. `sleep` is a parameter so tests don't actually wait.
11. **[src/agentlab/cost.py](src/agentlab/cost.py)** ★ (15 lines, 2 min): tokens × price.
    Thinking tokens are billed as output.

### Step 7: tracing (the "lab" half)

12. **[src/agentlab/semconv.py](src/agentlab/semconv.py)** ★ (26 lines, 3 min): attribute names.
    `gen_ai.*` comes from the OpenTelemetry standard; `agentlab.*` names are ours.
13. **[src/agentlab/store.py](src/agentlab/store.py)** ★★ (131 lines, 10 min): three tables.
    - `runs`: one row per run.
    - `spans`: one row per timed piece of work, linked into a tree by `parent_span_id`.
    - `recordings`: the exact request and response of each model or tool call, with a hash.
    The fork columns stay empty until Phase 4 (D-020).
14. **[src/agentlab/tracing.py](src/agentlab/tracing.py)** ★★★ (212 lines, 25 min). **The second
    most important file.** Read [Section 5](#5-tracing-in-five-minutes) first.
    - `span()`: open a span, make it the "current" one, and save it on exit.
    - `agent_run()`: the same, but it also creates the run row and decides its final status.
    - `Span.record()`: attaches a recording with its `request_hash`.
    - `agent()`: the `@lab.agent` decorator for people who don't use our loop.

### Step 8: close the loop

15. **[src/agentlab/llm/gemini.py](src/agentlab/llm/gemini.py)**, **lines 130–198** ★★★ (10 min).
    `TracedGenAIClient` is a stand-in for `genai.Client`. Its `models.generate_content` opens a
    `chat` span, makes the real call, records it, and fills in tokens, cost and attributes. Every
    other method passes straight through (`__getattr__`). This is the **model-call boundary**.
16. **Re-read `Tool.invoke` in [tools.py](src/agentlab/tools.py)** (lines 40–63). Now you can see
    that it is the **tool-call boundary**, and it works the same way as the wrapper above.
17. **[src/agentlab/\_\_init\_\_.py](src/agentlab/__init__.py)** ★★ (32 lines, 3 min): the public SDK
    is `lab.init`, `lab.wrap`, `@lab.tool` and `@lab.agent`. This is what a customer imports.

### Step 9: output and entry point

18. **[src/agentlab/render.py](src/agentlab/render.py)** ★ (93 lines, 5 min): it turns the flat
    list of spans back into a tree and draws it with `├─`.
19. **[src/agentlab/cli.py](src/agentlab/cli.py)** ★★ (140 lines, 10 min): the `main()` that
    connects everything. Read it last, because by now every line in it should make sense. Then
    trace Section 2 again against it.

### Step 10: tests (the specification)

The tests show how each piece is supposed to behave, and none of them call the network.

20. **[tests/test_loop.py](tests/test_loop.py)** ★★★: `ScriptedLLM` is a fake model that returns
    prewritten responses. It is how you test an agent without paying for or depending on Gemini.
21. **[tests/test_tools.py](tests/test_tools.py)**, **[tests/test_tracing.py](tests/test_tracing.py)** ★★:
    span nesting, run status, the no-op mode before `init`, and hash stability.
22. **[tests/test_gemini.py](tests/test_gemini.py)** ★★: a fake `genai` client; the thought
    signature round trip; a 503 is retried and a 400 is not.
23. **[tests/test_render.py](tests/test_render.py)** ★.

### Step 11: the why

These decisions.md entries come up in interviews: **D-004** (own loop, not LangGraph), **D-008**
(positioning), **D-009** (how users integrate), **D-012** (raw responses), **D-013** (tool errors
as data), **D-015** (step spans) and **D-016** (wrapping the SDK client). In
[learnings.md](learnings.md), read the Phase 0 and Phase 1 sections.

---

## 4. How tool calling works

**The model never runs your code.** It can only write text. Tool calling is an agreement:

1. We tell the model what tools exist: name, description and a JSON Schema for the arguments.
2. The model can reply with a structured *request* instead of an answer: "please call
   `get_payments` with `{"order_id": "4417"}`".
3. **Our code** runs the function and sends the result back in the next message.
4. The model reads the result and either asks for another tool or writes its answer.

Here is what your real run `0c692454` sent and received, taken from `.agentlab/lab.db`:

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
`function_response` part carrying the same `id` (`to_contents`, gemini.py lines 81–92). The model
sees two captured payments, asks for `get_order` to confirm the amount, and then answers.

One response can contain **several** function calls; we saw this live in Phase 0, when the model
called both tools at once. The `id` is how each result is matched to its call.

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

So after the decorator, `get_order` is **no longer a function**. It is a `Tool` object
(tools.py line 28) holding:

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
uv run python -c "from agents.support import get_order; print(type(get_order).__name__, get_order.parameters_schema)"
```

### Why validate the arguments

The model writes the arguments, and it can get them wrong. `invoke` checks them against the type
hints before running anything:

| The model sends | The model receives back |
|---|---|
| `{}` | `Invalid arguments: order_id: Field required` |
| `{"order_id": 4417}` (a number) | `Invalid arguments: order_id: Input should be a valid string` |
| `{"order_id": "9999"}` | `LookupError: No order with ID 9999` (raised by your function) |

All three go back to the model **as data**, and it gets a chance to fix the problem or tell the
user (D-013). Whether it does is exactly the kind of behaviour this lab exists to measure.

### Python ideas used here

- **Decorator**: see above.
- **`@dataclass`**: a class whose `__init__` is generated from its fields. `frozen=True` makes it
  read-only.
- **`Protocol`**: "anything with these methods", checked by shape, not by inheritance.
- **Context manager** (`with … as s:`): code that runs on entry and on exit, even when there is an
  exception. Written with `@contextmanager` and `yield`.
- **`ContextVar`**: a variable that is "current" for the code running now. See Section 5.

---

## 5. Tracing in five minutes

- **Run**: one execution of the agent on one input.
- **Span**: one timed unit of work inside a run, such as a step, a model call or a tool call. It
  has a parent, so spans form a tree.
- **Recording**: the exact request and response of one call, which is enough to replay it.

How `span()` works (tracing.py lines 104–129):

```
with span("tool", "execute_tool get_payments") as s:   # ENTER
    ...                                                 # BODY: fill in s.output, s.error, s.record(...)
                                                        # EXIT
```
- **Enter**: read `_current_span`, which is the parent, and make a new `Span` whose `parent_id`
  is that parent's id. Set `_current_span` to the new span and take the next `seq`.
- **Body**: any `span()` opened inside it automatically becomes a child. Nobody passes the parent
  around; that is **context propagation**, and it's why `Tool.invoke` deep in the loop still lands
  under the right step.
- **Exit**: put the old current span back. If an exception happened, store it as the span's error
  and re-raise it. Save the span and its recordings to SQLite. If `lab.init()` was never called,
  nothing is saved (D-018).

You can see it in your own database:
```
sqlite3 .agentlab/lab.db "select seq, kind, name, round(duration_ms) from spans where run_id like '0c692454%' order by seq"
```
That query returns 9 spans: 1 agent, 3 steps, 3 llm and 2 tool. The `recordings` table holds 3 llm
and 2 tool recordings for that run.

**Why record the exact request and hash it?** In Phase 3, replay will rerun the agent and, instead
of calling Gemini, look up "have I seen this exact request before?" by its hash and return the saved
response. Same inputs, same outputs, for free and instantly. A fork is then a replay that changes
one thing at one step.

---

## 6. For interviews and demos

**Files to have open:** [loop.py](src/agentlab/loop.py), [tools.py](src/agentlab/tools.py),
[tracing.py](src/agentlab/tracing.py), and the wrapper in [gemini.py](src/agentlab/llm/gemini.py)
(lines 130–186). Have a terminal ready with `lab run` and `lab show`.

**A 60-second explanation:**
> "An agent is a loop: call the model, run the tools it asks for, feed results back. I wrote my own
> loop and put interception at exactly two boundaries: the model client and the tool functions.
> Every call through them becomes a span in a tree (run → step → model call / tool calls), and I
> record the exact request and response, keyed by a hash. Today that gives full traces with cost,
> tokens, latency and retries. Those recordings are what make replay deterministic, and on top of
> replay I build fork-from-any-step, trajectory diff, and auto-blame, which finds the first wrong
> step and proves it by forking."

**Questions you should be able to answer:**

| Question | Short answer | Where |
|---|---|---|
| Why not LangGraph? | Tracing needs control of every call. Companies in this space build framework-agnostic SDKs, and a LangGraph adapter comes later. | D-004 |
| How do you intercept calls? | Wrap the SDK client (a stand-in object), and tools record themselves. No monkeypatching. | D-016 |
| What happens when a tool fails? | The error goes back to the model as data, and the span is marked as an error. | D-013, `_execute` |
| How do spans find their parent? | A `ContextVar` holds the current span. | tracing.py |
| Why the `step` spans? | A step is one decision, and it is the unit you fork from. The standard has no such layer. | D-015 |
| Why are retries in your code rather than the SDK's? | So each attempt is visible and the retry rate can be measured. | D-017 |
| How do you test without the network? | `ScriptedLLM` and a fake `genai` client. | tests/ |
| What is a thought signature? | Opaque bytes in Gemini's responses that must be sent back untouched. We resend the raw response. | D-012, C-005 |
| Is cost exact? | It's an estimate from a price table. Thinking tokens are billed as output. | D-019 |
| The model took 2 steps once and 3 another time. Why? | LLMs are nondeterministic, which is why replay uses recordings and forks run several times. | C-001, learnings.md |

---

## 7. Staying in the loop

### A review routine after each phase (about an hour)

1. **Run it first.** Do the phase's demo command before reading any code.
2. **See what changed.** Run `git diff --stat <last-phase-commit>`, then read the new
   "Phase N recap" at the bottom of this file.
3. **Read the code in order.** New files are placed in Section 3 with ★ ratings.
4. **Break something on purpose.** Each phase recap lists experiments. Predict the result before
   you run it.
5. **Explain it back.** Write 3–5 lines in your own words, or say them to Claude ("here's how I
   think X works, correct me"). If you can't explain a file, ask about it before committing.
6. **Write the commit message yourself.** If you can't summarise the change, you haven't
   understood it yet.

### Theory and practice side by side

For each concept: read the short explanation in learnings.md, find it in the code, then change
something and watch what happens.

| Concept | In the code | Experiment |
|---|---|---|
| The agent loop | `loop.py` `_loop` | Put `breakpoint()` after `messages.append(response.message)` and print `messages` at each step. |
| Tool descriptions steer the model | `support.py` docstrings | Make the `get_payments` docstring vague and see whether the model still calls it. Revert afterwards. |
| Tool errors as data | `loop.py` `_execute` | `lab run support "Was I charged twice for order 9999?"` |
| Step limits | `loop.py` `max_steps` | `lab run support "…4417?" --max-steps 1` gives `max_steps`. |
| Context propagation | `tracing.py` `span` | Read `test_spans_nest_under_the_span_open_around_them`, then add a third level. |
| Recordings | `store.py`, `Span.record` | Use the `sqlite3` query in Section 5, then `select request from recordings limit 1`. |
| Retries | `retry.py` | Read `test_loop.py`'s `FlakyLLM`, then change `max_attempts` and see which test fails. |
| Nondeterminism | `lab runs` | Run the same question 3 times and compare step counts with `lab show`. |

### Ways to work with Claude so you don't get lost

- **Ask for smaller slices.** For example: "implement only the eval dataset, then stop and explain
  it". A phase has 5–8 checklist items, and you can review after each one.
- **Ask for the plan before the code.** "Before writing Phase N, tell me which files you'll add or
  change and why." Then compare that with the result.
- **Write one piece yourself each phase.** Phase 2 has a good candidate: one eval check, such as
  "the agent called `get_payments` before answering". Ask Claude to review it instead of writing it.
- **Ask "where does this data come from?"** about any field you see in a trace. Following one
  value from the model's response to the database is the best way to learn the flow.

---

## Phase recaps

### Phase 0: a first agent
- **Added:** `loop.py`, `tools.py`, `llm/base.py`, `llm/gemini.py` (the adapter half),
  `config.py`, `cli.py` and `agents/support.py`.
- **Key ideas:** the agent loop; tool schemas built from type hints; tool errors as data; raw
  responses resent for thought signatures; Flash-Lite as the default.

### Phase 1: tracing and the trace store
- **Added:** `tracing.py`, `store.py`, `semconv.py`, `retry.py`, `cost.py` and `render.py`; the
  `TracedGenAIClient` wrapper in `gemini.py`; spans in `Tool.invoke`; step spans, retries and a
  run time limit in `loop.py`; `lab runs` and `lab show`.
- **Key ideas:** spans and context propagation; OpenTelemetry GenAI attribute names; recordings
  keyed by request hash; backoff with jitter; cost estimation.
- **Experiments:** the 9999 order, `--max-steps 1`, the `sqlite3` span query, and running the same
  question 3 times.
