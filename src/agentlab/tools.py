"""Tools: plain Python functions the agent is allowed to call.

`@tool` turns a function into a `Tool`. The JSON Schema the model sees is built from the function's
type hints, and its docstring becomes the description the model reads to decide when to call it.

`kind` says whether calling the tool again is harmless ("read") or has side effects ("write").
Replay and fork will depend on it (challenges.md C-002).

Every call, whether from our loop or from someone's own code, becomes an `execute_tool` span with
a recording of its arguments and result. That makes tools one of the two interception boundaries
(decisions.md D-004).

During a replay the function is never called, whatever its kind: the recorded result is returned,
or the recorded error raised again. So replaying a run can't repeat a refund or an email
(challenges.md C-002).

In a fork, calls after the fork point are live. A read tool runs as usual. A write tool must never
reach a real system, so it runs only if it has a stand-in:
- `@tool(kind="write", simulated=True)`: the function itself only touches simulated state;
- or a simulator registered with `@my_tool.simulator`.
Otherwise the fork stops (`ForkBlocked`). Before the fork point, recorded writes are re-applied to
the simulator, so the live part sees the world as the original run left it.
"""

import copy
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, get_type_hints

from pydantic import BaseModel, ValidationError, create_model

from agentlab import semconv
from agentlab.replay import session as replay
from agentlab.tracing import request_hash, span

ToolKind = Literal["read", "write"]


@dataclass(eq=False)
class Tool:
    name: str
    description: str
    kind: ToolKind
    fn: Callable[..., Any]
    args_model: type[BaseModel]
    simulated: bool = False  # True: `fn` only touches simulated state, so a fork may run it
    simulator_fn: Callable[..., Any] | None = None  # used in place of `fn` in a fork

    def simulator(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register the function a fork runs instead of this (real) write tool."""
        self.simulator_fn = fn
        return fn

    def _fork_fn(self) -> Callable[..., Any] | None:
        """What a fork may run for this tool, or None if nothing is safe."""
        if self.kind == "read" or self.simulated:
            return self.fn
        return self.simulator_fn

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
        session = replay.current()
        with span("tool", f"execute_tool {self.name}", input=args, attributes=attributes) as s:
            fn = self.fn
            if session:
                served = session.take("tool", request, request_hash(request))
                if served is not replay.LIVE:
                    return self._replay(s, session, request, served)
                # A fork past its fork point: only a safe stand-in may run.
                fn = self._fork_fn()
                if fn is None:
                    s.error = f"ForkBlocked: {self.name} is a write tool with no simulator"
                    raise replay.ForkBlocked(
                        f"{self.name} is a write tool with no simulator, so a fork can't run it. "
                        f"Register one with @{self.name}.simulator, or mark the tool simulated."
                    )
                if fn is not self.fn:
                    s.attributes[semconv.SIMULATED] = True
            try:
                validated = self.args_model.model_validate(args)
                # A snapshot, not a reference: if the tool returned its own live state, a later
                # write would otherwise change this result inside the conversation history too
                # (challenges.md C-016).
                output = copy.deepcopy(fn(**dict(validated)))
            except Exception as e:
                s.error = describe_error(e)
                s.record(request, {"error": s.error})
                raise
            s.output = output
            s.record(request, {"output": output})
            return output

    def _replay(
        self, s: Any, session: replay.ReplaySession, request: dict[str, Any], recorded: Any
    ) -> Any:
        s.attributes[semconv.REPLAYED] = True
        s.record(request, recorded)
        if "error" in recorded:
            s.error = recorded["error"]
            raise ReplayedToolError(recorded["error"])
        if isinstance(session, replay.ForkSession) and self.kind == "write":
            self._reapply(request["args"])
        s.output = recorded["output"]
        return recorded["output"]

    def _reapply(self, args: dict[str, Any]) -> None:
        """Before the fork point: apply a recorded write to the simulator, so the state the live
        part sees matches the original run. The result is discarded; the recorded one is used."""
        fn = self._fork_fn()
        if fn is None:
            return
        try:
            fn(**dict(self.args_model.model_validate(args)))
        except Exception:
            pass  # the recorded call succeeded; a simulator that disagrees can't change history

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        bound = inspect.signature(self.fn).bind(*args, **kwargs)
        return self.invoke(dict(bound.arguments))


def tool(kind: ToolKind, *, simulated: bool = False) -> Callable[[Callable[..., Any]], Tool]:
    def decorate(fn: Callable[..., Any]) -> Tool:
        return Tool(
            name=fn.__name__,
            description=inspect.getdoc(fn) or "",
            kind=kind,
            fn=fn,
            args_model=_args_model(fn),
            simulated=simulated,
        )

    return decorate


class ReplayedToolError(Exception):
    """A tool error served from a recording. Its message is the original error text, unchanged."""


def describe_error(e: Exception) -> str:
    """The error message the model (and the trace) sees when a tool call fails."""
    if isinstance(e, ReplayedToolError):
        return str(e)
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
