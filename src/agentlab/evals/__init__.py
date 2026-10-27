"""Evals: run an agent over a dataset of tasks and score every run.

- `tasks.py`: the dataset format (JSONL) and the checks.
- `trajectory.py`: a stored run, flattened into what checks read.
- `judge.py`: the LLM judge, with structured output.
- `categories.py`: failure categories.
- `metrics.py`: success rate, latency percentiles, cost per task.
- `runner.py`: the batch runner.
"""

from agentlab.evals.judge import LLMJudge
from agentlab.evals.runner import run_eval, score
from agentlab.evals.tasks import Task, load_dataset
from agentlab.evals.trajectory import Trajectory

__all__ = ["LLMJudge", "Task", "Trajectory", "load_dataset", "run_eval", "score"]
