# Challenges

Problems hit while building. Each entry: the problem, what was tried, the resolution (or "open").
Entries marked _anticipated_ were identified during planning and have not been hit yet.

---

## C-001 — LLM nondeterminism breaks exact replay _(resolved)_
- **Problem:** Re-running a step live may give a different answer even with identical input, so a
  difference between a fork and the original may not be caused by the change.
- **Resolution:** Open. Ideas: serve recorded responses for unchanged steps; run several samples of
  forked branches and compare distributions, not single runs.
- **Update 2026-10-27:** Gemini 3 guidance recommends keeping temperature at 1.0, so "just use
  temperature 0" is not an option. Statistical forks (N samples) are required, not optional.
- **Update 2026-10-27 (Phase 3):** Half solved. Replay serves every recorded step, so unchanged
  steps can no longer vary: 14 of 14 recorded triage runs replayed identically, offline. Steps
  that run live after a fork still vary; that's Phase 4's N-sample forks.
- **Resolved 2026-10-27 (Phase 4):** Every fork job runs N times with the change *and* N times
  without it (a control), and compares the pass counts with Fisher's exact test (D-040). Seen live
  on the ALR-999 failure: the control passed 3 of 5, so the original failure was partly bad luck at
  step 2. A single rerun could not have told a fix from a fluke.

## C-002 — Tools with side effects during replay _(resolved)_
- **Problem:** Replaying a run that sent an email or wrote to a database would do it again.
- **Resolution:** Resolved in Phase 3, more strictly than planned. During replay *no* tool function
  runs, read or write: `Tool.invoke` returns the recorded result or raises the recorded error, and a
  call with no recording stops the replay instead of falling back to the real tool. Tested with a
  write tool whose call counter must not move (decisions.md D-030).

## C-003 — Tool calls after a fork have no recording _(resolved)_
- **Problem:** After a fork the agent may call tools with arguments never seen before, so there is
  nothing recorded to serve back, and calling a real write tool is unsafe.
- **Resolution:** Open. Plan: every demo agent runs against a deterministic simulated backend
  (in-memory state seeded per task). It can answer new calls realistically and safely.
- **Update 2026-10-27 (Phase 3):** The demo half is done: `SupportBackend` gives every run its own
  copy of the seed data, and `refund_payment` writes to it. Still open for Phase 4: a way for
  customers to register simulators for their own write tools, since forks are when those would
  run without a recording (D-034).
- **Resolved 2026-10-27 (Phase 4):**
  - After the fork point, read tools run for real.
  - Write tools run only as `simulated=True` or through a registered `@tool.simulator`;
    otherwise the fork stops with `ForkBlocked` (D-039).
  - Recorded writes before the fork point are re-applied to the simulator, so the live part sees
    the same state, for example the refund already made (D-038).
  - Tests cover all four cases, including a write tool with no simulator, whose real function
    must never be called.

## C-004 — Ground truth for Auto-Blame _(resolved)_
- **Problem:** To measure whether blame finds the right step we need runs where the faulty step is
  known, and real failures rarely come labelled.
- **Resolution:** Open. Plan: a seeded failure catalog of deliberately injected bugs, plus
  fork-based verification as a second signal.
- **Resolved 2026-10-28 (Phase 6):**
  - 10 seeded prompt bugs (`blame/catalog.py`), each with a matcher that finds its guilty step.
  - `lab seed-failures` ran them through the normal eval runner; failed runs where the matcher
    fires are the labelled cases.
  - Fork-based verification is the second signal (D-047, D-048).

## C-005 — Replaying Gemini conversations exactly _(resolved)_
- **Problem:** Gemini responses can carry thinking and function-call parts that must go back to the
  model unchanged on the next turn. If a replay or fork rebuilds the history slightly differently,
  the live steps after a fork see a different conversation than the original did.
- **Resolution:** Open. Plan: store the raw response parts in each Recording and rebuild history
  from them, never from our own simplified copy. Check the Gemini function-calling docs in Phase 1.
- **Update 2026-10-27 (Phase 0):** Half done. Within a live run, model turns are resent as the raw
  `Content`, and a test checks that a `thought_signature` survives (decisions.md D-012). Still open:
  serializing that raw content into Recordings (Phase 1) and replaying from it (Phase 3).
- **Update 2026-10-27 (Phase 1):** Recordings now hold the exact request and the raw response in
  JSON mode. A test checks that a binary `thought_signature` survives storage and decodes back to
  the same bytes. Remaining: replaying from the recordings (Phase 3).
- **Resolved 2026-10-27 (Phase 3):** Replays rebuild each response from its recording
  (`GenerateContentResponse.model_validate`), the loop resends that raw content, and the next
  request's hash matches the recorded one. A test checks this with thinking parts and a binary
  signature. Live Flash-Lite responses carried a `thought_signature` on every call, and those runs
  replayed identically.

## C-006 — Gemini model IDs not yet confirmed _(resolved)_
- **Problem:** Sources disagreed on the current Flash and Flash-Lite IDs. The defaults
  (`gemini-3.8-flash`, `gemini-3.5-flash-lite`) come from Google's docs, but they couldn't be checked
  against the live API because no API key was available during Phase 0.
- **Resolution:** Resolved 2026-10-27. With Sehaj's key, `uv run lab models` showed both
  `gemini-3.8-flash` and `gemini-3.5-flash-lite` as available. The command stays useful: it marks
  the configured IDs and exits non-zero if one disappears.

## C-007 — Gemini Flash is sometimes unavailable _(resolved)_
- **Problem:** Sehaj has seen Gemini Flash become unavailable at times. A demo or a long eval run
  that hits this fails halfway through.
- **Resolution:** Resolved 2026-10-27 by making Flash-Lite the default (decisions.md D-014). Not
  yet handled: what a run should do if Flash-Lite itself returns an overload error. That belongs
  with the retries work in Phase 1.
- **Update 2026-10-27 (Phase 1):** Overload (503), rate limits (429) and timeouts are now retried
  with exponential backoff, up to 4 attempts, and every attempt is traced (decisions.md D-017).

## C-008 — Spans arrive in the store in the wrong order _(resolved)_
- **Problem:** A span is saved when it ends, and children end before their parents. Ordering by
  insert time would print each step's tools before the step itself.
- **Resolution:** Each span gets a `seq` number from a per-run counter when it *starts*. The tree
  is rebuilt from `parent_span_id` and sorted by `seq` (decisions.md D-015).

## C-009 — SQLite forgets timezones _(resolved)_
- **Problem:** Times were stored as timezone-aware UTC, but SQLite has no timezone type, so they
  came back without one. `lab runs` printed UTC as if it were local time (5h30 off in IST).
- **Resolution:** Store UTC, and on display treat the value as UTC and convert it to local time.
  Durations are unaffected, because both ends lose the timezone the same way.

## C-010 — Recorded requests grow with every step _(open, accepted for now)_
- **Problem:** Each model call sends the whole conversation so far, and we record each request in
  full. A run with N steps stores about N²/2 turns of history.
- **Resolution:** Accepted at demo scale (decisions.md D-016). If it matters, store each turn once
  and have recordings point to the turns.

## C-011 — The wheel ships a top-level `agents` package _(resolved)_
- **Problem:** `pyproject.toml` packages both `src/agentlab` and the demo `agents/`, so
  installing our wheel also installs a top-level `agents` module. The OpenAI Agents SDK
  (`openai-agents` on PyPI) installs a package with the same name, so a customer using both
  would get one overwriting the other. Found by building the wheel and listing its contents.
- **Also:** the name `agentlab` is already taken on PyPI, so publishing will need another name
  (`agent-reliability-lab` was free on 2026-10-27).
- **Resolution:** the demo agents moved to `agentlab.demo` at the start of Phase 2 (D-022). The
  PyPI name still needs choosing before anything is published.

## C-012 — The free tier allows 15 requests a minute; an eval needs about 100 _(resolved)_
- **Problem:** The first full eval (20 tasks, 4 at a time, plus a judge call each) failed 10 tasks
  with `429 RESOURCE_EXHAUSTED: ... free_tier_requests, limit: 15`. Six attempts with backoff
  weren't enough, because four workers kept refilling the quota as soon as it emptied.
- **What went right:** the eval labelled them `crash` (the agent's model call failed) and
  `eval_error` (the judge's call failed), not as agent mistakes. That is why those categories
  exist.
- **Resolution:**
  - A client-side sliding-window rate limiter (`llm/ratelimit.py`, `AGENTLAB_RPM`, default 15).
  - Retries now honour the server's `RetryInfo` delay.
  - The author also added a new API key.
  - Rerunning the 11 failed tasks gave 10 passes and one real agent failure (D-026).

## C-013 — A check that demanded one particular path _(resolved)_
- **Problem:** `support-two-orders` ("were both orders delivered?") required `get_order`. The
  agent answered correctly using `get_shipment`, and the eval failed it as `wrong_tool`.
- **Resolution:** The check now tests the answer (it mentions both orders) and leaves correctness
  to the judge. Lesson: check *outcomes* and *forbidden* actions; only require a specific tool
  when using it is the point of the task (see learnings.md, "Eval design").

## C-014 — npm crashed resolving vitest 5's optional peer dependencies _(resolved)_
- **Problem:** `npm install` with vitest 5.0.5 failed inside npm itself:
  `Cannot read properties of null (reading 'edgesOut')`, in the peer-dependency resolver.
- **Resolution:** Used vitest 4.1.12, which supports Vite 8, instead of hiding the problem with
  `--legacy-peer-deps`. Try vitest 5 again after an npm upgrade.

## C-015 — `@lab.agent` runs store their input differently from our loop _(resolved)_
- **Problem:** Our loop records `{"message": ...}` and `{"answer": ...}`. `@lab.agent` records the
  function's arguments (`{"question": ...}`) and its raw return value. The UI and `lab runs`
  showed blank messages for the customer example.
- **Resolution:** `store.run_message` and `store.run_answer` read both shapes: the first text
  argument and the plain return value. A test covers it.

## C-016 — A tool result changed after it was returned _(resolved)_
- **Problem:** The first live run with the refund tool ended with a false claim: *"P-902 was
  already marked as refunded! However… I've processed another refund."* It looked like a model
  hallucination. Replaying the run diverged at
  `$.contents[2].parts[1].function_response.response.payments[1].status`: the step-1
  `get_payments` result inside the step-3 request.
- **Cause:**
  - `get_payments` returned the backend's own payment dicts, and the loop kept that same object in
    its message history.
  - When `refund_payment` set P-902 to `refunded`, it also rewrote the *earlier* tool result.
  - So at step 3 the model was shown a history in which P-902 was refunded before it acted. It
    reported what it saw.
  - The recording, serialised at call time, still held the true value, so the replay noticed.
- **Resolution:** `Tool.invoke` returns a deep copy of every result (D-035), and a test checks that
  later writes can't change an earlier result. Rerun live, the agent answered correctly, and its
  replay was identical.
- **Lesson:** The fidelity check found a bug in *our* code that looked like a model failure. Without
  replay it would have been logged as a hallucination.

## C-017 — Two processes' monotonic clocks can't be compared _(resolved before it bit)_
- **Problem:** The loop's deadline is `start + timeout`, read from `lab.monotonic()`. In a fork,
  `start` comes from the recording (the original process's monotonic clock), but later reads are
  live (this process's clock). Monotonic clocks count from an arbitrary point per process, so the
  comparison is meaningless: a fork would time out at once, or never.
- **Resolution:** `ForkSession.continue_clock` pins the first live read to the last recorded value
  and moves forward from there, so the fork's clock continues the original's timeline (D-038).
  A unit test checks the arithmetic.

## C-018 — Forks wait forever with no worker, and a crashed worker strands its job _(open)_
- **Problem:** Fork jobs are only run by workers (D-041). With none running, a fork stays
  "queued"; if a worker dies mid-job, the job stays "running" for good.
- **Mitigation:** `lab ui` runs a worker for the demo agents itself, and the fork page tells you
  to start `lab worker` when a job is waiting.
- **Still open:** job leases with a heartbeat, so a dead worker's job is re-queued.


## C-019 — The same work, split into steps differently, shows as a bigger difference than it is _(open)_
- **Problem:** Flash-Lite asked for `list_deploys`, `get_metrics` and `search_logs` in one step;
  Flash called them one at a time over three steps. Aligning step by step shows three added steps
  and one changed step, though both runs made the same calls.
- **Idea:** a second view that compares the *set of calls made so far* at each point (or aligns
  individual tool calls rather than steps), so parallel and sequential versions of the same work
  line up. The step view stays the default, because steps are the unit you fork from.

## C-020 — Some planted bugs don't fire _(accepted)_
- **Problem:** The model sometimes ignores a planted bad instruction when the evidence contradicts
  it:
  - `blame-deploy` ("always blame the latest deploy") never fired in 5 runs, because the logs
    plainly blamed the card provider;
  - `voided-is-charged` fired in only some runs, because `get_payments`'s docstring explains what a
    voided authorization is;
  - `obey-notes` fired 3 times in 5.
- **Resolution:** Only failed runs where the bug's matcher fires count as cases, so the benchmark
  isn't polluted. The bugs that don't fire are a finding in themselves: tool descriptions and
  strong evidence can outweigh a bad system-prompt line.


## C-021 — Fixing the agent would have broken the blame demo _(resolved before it bit)_
- **Problem:** Shipping the refund-ID fix to the support prompt would make every *control* in
  future forks of the old failing run use the fixed prompt (live calls used the current code). So
  "without the correction" would pass too, and Blame would no longer confirm the failure it had
  found. That isn't wrong, but it is a different question from "what if, in that run, step 3 had
  been different?".
- **Resolution:** Forks keep the recorded system prompt unless the override changes it (D-051).
  A test fixes the prompt "in code" and checks that a control still fails.

## C-022 — The "after" benchmark hung silently for 40 minutes _(resolved)_
- **Problem:** The benchmark process sat at 0% CPU with no database writes. Retries waited "at
  least as long as the server asks" (D-017), with no upper bound. When a daily quota runs out,
  Gemini asks for a wait of hours, so the process slept.
- **Also:** the helper that was meant to start a job "after the benchmark finishes" used
  `pgrep -f "lab blame-bench"`, which matched its *own* command line, so it would have waited
  forever.
- **Resolution:** `RetryPolicy.max_hint_s` (120s). A longer hint fails at once with "probably a
  quota limit; not retrying", and a test covers it. The "after" benchmark wasn't rerun; the
  "before" numbers stand, and the rerun is one command (`lab blame-bench --verify 9 -n 3`).

## C-023 — The static preview served nothing from /data _(resolved)_
- **Problem:** Checking the read-only build with `npx vite preview` returned 404 for every
  `/data/*.json` file that was in `dist`. `npx` had downloaded a different Vite version instead of
  using the project's own, and that version didn't serve the folder as expected.
- **Resolution:** Checked with a plain static file server instead (`python3 -m http.server` in
  `ui/dist`), which behaves like Vercel and Netlify: JSON served as `application/json`, a missing
  file a 404. The UI also checks the content type, in case a host answers a missing file with the
  index page.
