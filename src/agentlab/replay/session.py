"""The replay session: serve a run's recorded responses back in place of live calls.

This is the record/replay ("VCR") pattern. While recording, each model call, tool call, clock read
and random number is saved with a hash of its request. While replaying, the same agent code runs
again, and each boundary asks the session for the response instead of making the call:

    request → hash → the next unused recording with that hash → its response

Recordings with the same hash are served in the order they were made, so a call that was retried
(a 429, then a success) replays as the same failure followed by the same success.

If the agent asks for something that was never recorded, its code or inputs have changed since the
recording. The session raises `ReplayDivergence`, naming what differs from the request it expected.

`ForkSession` is the counterfactual version: it serves the recording *up to a chosen point*, by
position rather than hash (an override such as a new prompt changes the requests on purpose), then
returns `LIVE` so the boundaries make real calls from there on, with the override applied.
"""

from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from agentlab.store import RecordingRow

# Returned by `take()` when a call should go out for real: in a fork, after the fork point.
LIVE = object()


class InterceptorStop(Exception):
    """Stops a replay or fork. Not an error of the tool or model, so the loop must not hand it to
    the model as a tool error."""


class ReplayDivergence(InterceptorStop):
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


class ForkBlocked(InterceptorStop):
    """A fork reached a write tool that has no simulator. Running it for real could move money or
    send email, so the fork stops instead."""


class Override(BaseModel):
    """What a fork changes. Empty means a control: the same point, no change."""

    system_prompt: str | None = None  # replaces the system instruction of every live model call
    model: str | None = None  # model ID for every live model call
    tool_output: Any = None  # replaces the result of the forked tool call (tool forks only)

    def is_empty(self) -> bool:
        return self.system_prompt is None and self.model is None and self.tool_output is None


@dataclass
class _Recorded:
    kind: str
    request_hash: str
    request: Any
    response: Any
    seq: int | None = None
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
        recordings = [_Recorded(r.kind, r.request_hash, r.request, r.response, r.seq) for r in rows]
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

    def run_fields(self) -> dict[str, Any]:
        """Columns for the run this session produces."""
        return {"mode": "replay", "parent_run_id": self.source_run_id}


@dataclass
class ForkSession(ReplaySession):
    """Replay up to `live_from_seq`, then go live with `override` applied."""

    live_from_seq: float = float("inf")
    override: Override = field(default_factory=Override)
    fork_id: str | None = None
    fork_span_id: str | None = None
    tool_override_seq: int | None = None  # the recorded tool call whose result is replaced
    live: bool = False
    _prefix: dict[tuple, deque[_Recorded]] = field(default_factory=dict)
    _last_clock: dict[str, float] = field(default_factory=dict)
    _clock_offset: dict[str, float] = field(default_factory=dict)

    @classmethod
    def for_fork(
        cls,
        source_run_id: str,
        rows: list[RecordingRow],
        *,
        live_from_seq: float,
        override: Override,
        run_id: str,
        fork_id: str | None = None,
        fork_span_id: str | None = None,
        tool_override_seq: int | None = None,
    ) -> "ForkSession":
        session = cls(
            source_run_id,
            [_Recorded(r.kind, r.request_hash, r.request, r.response, r.seq) for r in rows],
            replay_run_id=run_id,
            live_from_seq=live_from_seq,
            override=override,
            fork_id=fork_id,
            fork_span_id=fork_span_id,
            tool_override_seq=tool_override_seq,
        )
        prefix: dict[tuple, deque[_Recorded]] = defaultdict(deque)
        for r in session.recordings:
            if r.seq is not None and r.seq < live_from_seq:
                prefix[_prefix_key(r.kind, r.request_hash)].append(r)
        session._prefix = prefix
        return session

    def take(self, kind: str, request: Any, request_hash: str) -> Any:
        """Before the fork point: the next recorded call of this kind, in order. After: LIVE."""
        queue = None if self.live else self._prefix.get(_prefix_key(kind, request_hash))
        if not queue:
            if kind == "llm":
                self.live = True  # the first live model call: from here on, everything is live
            return LIVE
        recorded = queue.popleft()
        recorded.used = True
        if kind == "tool" and recorded.request.get("tool") != request.get("tool"):
            raise ReplayDivergence(kind, request, recorded.request)
        if kind == "clock":
            self._last_clock[request["source"]] = recorded.response["value"]
        if kind == "tool" and recorded.seq == self.tool_override_seq:
            return {"output": self.override.tool_output}
        return recorded.response

    def continue_clock(self, source: str, live_value: float) -> float:
        """A live clock read, shifted to continue the recorded timeline.

        Monotonic clocks from two processes are unrelated numbers, so mixing a recorded deadline
        with a fresh reading would time out at once, or never. The first live read is pinned to
        the last recorded one, and later reads move forward from there.
        """
        if source not in self._last_clock:
            return live_value
        if source not in self._clock_offset:
            self._clock_offset[source] = self._last_clock[source] - live_value
        return live_value + self._clock_offset[source]

    def run_fields(self) -> dict[str, Any]:
        return {
            "mode": "fork",
            "parent_run_id": self.source_run_id,
            "fork_id": self.fork_id,
            "fork_span_id": self.fork_span_id,
            "fork_override": None if self.override.is_empty() else self.override.model_dump(),
        }


def _prefix_key(kind: str, request_hash: str) -> tuple:
    # Model and tool calls are matched by position: an override changes their requests on purpose.
    # Clock and random reads are matched by source ("time", "monotonic", "random"), via the hash.
    return (kind, request_hash) if kind in ("clock", "random") else (kind,)


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
