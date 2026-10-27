"""Fork & Replay: rerun a recorded run from a chosen step with one change, N times, and measure.

- `point.py`: where a fork starts, in terms of the source run's recordings.
- `stats.py`: pass rates and Fisher's exact test.
- `runner.py`: run one fork job (N forks and N controls), score them, summarise.
- `worker.py`: the loop that claims queued fork jobs and runs them (`lab worker`).
"""
