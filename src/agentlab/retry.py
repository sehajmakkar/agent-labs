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


def call_with_retries[T](fn: Callable[[], T], policy: RetryPolicy) -> tuple[T, int]:
    """Call `fn`, retrying on TransientLLMError. Returns the result and the number of attempts.

    Waits grow exponentially (1s, 2s, 4s, …) with random jitter, so many clients retrying at once
    don't all hit the API at the same moment.
    """
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn(), attempt
        except TransientLLMError:
            if attempt == policy.max_attempts:
                raise
            delay = min(policy.max_delay_s, policy.base_delay_s * 2 ** (attempt - 1))
            policy.sleep(delay * random.uniform(0.5, 1.0))
    raise AssertionError("unreachable")
