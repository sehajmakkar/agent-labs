"""Gemini provider: converts between our neutral types and the `google-genai` SDK.

It also holds `wrap_genai_client`, the model-call interception boundary (decisions.md D-004):
every `generate_content` call made through a wrapped client becomes a `chat` span with a recording
of the exact request and raw response. Failed calls are recorded too, with their error. During a
replay the wrapper serves the recorded response (or raises the recorded error) and never calls
Gemini.
"""

from typing import Any

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from agentlab import semconv
from agentlab.cost import cost_usd
from agentlab.llm.base import LLMResponse, Message, ToolCall, TransientLLMError, Usage
from agentlab.llm.ratelimit import RateLimiter
from agentlab.replay import session as replay
from agentlab.tools import Tool
from agentlab.tracing import note_wait, request_hash, span

# HTTP statuses worth retrying: timeout, rate limit, and server-side failures or overload.
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class GeminiClient:
    def __init__(
        self,
        api_key: str | None = None,
        client: Any = None,
        timeout_s: float = 60,
        requests_per_minute: int | None = None,
    ):
        if client is None:
            http_options = types.HttpOptions(
                timeout=int(timeout_s * 1000),
                # One attempt only: retries happen in our loop, so each one is traced (retry.py).
                retry_options=types.HttpRetryOptions(attempts=1),
            )
            client = wrap_genai_client(genai.Client(api_key=api_key, http_options=http_options))
        self._client = client
        self._limiter = RateLimiter(requests_per_minute) if requests_per_minute else None

    def generate(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[Tool],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=[_declaration(t) for t in tools])]
            if tools
            else None,
            # The SDK can run Python functions for us; we turn that off so that every tool call
            # goes through our own loop, where it can be traced and later replayed.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            # Structured output: the model's reply is constrained to JSON matching this schema.
            response_mime_type="application/json" if response_schema else None,
            response_json_schema=response_schema,
        )
        if self._limiter:
            note_wait(self._limiter.acquire())
        try:
            response = self._client.models.generate_content(
                model=model, contents=to_contents(messages), config=config
            )
        except errors.APIError as e:
            if e.code in TRANSIENT_STATUS_CODES:
                message = f"Gemini API error {e.code}: {e.message}"
                raise TransientLLMError(message, retry_after_s=_retry_delay(e)) from e
            raise
        except httpx.TransportError as e:  # timeouts and dropped connections
            raise TransientLLMError(f"{type(e).__name__}: {e}") from e
        return from_response(response, model)

    def list_models(self) -> list[types.Model]:
        return list(self._client.models.list())


def _retry_delay(e: errors.APIError) -> float | None:
    """The wait the server asked for, from a google.rpc.RetryInfo detail such as "3s"."""
    error = e.details.get("error", {}) if isinstance(e.details, dict) else {}
    for detail in error.get("details") or []:
        if str(detail.get("@type", "")).endswith("RetryInfo"):
            try:
                return float(str(detail.get("retryDelay", "")).removesuffix("s"))
            except ValueError:
                return None
    return None


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


def wrap_genai_client(client: genai.Client) -> "TracedGenAIClient":
    return TracedGenAIClient(client)


class TracedGenAIClient:
    """Stands in for `genai.Client`: traces `models.generate_content`, passes the rest through."""

    def __init__(self, client: Any):
        self._client = client
        self.models = _TracedModels(client.models)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _TracedModels:
    def __init__(self, models: Any):
        self._models = models

    def generate_content(
        self, *, model: str, contents: Any, config: types.GenerateContentConfig | None = None
    ) -> types.GenerateContentResponse:
        attributes = {
            semconv.OPERATION_NAME: "chat",
            semconv.PROVIDER_NAME: semconv.PROVIDER_GEMINI,
            semconv.REQUEST_MODEL: model,
        }
        session = replay.current()
        served = None
        if session:
            original = _request_json(model, contents, config)
            served = session.take("llm", original, request_hash(original))
            if served is replay.LIVE and isinstance(session, replay.ForkSession):
                # Past the fork point: the override is applied here, at the boundary, so it works
                # for any agent, ours or a customer's.
                model, config = _apply_override(session.override, model, config)
                attributes[semconv.REQUEST_MODEL] = model
        request = _request_json(model, contents, config)
        with span("llm", f"chat {model}", attributes=attributes) as s:
            if served is not None and served is not replay.LIVE:
                s.attributes[semconv.REPLAYED] = True
                if "error" in served:
                    s.record(request, served)
                    raise _rebuild_error(served["error"])
                response = types.GenerateContentResponse.model_validate(served)
            else:
                try:
                    response = self._models.generate_content(
                        model=model, contents=contents, config=config
                    )
                except Exception as e:
                    s.record(request, {"error": _error_json(e)})
                    raise
            s.record(request, _dump(response))

            parsed = from_response(response, model)
            s.input_tokens = parsed.usage.input_tokens
            s.output_tokens = parsed.usage.output_tokens
            s.thinking_tokens = parsed.usage.thinking_tokens
            # A replayed call costs nothing: no request reached Gemini.
            replayed = served is not None and served is not replay.LIVE
            s.cost_usd = 0.0 if replayed else cost_usd(model, parsed.usage)
            s.output = {
                "text": parsed.message.text,
                "tool_calls": [{"name": c.name, "args": c.args} for c in parsed.message.tool_calls],
            }
            s.attributes.update(
                {
                    semconv.RESPONSE_MODEL: response.model_version,
                    semconv.RESPONSE_FINISH_REASONS: [
                        c.finish_reason for c in response.candidates or [] if c.finish_reason
                    ],
                    semconv.USAGE_INPUT_TOKENS: parsed.usage.input_tokens,
                    # The spec counts reasoning inside output tokens; Gemini reports it separately.
                    semconv.USAGE_OUTPUT_TOKENS: parsed.usage.output_tokens
                    + parsed.usage.thinking_tokens,
                    semconv.USAGE_REASONING_OUTPUT_TOKENS: parsed.usage.thinking_tokens,
                }
            )
            return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._models, name)


def _apply_override(override: Any, model: str, config: Any) -> tuple[str, Any]:
    if override.model:
        model = override.model
    if override.system_prompt is not None:
        config = (config or types.GenerateContentConfig()).model_copy(
            update={"system_instruction": override.system_prompt}
        )
    return model, config


def _error_json(e: Exception) -> dict[str, Any]:
    """Enough of a failed call to raise the same error again during a replay."""
    if isinstance(e, errors.APIError):
        return {"type": "api", "code": e.code, "details": e.details}
    return {"type": "transport", "message": f"{type(e).__name__}: {e}"}


def _rebuild_error(error: dict[str, Any]) -> Exception:
    if error.get("type") == "api":
        cls = errors.ClientError if error["code"] < 500 else errors.ServerError
        return cls(error["code"], error.get("details"))
    return httpx.TransportError(error.get("message", "recorded transport error"))


def _dump(value: Any) -> Any:
    # JSON mode encodes bytes such as thought signatures as base64, and decodes them on load.
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def _request_json(model: str, contents: Any, config: Any) -> dict[str, Any]:
    items = contents if isinstance(contents, list) else [contents]
    return {"model": model, "contents": [_dump(c) for c in items], "config": _dump(config)}
