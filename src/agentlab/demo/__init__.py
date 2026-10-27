"""Demo agents that play the customer's role. Their data is simulated, so runs repeat and nothing
real is touched.

- `support`: customer support for an online store (orders, payments, shipping).
- `triage`: an on-call assistant that investigates production alerts.
"""

from agentlab.loop import Agent


def demo_agents() -> dict[str, Agent]:
    from agentlab.demo import support, triage

    return {a.name: a for a in (support.AGENT, triage.AGENT)}
