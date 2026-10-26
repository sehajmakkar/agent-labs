"""Demo support agent for an online store. Phase 0 version: two read-only tools.

The data below stands in for the store's real systems, so runs are repeatable and nothing real is
ever touched. Later phases grow it into a simulated backend with write tools (challenges.md C-003).
Order 4417 was charged twice on purpose: it is the case from the worked example in learnings.md.
"""

from agentlab.loop import Agent
from agentlab.tools import tool

ORDERS = {
    "4417": {
        "order_id": "4417",
        "item": "Wireless earbuds",
        "amount": 2499,
        "currency": "INR",
        "status": "delivered",
    },
    "4471": {
        "order_id": "4471",
        "item": "Phone case",
        "amount": 499,
        "currency": "INR",
        "status": "shipped",
    },
}

PAYMENTS = {
    "4417": [
        {"payment_id": "P-901", "amount": 2499, "status": "captured"},
        {"payment_id": "P-902", "amount": 2499, "status": "captured"},
    ],
    "4471": [{"payment_id": "P-917", "amount": 499, "status": "captured"}],
}


@tool(kind="read")
def get_order(order_id: str) -> dict:
    """Look up an order by its ID. Returns the item, amount, currency and delivery status."""
    if order_id not in ORDERS:
        raise LookupError(f"No order with ID {order_id}")
    return ORDERS[order_id]


@tool(kind="read")
def get_payments(order_id: str) -> dict:
    """List every payment charged for an order, with its amount and status."""
    if order_id not in ORDERS:
        raise LookupError(f"No order with ID {order_id}")
    return {"order_id": order_id, "payments": PAYMENTS.get(order_id, [])}


SYSTEM_PROMPT = """\
You are a customer support agent for an online store.
Use the tools to look up order and payment facts; never guess them.
If a tool returns an error, tell the customer plainly instead of inventing an answer.
You cannot issue refunds yet: if one is needed, say it will be passed to the billing team.
Keep replies short and friendly."""

AGENT = Agent(name="support", system_prompt=SYSTEM_PROMPT, tools=[get_order, get_payments])
