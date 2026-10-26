import pytest

from agentlab import semconv
from agentlab.llm.base import LLMResponse, Message, ToolCall, TransientLLMError, Usage
from agentlab.loop import Agent, run_agent
from agentlab.retry import RetryPolicy
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


class FlakyLLM(ScriptedLLM):
    """Fails with a transient error a set number of times before each scripted response."""

    def __init__(self, failures: int, *messages: Message):
        super().__init__(*messages)
        self.failures = failures

    def generate(self, **kwargs):
        if self.failures:
            self.failures -= 1
            raise TransientLLMError("503 overloaded")
        return super().generate(**kwargs)


NO_WAIT = RetryPolicy(max_attempts=3, sleep=lambda seconds: None)


def test_run_is_traced_as_agent_step_tool_tree(store):
    llm = ScriptedLLM(
        calls(ToolCall("get_order", {"order_id": "4417"}), ToolCall("cancel", {})),
        answer("Delivered."),
    )
    result = run(llm)

    run_row = store.find_run(result.run_id)
    assert (run_row.status, run_row.output) == ("completed", {"answer": "Delivered."})
    spans = store.spans(result.run_id)
    by_id = {s.id: s for s in spans}
    tree = [(s.name, by_id[s.parent_span_id].name if s.parent_span_id else None) for s in spans]
    assert tree == [
        ("invoke_agent test", None),
        ("step 1", "invoke_agent test"),
        ("execute_tool get_order", "step 1"),
        ("execute_tool cancel", "step 1"),
        ("step 2", "invoke_agent test"),
    ]
    unknown = spans[3]
    assert unknown.error == "Unknown tool: cancel"


def test_transient_errors_are_retried_and_counted(store):
    result = run_agent(
        AGENT, llm=FlakyLLM(2, answer("ok")), model="fake", user_message="hi", retry=NO_WAIT
    )
    assert result.answer == "ok"
    assert result.steps[0].attempts == 3
    step = store.spans(result.run_id)[1]
    assert step.attributes[semconv.LLM_ATTEMPTS] == 3


def test_run_fails_when_retries_run_out(store):
    with pytest.raises(TransientLLMError):
        run_agent(
            AGENT, llm=FlakyLLM(5, answer("ok")), model="fake", user_message="hi", retry=NO_WAIT
        )
    (run_row,) = store.runs()
    assert run_row.status == "error"
    assert run_row.error == "TransientLLMError: 503 overloaded"


def test_run_stops_when_time_is_up(store):
    ticks = iter([0, 10, 100])  # start, before step 1, before step 2
    llm = ScriptedLLM(calls(ToolCall("get_order", {"order_id": "4417"})), answer("never reached"))
    result = run_agent(
        AGENT,
        llm=llm,
        model="fake",
        user_message="hi",
        timeout_s=50,
        clock=lambda: next(ticks),
    )
    assert result.status == "timeout"
    assert len(result.steps) == 1
    assert store.find_run(result.run_id).status == "timeout"
