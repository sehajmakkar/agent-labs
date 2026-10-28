import json

import pytest
from fastapi.testclient import TestClient
from test_fork import AGENT, STATE, TASK, record_source, smart_genai

from agentlab.blame.bench import SEED_PREFIX, benchmark_proposals, seeded_failures
from agentlab.blame.catalog import BUGS_BY_ID, seeded_agents
from agentlab.blame.propose import BlameJudge, render_steps
from agentlab.blame.runner import execute_blame
from agentlab.blame.verify import classify
from agentlab.diff.steps import StepView, ToolCallView
from agentlab.evals.runner import run_eval
from agentlab.fork.worker import work
from agentlab.llm.base import LLMResponse, Message, Usage
from agentlab.server import create_app

FIX = "Always give the customer the refund ID."


class FakeBlameLLM:
    """A blame judge that proposes the given candidates: [(step, correction), …]."""

    def __init__(self, *candidates: tuple[int, str]):
        self.candidates = candidates
        self.prompts: list[str] = []

    def generate(self, *, model, system, messages, tools, response_schema=None):
        self.prompts.append(messages[0].text)
        body = {
            "analysis": "The answer left out the refund ID.",
            "candidates": [
                {"reasoning": f"step {s} went wrong", "step": s, "correction": c}
                for s, c in self.candidates
            ],
        }
        return LLMResponse(Message(role="model", text=json.dumps(body)), Usage(200, 50), model)


@pytest.fixture(autouse=True)
def reset_state():
    STATE.update(refunds=[], real_gateway_calls=0, simulator_calls=0, by_run={})


def blame(store, *candidates, n=5, k=2):
    source = record_source()  # the agent refunds, then answers without the refund ID: fails TASK
    blame_id = store.create_blame(
        source_run_id=source, judge_model="judge", n=n, max_candidates=k, status="running"
    )
    llm, _ = smart_genai()
    context = {
        "llm": llm,
        "agents": {"shop": AGENT},
        "entry": None,
        "judge": None,
        "tasks": {TASK.id: TASK},
    }
    judge_llm = FakeBlameLLM(*candidates)
    report = execute_blame(
        store,
        store.get_blame(blame_id),
        blame_judge=BlameJudge(judge_llm, "judge"),
        tasks={TASK.id: TASK},
        fork_context=context,
    )
    return report, judge_llm


def test_the_right_step_is_confirmed_and_decisive(store):
    report, judge = blame(store, (3, FIX))

    blamed = report["blamed"]
    assert blamed["step"] == 3
    v = blamed["verification"]
    assert (v["passed"], v["control_passed"], v["status"]) == (5, 0, "confirmed")
    assert v["decisive"] is True and v["later_passed"] is None  # the last step: nothing after it
    assert report["confidence"] == "high"
    assert report["verdict"].startswith("Step 3 is at fault. Verified: with the correction 5/5")
    # The judge saw the run as numbered steps, plus the expectation.
    assert "STEP 2: the agent called" in judge.prompts[0]
    assert TASK.expected in judge.prompts[0]


def test_a_step_that_is_too_early_shows_as_recoverable(store):
    report, _ = blame(store, (2, FIX))

    v = report["blamed"]["verification"]
    assert v["status"] == "confirmed"
    # Fixing step 3 instead (keeping step 2 as it was) still saves the run.
    assert v["later_passed"] == 5 and v["decisive"] is False
    assert report["confidence"] == "medium"
    assert "recoverable" in report["verdict"]


def test_a_wrong_correction_is_rejected_and_the_next_candidate_tried(store):
    report, _ = blame(store, (3, "Be polite."), (2, FIX), k=2)

    first, second = report["candidates"]
    assert first["verification"]["status"] == "rejected"
    assert first["verification"]["passed"] == 0
    assert report["blamed"]["step"] == 2


def test_no_confirmed_candidate_means_no_blame(store):
    report, _ = blame(store, (3, "Be polite."), (1, "Be brief."), n=2, k=2)
    assert report["blamed"] is None and report["confidence"] is None
    assert report["verdict"].startswith("Not proved")
    assert "best guess, unproven, is step 3" in report["verdict"]


def test_classification_rules():
    assert classify(5, 0, 5) == "confirmed"
    assert classify(3, 0, 3) == "confirmed"
    assert classify(1, 0, 5) == "rejected"
    assert classify(4, 4, 5) == "rejected"
    assert classify(3, 1, 5) == "inconclusive"


def test_the_judge_drops_steps_that_do_not_exist_and_repeats(store):
    steps = [
        StepView(1, "a", [ToolCallView("get_order", {"order_id": "1"}, {"ok": True})]),
        StepView(2, "b", text="Done."),
    ]
    judge = BlameJudge(FakeBlameLLM((2, "x"), (2, "y"), (9, "z"), (1, "w")), "judge")
    result = judge(request="q", expected="e", failures=["f"], steps=steps)
    assert [c.step for c in result.proposal.candidates] == [2, 1]
    text = render_steps(steps)
    assert 'get_order({"order_id": "1"})' in text and "STEP 2: the agent answered" in text


def test_seeded_bugs_find_their_guilty_step():
    bug = BUGS_BY_ID["refund-original"]
    steps = [
        StepView(1, "a", [ToolCallView("get_payments", {"order_id": "4471"})]),
        StepView(2, "b", [ToolCallView("refund_payment", {"payment_id": "P-901", "reason": "x"})]),
        StepView(3, "c", text="Refunded."),
    ]
    assert bug.guilty_step(steps) == 2
    assert BUGS_BY_ID["skip-shipment"].guilty_step(steps) == 3
    assert BUGS_BY_ID["swap-digits"].guilty_step(steps) is None  # 4471 was looked up correctly

    from agentlab.demo import demo_agents

    seeded = seeded_agents(demo_agents())
    assert bug.instruction in seeded["support~refund-original"].system_prompt
    assert seeded["support~refund-original"].tools == demo_agents()["support"].tools


def test_seeded_failures_and_the_proposal_benchmark(store):
    llm, _ = smart_genai("refund_payment", {"payment_id": "P-901"})
    run_eval(
        [TASK, TASK],
        agents={"shop": AGENT},
        llm=llm,
        model="m",
        store=store,
        judge=None,
        datasets=[SEED_PREFIX + "refund-original"],
    )

    failures = seeded_failures(store)
    assert len(failures) == 2
    assert {f.guilty_step for f in failures} == {2}

    results = benchmark_proposals(
        store,
        failures,
        judges={
            "good": BlameJudge(FakeBlameLLM((2, FIX)), "good"),
            "late": BlameJudge(FakeBlameLLM((3, FIX), (2, FIX)), "late"),
        },
        tasks={"support-refund-request": TASK},
    )
    assert (results["good"]["top1"], results["good"]["top3"]) == (1.0, 1.0)
    assert (results["late"]["top1"], results["late"]["top3"], results["late"]["within1"]) == (
        0.0,
        1.0,
        1.0,
    )
    assert results["late"]["by_bug"]["refund-original"] == {"cases": 2, "top1": 0, "top3": 2}


def test_the_worker_runs_queued_blames(store, monkeypatch):
    source = record_source()
    blame_id = store.create_blame(source_run_id=source, judge_model="judge", n=2, max_candidates=1)
    llm, _ = smart_genai()
    import agentlab.blame.propose as propose_module

    monkeypatch.setattr(
        propose_module, "BlameJudge", lambda _llm, model: BlameJudge(FakeBlameLLM((3, FIX)), model)
    )
    ran = work(
        store, llm=llm, agents={"shop": AGENT}, tasks={TASK.id: TASK}, once=True, log=lambda _: None
    )
    assert ran == 1
    row = store.get_blame(blame_id)
    assert (row.status, row.report["blamed"]["step"]) == ("done", 3)


def test_blame_api(store, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLAB_DATASETS", str(tmp_path))
    (tmp_path / "d.jsonl").write_text(TASK.model_dump_json() + "\n")
    source = record_source()
    client = TestClient(create_app(store, ui_dist=None))

    created = client.post("/api/blames", json={"run_id": source, "n": 3}).json()
    assert (created["status"], created["n"]) == ("queued", 3)
    detail = client.get(f"/api/blames/{created['id'][:8]}").json()
    assert detail["source"]["id"] == source
    assert client.get(f"/api/runs/{source}").json()["blames"][0]["id"] == created["id"]

    from agentlab import tracing

    tracing.init(store)
    import agentlab as lab

    @lab.agent("no-task")
    def free(message: str) -> str:
        return "hi"

    free("x")
    untasked = store.runs(1)[0].id
    assert client.post("/api/blames", json={"run_id": untasked}).status_code == 400
    assert client.get("/api/benchmarks/blame").status_code == 404
    store.save_benchmark("blame", {"failures": 1})
    assert client.get("/api/benchmarks/blame").json()["results"] == {"failures": 1}


def test_the_judge_sees_the_agents_system_prompt(store):
    _, judge = blame(store, (3, FIX), n=1, k=1)
    assert judge.prompts[0].startswith("THE AGENT'S SYSTEM PROMPT:\nYou are a support agent.")
