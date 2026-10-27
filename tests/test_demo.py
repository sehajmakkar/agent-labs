"""The demo agents and datasets stay consistent with each other."""

from pathlib import Path

import pytest

from agentlab.demo import demo_agents
from agentlab.demo.triage import search_logs
from agentlab.evals import load_dataset
from agentlab.evals.tasks import ToolCalled, ToolNotCalled

DATASETS = sorted((Path(__file__).parents[1] / "datasets").glob("*.jsonl"))


def test_there_are_twenty_tasks():
    assert sum(len(load_dataset(path)) for path in DATASETS) == 20


@pytest.mark.parametrize("path", DATASETS, ids=lambda p: p.name)
def test_every_check_names_a_real_agent_and_tool(path):
    agents = demo_agents()
    for task in load_dataset(path):
        assert task.agent in agents, task.id
        tools = {t.name: t for t in agents[task.agent].tools}
        for check in task.checks:
            if isinstance(check, ToolCalled | ToolNotCalled):
                assert check.tool in tools, f"{task.id}: no tool {check.tool}"
            if isinstance(check, ToolCalled) and check.args:
                # The expected arguments must be valid arguments for that tool.
                tools[check.tool].args_model.model_validate(check.args)


def test_triage_tools_report_unknown_services():
    with pytest.raises(LookupError, match="Known services: auth, checkout"):
        search_logs("billing")
    assert search_logs("checkout", "POOL")["lines"]
