"""Demo agents that play the customer's role. Their data is simulated, so runs repeat and nothing
real is touched.

- `support`: customer support for an online store (orders, payments, shipping).
- `triage`: an on-call assistant that investigates production alerts.
"""

from agentlab.loop import Agent


def demo_agents(*, seeded: bool = False) -> dict[str, Agent]:
    """The demo agents by name. With `seeded`, also each seeded-bug variant (blame/catalog.py),
    which replay, fork and blame need to rerun those runs' code."""
    from agentlab.demo import support, triage

    agents = {a.name: a for a in (support.AGENT, triage.AGENT)}
    if seeded:
        from agentlab.blame.catalog import seeded_agents

        agents |= seeded_agents(agents)
    return agents
