"""Tools: plain Python functions the agent is allowed to call.

`@tool` turns a function into a `Tool`. The JSON Schema the model sees is built from the function's
type hints, and its docstring becomes the description the model reads to decide when to call it.

`kind` says whether calling the tool again is harmless ("read") or has side effects ("write").
Replay and fork will depend on it (challenges.md C-002).

Every call, whether from our loop or from someone's own code, becomes an `execute_tool` span with
a recording of its arguments and result. That makes tools one of the two interception boundaries
(decisions.md D-004).
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, get_type_hints

from pydantic import BaseModel, ValidationError, create_model

from agentlab import semconv
from agentlab.tracing import span

ToolKind = Literal["read", "write"]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    kind: ToolKind
    fn: Callable[..., Any]
    args_model: type[BaseModel]

    @property
    def parameters_schema(self) -> dict[str, Any]:
        """JSON Schema for the arguments, in the shape function-calling APIs expect."""
        return self.args_model.model_json_schema()

    def invoke(self, args: dict[str, Any], *, call_id: str | None = None) -> Any:
        """Validate model-supplied arguments against the type hints, then call the function.

        Raises pydantic.ValidationError if the model sent arguments that don't fit, or whatever the
        function itself raises. Either way the span records the error before it propagates.
        """
        attributes = {
            semconv.OPERATION_NAME: "execute_tool",
            semconv.TOOL_NAME: self.name,
            semconv.TOOL_CALL_ID: call_id,
            semconv.TOOL_KIND: self.kind,
        }
        request = {"tool": self.name, "args": args}
        with span("tool", f"execute_tool {self.name}", input=args, attributes=attributes) as s:
            try:
                validated = self.args_model.model_validate(args)
                output = self.fn(**dict(validated))
            except Exception as e:
                s.error = describe_error(e)
                s.record(request, {"error": s.error})
                raise
            s.output = output
            s.record(request, {"output": output})
            return output

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        bound = inspect.signature(self.fn).bind(*args, **kwargs)
        return self.invoke(dict(bound.arguments))


def tool(kind: ToolKind) -> Callable[[Callable[..., Any]], Tool]:
    def decorate(fn: Callable[..., Any]) -> Tool:
        return Tool(
            name=fn.__name__,
            description=inspect.getdoc(fn) or "",
            kind=kind,
            fn=fn,
            args_model=_args_model(fn),
        )

    return decorate


def describe_error(e: Exception) -> str:
    """The error message the model (and the trace) sees when a tool call fails."""
    if isinstance(e, ValidationError):
        problems = "; ".join(
            f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
        )
        return f"Invalid arguments: {problems}"
    return f"{type(e).__name__}: {e}"


def _args_model(fn: Callable[..., Any]) -> type[BaseModel]:
    """Build a pydantic model whose fields mirror the function's parameters."""
    hints = get_type_hints(fn)
    fields: dict[str, Any] = {}
    for name, param in inspect.signature(fn).parameters.items():
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (hints.get(name, Any), default)
    return create_model(f"{fn.__name__}_args", **fields)
