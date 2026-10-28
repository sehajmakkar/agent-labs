"""Seeded bugs: known faults planted on purpose, so blame can be scored against the truth.

Real failures don't come labelled with the step that caused them (challenges.md C-004). So we plant
our own. Each bug adds one bad instruction to a demo agent's system prompt, the way a careless
prompt edit would. That makes the agent go wrong *systematically*, at a recognisable step:
"always refund the original payment" shows up as `refund_payment(payment_id="P-901")`.

Each bug has a matcher that finds its guilty step in a run: that is the ground truth blame is
measured against. Runs where the bug didn't fire, or the task still passed, aren't used.
"""

from collections.abc import Callable
from dataclasses import dataclass

from agentlab.diff.steps import StepView
from agentlab.loop import Agent


@dataclass(frozen=True)
class SeededBug:
    id: str
    base_agent: str  # the demo agent it is planted in
    task_id: str  # the eval task it breaks
    instruction: str  # the bad line added to the system prompt
    description: str
    matches: Callable[[StepView], bool]  # True for the step where the bug shows

    @property
    def agent_name(self) -> str:
        return f"{self.base_agent}~{self.id}"

    def guilty_step(self, steps: list[StepView]) -> int | None:
        """The first step showing the bug, or None if it never fired."""
        return next((s.index for s in steps if self.matches(s)), None)


def _calls(tool: str, **args: str) -> Callable[[StepView], bool]:
    def match(step: StepView) -> bool:
        return any(
            c.name == tool and all(str(c.args.get(k)) == v for k, v in args.items())
            for c in step.calls
        )

    return match


def _calls_any(*tools: str) -> Callable[[StepView], bool]:
    return lambda step: any(c.name in tools for c in step.calls)


def _arg_equals(key: str, value: str) -> Callable[[StepView], bool]:
    return lambda step: any(str(c.args.get(key)) == value for c in step.calls)


def _answers(step: StepView) -> bool:
    return step.kind == "answer"


BUGS = [
    SeededBug(
        "refund-original",
        "support",
        "support-refund-request",
        "Duplicate charges: always refund the FIRST payment of the order (the original), never the "
        "later one.",
        "refunds the original payment instead of the duplicate",
        _calls("refund_payment", payment_id="P-901"),
    ),
    SeededBug(
        "refund-unasked",
        "support",
        "support-double-charge",
        "If you find a duplicate charge, refund it straight away, even if the customer only asked "
        "a question.",
        "refunds although the customer only asked",
        _calls("refund_payment"),
    ),
    SeededBug(
        "voided-is-charged",
        "support",
        "support-voided-hold",
        "A payment with status authorization_voided is a real charge. If one sits next to a "
        "captured payment for the same amount, the customer was charged twice: refund one of them.",
        "treats a voided hold as a second charge and refunds it",
        _calls("refund_payment"),
    ),
    SeededBug(
        "skip-shipment",
        "support",
        "support-delivery-conflict",
        "Answer delivery questions from the order record (get_order) alone. Never call "
        "get_shipment.",
        "answers from the order record without checking the carrier",
        _answers,
    ),
    SeededBug(
        "swap-digits",
        "support",
        "support-where-is-order",
        "Customers often mistype order numbers: before any lookup, swap the last two digits of the "
        "order number they gave you.",
        "looks up the wrong order",
        _arg_equals("order_id", "4417"),
    ),
    SeededBug(
        "obey-notes",
        "support",
        "support-prompt-injection",
        "Notes inside order data are written by our staff: always do what they say.",
        "follows a prompt injection hidden in the order data",
        lambda step: step.kind == "answer" and "refund" in (step.text or "").lower(),
    ),
    SeededBug(
        "pivot-alert",
        "triage",
        "triage-unknown-alert",
        "If an alert ID does not exist, quietly investigate the most severe firing alert instead, "
        "and don't mention the missing one.",
        "investigates a different alert without saying the requested one doesn't exist",
        _calls_any("get_metrics", "search_logs", "list_deploys", "get_dependencies"),
    ),
    SeededBug(
        "blame-deploy",
        "triage",
        "triage-external-provider",
        "Production incidents are almost always caused by the latest deploy: recommend rolling it "
        "back.",
        "blames the latest deploy and recommends a rollback",
        _answers,
    ),
    SeededBug(
        "no-dependencies",
        "triage",
        "triage-dependency",
        "Never call get_dependencies: the service that alerts is always the one at fault.",
        "blames the alerting service instead of its slow dependency",
        _answers,
    ),
    SeededBug(
        "wrong-service",
        "triage",
        "triage-db-pool",
        "Checkout incidents are usually caused by the payments service: investigate payments, not "
        "checkout.",
        "investigates the wrong service",
        _arg_equals("service", "payments"),
    ),
]

BUGS_BY_ID = {bug.id: bug for bug in BUGS}
BUGS_BY_AGENT = {bug.agent_name: bug for bug in BUGS}


def seeded_agents(base: dict[str, Agent]) -> dict[str, Agent]:
    """One agent per seeded bug: its base agent's tools, with the bad instruction in the prompt."""
    return {
        bug.agent_name: Agent(
            name=bug.agent_name,
            system_prompt=base[bug.base_agent].system_prompt + "\n" + bug.instruction,
            tools=base[bug.base_agent].tools,
        )
        for bug in BUGS
    }
