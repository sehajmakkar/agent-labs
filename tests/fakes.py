"""Fakes shared by several test modules."""

from agentlab.llm.base import LLMResponse, Message, ToolCall, Usage
from agentlab.loop import Agent
from agentlab.tools import tool


@tool(kind="read")
def lookup(key: str) -> dict:
    """Look a key up."""
    return {"key": key, "value": key.upper()}


AGENT = Agent(name="echo", system_prompt="", tools=[lookup])


class RoutedLLM:
    """Scripted by user message, so tasks running in parallel threads each get their own script."""

    def generate(self, *, model, system, messages, tools, response_schema=None):
        question = messages[0].text
        if question == "crash":
            raise RuntimeError("model exploded")
        if len(messages) == 1:
            call = ToolCall(name="lookup", args={"key": question}, id="c1")
            return LLMResponse(Message(role="model", tool_calls=[call]), Usage(10, 5), "fake")
        value = messages[-1].tool_results[0].output["value"]
        return LLMResponse(Message(role="model", text=f"It is {value}"), Usage(10, 5), "fake")
