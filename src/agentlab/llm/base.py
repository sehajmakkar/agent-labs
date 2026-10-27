"""Provider-neutral types for talking to an LLM.

The agent loop only ever sees these types, never a provider's SDK, so swapping or adding providers
doesn't touch the loop (decisions.md D-005).

Every model message also keeps the provider's original response in `raw`. The provider sends that
back unchanged on the next turn instead of rebuilding it from our simplified fields. Gemini needs
this: its responses can carry thought signatures that must be returned as-is (challenges.md C-005).
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from agentlab.tools import Tool


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass
class ToolResult:
    call: ToolCall
    output: dict[str, Any]
    is_error: bool = False


@dataclass
class Message:
    role: Literal["user", "model", "tool"]
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    raw: Any = None

    @classmethod
    def user(cls, text: str) -> "Message":
        return cls(role="user", text=text)

    @classmethod
    def tool(cls, results: list[ToolResult]) -> "Message":
        return cls(role="tool", tool_results=results)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.thinking_tokens + other.thinking_tokens,
        )


@dataclass
class LLMResponse:
    message: Message
    usage: Usage
    model: str


class TransientLLMError(Exception):
    """A model call failed for a reason that may pass on retry: overload, rate limit, timeout.

    `retry_after_s` is the server's own hint for how long to wait, when it gave one."""

    def __init__(self, message: str, retry_after_s: float | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LLMClient(Protocol):
    def generate(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[Tool],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """One model call. With `response_schema` (a JSON Schema), the reply text is JSON that
        matches it ("structured output")."""
        ...
