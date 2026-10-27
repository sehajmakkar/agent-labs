import pytest
from fakes import AGENT, RoutedLLM
from fastapi.testclient import TestClient

from agentlab.evals import run_eval
from agentlab.evals.tasks import Task
from agentlab.server import create_app
from agentlab.tracing import agent_run, span


@pytest.fixture
def client(store):
    return TestClient(create_app(store, ui_dist=None))


@pytest.fixture
def eval_id(store):
    tasks = [
        Task.model_validate(
            {
                "id": key,
                "agent": "echo",
                "input": key,
                "expected": "e",
                "checks": [{"type": "answer_contains", "any_of": ["It is A"]}],
            }
        )
        for key in ("a", "b")
    ]
    return run_eval(
        tasks,
        agents={"echo": AGENT},
        llm=RoutedLLM(),
        model="fake",
        store=store,
        judge=None,
        datasets=["d.jsonl"],
        concurrency=1,
    )


def test_runs_list_includes_totals_and_eval_results(client, eval_id):
    runs = client.get("/api/runs").json()
    assert {r["task_id"] for r in runs} == {"a", "b"}
    a = next(r for r in runs if r["task_id"] == "a")
    assert a["message"] == "a"
    assert a["answer"] == "It is A"
    assert a["eval"]["passed"] is True
    assert a["started_at"].endswith("Z") or a["started_at"].endswith("+00:00")


def test_run_detail_has_the_span_tree(client, eval_id):
    run_id = client.get("/api/runs").json()[0]["id"]
    detail = client.get(f"/api/runs/{run_id}").json()
    kinds = [s["kind"] for s in detail["spans"]]
    assert kinds == ["agent", "step", "tool", "step"]
    root = detail["spans"][0]
    assert root["parent_span_id"] is None
    assert all(s["parent_span_id"] for s in detail["spans"][1:])


def test_recordings_of_a_tool_span(client, eval_id):
    run_id = client.get("/api/runs").json()[0]["id"]
    tool = next(s for s in client.get(f"/api/runs/{run_id}").json()["spans"] if s["kind"] == "tool")
    (recording,) = client.get(f"/api/spans/{tool['id']}/recordings").json()
    assert recording["request"]["tool"] == "lookup"
    assert len(recording["request_hash"]) == 64


def test_eval_detail_has_metrics_and_runs(client, eval_id):
    (summary,) = client.get("/api/evals").json()
    assert summary["metrics"]["passed"] == 1
    detail = client.get(f"/api/evals/{eval_id[:8]}").json()
    assert detail["eval"]["id"] == eval_id
    assert {r["task_id"] for r in detail["runs"]} == {"a", "b"}
    failed = next(r for r in detail["runs"] if r["task_id"] == "b")
    assert failed["eval"]["failure_category"] == "incomplete"


def test_unknown_ids_are_404(client):
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/spans/nope/recordings").status_code == 404
    assert client.get("/api/evals/nope").status_code == 404


def test_status_filter(client, eval_id):
    assert len(client.get("/api/runs", params={"status": "completed"}).json()) == 2
    assert client.get("/api/runs", params={"status": "error"}).json() == []


def test_run_totals_sum_its_model_calls(client):
    with agent_run("x"):
        for _ in range(2):
            with span("llm", "chat m") as s:
                s.input_tokens, s.output_tokens, s.thinking_tokens, s.cost_usd = 10, 5, 1, 0.001
    (run,) = client.get("/api/runs").json()
    assert run["tokens"] == 32
    assert run["cost_usd"] == pytest.approx(0.002)


def test_runs_from_lab_agent_show_their_question_and_answer(client):
    import agentlab as lab

    @lab.agent("weather-bot")
    def answer(question: str) -> str:
        return "Take an umbrella."

    answer("Rain in Pune?")
    (run,) = client.get("/api/runs").json()
    assert (run["message"], run["answer"]) == ("Rain in Pune?", "Take an umbrella.")


def test_replay_endpoint_replays_a_demo_run_offline(client, store):
    from fakes import fake_genai, gemini_response

    from agentlab.demo.support import AGENT as support
    from agentlab.llm.gemini import GeminiClient, wrap_genai_client
    from agentlab.loop import run_agent

    llm = GeminiClient(client=wrap_genai_client(fake_genai(gemini_response([{"text": "Hi!"}]))))
    source = run_agent(support, llm=llm, model="m", user_message="hello").run_id

    response = client.post(f"/api/runs/{source}/replay").json()
    assert response["identical"] is True

    detail = client.get(f"/api/runs/{source}").json()
    assert [r["id"] for r in detail["replays"]] == [response["run_id"]]
    replay = client.get(f"/api/runs/{response['run_id']}").json()["run"]
    assert (replay["mode"], replay["parent_run_id"]) == ("replay", source)
    assert replay["replay_report"]["identical"] is True


def test_replaying_a_custom_agent_needs_its_code(client):
    import agentlab as lab

    @lab.agent("custom")
    def custom(message: str) -> str:
        return "ok"

    custom("hi")
    run_id = client.get("/api/runs").json()[0]["id"]
    response = client.post(f"/api/runs/{run_id}/replay")
    assert response.status_code == 400
    assert "--entry" in response.json()["detail"]
