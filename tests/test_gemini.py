from types import SimpleNamespace

from google.genai import types

from agentlab.llm.base import Message, ToolCall, ToolResult, Usage
from agentlab.llm.gemini import GeminiClient, from_response, to_contents
from agentlab.tools import tool


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
