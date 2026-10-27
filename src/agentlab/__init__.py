"""Agent Reliability Lab SDK.

import agentlab as lab
from google import genai

lab.init(".agentlab/lab.db")          # start saving runs to the trace store
client = lab.wrap(genai.Client())     # every model call becomes a traced, recorded span

@lab.tool(kind="read")
def get_order(order_id: str) -> dict: ...

@lab.agent("support")                 # each call becomes a run
def support_agent(message: str) -> str: ...

Read the clock and random numbers through `lab.now()`, `lab.monotonic()` and `lab.random()`, so
that `lab replay` can reproduce a run exactly.
"""

from typing import Any

from agentlab.determinism import monotonic, now, random
from agentlab.tools import tool
from agentlab.tracing import agent, init, shutdown, span

__all__ = ["agent", "init", "monotonic", "now", "random", "shutdown", "span", "tool", "wrap"]


def wrap(client: Any) -> Any:
    """Return a traced stand-in for a model client. Only `google.genai.Client` for now."""
    from google import genai

    from agentlab.llm.gemini import wrap_genai_client

    if isinstance(client, genai.Client):
        return wrap_genai_client(client)
    raise TypeError(f"Don't know how to trace a {type(client).__name__}; expected genai.Client")
