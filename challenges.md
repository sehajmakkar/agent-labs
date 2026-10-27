# Challenges

Problems hit while building. Each entry: the problem, what was tried, the resolution (or "open").
Entries marked _anticipated_ were identified during planning and have not been hit yet.

---

## C-001 — LLM nondeterminism breaks exact replay _(anticipated)_
- **Problem:** Re-running a step live may give a different answer even with identical input, so a
  difference between a fork and the original may not be caused by the change.
- **Resolution:** Open. Ideas: serve recorded responses for unchanged steps; run several samples of
  forked branches and compare distributions, not single runs.
- **Update 2026-10-27:** Gemini 3 guidance recommends keeping temperature at 1.0, so "just use
  temperature 0" is not an option. Statistical forks (N samples) are required, not optional.

## C-002 — Tools with side effects during replay _(anticipated)_
- **Problem:** Replaying a run that sent an email or wrote to a database would do it again.
- **Resolution:** Open. Idea: classify tools as read or write; write tools always come from recorded
  fixtures during replay.

## C-003 — Tool calls after a fork have no recording _(anticipated)_
- **Problem:** After a fork the agent may call tools with arguments never seen before, so there is
  nothing recorded to serve back, and calling a real write tool is unsafe.
- **Resolution:** Open. Plan: every demo agent runs against a deterministic simulated backend
  (in-memory state seeded per task). It can answer new calls realistically and safely.

## C-004 — Ground truth for Auto-Blame _(anticipated)_
- **Problem:** To measure whether blame finds the right step we need runs where the faulty step is
  known, and real failures rarely come labelled.
- **Resolution:** Open. Plan: a seeded failure catalog of deliberately injected bugs, plus
  fork-based verification as a second signal.

## C-005 — Replaying Gemini conversations exactly _(anticipated)_
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

