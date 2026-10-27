"""The lab over HTTP: a RemoteStore and a worker talking to the API, in-process."""

import pytest
from fastapi.testclient import TestClient
from test_fork import AGENT, FIXED_PROMPT, TASK, record_source, smart_genai, step_span

from agentlab import tracing
from agentlab.fork.worker import work
from agentlab.remote import RemoteStore
from agentlab.replay.runner import replay_run
from agentlab.server import create_app


@pytest.fixture
def client(store):
    return TestClient(create_app(store, ui_dist=None))


@pytest.fixture
def remote(client):
    return RemoteStore("http://testserver", client=client)


def test_runs_traced_through_a_remote_store_land_in_the_lab(store, remote):
    tracing.init(remote)  # what lab.init("http://lab:8000") does
    source = record_source()

    run = store.get_run(source)  # the lab's own database has it
    assert run.status == "completed"
    assert [s.kind for s in store.spans(source)][:3] == ["agent", "step", "llm"]
    assert len(store.run_recordings(source)) == len(remote.run_recordings(source))

    # And it can be replayed through the same remote store.
    result = replay_run(remote, source, agents={"shop": AGENT})
    assert result.report.identical, result.report.differences


def test_the_store_endpoint_checks_the_token(client, monkeypatch):
    monkeypatch.setenv("AGENTLAB_TOKEN", "s3cret")
    assert client.post("/api/store/get_run", json={"run_id": "x"}).status_code == 401
    ok = RemoteStore("http://testserver", client=client, token="s3cret")
    assert ok.get_run("x") is None
    assert client.post("/api/store/drop_tables", json={}).status_code in (401, 404)


def test_a_fork_queued_in_the_ui_is_run_by_a_remote_worker(store, client, remote):
    source = record_source()
    response = client.post(
        "/api/forks",
        json={
            "run_id": source,
            "span_id": step_span(store, source, 3).id,
            "override": {"system_prompt": FIXED_PROMPT},
            "n": 2,
            "control": True,
        },
    )
    assert response.status_code == 200
    fork = response.json()
    assert (fork["status"], fork["label"]) == ("queued", "step 3")

    tracing.init(remote)  # the worker lives elsewhere: it only has the HTTP API
    llm, _ = smart_genai()
    assert (
        work(remote, llm=llm, agents={"shop": AGENT}, tasks={TASK.id: TASK}, once=True, log=print)
        == 1
    )

    detail = client.get(f"/api/forks/{fork['id'][:8]}").json()
    assert detail["fork"]["status"] == "done"
    assert detail["fork"]["summary"]["fork"]["passed"] == 2
    assert detail["fork"]["summary"]["control"]["passed"] == 0
    assert len(detail["runs"]) == 4
    assert {r["mode"] for r in detail["runs"]} == {"fork"}

    family = client.get(f"/api/runs/{detail['runs'][0]['id']}/family").json()
    assert family["run"]["id"] == source  # the family is shown from its root
    assert len(family["forks"][0]["runs"]) == 4

    run_detail = client.get(f"/api/runs/{source}").json()
    assert [f["id"] for f in run_detail["forks"]] == [fork["id"]]


def test_fork_requests_are_validated(store, client):
    source = record_source()
    step = step_span(store, source, 3).id
    bad_tool_output = {"run_id": source, "span_id": step, "override": {"tool_output": {"x": 1}}}
    assert client.post("/api/forks", json=bad_tool_output).status_code == 400
    assert client.post("/api/forks", json={"run_id": source, "span_id": "nope"}).status_code == 400
    assert client.post("/api/forks", json={"run_id": "nope", "span_id": step}).status_code == 404
    too_many = {"run_id": source, "span_id": step, "n": 50}
    assert client.post("/api/forks", json=too_many).status_code == 400
