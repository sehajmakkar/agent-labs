"""Gemini provider: converts between our neutral types and the `google-genai` SDK."""

from typing import Any

from google import genai
from google.genai import types

from agentlab.llm.base import LLMResponse, Message, ToolCall, Usage
from agentlab.tools import Tool


class GeminiClient:
    def __init__(self, api_key: str | None = None, client: Any = None):
        self._client = client or genai.Client(api_key=api_key)

    def generate(
        self, *, model: str, system: str, messages: list[Message], tools: list[Tool]
    ) -> LLMResponse:
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=[_declaration(t) for t in tools])]
            if tools
            else None,
            # The SDK can run Python functions for us; we turn that off so that every tool call
            # goes through our own loop, where it can be traced and later replayed.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._client.models.generate_content(
            model=model, contents=to_contents(messages), config=config
        )
        return from_response(response, model)

    def list_models(self) -> list[types.Model]:
        return list(self._client.models.list())


def _declaration(tool: Tool) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=tool.name,
        description=tool.description,
        parameters_json_schema=tool.parameters_schema,
    )


def to_contents(messages: list[Message]) -> list[types.Content]:
    contents = []
    for message in messages:
        if message.role == "user":
            contents.append(
                types.Content(role="user", parts=[types.Part.from_text(text=message.text or "")])
            )
        elif message.role == "model":
            contents.append(message.raw if message.raw is not None else _model_content(message))
        else:
            # Gemini expects tool results as function_response parts in a "user" turn, each
            # matched to its call by id.
            parts = [
                types.Part(
                    function_response=types.FunctionResponse(
                        id=result.call.id, name=result.call.name, response=result.output
                    )
                )
                for result in message.tool_results
            ]
            contents.append(types.Content(role="user", parts=parts))
    return contents


def _model_content(message: Message) -> types.Content:
    """Rebuild a model turn from our fields. Only used when there is no raw response to resend."""
    parts = [types.Part.from_text(text=message.text)] if message.text else []
    parts += [
        types.Part(function_call=types.FunctionCall(id=call.id, name=call.name, args=call.args))
        for call in message.tool_calls
    ]
    return types.Content(role="model", parts=parts)


def from_response(response: types.GenerateContentResponse, model: str) -> LLMResponse:
    content = response.candidates[0].content if response.candidates else None
    parts = (content.parts if content else None) or []

    # Parts flagged `thought` are the model's thinking summary, not part of its answer.
    text = "".join(p.text for p in parts if p.text and not p.thought) or None
    tool_calls = [
        ToolCall(
            name=p.function_call.name, args=dict(p.function_call.args or {}), id=p.function_call.id
        )
        for p in parts
        if p.function_call
    ]

    meta = response.usage_metadata
    usage = Usage(
        input_tokens=(meta.prompt_token_count or 0) if meta else 0,
        output_tokens=(meta.candidates_token_count or 0) if meta else 0,
        thinking_tokens=(meta.thoughts_token_count or 0) if meta else 0,
    )
    message = Message(role="model", text=text, tool_calls=tool_calls, raw=content)
    return LLMResponse(message=message, usage=usage, model=model)
