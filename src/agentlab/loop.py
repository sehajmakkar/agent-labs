"""The agent loop: call the model, run the tools it asks for, feed the results back, repeat.

This is all an "agent" is mechanically. Frameworks such as LangGraph add structure around it, but
underneath they do the same thing. We keep our own loop so that every model and tool call passes
through code we control (decisions.md D-004).

Each run is traced as a tree: `invoke_agent` → `step N` → the model call and the tool calls it
asked for. A step is one decision by the model plus its consequences, which is the unit a fork
will start from in Phase 4 (decisions.md D-015).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from agentlab import determinism, semconv
from agentlab.llm.base import LLMClient, LLMResponse, Message, ToolCall, ToolResult, Usage
from agentlab.replay.session import InterceptorStop
from agentlab.retry import RetryPolicy, call_with_retries
from agentlab.tools import Tool, describe_error
from agentlab.tracing import agent_run, span

RunStatus = Literal["completed", "max_steps", "timeout"]
DEFAULT_RETRY = RetryPolicy()


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
    attempts: int = 1


@dataclass
class AgentResult:
    answer: str | None
    status: RunStatus
    steps: list[Step]
    messages: list[Message]
    run_id: str | None = None

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
    timeout_s: float | None = None,
    retry: RetryPolicy = DEFAULT_RETRY,
    # Read through the interceptor, so a replay sees the same times and times out at the same step.
    clock: Callable[[], float] = determinism.monotonic,
    task_id: str | None = None,
    run_id: str | None = None,
) -> AgentResult:
    """Run the agent on one message.

    Stops when the model answers without calling a tool ("completed"), after `max_steps` model
    calls ("max_steps"), or when `timeout_s` has passed before a new step starts ("timeout").
    Model errors that survive the retries propagate, and the run is recorded as "error".
    `task_id` links the run to an eval task; `run_id` chooses its ID up front.
    """
    with agent_run(
        agent.name, input={"message": user_message}, model=model, task_id=task_id, run_id=run_id
    ) as agent_span:
        # Recorded so a replay can run with the same limits.
        agent_span.attributes[semconv.RUN_MAX_STEPS] = max_steps
        agent_span.attributes[semconv.RUN_TIMEOUT_S] = timeout_s
        agent_span.attributes[semconv.RUN_MAX_ATTEMPTS] = retry.max_attempts
        result = _loop(agent, llm, model, user_message, max_steps, timeout_s, retry, clock)
        result.run_id = agent_span.run_id
        agent_span.output = {"answer": result.answer}
        agent_span.attributes[semconv.RUN_STATUS] = result.status
        return result


def _loop(
    agent: Agent,
    llm: LLMClient,
    model: str,
    user_message: str,
    max_steps: int,
    timeout_s: float | None,
    retry: RetryPolicy,
    clock: Callable[[], float],
) -> AgentResult:
    tools_by_name = {t.name: t for t in agent.tools}
    messages = [Message.user(user_message)]
    steps: list[Step] = []
    deadline = clock() + timeout_s if timeout_s is not None else None

    for index in range(1, max_steps + 1):
        if deadline is not None and clock() >= deadline:
            return AgentResult(None, "timeout", steps, messages)

        with span("step", f"step {index}", attributes={semconv.STEP_INDEX: index}) as step_span:
            response, attempts = call_with_retries(
                lambda: llm.generate(
                    model=model, system=agent.system_prompt, messages=messages, tools=agent.tools
                ),
                retry,
            )
            step_span.attributes[semconv.LLM_ATTEMPTS] = attempts
            messages.append(response.message)
            results = [_execute(call, tools_by_name) for call in response.message.tool_calls]

        steps.append(Step(index, response, results, attempts))
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
        error = f"Unknown tool: {call.name}"
        attributes = {
            semconv.OPERATION_NAME: "execute_tool",
            semconv.TOOL_NAME: call.name,
            semconv.TOOL_CALL_ID: call.id,
        }
        with span("tool", f"execute_tool {call.name}", input=call.args, attributes=attributes) as s:
            s.error = error
        return ToolResult(call, {"error": error}, is_error=True)
    try:
        output = tool.invoke(call.args, call_id=call.id)
    except InterceptorStop:
        raise  # not the tool's error: a replay diverged, or a fork hit an unsafe write
    except Exception as e:
        return ToolResult(call, {"error": describe_error(e)}, is_error=True)
    return ToolResult(call, output if isinstance(output, dict) else {"result": output})
