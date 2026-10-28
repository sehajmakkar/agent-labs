"""`lab worker`: claim queued fork jobs and run them, here, with this code.

The lab never runs a customer's agent itself (decisions.md D-009): it can't, because the agent's
code, tools and API keys live in the customer's repo. A fork is therefore a *job*. The UI queues
it; a worker started inside the customer's repo claims it, runs it with the real agent code, and
sends the runs back. With `--server`, the worker reaches the lab over HTTP (`RemoteStore`);
without it, the worker and the lab share one local database.
"""

import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from agentlab.evals.judge import LLMJudge
from agentlab.evals.tasks import Task
from agentlab.fork.runner import execute_fork
from agentlab.llm.gemini import GeminiClient
from agentlab.loop import Agent
from agentlab.store import Store


def work(
    store: Store,
    *,
    llm: GeminiClient,
    agents: dict[str, Agent] | None = None,
    entry: Callable[..., Any] | None = None,
    judge: LLMJudge | None = None,
    tasks: dict[str, Task] | None = None,
    poll_s: float = 2.0,
    once: bool = False,
    stop: threading.Event | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Run fork jobs until `stop` is set (or after one job, with `once`). Returns how many ran."""
    names = [entry.agent_name] if entry is not None else sorted(agents or {})
    name = f"{socket.gethostname()}:{threading.get_ident()}"
    done = 0
    while not (stop and stop.is_set()):
        fork = store.claim_fork(names, worker=name)
        if fork is None:
            blame = store.claim_blame(names, worker=name) if hasattr(store, "claim_blame") else None
            if blame is not None:
                _run_blame(
                    store,
                    blame,
                    llm=llm,
                    agents=agents,
                    entry=entry,
                    judge=judge,
                    tasks=tasks,
                    log=log,
                )
                done += 1
                if once:
                    return done
                continue
            if once:
                return done
            time.sleep(poll_s)
            continue
        log(
            f"fork {fork.id[:8]}: {fork.label}, {fork.n} runs"
            + (" + control" if fork.control else "")
        )
        try:
            summary = execute_fork(
                store,
                fork,
                llm=llm,
                agents=agents,
                entry=entry,
                judge=judge,
                tasks=tasks,
                on_run=lambda role, r: log(f"  {role:7} {r['run_id'][:8]} {_mark(r)}"),
            )
            store.finish_fork(fork.id, summary=summary)
            log(f"fork {fork.id[:8]} done: {summary['verdict']}")
        except Exception as e:
            store.finish_fork(fork.id, error=f"{type(e).__name__}: {e}")
            log(f"fork {fork.id[:8]} failed: {e}")
        done += 1
        if once:
            return done
    return done


def _mark(result: dict[str, Any]) -> str:
    if result["passed"] is None:
        return result["status"]
    return "✓" if result["passed"] else f"✗ {result['category']}"


def _run_blame(store: Store, blame: Any, *, log: Callable[[str], None], **context: Any) -> None:
    from agentlab.blame.propose import BlameJudge
    from agentlab.blame.runner import execute_blame

    log(f"blame {blame.id[:8]} for run {blame.source_run_id[:8]}")
    try:
        report = execute_blame(
            store,
            blame,
            blame_judge=BlameJudge(context["llm"], blame.judge_model),
            tasks=context["tasks"] or {},
            fork_context=context,
        )
        store.finish_blame(blame.id, report=report)
        log(f"blame {blame.id[:8]} done: {report['verdict']}")
    except Exception as e:
        store.finish_blame(blame.id, error=f"{type(e).__name__}: {e}")
        log(f"blame {blame.id[:8]} failed: {e}")
