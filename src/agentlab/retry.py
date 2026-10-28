"""Retrying model calls that fail for temporary reasons (overload, rate limits, timeouts).

Retries live here rather than in the Gemini SDK so that every attempt passes through our wrapper
and shows up as its own span. That is what makes the README's Retry Rate measurable.
"""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from agentlab.llm.base import TransientLLMError


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_s: float = 1.0
    max_delay_s: float = 16.0
    sleep: Callable[[float], None] = time.sleep
    # A server asking us to wait longer than this has usually run out of quota (a daily limit),
    # not hit a blip: waiting hours would just look like a hang, so give up at once (C-022).
    max_hint_s: float = 120.0


def call_with_retries[T](fn: Callable[[], T], policy: RetryPolicy) -> tuple[T, int]:
    """Call `fn`, retrying on TransientLLMError. Returns the result and the number of attempts.

    Waits grow exponentially (1s, 2s, 4s, …) with random jitter, so many clients retrying at once
    don't all hit the API at the same moment. A server's retry hint is a lower bound on the wait.
    """
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn(), attempt
        except TransientLLMError as e:
            if attempt == policy.max_attempts:
                raise
            if e.retry_after_s and e.retry_after_s > policy.max_hint_s:
                raise TransientLLMError(
                    f"{e} (the server asked to wait {e.retry_after_s:.0f}s: probably a quota "
                    "limit; not retrying)",
                    retry_after_s=e.retry_after_s,
                ) from e
            delay = min(policy.max_delay_s, policy.base_delay_s * 2 ** (attempt - 1))
            delay *= random.uniform(0.5, 1.0)
            # If the server said how long to wait ("retry in 3.6s"), wait at least that long.
            policy.sleep(max(delay, e.retry_after_s or 0))
    raise AssertionError("unreachable")
