"""Clock and randomness that replay can reproduce: `lab.now()`, `lab.monotonic()`, `lab.random()`.

An agent that puts today's date in its prompt, or picks something at random, would never replay:
the date changes, so the model request changes, so its hash matches no recording. These functions
go through the same interception as model and tool calls. While recording they return the real
value and save it; while replaying they return the saved value, in the same order.
"""

import random as _random
import time
from collections.abc import Callable
from datetime import UTC, datetime

from agentlab import tracing
from agentlab.replay import session as replay


def now() -> datetime:
    """The current time (UTC), recorded so that a replay sees the same time."""
    return datetime.fromtimestamp(_read("clock", "time", time.time), UTC)


def monotonic() -> float:
    """A monotonic clock for measuring durations and deadlines, recorded like `now()`."""
    return _read("clock", "monotonic", time.monotonic)


def random() -> float:
    """A random float in [0, 1), recorded so that a replay draws the same number."""
    return _read("random", "random", _random.random)


def _read(kind: str, source: str, live: Callable[[], float]) -> float:
    request = {"source": source}
    session = replay.current()
    if session is None:
        value = live()
    elif not session.has(kind):
        # The source run recorded no reads of this kind (it predates Phase 3): use the live value
        # and count it, so the replay report can say the replay wasn't fully pinned down.
        session.fallbacks[kind] += 1
        value = live()
    else:
        served = session.take(kind, request, tracing.request_hash(request))
        if served is replay.LIVE:  # a fork, past its fork point
            value = live()
            if kind == "clock":
                value = session.continue_clock(source, value)
        else:
            value = served["value"]

    span = tracing.current_span()
    if span is not None and span.run_id:
        span.record(request, {"value": value}, kind=kind)
    return value
