"""Deterministic replay: re-run a recorded agent with every call served from its recordings.

- `session.py`: the replay session ("cassette") and `ReplayDivergence`.
- `fidelity.py`: does a replay reproduce its source run exactly?
- `runner.py`: replay a stored run, from the demo agents or a customer's entry point.
"""
