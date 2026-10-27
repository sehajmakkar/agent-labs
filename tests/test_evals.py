import json

import pytest
from fakes import AGENT, RoutedLLM

from agentlab.evals import LLMJudge, Task, Trajectory, load_dataset, run_eval, score
from agentlab.evals.categories import pick_category
from agentlab.evals.metrics import percentile
from agentlab.evals.trajectory import ToolCallRecord
from agentlab.llm.base import LLMResponse, Message, Usage


def traj(answer="", calls=(), status="completed", steps=1) -> Trajectory:
    return Trajectory(
        run_id="r1",
        status=status,
        message="q",
        answer=answer,
        tool_calls=[ToolCallRecord(name, args) for name, args in calls],
        steps=steps,
    )


def task(*checks, expected="the right thing") -> Task:
    return Task.model_validate(
        {"id": "t", "agent": "a", "input": "q", "expected": expected, "checks": list(checks)}
    )


class FakeJudgeLLM:
    """Answers every judge call with the same JSON verdict, or raises."""

    def __init__(self, verdict: dict | Exception):
        self.verdict = verdict
        self.prompts: list[str] = []

    def generate(self, *, model, system, messages, tools, response_schema=None):
        assert response_schema is not None
        self.prompts.append(messages[0].text)
        if isinstance(self.verdict, Exception):
            raise self.verdict
        message = Message(role="model", text=json.dumps(self.verdict))
        return LLMResponse(message, Usage(100, 20), model)


# Programmatic checks


def test_tool_called_checks_name_and_arguments():
    t = task({"type": "tool_called", "tool": "get_order", "args": {"order_id": "4417"}})
    assert score(t, traj(calls=[("get_order", {"order_id": "4417"})]), None).passed

    wrong_args = score(t, traj(calls=[("get_order", {"order_id": "4471"})]), None)
    assert (wrong_args.passed, wrong_args.category) == (False, "invalid_arguments")

    not_called = score(t, traj(calls=[("get_payments", {"order_id": "4417"})]), None)
    assert not_called.category == "wrong_tool"
    assert "called: get_payments" in not_called.checks[0].detail


def test_argument_match_ignores_case_type_and_extra_keys():
    t = task({"type": "tool_called", "tool": "f", "args": {"id": "ALR-101", "n": 5}})
    assert score(t, traj(calls=[("f", {"id": "alr-101", "n": "5", "extra": 1})]), None).passed


def test_answer_contains_any_and_all():
    t = task({"type": "answer_contains", "any_of": ["twice", "double"], "all_of": ["2499"]})
    assert score(t, traj("You were charged TWICE, 2499 each"), None).passed
    result = score(t, traj("Charged once for 2499"), None)
    assert result.category == "incomplete"
    assert "'twice' or 'double'" in result.checks[0].detail


def test_answer_excludes_is_a_false_claim():
    t = task({"type": "answer_excludes", "any_of": ["has been refunded"]})
    result = score(t, traj("Your money has been refunded."), None)
    assert (result.passed, result.category) == (False, "false_claim")


def test_tool_not_called_and_max_steps():
    t = task({"type": "tool_not_called", "tool": "refund"}, {"type": "max_steps", "limit": 3})
    assert score(t, traj(steps=3), None).passed
    assert score(t, traj(steps=4), None).category == "inefficient"
    assert score(t, traj(calls=[("refund", {})]), None).category == "wrong_tool"


def test_a_check_can_override_its_category():
    t = task({"type": "answer_contains", "any_of": ["x"], "category": "false_claim"})
    assert score(t, traj("y"), None).category == "false_claim"


def test_unknown_check_type_is_rejected():
    with pytest.raises(ValueError):
        task({"type": "vibes"})


# Categories and metrics


def test_category_precedence_puts_run_failures_first():
    assert pick_category("completed", []) is None
    assert pick_category("max_steps", ["incomplete"]) == "max_steps"
    assert pick_category("completed", ["incomplete", "false_claim"]) == "false_claim"
    assert pick_category("error", []) == "crash"


def test_failed_run_fails_even_when_checks_pass():
    t = task({"type": "max_steps", "limit": 20})
    assert score(t, traj(status="timeout"), None).category == "timeout"


def test_percentile_interpolates_between_ranks():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 50) == 3.0
    assert percentile(values, 95) == pytest.approx(4.8)
    assert percentile([7.0], 95) == 7.0
    assert percentile([], 50) is None


# The judge


def test_judge_verdict_becomes_a_check_result():
    llm = FakeJudgeLLM(
        {"reasoning": "Promised a refund", "passed": False, "failure_category": "false_claim"}
    )
    judge = LLMJudge(llm, "gemini-3.5-flash-lite")
    t = task({"type": "judge", "rubric": "No refund promises."}, expected="Says billing will help")
    result = score(t, traj("Refund done!", calls=[("get_payments", {"order_id": "1"})]), judge)

    assert (result.passed, result.category) == (False, "false_claim")
    assert result.checks[0].detail == "Promised a refund"
    assert result.checks[0].cost_usd == pytest.approx((100 * 0.30 + 20 * 2.50) / 1e6)
    # The judge sees the expectation, the rubric and the transcript.
    prompt = llm.prompts[0]
    assert "Says billing will help\nNo refund promises." in prompt
    assert 'TOOL CALL: get_payments({"order_id": "1"})' in prompt
    assert "AGENT ANSWER: Refund done!" in prompt


def test_judge_failure_is_an_eval_error_not_an_agent_failure():
    judge = LLMJudge(FakeJudgeLLM(RuntimeError("quota")), "m")
    result = score(task({"type": "judge"}), traj("fine"), judge)
    assert (result.passed, result.category) == (False, "eval_error")
    assert "quota" in result.checks[0].detail


def test_passing_verdict_drops_any_category():
    judge = LLMJudge(
        FakeJudgeLLM({"reasoning": "ok", "passed": True, "failure_category": "incomplete"}), "m"
    )
    assert score(task({"type": "judge"}), traj("fine"), judge).category is None


# Datasets


def test_load_dataset_reports_file_and_line(tmp_path):
    path = tmp_path / "d.jsonl"
    good = {"id": "a", "agent": "x", "input": "q", "expected": "e"}
    path.write_text(json.dumps(good) + "\n\n" + '{"id": "b"}\n')
    with pytest.raises(ValueError, match=r"d\.jsonl:3: invalid task"):
        load_dataset(path)


def test_load_dataset_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "d.jsonl"
    row = json.dumps({"id": "a", "agent": "x", "input": "q", "expected": "e"})
    path.write_text(f"{row}\n{row}\n")
    with pytest.raises(ValueError, match="duplicate task IDs: a"):
        load_dataset(path)


# The batch runner


def test_run_eval_runs_scores_and_summarizes(store):
    tasks = [
        Task.model_validate(
            {
                "id": key,
                "agent": "echo",
                "input": key,
                "expected": "e",
                "checks": [
                    {"type": "tool_called", "tool": "lookup", "args": {"key": key}},
                    {"type": "answer_contains", "any_of": ["It is A", "It is B"]},
                ],
            }
        )
        for key in ("a", "b", "c", "crash")
    ]
    seen = []
    eval_id = run_eval(
        tasks,
        agents={"echo": AGENT},
        llm=RoutedLLM(),
        model="fake",
        store=store,
        judge=None,
        datasets=["d.jsonl"],
        concurrency=3,
        on_result=lambda o: seen.append(o.task.id),
    )

    assert sorted(seen) == ["a", "b", "c", "crash"]
    results = {r.task_id: r for r in store.eval_results(eval_id)}
    assert results["a"].passed and results["b"].passed
    assert results["c"].failure_category == "incomplete"
    assert results["crash"].failure_category == "crash"
    # Each task is an ordinary traced run, linked to its task.
    run = store.get_run(results["a"].run_id)
    assert (run.task_id, run.status) == ("a", "completed")
    # No "llm" spans: a fake LLM bypasses the wrapped Gemini client, where those are recorded.
    assert [s.kind for s in store.spans(run.id)] == ["agent", "step", "tool", "step"]

    metrics = store.find_eval_run(eval_id).metrics
    assert (metrics["tasks"], metrics["passed"], metrics["success_rate"]) == (4, 2, 0.5)
    assert metrics["failure_categories"] == {"crash": 1, "incomplete": 1}
    assert metrics["by_agent"] == {"echo": {"tasks": 4, "passed": 2}}
    assert metrics["latency_p95_s"] >= metrics["latency_p50_s"]


def test_run_eval_rejects_unknown_agents(store):
    t = Task(id="t", agent="ghost", input="q", expected="e")
    with pytest.raises(ValueError, match="Unknown agents in dataset: ghost"):
        run_eval([t], agents={}, llm=RoutedLLM(), model="m", store=store, judge=None, datasets=[])


def test_run_eval_without_judge_drops_judge_checks(store):
    t = task({"type": "judge"})
    t = t.model_copy(update={"agent": "echo", "input": "a"})
    eval_id = run_eval(
        [t],
        agents={"echo": AGENT},
        llm=RoutedLLM(),
        model="m",
        store=store,
        judge=None,
        datasets=[],
    )
    (result,) = store.eval_results(eval_id)
    assert result.passed and result.checks == []
