from types import SimpleNamespace

import pytest
from google.genai import errors, types

from agentlab import semconv
from agentlab.llm.base import Message, ToolCall, ToolResult, TransientLLMError, Usage
from agentlab.llm.gemini import GeminiClient, from_response, to_contents, wrap_genai_client
from agentlab.tools import tool
from agentlab.tracing import agent_run


@tool(kind="read")
def get_order(order_id: str) -> dict:
    """Look up an order."""
    return {}


def gemini_response(parts: list[dict]) -> types.GenerateContentResponse:
    return types.GenerateContentResponse.model_validate(
        {
            "candidates": [{"content": {"role": "model", "parts": parts}}],
            "usage_metadata": {
                "prompt_token_count": 40,
                "candidates_token_count": 12,
                "thoughts_token_count": 30,
            },
        }
    )


def test_from_response_reads_calls_text_and_usage_and_skips_thoughts():
    response = gemini_response(
        [
            {"text": "Let me think about this...", "thought": True},
            {"text": "Checking."},
            {"function_call": {"id": "c1", "name": "get_order", "args": {"order_id": "4417"}}},
        ]
    )
    result = from_response(response, "m")

    assert result.message.text == "Checking."
    assert result.message.tool_calls == [ToolCall("get_order", {"order_id": "4417"}, id="c1")]
    assert result.usage == Usage(input_tokens=40, output_tokens=12, thinking_tokens=30)


def test_model_turn_is_resent_unchanged_including_thought_signature():
    response = gemini_response(
        [{"function_call": {"name": "get_order", "args": {}}, "thought_signature": b"sig"}]
    )
    model_message = from_response(response, "m").message

    contents = to_contents([Message.user("hi"), model_message])
    assert contents[1] is model_message.raw
    assert contents[1].parts[0].thought_signature == b"sig"


def test_tool_results_become_function_responses_matched_by_id():
    call = ToolCall("get_order", {"order_id": "4417"}, id="c1")
    contents = to_contents([Message.tool([ToolResult(call, {"status": "delivered"})])])

    (part,) = contents[0].parts
    assert contents[0].role == "user"
    assert part.function_response.id == "c1"
    assert part.function_response.name == "get_order"
    assert part.function_response.response == {"status": "delivered"}


def test_generate_sends_declarations_and_disables_automatic_calling():
    sent = {}

    def generate_content(**kwargs):
        sent.update(kwargs)
        return gemini_response([{"text": "hello"}])

    fake = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    result = GeminiClient(client=fake).generate(
        model="m", system="be brief", messages=[Message.user("hi")], tools=[get_order]
    )

    config = sent["config"]
    assert result.message.text == "hello"
    assert config.system_instruction == "be brief"
    assert config.automatic_function_calling.disable is True
    (declaration,) = config.tools[0].function_declarations
    assert declaration.name == "get_order"
    assert declaration.parameters_json_schema["required"] == ["order_id"]


def fake_genai(*responses):
    """A stand-in for genai.Client that returns the given responses in order."""
    queue = list(responses)

    def generate_content(**kwargs):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


def test_wrapped_client_traces_and_records_each_call(store):
    response = gemini_response(
        [
            {"function_call": {"id": "c1", "name": "get_order", "args": {"order_id": "4417"}}},
        ]
    )
    client = GeminiClient(client=wrap_genai_client(fake_genai(response)))

    with agent_run("a"):
        client.generate(
            model="gemini-3.5-flash-lite",
            system="s",
            messages=[Message.user("hi")],
            tools=[get_order],
        )

    _, llm = store.spans(store.runs()[0].id)
    assert llm.name == "chat gemini-3.5-flash-lite"
    assert llm.output == {
        "text": None,
        "tool_calls": [{"name": "get_order", "args": {"order_id": "4417"}}],
    }
    assert (llm.input_tokens, llm.output_tokens, llm.thinking_tokens) == (40, 12, 30)
    # 40 input tokens at $0.30/M plus (12 + 30) output tokens at $2.50/M.
    assert llm.cost_usd == pytest.approx((40 * 0.30 + 42 * 2.50) / 1_000_000)
    assert llm.attributes[semconv.PROVIDER_NAME] == "gcp.gemini"
    assert llm.attributes[semconv.USAGE_OUTPUT_TOKENS] == 42
    assert llm.attributes[semconv.USAGE_REASONING_OUTPUT_TOKENS] == 30

    (recording,) = store.recordings(llm.id)
    assert recording.request["model"] == "gemini-3.5-flash-lite"
    assert recording.request["contents"][0]["parts"][0]["text"] == "hi"
    assert recording.request["config"]["system_instruction"] == "s"


def test_recorded_response_round_trips_thought_signatures(store):
    response = gemini_response(
        [{"function_call": {"name": "get_order", "args": {}}, "thought_signature": b"\x00\xffsig"}]
    )
    client = GeminiClient(client=wrap_genai_client(fake_genai(response)))
    with agent_run("a"):
        client.generate(model="m", system="s", messages=[Message.user("hi")], tools=[])

    llm = store.spans(store.runs()[0].id)[1]
    (recording,) = store.recordings(llm.id)
    restored = types.GenerateContentResponse.model_validate(recording.response)
    assert restored.candidates[0].content.parts[0].thought_signature == b"\x00\xffsig"


def test_overload_becomes_a_transient_error(store):
    overloaded = errors.ServerError(503, {"error": {"code": 503, "message": "overloaded"}})
    client = GeminiClient(client=wrap_genai_client(fake_genai(overloaded)))

    with pytest.raises(TransientLLMError, match="503"), agent_run("a"):
        client.generate(model="m", system="s", messages=[Message.user("hi")], tools=[])

    llm = store.spans(store.runs()[0].id)[1]
    assert llm.status == "error"


def test_bad_request_is_not_retried():
    bad = errors.ClientError(400, {"error": {"code": 400, "message": "bad request"}})
    client = GeminiClient(client=fake_genai(bad))
    with pytest.raises(errors.ClientError):
        client.generate(model="m", system="s", messages=[Message.user("hi")], tools=[])
