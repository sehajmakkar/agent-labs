# The Story So Far

The whole project as one narrative: what we built, how it works, and why each piece exists. Read it
before an interview or a demo. For the file-by-file reading order, see
[WALKTHROUGH.md](WALKTHROUGH.md).

Claude updates this file at the end of every phase. Last updated: **Phase 5 (2026-10-27)**.

**In one line:** we built a flight recorder for AI agents, a way to replay any recorded run
exactly, a way to fork a run at any step with one change and *prove* whether the change fixed it,
and a diff that shows exactly where two runs went different ways.

---

## Chapter 0: what an agent actually is (Phase 0)

An agent is just a loop. The model can't run code; it can only *ask* us to run a tool.

```
user: "Order 4417 charged me twice. Refund the extra charge."
  │
  ▼
┌─ loop ─────────────────────────────────────────────────┐
│ send conversation + tool list to Gemini                │
│   ← model replies: "call get_payments(order_id=4417)"  │
│ WE run get_payments → result goes back into the convo  │
│ repeat… until the model replies with plain text        │
└────────────────────────────────────────────────────────┘
```

`@tool` turns a normal Python function into something the model can ask for. It reads the type
hints (`order_id: str`) and builds the JSON schema the model sees. The docstring becomes the
description the model reads to decide *when* to call it.

## Chapter 1: recording everything (Phase 1)

To debug an agent you need to see every decision. We intercept at exactly **two boundaries**: the
model client (`lab.wrap`) and the tools (`@tool`). Every call through them becomes a **span**, and
spans nest into a tree:

```
invoke_agent support                        ← the run
├─ step 1                                   ← one decision
│  ├─ chat gemini-flash-lite    → get_order, get_payments
│  ├─ execute_tool get_order    ← {item: earbuds, 2499}
│  └─ execute_tool get_payments ← {P-901 captured, P-902 captured}
├─ step 2
│  ├─ chat                      → refund_payment(P-902)
│  └─ execute_tool refund_payment ← {RF-1001, pending}
└─ step 3
   └─ chat                      "I've processed a refund…"
```

**How spans find their parent:** a `ContextVar` holds "the span that's open right now". A new span
makes that one its parent. Nobody passes anything down through the agent's code.

**Alongside the tree, we save a recording of every call.** That means the exact request, the exact
response, and a **hash** of the request. That hash is the key to everything after.

## Chapter 2: judging runs (Phase 2)

A recorder alone tells you *what* happened, not whether it was *good*. So we added:
- **A dataset:** 21 tasks, each with a question, the expected outcome in words, and checks.
- **Checks:**
  - code checks: "called `refund_payment` with P-902", "never called refund";
  - an **LLM judge** that grades meaning, returning structured JSON.
- **A failure category** for every failed task (`ignored_tool_error`, `false_claim`, …), plus
  success rate, p50/p95 latency and cost.
- **Scoring from the stored trace,** not from the agent's memory. So it works on *anyone's* agent.

The UI shows any run as that tree, with a red path to the failure. The best catch was **ALR-999**.
The tool said "no such alert", and the agent quietly investigated a *different* alert. The answer
looked expert; only the tree shows the error being ignored.

## Chapter 3: replay, the core engine (Phase 3)

**The idea:** run the *same agent code* again, but at each boundary, instead of calling Gemini or
the tool, hand back what was recorded.

### How the hash works

```
request = {model, system prompt, tools, full conversation so far}
   │  canonical JSON (keys sorted, no spaces: same data → same text)
   ▼
SHA-256 → "815070c109c5…" (64 hex chars, a fingerprint of the request)
```

The **recording table** for one run looks like a cassette:

```
seq  kind   hash      response
 2   llm    a91f…     → get_order, get_payments
 3   tool   77c2…     → {item: earbuds…}
 4   tool   e03b…     → {P-901, P-902 captured}
 6   llm    5d10…     → refund_payment(P-902)
 7   tool   c4e8…     → {RF-1001}
 9   llm    0b6a…     → "I've processed a refund…"
```

### Why a replay matches, step after step

Each step builds on the one before:
- **Step 1's request** is built only from things that haven't changed: the user message, the
  prompt and the tools. Same request, same hash, so its recorded response is found.
- **Step 2's request** is step 1's request plus step 1's *responses*. Those responses came from the
  recording, so step 2's request is identical too. Same hash, so it's found as well.
- **Every later step** follows the same way.

```
step 1 request ── hash matches ──► recorded reply ─┐
                                                  ▼
step 2 request (built from step 1's reply) ── matches ──► recorded reply ─┐
                                                                           ▼
… and so on to the final answer
```

The one thing that breaks the chain is **a change in the code**: a different prompt, a different
tool, or a tool returning something different. Then a hash has no recording, and the replay stops
with a `ReplayDivergence` that says *where*. It compares the new request with the one it expected
and prints the path: `$.config.system_instruction`.

**Small details that make it exact:**
- **Two calls with the same hash** (for example a 429 error, then the successful retry) wait in a
  queue and are served in their original order.
- **The clock and random numbers** go through `lab.now()` and `lab.random()`, so they replay too.
- **Tools never run during a replay,** so a refund can never happen twice.

### Why we compare the replay against the original

The **fidelity check** puts the two trees side by side and compares what the agent *decided*: the
shape, tool arguments and results, model outputs and the final answer. It ignores IDs, timing and
cost.

```
original run                   replay run
invoke_agent ───────────── = ── invoke_agent
├─ step 1 → get_payments ── = ── step 1 → get_payments
├─ step 2 → refund(P-902) ─ = ── step 2 → refund(P-902)
└─ step 3 "processed…" ──── = ── step 3 "processed…"        ✓ identical, $0
```

It matters for three reasons:
1. **Trust.** If a replay with *no* change is identical, then in a fork any difference must come
   from *your* change, not from chance. Without this, Fork, Diff and Blame can't prove anything.
2. **Change detection.** Replaying old runs against new code shows what changed. All 16 old
   support runs stopped at the first model call, at `system_instruction`, because the prompt
   changed; all 14 triage runs, untouched, replayed identically.
3. **It finds bugs.** A refund run's answer looked like a hallucination ("P-902 was already
   refunded"). Its replay stopped inside an *earlier* tool result. Our tool had returned live data
   that the refund later changed, so the model was shown a rewritten history. The fix was to copy
   tool results when they're returned. Without replay, that would have been blamed on the model.

---

## Chapter 4: Fork, change one thing, prove it (Phase 4)

A fork is replay with a twist: freeze everything *before* step N, change one thing, and run live
from step N.

```
source run (failed)        fork at step 3, prompt += "always give the refund ID"
step 1 → get_payments  ──► served from the recording (exactly the same)
step 2 → refund(P-902) ──► served from the recording, and re-applied to the simulator
step 3 "processed…"        LIVE: the model answers again, with the new prompt
```

**How it works, in four ideas:**
1. **Match by position before the fork point.** Changing the prompt changes every request's hash,
   so "the 2nd model call gets the 2nd recorded reply" instead. After the fork point, everything
   is live.
2. **Apply the change at the boundary.** The wrapped Gemini client swaps the prompt or model on
   live calls, so it works even for a customer's agent whose code we can't edit.
3. **Keep the world consistent.** The step-2 refund is served from the recording *and* re-applied
   to the simulated backend (event sourcing), so step 3 sees P-902 as refunded. A write tool with
   no simulator stops the fork rather than touching a real system.
4. **Prove it with statistics.** The live part is random, so a fork runs **N times with the change
   and N times without it** (the control). Each run is scored with the original task's checks, and
   Fisher's exact test says how likely the gap would be by luck.

**The demo, live:** the refund task's failure (the agent never gave the refund ID), forked at
step 3 with one sentence added to the prompt:

```
with the change      5/5 pass    "Your refund ID is RF-1001, arriving in 5-7 business days"
without (control)    0/5 pass    "I've processed a refund…"
p = 0.0079 → the change fixes it          (one live call per run, about $0.0004)
```

**The best story: three forks of ALR-999,** where the agent ignored "no such alert" and
investigated a different alert:

```
ALR-999 run (failed)
├─ ⑂ fork 1: "say it doesn't exist and stop"          0/5 vs control 3/5
│     the fix read well but missed half the task: it never offered the real alerts
├─ ⑂ fork 2: "say so, then list what's firing"        4/5 vs 0/5, p = 0.048 … but fake
│     the agent invented ALR-42 and ALR-404 without calling list_alerts; the judge passed them
│     → a new exact check, `grounded`, rescored it to 1/5 vs 1/5: no effect
└─ ⑂ fork 3: "call list_alerts, name only what it    5/5 vs 0/5, p = 0.008 ✓ real
              returns, ask which one"
```

Three lessons to retell:
- **A fix that reads well can fail 5 times out of 5.**
- **A fork is only as good as its checks.** An LLM judge missed invented IDs that a one-line
  exact check catches.
- **Controls matter.** The same control passed 3/5 in one batch and 0/5 in another, so one run
  proves nothing.

**Where forks run:** the lab never runs your agent. "Fork" in the UI queues a job; a **worker**
with the agent's code claims it and sends the runs back:

```
  UI ──POST /api/forks──► lab server (job queue in the `forks` table)
                               ▲      │  claim (compare-and-set) / results
                               │      ▼
                         lab worker --entry app.py:agent   (in your repo, your API key)
                         or the worker built into `lab ui` (demo agents)
```

Over HTTP the worker uses `RemoteStore` (the same methods as the local store, as POSTs), so it
works from another repo or machine. That was tested live with the worker's own database never even
created.

---

## Chapter 5: Trajectory Diff, where two runs part ways (Phase 5)

A fork's pass rate says *whether* a change helped. The diff says *how*: it lines two runs up step
by step and points at the first place they differ.

**Step 1: turn each run into steps.** A step is one model decision plus what it caused:

```
step 1   → get_order(4417), get_payments(4417)     ← {earbuds…}, {P-901, P-902 captured}
step 2   → refund_payment(P-902)                   ← {RF-1001}
step 3   "I've processed a refund…"
```

**Step 2: line them up.** You can't just compare step 3 with step 3: if one run does an extra
check, every later step shifts. This is the problem `diff` solves for lines of code and biologists
solve for DNA. We use **Needleman–Wunsch**:
- Fill a table where each cell is the best score for lining up the first *i* steps of A with the
  first *j* of B.
- Each cell picks the best of three moves: *pair* these two steps (scored by how similar they
  are), or *skip* one of them (a gap, with a penalty).
- Read the answer back from the corner.

Because pairs are scored by *similarity* (same tools? same arguments? same results? same words?),
"the same lookup for a different order" lines up as a **change**, and an extra check shows as an
**added** step, with no shifting.

**Step 3: say what changed, and what it caused.** Each changed row gets notes in words
(`get_order: order_id '4417' → '4471'`), and the effects sit side by side: outcome, steps, tokens,
cost, time, plus a word-level diff of the two final answers.

**Seen live, original vs fork** (the refund fix from Chapter 4):

```
   A original                        B fork
=  1. get_order, get_payments    │   1. ↺ get_order, get_payments
=  2. refund_payment(P-902)      │   2. ↺ refund_payment(P-902)
≠  3. "I've successfully issued… │   3. "…Your refund ID is RF-1001…"
first divergence: step 3 · outcome ✗ incomplete → ✓ passed
```

**Seen live, Flash-Lite vs Flash** on the same eight tasks. Flash passed 8/8, and the diff shows
what its extra cost buys:

```
   A Flash-Lite                          B Flash
=  1. get_alert(ALR-103)             │   1. get_alert(ALR-103)
+                                    │   2. list_deploys(payments)
+                                    │   3. list_alerts()
+                                    │   4. get_metrics(payments)
≠  2. list_deploys, get_metrics,     │   5. search_logs(payments)
      search_logs (all at once)
=  3. get_dependencies(payments)     │   6. get_dependencies(payments)
≠  4. "Root cause: acmepay…"         │   7. "No, do not roll back…"
steps 4 → 7 · tokens 3,713 → 8,998 · cost 5× · time 5× · both pass
```

So **Flash verifies more**: an extra `get_order` cross-check on order questions, and deploy
history and `list_alerts` before answering "should I roll back?". Flash-Lite skips those checks,
bundles its lookups into one step, and usually passes anyway. The one task where the extra care
paid off was the refund: Flash gave the refund ID.

**A limit we found:** when one model bundles three calls into one step and the other spreads them
over three, the diff shows extra steps, though the same work was done. It's noted as an open
challenge.

---

## What comes next, on top of fork and diff

### Auto-Blame (Phase 6)

Fork lets *you* test a guess about which step was wrong; diff shows how runs differ. Blame makes
the guess itself, then proves it:
1. A judge reads a failed run and ranks candidate "first wrong steps", each with a correction.
2. Fork each candidate with its correction, N times with controls (Chapter 4).
3. The step whose correction turns failures into passes is confirmed as the cause.
4. The diff of the winning fork against the original shows exactly what changed.

```
ALR-999 run (failed)
├─ candidate: step 1 (get_alert call)    fork → 0/5   not the cause
└─ candidate: step 2 (switched alerts)   fork → 5/5 vs control 0/5, p = 0.008   ✓ confirmed
```

The three manual ALR-999 forks from Chapter 4 are exactly what Blame will automate, including the
trap from fork 2: a "fix" that only fools the checks. Blame will be measured on a catalogue of
deliberately planted bugs, where the guilty step is known.

**The pitch:** "Other tools let you rerun from a step. We tell you *which* step was wrong, prove
it by forking against a control, and show you the exact diff."

---

## Finding your way around the platform

```
Evals tab → eval report (success %, p50/p95, failure chart)
   └─ click a failed task → run page
        ├─ header: checks + the judge's reasoning, ↺ Replay button, Run family tree
        ├─ tree: red path to the error
        └─ click a node → inspector: exact prompt sent, reply, tool args and result
              └─ ⑂ Fork from here → change prompt / model / tool output, N, control
                    └─ fork page: 5/5 vs 0/5, p-value, verdict, every run (⇄ diff vs source)
        └─ Compare with (source, or other runs of the task) → ⇄ Diff
              └─ diff page: first divergence, effects, steps side by side, answer diff
Runs tab  → every run ("Show replays and forks" reveals them)
CLI       → lab run · lab eval · lab replay · lab fidelity · lab fork · lab diff · lab worker · lab ui
```
