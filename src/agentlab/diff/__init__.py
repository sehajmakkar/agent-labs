"""Trajectory Diff: line two runs up step by step and say where, and how, they went different ways.

- `steps.py`: a run's spans → a list of steps (one model decision plus what it caused).
- `align.py`: how similar two steps are, and Needleman–Wunsch alignment of two step lists.
- `report.py`: the full diff: aligned rows, the first divergence, and the downstream effects.
"""

from agentlab.diff.report import TrajectoryDiff, diff_runs

__all__ = ["TrajectoryDiff", "diff_runs"]
