"""Tools: plain Python functions the agent is allowed to call.

`@tool` turns a function into a `Tool`. The JSON Schema the model sees is built from the function's
type hints, and its docstring becomes the description the model reads to decide when to call it.

`kind` says whether calling the tool again is harmless ("read") or has side effects ("write").
Phase 0 only records it; replay and fork will depend on it (challenges.md C-002).
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, get_type_hints

from pydantic import BaseModel, create_model

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

    def invoke(self, args: dict[str, Any]) -> Any:
        """Validate model-supplied arguments against the type hints, then call the function.

        Raises pydantic.ValidationError if the model sent arguments that don't fit.
        """
        validated = self.args_model.model_validate(args)
        return self.fn(**dict(validated))

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.fn(*args, **kwargs)


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


def _args_model(fn: Callable[..., Any]) -> type[BaseModel]:
    """Build a pydantic model whose fields mirror the function's parameters."""
    hints = get_type_hints(fn)
    fields: dict[str, Any] = {}
    for name, param in inspect.signature(fn).parameters.items():
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (hints.get(name, Any), default)
    return create_model(f"{fn.__name__}_args", **fields)
