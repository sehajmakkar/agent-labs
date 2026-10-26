"""The agent loop: call the model, run the tools it asks for, feed the results back, repeat.

This is all an "agent" is mechanically. Frameworks such as LangGraph add structure around it, but
underneath they do the same thing. We keep our own loop so that every model and tool call passes
through code we control (decisions.md D-004).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from agentlab.llm.base import LLMClient, LLMResponse, Message, ToolCall, ToolResult, Usage
from agentlab.tools import Tool


@dataclass(frozen=True)
class Agent:
    name: str
    system_prompt: str
    tools: list[Tool] = field(default_factory=list)


@dataclass
class Step:
    """One model call plus the tool calls it asked for."""

    index: int
    response: LLMResponse
    tool_results: list[ToolResult]


@dataclass
class AgentResult:
    answer: str | None
    status: Literal["completed", "max_steps"]
    steps: list[Step]
    messages: list[Message]

    @property
    def usage(self) -> Usage:
        return sum((step.response.usage for step in self.steps), Usage())


def run_agent(
    agent: Agent,
    *,
    llm: LLMClient,
    model: str,
    user_message: str,
    max_steps: int = 10,
    on_step: Callable[[Step], None] | None = None,
) -> AgentResult:
    tools_by_name = {t.name: t for t in agent.tools}
    messages = [Message.user(user_message)]
    steps: list[Step] = []

    for index in range(1, max_steps + 1):
        response = llm.generate(
            model=model, system=agent.system_prompt, messages=messages, tools=agent.tools
        )
        messages.append(response.message)

        results = [_execute(call, tools_by_name) for call in response.message.tool_calls]
        step = Step(index=index, response=response, tool_results=results)
        steps.append(step)
        if on_step:
            on_step(step)

        # No tool calls means the model has given its final answer.
        if not results:
            return AgentResult(response.message.text, "completed", steps, messages)
        messages.append(Message.tool(results))

    return AgentResult(None, "max_steps", steps, messages)


def _execute(call: ToolCall, tools_by_name: dict[str, Tool]) -> ToolResult:
    """Run one tool call. Failures go back to the model as data so it can react to them.

    A tool error must never crash the loop: noticing and handling errors is part of the agent's job,
    and an agent that ignores them is exactly the kind of failure this lab exists to catch.
    """
    tool = tools_by_name.get(call.name)
    if tool is None:
        return ToolResult(call, {"error": f"Unknown tool: {call.name}"}, is_error=True)
    try:
        output = tool.invoke(call.args)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
        )
        return ToolResult(call, {"error": f"Invalid arguments: {problems}"}, is_error=True)
    except Exception as e:
        return ToolResult(call, {"error": f"{type(e).__name__}: {e}"}, is_error=True)
    return ToolResult(call, output if isinstance(output, dict) else {"result": output})
