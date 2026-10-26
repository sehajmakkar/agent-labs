"""Tracing: record every run as a tree of spans in the trace store.

The current run and the current span live in context variables. Code deep inside an agent (a tool,
a model call) finds its parent span without anyone passing it down, and each new span becomes a
child of whatever span is open around it. That is "context propagation".

Until `init()` is called there is no store: spans are still created but thrown away when they end,
so tests and plain library use need no database.
"""

import functools
import hashlib
import inspect
import itertools
import json
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python

from agentlab import semconv
from agentlab.store import RecordingRow, SpanRow, Store

_store: Store | None = None


@dataclass
class _ActiveRun:
    id: str
    store: Store
    seq: Iterator[int] = field(default_factory=itertools.count)


@dataclass
class Span:
    """An open span. Callers fill in output, error, tokens and attributes before it ends."""

    kind: str
    name: str
    run_id: str | None
    parent_id: str | None
    seq: int
    input: Any = None
    attributes: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    output: Any = None
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cost_usd: float | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _start: float = field(default_factory=time.perf_counter)
    _recordings: list[RecordingRow] = field(default_factory=list)

    def record(self, request: Any, response: Any) -> None:
        """Keep the exact request and response of this call, for replay later."""
        request = jsonable(request)
        self._recordings.append(
            RecordingRow(
                span_id=self.id,
                kind=self.kind,
                request_hash=request_hash(request),
                request=request,
                response=jsonable(response),
            )
        )


_current_run: ContextVar[_ActiveRun | None] = ContextVar("agentlab_run", default=None)
_current_span: ContextVar[Span | None] = ContextVar("agentlab_span", default=None)


def init(db_path: str | Path) -> Store:
    """Start saving runs to the trace store at `db_path`."""
    global _store
    _store = Store(db_path)
    return _store


def shutdown() -> None:
    """Stop saving runs. Mainly for tests."""
    global _store
    _store = None


def jsonable(value: Any) -> Any:
    return to_jsonable_python(value, fallback=str)


def request_hash(request: Any) -> str:
    """A stable fingerprint of a request: the same request always gives the same hash."""
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@contextmanager
def span(
    kind: str, name: str, *, input: Any = None, attributes: dict[str, Any] | None = None
) -> Iterator[Span]:
    run = _current_run.get()
    parent = _current_span.get()
    current = Span(
        kind=kind,
        name=name,
        run_id=run.id if run else None,
        parent_id=parent.id if parent else None,
        seq=next(run.seq) if run else 0,
        input=jsonable(input),
        attributes={k: v for k, v in (attributes or {}).items() if v is not None},
    )
    token = _current_span.set(current)
    try:
        yield current
    except BaseException as e:
        if current.error is None:
            current.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        _current_span.reset(token)
        if run:
            run.store.save_span(_to_row(current), current._recordings)


@contextmanager
def agent_run(
    agent_name: str, input: Any = None, *, model: str | None = None, task_id: str | None = None
) -> Iterator[Span]:
    """Open an `invoke_agent` span, starting a new run first if none is active.

    Set `attributes[semconv.RUN_STATUS]` on the yielded span to record how the run ended
    (default "completed"). An exception marks the run "error".
    """
    name = f"invoke_agent {agent_name}"
    attributes = {semconv.OPERATION_NAME: "invoke_agent", semconv.AGENT_NAME: agent_name}

    # Already inside a run (a sub-agent), or not recording: just open the span.
    if _store is None or _current_run.get() is not None:
        with span("agent", name, input=input, attributes=attributes) as current:
            yield current
        return

    store = _store
    run_id = store.create_run(
        agent_name=agent_name, input=jsonable(input), model=model, task_id=task_id
    )
    token = _current_run.set(_ActiveRun(run_id, store))
    status, output, error = "error", None, None
    try:
        with span("agent", name, input=input, attributes=attributes) as current:
            yield current
        status = current.attributes.get(semconv.RUN_STATUS, "completed")
        output = jsonable(current.output)
    except BaseException as e:
        error = f"{type(e).__name__}: {e}"
        raise
    finally:
        _current_run.reset(token)
        store.finish_run(run_id, status=status, output=output, error=error)


def agent(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for an agent's entry point: each call becomes a run (`@lab.agent("support")`)."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            arguments = dict(signature.bind(*args, **kwargs).arguments)
            with agent_run(name, input=arguments) as current:
                result = fn(*args, **kwargs)
                current.output = result
                return result

        return wrapper

    return decorate


def current_run_id() -> str | None:
    run = _current_run.get()
    return run.id if run else None


def _to_row(s: Span) -> SpanRow:
    return SpanRow(
        id=s.id,
        run_id=s.run_id,
        parent_span_id=s.parent_id,
        seq=s.seq,
        kind=s.kind,
        name=s.name,
        status="error" if s.error else "ok",
        started_at=s.started_at,
        duration_ms=(time.perf_counter() - s._start) * 1000,
        input=s.input,
        output=jsonable(s.output),
        error=s.error,
        attributes=jsonable(s.attributes),
        input_tokens=s.input_tokens,
        output_tokens=s.output_tokens,
        thinking_tokens=s.thinking_tokens,
        cost_usd=s.cost_usd,
    )
