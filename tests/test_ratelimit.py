import threading

import pytest
from google.genai import errors

from agentlab.llm.base import TransientLLMError
from agentlab.llm.gemini import _retry_delay
from agentlab.llm.ratelimit import RateLimiter
from agentlab.retry import RetryPolicy, call_with_retries


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_limiter_waits_for_the_oldest_request_to_leave_the_window():
    clock = FakeClock()
    limiter = RateLimiter(2, clock=clock, sleep=clock.sleep)
    assert limiter.acquire() == 0
    clock.now = 10
    assert limiter.acquire() == 0
    # Third request: the first one (t=0) leaves the 60s window at t=60.
    assert limiter.acquire() == pytest.approx(50)
    assert clock.now == pytest.approx(60)


def test_limiter_is_shared_safely_by_threads():
    limiter = RateLimiter(1000)
    threads = [threading.Thread(target=limiter.acquire) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(limiter._sent) == 50


def test_retry_waits_at_least_as_long_as_the_server_asks():
    waits = []
    attempts = iter([TransientLLMError("429", retry_after_s=7.5), "ok"])

    def flaky():
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    policy = RetryPolicy(max_attempts=2, base_delay_s=1, sleep=waits.append)
    assert call_with_retries(flaky, policy) == ("ok", 2)
    assert waits == [7.5]


def test_retry_delay_is_read_from_retry_info():
    detail = {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3.6s"}
    e = errors.ClientError(429, {"error": {"code": 429, "message": "quota", "details": [detail]}})
    assert _retry_delay(e) == 3.6
    assert _retry_delay(errors.ClientError(429, {"error": {"code": 429, "message": "x"}})) is None
