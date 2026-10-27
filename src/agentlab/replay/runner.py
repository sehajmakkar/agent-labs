"""Replay a stored run: run the same agent code again, with every call served from recordings.

Two ways to say which code to run:
- a demo agent from `agentlab.demo`, which `lab replay <run>` finds by the run's agent name;
- a customer's own entry point, the function decorated with `@lab.agent`, passed as `entry`
  (`lab replay <run> --entry examples/customer_app.py:answer`).

Replays never touch the network. Demo agents get a Gemini client whose inner SDK client refuses to
be called, so a replay that tried to reach Gemini would fail loudly instead of quietly costing
money.
"""

import importlib
import importlib.util
import sys
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agentlab import semconv
from agentlab.llm.gemini import GeminiClient, wrap_genai_client
from agentlab.loop import Agent, run_agent
from agentlab.replay.fidelity import FidelityReport, compare
from agentlab.replay.session import ReplayDivergence, ReplaySession, replaying
from agentlab.retry import RetryPolicy
from agentlab.store import Store, run_message

DEFAULT_MAX_ATTEMPTS = 10  # for runs recorded before their retry limit was


@dataclass
class ReplayResult:
    source_run_id: str
    run_id: str
    report: FidelityReport
    error: str | None = None


class _Offline:
    """Stands in for `genai.Client` during a replay. Any real call is a bug, so it raises."""

    class models:  # noqa: N801 - mirrors `client.models`
        @staticmethod
        def generate_content(**_: Any) -> Any:
            raise RuntimeError("A replay tried to call Gemini; every call should be recorded")


def replay_llm() -> GeminiClient:
    return GeminiClient(client=wrap_genai_client(_Offline()))


def replay_run(
    store: Store,
    run_id: str,
    *,
    agents: dict[str, Agent] | None = None,
    entry: Callable[..., Any] | None = None,
) -> ReplayResult:
    """Replay `run_id` and compare the result with it. The store must be the active one
    (`tracing.init`), so the replay is recorded as a run of its own."""
    source = store.get_run(run_id)
    if source is None:
        raise LookupError(f"No run {run_id}")
    if entry is None and source.agent_name not in (agents or {}):
        raise LookupError(
            f"{source.agent_name!r} is not a demo agent. Replay it from its own code with "
            f"--entry path/to/file.py:function"
        )

    replay_id = uuid.uuid4().hex
    session = ReplaySession.from_rows(run_id, store.run_recordings(run_id), replay_id)
    error: Exception | None = None
    with replaying(session):
        try:
            if entry is not None:
                inputs = source.input
                entry(**inputs) if isinstance(inputs, dict) else entry(inputs)
            else:
                settings = _settings(store, run_id)
                run_agent(
                    agents[source.agent_name],
                    llm=replay_llm(),
                    model=source.model or "",
                    user_message=run_message(source),
                    max_steps=settings.get(semconv.RUN_MAX_STEPS) or 10,
                    timeout_s=settings.get(semconv.RUN_TIMEOUT_S),
                    # Same retry limit as the source, but no waiting between recorded failures.
                    retry=RetryPolicy(
                        max_attempts=settings.get(semconv.RUN_MAX_ATTEMPTS) or DEFAULT_MAX_ATTEMPTS,
                        sleep=lambda _: None,
                    ),
                    task_id=source.task_id,
                    run_id=replay_id,
                )
        except Exception as e:
            error = e

    if store.get_run(replay_id) is None:
        raise RuntimeError(
            "The entry point did not start a run; is it decorated with @lab.agent?"
        ) from error

    report = compare(
        store.spans(run_id),
        store.spans(replay_id),
        unused_recordings=len(session.unused()),
        fallbacks=session.fallbacks,
    )
    if isinstance(error, ReplayDivergence):
        report.differences.insert(0, f"diverged: {error}")
    message = f"{type(error).__name__}: {error}" if error else None
    store.set_replay_report(replay_id, asdict(report) | {"error": message})
    return ReplayResult(run_id, replay_id, report, message)


def load_entry(spec: str) -> Callable[..., Any]:
    """`path/to/file.py:function` or `package.module:function` → the function."""
    target, _, name = spec.rpartition(":")
    if not target or not name:
        raise ValueError(f"Expected FILE.py:FUNCTION or MODULE:FUNCTION, got {spec!r}")
    if target.endswith(".py"):
        path = Path(target).resolve()
        module_name = f"agentlab_entry_{path.stem}"
        loader = importlib.util.spec_from_file_location(module_name, path)
        if loader is None or loader.loader is None:
            raise ValueError(f"Can't import {target}")
        module = importlib.util.module_from_spec(loader)
        sys.modules[module_name] = module
        loader.loader.exec_module(module)
    else:
        module = importlib.import_module(target)
    return getattr(module, name)


def _settings(store: Store, run_id: str) -> dict[str, Any]:
    """The run's limits, recorded on its root span (missing for runs before Phase 3)."""
    root = next((s for s in store.spans(run_id) if s.parent_span_id is None), None)
    return root.attributes if root else {}
