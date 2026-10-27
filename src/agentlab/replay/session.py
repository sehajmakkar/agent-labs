"""The replay session: serve a run's recorded responses back in place of live calls.

This is the record/replay ("VCR") pattern. While recording, each model call, tool call, clock read
and random number is saved with a hash of its request. While replaying, the same agent code runs
again, and each boundary asks the session for the response instead of making the call:

    request → hash → the next unused recording with that hash → its response

Recordings with the same hash are served in the order they were made, so a call that was retried
(a 429, then a success) replays as the same failure followed by the same success.

If the agent asks for something that was never recorded, its code or inputs have changed since the
recording. The session raises `ReplayDivergence`, naming what differs from the request it expected.
"""

from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from agentlab.store import RecordingRow


class ReplayDivergence(Exception):
    """The replayed agent made a call that isn't in the recording."""

    def __init__(self, kind: str, request: Any, expected: Any | None):
        self.kind = kind
        self.request = request
        self.expected = expected
        self.differences = json_differences(expected, request) if expected is not None else []
        what = f"no recorded {kind} call matches this request"
        if expected is None:
            detail = f"; the recording has no more {kind} calls"
        else:
            detail = "; differs from the next recorded call at " + ", ".join(self.differences[:4])
        super().__init__(what + detail)


@dataclass
class _Recorded:
    kind: str
    request_hash: str
    request: Any
    response: Any
    used: bool = False


@dataclass
class ReplaySession:
    source_run_id: str
    recordings: list[_Recorded]
    _queues: dict[tuple[str, str], deque[_Recorded]] = field(default_factory=dict)
    # The ID the replay's own run will get, chosen up front so the caller can find it afterwards.
    replay_run_id: str | None = None
    # Reads of a source that was never recorded (clock, random) in runs from before Phase 3.
    fallbacks: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @classmethod
    def from_rows(
        cls, source_run_id: str, rows: list[RecordingRow], replay_run_id: str | None = None
    ) -> "ReplaySession":
        recordings = [_Recorded(r.kind, r.request_hash, r.request, r.response) for r in rows]
        queues: dict[tuple[str, str], deque[_Recorded]] = defaultdict(deque)
        for r in recordings:
            queues[(r.kind, r.request_hash)].append(r)
        return cls(source_run_id, recordings, queues, replay_run_id)

    def has(self, kind: str) -> bool:
        return any(r.kind == kind for r in self.recordings)

    def take(self, kind: str, request: Any, request_hash: str) -> Any:
        """The recorded response for this request, or ReplayDivergence if there is none."""
        queue = self._queues.get((kind, request_hash))
        if queue:
            recorded = queue.popleft()
            recorded.used = True
            return recorded.response
        expected = next((r for r in self.recordings if r.kind == kind and not r.used), None)
        raise ReplayDivergence(kind, request, expected.request if expected else None)

    def unused(self) -> list[_Recorded]:
        """Recordings the replay never asked for: the replay did less than the original."""
        return [r for r in self.recordings if not r.used]


_session: ContextVar[ReplaySession | None] = ContextVar("agentlab_replay", default=None)


def current() -> ReplaySession | None:
    """The active replay session, or None when calls should go out for real."""
    return _session.get()


@contextmanager
def replaying(session: ReplaySession) -> Iterator[ReplaySession]:
    """Serve every intercepted call inside this block from `session`."""
    token = _session.set(session)
    try:
        yield session
    finally:
        _session.reset(token)


def json_differences(expected: Any, actual: Any, path: str = "$") -> list[str]:
    """The JSON paths where two values differ, e.g. `$.config.system_instruction`."""
    if type(expected) is not type(actual):
        return [path]
    if isinstance(expected, dict):
        differences = []
        for key in sorted(set(expected) | set(actual), key=str):
            if key in expected and key in actual:
                differences += json_differences(expected[key], actual[key], f"{path}.{key}")
            else:
                differences.append(f"{path}.{key}")
        return differences
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [f"{path} (length {len(expected)} → {len(actual)})"]
        differences = []
        for i, (a, b) in enumerate(zip(expected, actual, strict=True)):
            differences += json_differences(a, b, f"{path}[{i}]")
        return differences
    return [] if expected == actual else [path]
