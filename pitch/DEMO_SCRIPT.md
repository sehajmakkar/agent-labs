# 2-minute demo script

One story, told end to end: **a support agent fails → Blame names the step and proves it → Diff
shows the fix → the failure is locked in so CI catches it next time.** Every screen shows real runs.

## Before you record

- Record from `uv run lab ui` (local, everything live) at 1440×900, not the hosted demo: the hosted
  copy is read-only, so its Blame button is hidden. Close other tabs and turn notifications off.
- Pre-open, in order: **Overview** · **the refund run** (Overview → "Open a recorded run") ·
  **its blame** · **the diff** (Overview → "Original vs fixed") · **the Blame accuracy** page.
- Have a terminal ready with the gate clip (see 1:40), or record that part separately.
- Record with QuickTime (File → New Screen Recording) or Loom. Speak slower than feels natural.

## The script

| Time | Screen | Say |
|---|---|---|
| 0:00 | **Overview** | "AI agents fail quietly. Today's tools show you the trace and maybe let you rerun it. I built a lab that tells you *which step* was wrong, and *proves* the fix with statistics." |
| 0:12 | Point at the four numbers | "Everything here is real: 95% on 20 eval tasks, a fix proved 5 out of 5 against 0 out of 5, and blame that finds the planted bug 92% of the time." |
| 0:22 | **The refund run** (tree) | "A support agent was asked to refund a duplicate charge. It did refund the right payment, but the customer never got a refund ID, so the eval failed it. Every model call and tool call is in this tree; I added three lines to the agent to record it." |
| 0:40 | Click **⚑ Step 3**, then **See the blame** | "One click on Blame. A judge proposes the first wrong step and a correction. Then the lab *forks* the run at that step: it replays steps 1 and 2 from the recording, free and with no side effects, and reruns step 3 live, five times with the correction and five times without." |
| 1:00 | Blame verdict | "5 out of 5 pass with the correction, 0 out of 5 without, p = 0.008. And because fixing it one step later is no longer possible, this step was decisive. That's a root cause you've proved, not guessed." |
| 1:15 | **Diff** (original vs fixed) | "The diff lines the two runs up step by step: identical until step 3, and here's the refund ID that was missing." |
| 1:28 | **Blame accuracy** | "How do I know blame works? I planted ten bugs on purpose: 50 failures with a known guilty step. Flash finds the right step 92% of the time, against 30% for the naive baseline. And when forking confirms a blame, it has been right every time." |
| 1:40 | **Terminal** | "Last: lock it in. The failure becomes a regression test. Before the fix, the CI gate fails and blocks the merge. With the fix shipped, it passes. This bug can't come back silently." |
| 1:52 | **Overview** → GitHub link | "It's a Python SDK plus a lab; forks run in a worker inside your own repo, so your agent never leaves your servers. The code is on GitHub. I'd love to show you how it'd work on your agents." |

## The terminal clip (1:40)

```bash
uv run lab lock-in 710849a3
uv run lab eval datasets/regressions.jsonl --gate 0.9   # before the fix: GATE FAILED, exit 1
# (the fix is the prompt line "When a refund succeeds, tell the customer its refund ID…")
uv run lab eval datasets/regressions.jsonl --gate 0.9   # after the fix: GATE PASSED, exit 0
```

The fix is already shipped in the repo. To film the "before" half, temporarily remove that line
from `src/agentlab/demo/support.py`, or use a recording of the run from 2026-10-28.

## If you have 30 more seconds (a live call)

Show the ALR-999 run's **Replays & forks** tab: three forks of the same failure. The first "fix"
made it *worse* (0/5); the second looked significant (4/5, p = 0.048) but the agent was inventing
alert IDs, which a cheap exact check caught; the third was the real fix (5/5 vs 0/5). "A fork is
only as good as its checks, and the lab is built to catch a fix that only fools them."

## Questions to expect

- *"How is this different from rerunning a span?"* Rerun gives you one sample. Fork gives N
  samples against a control, so you know the fix isn't luck. Blame picks the step for you, and
  replay guarantees everything before it is identical.
- *"Does it work with LangGraph / our framework?"* It intercepts at the model client and the tool
  functions, so it works with any loop. The demo includes an agent with its own loop
  (`examples/customer_app.py`).
- *"What does it cost?"* Replay is free. A blame is about 3N runs per candidate, roughly 30 calls
  at N=5, which is cents on Flash-Lite.
