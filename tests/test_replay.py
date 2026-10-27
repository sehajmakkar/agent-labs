import sqlite3

import pytest
from fakes import fake_genai, gemini_response
from google.genai import errors

import agentlab as lab
from agentlab import semconv
from agentlab.llm.gemini import GeminiClient, wrap_genai_client
from agentlab.loop import Agent, run_agent
from agentlab.replay.runner import replay_run
from agentlab.replay.session import json_differences
from agentlab.retry import RetryPolicy
from agentlab.store import Store
from agentlab.tools import tool

CALLS = {"lookup": 0, "refund": 0}


@tool(kind="read")
def lookup(order_id: str) -> dict:
    """Look an order up."""
    CALLS["lookup"] += 1
    if order_id == "missing":
        raise LookupError("No order with ID missing")
    return {"order_id": order_id, "status": "delivered"}


@tool(kind="write")
def refund(payment_id: str) -> dict:
    """Refund a payment."""
    CALLS["refund"] += 1
    return {"refund_id": "RF-1", "payment_id": payment_id}


AGENT = Agent(name="shop", system_prompt="Be helpful.", tools=[lookup, refund])
NO_WAIT = RetryPolicy(max_attempts=4, sleep=lambda _: None)


def call(name: str, args: dict, call_id: str, signature: bytes | None = None) -> dict:
    part = {"function_call": {"id": call_id, "name": name, "args": args}}
    if signature:
        part["thought_signature"] = signature
    return part


def record(*responses, agent=AGENT, message="Refund order 1", timeout_s=None) -> str:
    """Run the agent live against a fake Gemini that returns `responses`; return the run's ID."""
    llm = GeminiClient(client=wrap_genai_client(fake_genai(*responses)))
    result = run_agent(
        agent, llm=llm, model="m", user_message=message, retry=NO_WAIT, timeout_s=timeout_s
    )
    return result.run_id


def scripted_run():
    """Thinking, a parallel read and write call with a thought signature, then an answer."""
    return (
        gemini_response(
            [
                {"text": "The user wants a refund.", "thought": True},
                call("lookup", {"order_id": "1"}, "c1", signature=b"\x00\x01sig\xff"),
                call("refund", {"payment_id": "P-1"}, "c2"),
            ]
        ),
        gemini_response([{"text": "Refunded P-1 for order 1."}]),
    )


@pytest.fixture(autouse=True)
def reset_calls():
    CALLS.update(lookup=0, refund=0)


def test_replay_reproduces_the_run_exactly_without_calling_anything(store):
    source = record(*scripted_run())
    assert CALLS == {"lookup": 1, "refund": 1}

    result = replay_run(store, source, agents={"shop": AGENT})

    assert result.error is None
    assert result.report.identical, result.report.differences
    # No tool ran again, the write tool included; the offline client would have raised on any
    # model call that wasn't served from the recording.
    assert CALLS == {"lookup": 1, "refund": 1}
    replay = store.get_run(result.run_id)
    assert (replay.mode, replay.parent_run_id) == ("replay", source)
    assert replay.replay_report["identical"] is True
    assert store.run_totals([result.run_id])[result.run_id].cost_usd == 0


def test_thought_signatures_survive_so_the_second_request_matches_byte_for_byte(store):
    source = record(*scripted_run())
    result = replay_run(store, source, agents={"shop": AGENT})

    def second_request(run_id):
        llm_recordings = [r for r in store.run_recordings(run_id) if r.kind == "llm"]
        return llm_recordings[1]

    original, replayed = second_request(source), second_request(result.run_id)
    # The model turn inside the second request carries the signature, base64-encoded in JSON.
    assert "thought_signature" in str(original.request)
    assert replayed.request_hash == original.request_hash


def test_recorded_tool_errors_are_raised_again_with_the_same_text(store):
    source = record(
        gemini_response([call("lookup", {"order_id": "missing"}, "c1")]),
        gemini_response([{"text": "I couldn't find that order."}]),
    )
    result = replay_run(store, source, agents={"shop": AGENT})
    assert result.report.identical, result.report.differences
    tool = next(s for s in store.spans(result.run_id) if s.kind == "tool")
    assert tool.error == "LookupError: No order with ID missing"


def test_retries_replay_as_the_same_failures(store):
    overloaded = errors.ServerError(503, {"error": {"code": 503, "message": "overloaded"}})
    source = record(overloaded, overloaded, gemini_response([{"text": "Done."}]))
    step = next(s for s in store.spans(source) if s.kind == "step")
    assert step.attributes[semconv.LLM_ATTEMPTS] == 3

    result = replay_run(store, source, agents={"shop": AGENT})
    assert result.report.identical, result.report.differences


def test_a_changed_prompt_diverges_and_says_where(store):
    source = record(*scripted_run())
    changed = Agent(name="shop", system_prompt="Be terse.", tools=[lookup, refund])

    result = replay_run(store, source, agents={"shop": changed})

    assert not result.report.identical
    assert result.error.startswith("ReplayDivergence")
    assert "$.config.system_instruction" in result.report.differences[0]
    assert store.get_run(result.run_id).status == "error"
    assert CALLS["refund"] == 1  # still never re-executed


def test_timeouts_replay_from_the_recorded_clock(store):
    times = iter([0.0, 1.0, 999.0])  # start, before step 1, before step 2 (past the deadline)

    def clock():
        return next(times)

    # Record with a fake clock read through the interceptor, as the default clock is.
    from agentlab import determinism

    original = determinism.time.monotonic
    determinism.time.monotonic = clock
    try:
        source = record(
            gemini_response([call("lookup", {"order_id": "1"}, "c1")]),
            timeout_s=10,
        )
    finally:
        determinism.time.monotonic = original
    assert store.get_run(source).output == {"answer": None}

    result = replay_run(store, source, agents={"shop": AGENT})
    assert result.report.identical, result.report.differences
    assert result.report.fallbacks == {}


def test_entry_points_replay_clock_and_random_too(store):
    client = wrap_genai_client(fake_genai(gemini_response([{"text": "Sunny"}])))

    @lab.agent("weather")
    def answer(question: str) -> str:
        today = lab.now().date().isoformat()
        response = client.models.generate_content(
            model="m", contents=f"Today is {today}. {question}", config=None
        )
        return f"{response.text} (ticket {lab.random():.6f})"

    answer("Rain?")
    source = store.runs(1)[0]

    # The fake client is now empty: any real call during the replay would fail.
    result = replay_run(store, source.id, entry=answer)
    assert result.report.identical, result.report.differences
    assert store.get_run(result.run_id).output == source.output


def test_runs_without_clock_recordings_fall_back_and_say_so(store):
    source = record(gemini_response([{"text": "Hi"}]), timeout_s=10)
    with sqlite3.connect(store.engine.url.database) as db:
        db.execute("DELETE FROM recordings WHERE kind = 'clock'")  # as recorded before Phase 3

    result = replay_run(store, source, agents={"shop": AGENT})
    assert result.report.identical
    assert result.report.fallbacks == {"clock": 2}
    assert "live values used" in result.report.summary()


def test_unknown_agents_need_an_entry_point(store):
    @lab.agent("custom")
    def custom(message: str) -> str:
        return "ok"

    custom("hi")
    with pytest.raises(LookupError, match="--entry"):
        replay_run(store, store.runs(1)[0].id, agents={})


def test_json_differences_names_paths():
    assert json_differences({"a": 1, "b": [1, 2]}, {"a": 1, "b": [1, 2]}) == []
    assert json_differences({"a": {"x": 1}}, {"a": {"x": 2}}) == ["$.a.x"]
    assert json_differences({"l": [1]}, {"l": [1, 2]}) == ["$.l (length 1 → 2)"]
    assert json_differences({"a": 1}, {"b": 1}) == ["$.a", "$.b"]


def test_old_databases_gain_new_columns(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE runs (id VARCHAR PRIMARY KEY, agent_name VARCHAR NOT NULL)")
        db.execute("INSERT INTO runs VALUES ('r1', 'support')")
    Store(path)
    with sqlite3.connect(path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
        kept = db.execute("SELECT agent_name FROM runs").fetchall()
    assert {"mode", "replay_report", "parent_run_id"} <= columns
    assert kept == [("support",)]
