from agentlab.llm.base import LLMResponse, Message, ToolCall, Usage
from agentlab.loop import Agent, run_agent
from agentlab.render import render_run
from agentlab.tools import tool


@tool(kind="read")
def get_order(order_id: str) -> dict:
    """Look up an order."""
    raise LookupError(f"No order with ID {order_id}")


class OneCallLLM:
    def __init__(self):
        self.replies = [
            Message(role="model", tool_calls=[ToolCall("get_order", {"order_id": "9999"})]),
            Message(role="model", text="I couldn't find that order."),
        ]

    def generate(self, **kwargs):
        return LLMResponse(self.replies.pop(0), Usage(10, 5), "fake")


def test_tree_shows_steps_tools_and_errors(store):
    agent = Agent(name="support", system_prompt="", tools=[get_order])
    result = run_agent(agent, llm=OneCallLLM(), model="fake", user_message="where is 9999?")
    run = store.find_run(result.run_id)
    lines = render_run(run, store.spans(run.id)).splitlines()

    assert lines[0].startswith(f"run {run.id[:8]} · support · fake · completed")
    assert lines[1].startswith("└─ invoke_agent support")
    assert any(line.strip().startswith("├─ step 1") for line in lines)
    assert any("execute_tool get_order" in line and "✗" in line for line in lines)
    assert any('args {"order_id": "9999"}' in line for line in lines)
    assert any("✗ LookupError: No order with ID 9999" in line for line in lines)
    assert any(line.strip().startswith("└─ step 2") for line in lines)
