# Proving why an AI agent failed

*A technical write-up of Agent Reliability Lab: what I built, how it works, and what the numbers
showed.*

## The problem

When an agent fails, observability tools show you its trace: 15 model and tool calls, and a wrong
answer at the end. Some let you rerun from a span. What none of them answer is the question an
engineer actually has: **which step was wrong, and will my fix actually work?** A single rerun
can't answer the second half, because a sampled model passes and fails by chance.

I built a lab that answers both, on top of one engine: **deterministic replay**.

## Recording at two boundaries

An agent is a loop: call the model, run the tools it asks for, feed the results back. The lab
intercepts it at exactly two places, the **model client** (`lab.wrap(genai.Client())`) and the
**tool functions** (`@lab.tool`). That is three lines in someone else's agent, whatever loop or
framework they use. Every call becomes a span in a tree (run → step → model call or tool calls),
and is also *recorded*: the exact request, the exact response, and a SHA-256 hash of the request in
canonical JSON.

## Replay: re-running the same code from recordings

Replay runs the same agent code again, but at each boundary it looks the request's hash up in the
recording and returns the saved response. Step 1's request depends only on the prompt and the user
message, so it matches. Step 2's request is built from step 1's *recorded* response, so it matches
too, and so on to the end. Clock and random reads go through the same interception, failed calls
are recorded too (so retries replay identically), and **no tool ever runs during a replay**, so a
refund can't happen twice.

A **fidelity check** compares the two runs' decisions span by span. Results: 13 of 13 runs from a
fresh eval replayed identically, offline, at $0. When the code changes, replay stops at the first
changed request and names the JSON path (`$.config.system_instruction`).

It also found a real bug. A refund run's answer looked like a hallucination ("P-902 was already
refunded"). Its replay diverged inside an *earlier* tool result: the tool had returned a reference
to live state, and the later refund rewrote history the model was shown. The model was accurately
describing a corrupted conversation. The fix: tool results are snapshots.

## Fork: one change, N times, against a control

A fork replays everything before step N (matched by *position*, since a changed prompt changes
every hash), applies one override at the boundary (a prompt, a model, or a tool's result), and runs
live from step N. Two details make it a fair experiment:
- recorded writes before the fork point are re-applied to a simulator (event sourcing), so the live
  part sees the same world;
- live calls keep the *recorded* prompt unless the prompt is what's being changed.

Each fork runs **N times next to N controls** without the change, is scored by the task's checks,
and is compared with Fisher's exact test. On a support-agent failure (it never gave the customer
the refund ID), one added sentence: **5/5 vs 0/5, p = 0.008**.

The most useful result came from a failure where the agent ignored "no such alert" and investigated
a different one. The first fix made it *worse* (0/5 vs 3/5). The second looked significant (4/5 vs
0/5, p = 0.048), but the agent was inventing alert IDs, and the LLM judge passed them. A one-line
exact check (every ID in the answer must appear in a tool result) rescored it to 1/5 vs 1/5. The
third fix was real: 5/5 vs 0/5. **A fork is only as trustworthy as its checks.**

## Diff: where two runs part ways

Two runs are turned into steps and aligned with Needleman–Wunsch: a dynamic-programming alignment
that pairs *similar* steps (same tool, different argument) instead of only identical ones, so an
extra verification step shows as an insertion without shifting every later step. Diffing Flash
against Flash-Lite on the same tasks showed that Flash verifies more: on one task, 7 steps against
4, for 5× the cost, and both passed.

## Blame: propose, verify, pin down

1. A judge reads the failed run as numbered steps (plus the task, the failed checks and the agent's
   prompt) and ranks up to three candidate first wrong steps, each with a correction phrased as a
   prompt rule.
2. Each candidate is **forked with its correction against a control**. The first confirmed wins.
3. A second fork applies the same correction **one step later**. If that can no longer save the
   run, the step was decisive.
4. If nothing is confirmed, the lab **abstains** rather than guessing.

To measure it, I planted 10 bugs in the agents' prompts, each with a matcher for the step where it
shows: **50 failures with a known guilty step**.
- Flash as the judge found the right step first 92% of the time, Flash-Lite 72%, and a "blame the
  last step" baseline 30%.
- With verification, every confirmed blame was right (precision 100% on the sample).

The surprise: the judge picked the right step 8 times in 9 but could *prove* only 4. It hadn't seen
the agent's prompt, so its corrections were generic advice that lost to the planted instruction
they contradicted. A blame is only as useful as its fix; the judge now sees the prompt and writes
corrections that override the offending line.

## Lock it in

A blamed failure becomes a regression test with one click: the same input, the original checks,
plus a judge check built from the proved correction. `lab eval --gate 0.9` exits 1 if the pass rate
drops or any regression fails, so CI blocks the merge. Live: the gate failed while the bug existed,
and passed once the proved fix shipped.

## Engineering notes

- Python 3.12, FastAPI, SQLite (WAL) via SQLModel, React + React Flow, and Gemini Flash and
  Flash-Lite through `google-genai`.
- 130+ offline tests, with fakes for the model (a fake Gemini that answers according to the prompt
  it's given, so a prompt fix really flips the outcome in tests).
- The lab never hosts the customer's agent: forks and blames are jobs, claimed with a
  compare-and-set by a worker running in the customer's repo, locally or over HTTP.
- Every decision, trade-off and problem is logged (`decisions.md`, `challenges.md`), and the
  concepts are in `learnings.md`.

## What I'd do next

Compare whole experiments (prompt v1 against v2 over every task), import OpenTelemetry traces from
other frameworks for view, diff and blame suggestions, and run each regression test N times to gate
on its pass rate rather than a single sample.
