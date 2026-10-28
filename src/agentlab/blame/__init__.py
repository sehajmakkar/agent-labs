"""Auto-Blame: find the step that made a run fail, and prove it by forking.

- `catalog.py`: seeded bugs, planted on purpose, whose guilty step is known (the ground truth).
- `propose.py`: an LLM judge ranks candidate "first wrong steps", each with a correction.
- `verify.py`: fork each candidate with its correction against a control, then pin it down.
- `runner.py`: one blame job, from proposal to report.
- `bench.py`: seed failures, and measure how often blame finds the planted step.
"""
