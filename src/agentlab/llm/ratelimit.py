"""Client-side rate limiting: stay under the provider's requests-per-minute quota.

Retrying after a 429 works for the odd burst, but an eval running tasks in parallel can blow
through a free-tier quota (15 requests per minute for Flash-Lite) in seconds and then fail every
retry. Waiting *before* sending is cheaper than being refused.

This is a sliding-window limiter: it remembers when each of the last `per_minute` requests was
sent, and a new request waits until the oldest of them is more than 60 seconds old.
"""

import threading
import time
from collections import deque
from collections.abc import Callable

WINDOW_S = 60.0


class RateLimiter:
    def __init__(
        self,
        per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if per_minute < 1:
            raise ValueError("per_minute must be at least 1")
        self.per_minute = per_minute
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()
        self._lock = threading.Lock()  # shared by every thread using the same client

    def acquire(self) -> float:
        """Block until a request may be sent. Returns the seconds spent waiting."""
        waited = 0.0
        while True:
            with self._lock:
                now = self._clock()
                while self._sent and now - self._sent[0] >= WINDOW_S:
                    self._sent.popleft()
                if len(self._sent) < self.per_minute:
                    self._sent.append(now)
                    return waited
                delay = WINDOW_S - (now - self._sent[0])
            # Sleep outside the lock so other threads can check in meanwhile.
            self._sleep(delay)
            waited += delay
