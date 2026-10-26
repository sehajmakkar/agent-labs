"""Cost of a model call, from its token usage and the price table in config.py."""

from agentlab.config import PRICES_PER_MILLION
from agentlab.llm.base import Usage


def cost_usd(model: str, usage: Usage) -> float | None:
    """Estimated USD cost, or None when the model has no known price."""
    price = PRICES_PER_MILLION.get(model)
    if price is None:
        return None
    input_price, output_price = price
    # Thinking tokens are billed at the output price.
    billed_output = usage.output_tokens + usage.thinking_tokens
    return (usage.input_tokens * input_price + billed_output * output_price) / 1_000_000
