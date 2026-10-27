import pytest
from fakes import fake_genai, gemini_response
from fastapi.testclient import TestClient

import agentlab as lab
from agentlab.diff import diff_runs
from agentlab.diff.align import align, args_similarity, similarity
from agentlab.diff.report import word_diff
from agentlab.diff.steps import StepView, ToolCallView, extract_steps
from agentlab.llm.gemini import GeminiClient, wrap_genai_client
from agentlab.loop import Agent, run_agent
from agentlab.retry import RetryPolicy
from agentlab.server import create_app
from agentlab.tools import tool


def step(index, *calls, text=None):
    return StepView(index, f"s{index}", [ToolCallView(n, a, o) for n, a, o in calls], text=text)


LOOKUP = ("get_order", {"order_id": "4417"}, {"status": "delivered"})
PAYMENTS = ("get_payments", {"order_id": "4417"}, {"payments": 2})
REFUND = ("refund_payment", {"payment_id": "P-902"}, {"refund_id": "RF-1001"})


def statuses(rows):
    return [r.status for r in rows]


def test_identical_runs_align_as_all_same():
    a = [step(1, LOOKUP), step(2, text="Delivered.")]
    rows = align(a, a)
    assert statuses(rows) == ["same", "same"]


def test_an_extra_step_shows_as_added_not_as_everything_shifting():
    a = [step(1, LOOKUP), step(2, REFUND), step(3, text="Refunded.")]
    b = [step(1, LOOKUP), step(2, PAYMENTS), step(3, REFUND), step(4, text="Refunded.")]
    # B verifies the payments before refunding; the steps after it still line up.
    assert statuses(align(a, b)) == ["same", "added", "same", "same"]


def test_a_skipped_step_shows_as_removed():
    a = [step(1, LOOKUP), step(2, PAYMENTS), step(3, text="Done.")]
    b = [step(1, LOOKUP), step(2, text="Done.")]
    assert statuses(align(a, b)) == ["same", "removed", "same"]


def test_same_tool_with_different_arguments_is_a_change_with_details():
    a = [step(1, LOOKUP)]
    b = [step(1, ("get_order", {"order_id": "4471"}, {"status": "shipped"}))]
    (row,) = align(a, b)
    assert row.status == "changed"
    assert row.notes == ["get_order: order_id '4417' → '4471'"]
    assert 0.5 <= row.similarity < 1  # same tool, every argument different


def test_different_kinds_of_step_are_described():
    (row,) = align([step(1, LOOKUP)], [step(1, text="I can't help.")])
    assert row.notes == ["A calls get_order; B answers"]
    (row,) = align([step(1, LOOKUP)], [step(1, ("get_order", {"order_id": "4417"}, {"x": 1}))])
    assert row.notes == ["get_order: same call, different result"]


def test_similarity_measures():
    assert similarity(step(1, LOOKUP), step(1, LOOKUP)) == 1.0
    assert similarity(step(1, LOOKUP), step(1, text="x")) == 0.0
    assert (
        similarity(
            step(1, text="the refund is on its way"), step(1, text="the refund is on its way now")
        )
        > 0.8
    )
    assert args_similarity({"a": 1, "b": 2}, {"a": "1", "b": 3}) == 0.5


def test_word_diff_keeps_equal_deleted_and_inserted_words():
    parts = word_diff("Your refund is on its way.", "Your refund RF-1001 is on its way.")
    assert "".join(p["text"] for p in parts if p["op"] != "insert") == "Your refund is on its way."
    assert (
        "".join(p["text"] for p in parts if p["op"] != "delete")
        == "Your refund RF-1001 is on its way."
    )
    assert {"op": "insert", "text": "RF-1001 "} in parts or any(
        p["op"] == "insert" and "RF-1001" in p["text"] for p in parts
    )


# Diffs of real stored runs


@tool(kind="read")
def get_order(order_id: str) -> dict:
    """Look up an order."""
    return {"order_id": order_id, "status": "delivered"}


AGENT = Agent("shop", "Be helpful.", [get_order])


def record(*responses) -> str:
    llm = GeminiClient(client=wrap_genai_client(fake_genai(*responses)))
    return run_agent(
        AGENT,
        llm=llm,
        model="m",
        user_message="Where is 4417?",
        retry=RetryPolicy(sleep=lambda _: None),
    ).run_id


def call(order_id):
    return gemini_response(
        [{"function_call": {"name": "get_order", "args": {"order_id": order_id}}}]
    )


def test_diff_of_stored_runs_finds_the_divergence_and_the_effects(store):
    a = record(call("4417"), gemini_response([{"text": "It was delivered."}]))
    b = record(call("4417"), call("4471"), gemini_response([{"text": "Both were delivered."}]))

    d = diff_runs(store, a, b)

    assert statuses(d.rows) == ["same", "added", "changed"]
    assert d.divergence.summary.startswith("step 2: only in B: get_order(order_id='4471')")
    assert (d.divergence.a_step, d.divergence.b_step) == (None, 2)
    assert (d.a.steps, d.b.steps) == (2, 3)
    assert "steps 2 → 3" in d.effects()
    assert d.b.tokens > d.a.tokens


def test_steps_of_an_agent_with_its_own_loop(store):
    client = wrap_genai_client(fake_genai(call("4417"), gemini_response([{"text": "Delivered."}])))

    @lab.agent("own-loop")
    def answer(question: str) -> str:
        first = client.models.generate_content(model="m", contents=question, config=None)
        get_order.invoke(dict(first.candidates[0].content.parts[0].function_call.args))
        return client.models.generate_content(model="m", contents="next", config=None).text

    answer("Where is 4417?")
    steps = extract_steps(store.spans(store.runs(1)[0].id))
    assert [s.kind for s in steps] == ["tools", "answer"]
    assert steps[0].calls[0].output == {"order_id": "4417", "status": "delivered"}


def test_diff_api(store):
    a = record(call("4417"), gemini_response([{"text": "It was delivered."}]))
    b = record(call("4417"), gemini_response([{"text": "It was delivered yesterday."}]))
    client = TestClient(create_app(store, ui_dist=None))

    body = client.get("/api/diff", params={"a": a[:8], "b": b}).json()
    assert [r["status"] for r in body["rows"]] == ["same", "changed"]
    assert body["rows"][0]["a"]["label"] == "get_order(order_id='4417')"
    assert body["divergence"]["b_step"] == 2
    assert any(p["op"] == "insert" for p in body["answer_diff"])
    assert client.get("/api/diff", params={"a": "nope", "b": b}).status_code == 404


def test_identical_runs_have_no_divergence(store):
    a = record(call("4417"), gemini_response([{"text": "Delivered."}]))
    b = record(call("4417"), gemini_response([{"text": "Delivered."}]))
    d = diff_runs(store, a, b)
    assert d.identical and d.divergence is None


@pytest.mark.parametrize("gap_steps", [1, 3])
def test_long_insertions_stay_aligned(gap_steps):
    a = [step(1, LOOKUP), step(2, text="Done.")]
    b = (
        [step(1, LOOKUP)]
        + [step(i + 2, PAYMENTS) for i in range(gap_steps)]
        + [step(gap_steps + 2, text="Done.")]
    )
    assert statuses(align(a, b)) == ["same"] + ["added"] * gap_steps + ["same"]


def test_an_argument_given_on_one_side_only_is_named_as_such():
    a = [step(1, ("search_logs", {"service": "checkout", "query": "error"}, {}))]
    b = [step(1, ("search_logs", {"service": "checkout"}, {}))]
    (row,) = align(a, b)
    assert row.notes == ["search_logs: query 'error' → (not given)"]
