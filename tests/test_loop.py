from agentlab.llm.base import LLMResponse, Message, ToolCall, Usage
from agentlab.loop import Agent, run_agent
from agentlab.tools import tool


class ScriptedLLM:
    """Returns pre-written responses in order and records what it was sent."""

    def __init__(self, *messages: Message):
        self.responses = [LLMResponse(m, Usage(10, 5, 1), "fake") for m in messages]
        self.calls: list[list[Message]] = []

    def generate(self, *, model, system, messages, tools):
        self.calls.append(list(messages))
        return self.responses.pop(0)


def calls(*tool_calls: ToolCall) -> Message:
    return Message(role="model", tool_calls=list(tool_calls))


def answer(text: str) -> Message:
    return Message(role="model", text=text)


@tool(kind="read")
def get_order(order_id: str) -> dict:
    """Look up an order."""
    if order_id != "4417":
        raise LookupError(f"No order with ID {order_id}")
    return {"order_id": order_id, "status": "delivered"}


AGENT = Agent(name="test", system_prompt="be helpful", tools=[get_order])


def run(llm, max_steps=10):
    return run_agent(
        AGENT, llm=llm, model="fake", user_message="where is 4417?", max_steps=max_steps
    )


def test_tool_result_is_fed_back_and_answer_returned():
    llm = ScriptedLLM(
        calls(ToolCall("get_order", {"order_id": "4417"}, id="c1")), answer("Delivered.")
    )
    result = run(llm)

    assert result.status == "completed"
    assert result.answer == "Delivered."
    assert len(result.steps) == 2
    second_request = llm.calls[1]
    assert [m.role for m in second_request] == ["user", "model", "tool"]
    tool_result = second_request[-1].tool_results[0]
    assert tool_result.output == {"order_id": "4417", "status": "delivered"}
    assert tool_result.call.id == "c1"


def test_usage_is_summed_across_steps():
    llm = ScriptedLLM(calls(ToolCall("get_order", {"order_id": "4417"})), answer("ok"))
    assert run(llm).usage == Usage(20, 10, 2)


def test_tool_exception_goes_back_to_model_as_error():
    llm = ScriptedLLM(calls(ToolCall("get_order", {"order_id": "9999"})), answer("Not found."))
    result = run(llm)
    tool_result = result.steps[0].tool_results[0]
    assert tool_result.is_error
    assert tool_result.output == {"error": "LookupError: No order with ID 9999"}
    assert result.status == "completed"


def test_unknown_tool_and_invalid_args_are_errors_not_crashes():
    llm = ScriptedLLM(
        calls(ToolCall("refund", {"payment_id": "P-1"}), ToolCall("get_order", {})),
        answer("Sorry."),
    )
    unknown, invalid = run(llm).steps[0].tool_results
    assert unknown.output == {"error": "Unknown tool: refund"}
    assert invalid.is_error and invalid.output["error"].startswith("Invalid arguments: order_id")


def test_stops_after_max_steps():
    looping = [calls(ToolCall("get_order", {"order_id": "4417"})) for _ in range(3)]
    result = run(ScriptedLLM(*looping), max_steps=3)
    assert result.status == "max_steps"
    assert result.answer is None
    assert len(result.steps) == 3
