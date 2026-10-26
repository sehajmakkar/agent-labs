import pytest

import agentlab as lab
from agentlab import semconv
from agentlab.tracing import agent_run, request_hash, span


def test_spans_nest_under_the_span_open_around_them(store):
    with agent_run("a", input={"message": "hi"}):
        with span("step", "step 1"):
            with span("tool", "execute_tool t"):
                pass
        with span("step", "step 2"):
            pass

    (run,) = store.runs()
    agent, step1, tool, step2 = store.spans(run.id)
    assert [s.name for s in (agent, step1, tool, step2)] == [
        "invoke_agent a",
        "step 1",
        "execute_tool t",
        "step 2",
    ]
    assert agent.parent_span_id is None
    assert step1.parent_span_id == agent.id
    assert tool.parent_span_id == step1.id
    assert step2.parent_span_id == agent.id
    assert agent.attributes[semconv.AGENT_NAME] == "a"


def test_run_records_input_output_and_status(store):
    with agent_run("a", input={"message": "hi"}) as s:
        s.output = {"answer": "hello"}
        s.attributes[semconv.RUN_STATUS] = "max_steps"

    (run,) = store.runs()
    assert run.input == {"message": "hi"}
    assert run.output == {"answer": "hello"}
    assert run.status == "max_steps"
    assert run.ended_at is not None


def test_exception_marks_span_and_run_as_error(store):
    with pytest.raises(ValueError):
        with agent_run("a"):
            with span("step", "step 1"):
                raise ValueError("boom")

    (run,) = store.runs()
    assert run.status == "error"
    assert run.error == "ValueError: boom"
    assert all(s.status == "error" for s in store.spans(run.id))


def test_nothing_is_saved_without_init(tmp_path):
    with agent_run("a"):
        with span("step", "step 1") as s:
            assert s.run_id is None


def test_recordings_are_saved_with_a_stable_hash(store):
    with agent_run("a"):
        with span("tool", "execute_tool t") as s:
            s.record({"tool": "t", "args": {"b": 1, "a": 2}}, {"output": 3})

    tool_span = store.spans(store.runs()[0].id)[1]
    (recording,) = store.recordings(tool_span.id)
    assert recording.response == {"output": 3}
    # Key order doesn't change the hash, so the same request always matches its recording.
    assert recording.request_hash == request_hash({"args": {"a": 2, "b": 1}, "tool": "t"})


def test_agent_decorator_turns_each_call_into_a_run(store):
    @lab.agent("echo")
    def echo(message: str) -> str:
        return message.upper()

    assert echo("hi") == "HI"
    (run,) = store.runs()
    assert (run.agent_name, run.input, run.output, run.status) == (
        "echo",
        {"message": "hi"},
        "HI",
        "completed",
    )


def test_tool_calls_are_traced_and_recorded(store):
    @lab.tool(kind="write")
    def refund(payment_id: str) -> dict:
        """Refund a payment."""
        if payment_id == "bad":
            raise LookupError("no such payment")
        return {"refunded": payment_id}

    with agent_run("a"):
        refund("P-1")
        with pytest.raises(LookupError):
            refund.invoke({"payment_id": "bad"}, call_id="c2")

    _, ok, failed = store.spans(store.runs()[0].id)
    assert (ok.name, ok.input, ok.output, ok.status) == (
        "execute_tool refund",
        {"payment_id": "P-1"},
        {"refunded": "P-1"},
        "ok",
    )
    assert ok.attributes[semconv.TOOL_KIND] == "write"
    assert failed.error == "LookupError: no such payment"
    assert failed.attributes[semconv.TOOL_CALL_ID] == "c2"
    assert store.recordings(failed.id)[0].response == {"error": "LookupError: no such payment"}
