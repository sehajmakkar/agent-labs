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
