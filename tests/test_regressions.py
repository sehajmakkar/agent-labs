import json

from fastapi.testclient import TestClient
from test_blame import FIX, blame
from test_fork import TASK, record_source

from agentlab.evals.regressions import REGRESSIONS_FILE, check_gate, lock_in
from agentlab.evals.tasks import Task, load_dataset
from agentlab.server import create_app
from agentlab.store import EvalResultRow


def test_a_blamed_failure_becomes_a_regression_test_with_the_proved_rule(store, tmp_path):
    report, _ = blame(store, (3, FIX), n=2, k=1)  # blames the refund-ID failure at step 3
    source = next(r for r in store.runs(500) if r.mode == "record")
    store.finish_blame(store.blames_of(source.id)[0].id, report=report)

    task, created = lock_in(store, source.id, tasks={TASK.id: TASK}, datasets_dir=tmp_path)

    assert created and task.id == f"regression-{TASK.id}-{source.id[:8]}"
    assert task.input == TASK.input and "regression" in task.tags
    assert task.checks[: len(TASK.checks)] == TASK.checks  # the original checks, plus…
    assert task.checks[-1].type == "judge" and FIX in task.checks[-1].rubric  # …the proved rule
    assert task.origin["blamed_step"] == 3 and task.origin["correction"] == FIX
    (saved,) = load_dataset(tmp_path / REGRESSIONS_FILE)
    assert saved == task


def test_locking_in_twice_does_not_duplicate(store, tmp_path):
    source = record_source()
    first, created = lock_in(store, source, tasks={TASK.id: TASK}, datasets_dir=tmp_path)
    again, created_again = lock_in(store, source, tasks={TASK.id: TASK}, datasets_dir=tmp_path)
    assert (created, created_again) == (True, False) and first.id == again.id
    assert len(load_dataset(tmp_path / REGRESSIONS_FILE)) == 1
    assert first.checks == TASK.checks  # no blame: just the original checks


def result(
    task_id: str, passed: bool, detail: str = "answer is missing 'RF-1001'"
) -> EvalResultRow:
    checks = [{"type": "answer_contains", "passed": passed, "category": None, "detail": detail}]
    return EvalResultRow(eval_run_id="e", task_id=task_id, run_id="r", passed=passed, checks=checks)


def test_the_gate_fails_on_a_low_rate_or_any_regression():
    tasks = {
        "a": Task(id="a", agent="x", input="q", expected="e"),
        "reg": Task(id="reg", agent="x", input="q", expected="e", tags=["regression"]),
    }
    ok = [result("a", True)] * 9 + [result("reg", True)]
    assert check_gate(ok, tasks, 0.9).passed

    regressed = [result("a", True)] * 9 + [result("reg", False)]
    gate = check_gate(regressed, tasks, 0.8)  # 90% clears 80%, but a regression came back
    assert not gate.passed
    assert gate.reasons == [
        "regression reg failed again: answer_contains: answer is missing 'RF-1001'"
    ]

    low = [result("a", True)] * 5 + [result("a", False)] * 5
    assert check_gate(low, tasks, 0.9).reasons == ["success rate 50% is below the gate's 90%"]


def test_lock_in_api(store, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLAB_DATASETS", str(tmp_path))
    (tmp_path / "d.jsonl").write_text(TASK.model_dump_json() + "\n")
    source = record_source()
    client = TestClient(create_app(store, ui_dist=None))

    body = client.post("/api/regressions", json={"run_id": source}).json()
    assert body["created"] is True and body["task_id"].startswith("regression-")
    assert client.post("/api/regressions", json={"run_id": source}).json()["created"] is False
    assert client.post("/api/regressions", json={"run_id": "nope"}).status_code == 404
    rows = [json.loads(line) for line in (tmp_path / REGRESSIONS_FILE).read_text().splitlines()]
    assert len(rows) == 1
