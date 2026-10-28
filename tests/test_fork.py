from types import SimpleNamespace

import pytest
from fakes import gemini_response

from agentlab import semconv
from agentlab.evals.tasks import Task
from agentlab.fork.point import resolve_fork_point
from agentlab.fork.runner import execute_fork
from agentlab.fork.stats import fisher_exact, verdict
from agentlab.fork.worker import work
from agentlab.llm.gemini import GeminiClient, wrap_genai_client
from agentlab.loop import Agent, run_agent
from agentlab.replay.session import ForkSession, Override
from agentlab.retry import RetryPolicy
from agentlab.tools import tool
from agentlab.tracing import current_run_id

PROMPT = "You are a support agent."
FIXED_PROMPT = PROMPT + " Always give the customer the refund ID."
STATE = {"refunds": [], "real_gateway_calls": 0, "simulator_calls": 0}


def _run_refunds() -> list:
    """This run's refunds: like the demo's SupportBackend, each run starts from a clean slate."""
    return STATE.setdefault("by_run", {}).setdefault(current_run_id(), [])


@tool(kind="read")
def get_payments(order_id: str) -> dict:
    """List payments."""
    refunded = {r["payment_id"] for r in _run_refunds()}
    return {
        "payments": [
            {"payment_id": "P-2", "status": "refunded" if "P-2" in refunded else "captured"}
        ]
    }


@tool(kind="write", simulated=True)
def refund_payment(payment_id: str) -> dict:
    """Refund a payment (simulated backend)."""
    STATE["refunds"].append({"payment_id": payment_id})
    _run_refunds().append({"payment_id": payment_id})
    return {"refund_id": f"RF-{1000 + len(_run_refunds())}"}


@tool(kind="write")
def charge_card(amount: int) -> dict:
    """Charge a real card. No simulator."""
    STATE["real_gateway_calls"] += 1
    return {"charged": amount}


@tool(kind="write")
def send_email(to: str) -> dict:
    """Send a real email; has a simulator."""
    STATE["real_gateway_calls"] += 1
    return {"sent": to}


@send_email.simulator
def _fake_send_email(to: str) -> dict:
    STATE["simulator_calls"] += 1
    return {"sent": to, "simulated": True}


AGENT = Agent("shop", PROMPT, [get_payments, refund_payment, charge_card, send_email])


def smart_genai(next_tool: str = "refund_payment", next_args: dict | None = None):
    """A fake Gemini that answers from the request: what was called last, and the prompt."""
    seen = []

    def generate_content(*, model, contents, config):
        seen.append(SimpleNamespace(model=model, contents=contents, config=config))
        last = contents[-1].parts[0]
        if len(contents) == 1:
            part = {
                "function_call": {"id": "c1", "name": "get_payments", "args": {"order_id": "1"}}
            }
            return gemini_response([part])
        if last.function_response and last.function_response.name == "get_payments":
            args = next_args or {"payment_id": "P-2"}
            return gemini_response(
                [{"function_call": {"id": "c2", "name": next_tool, "args": args}}]
            )
        result = last.function_response.response if last.function_response else {}
        if "refund ID" in (config.system_instruction or ""):
            return gemini_response(
                [{"text": f"Refunded. Your refund ID is {result.get('refund_id')}."}]
            )
        return gemini_response([{"text": "Refunded."}])

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return GeminiClient(client=wrap_genai_client(client)), seen


TASK = Task.model_validate(
    {
        "id": "refund-id",
        "agent": "shop",
        "input": "Refund my duplicate charge",
        "expected": "Refunds P-2 and gives the refund ID",
        "checks": [{"type": "answer_contains", "any_of": ["RF-1001"]}],
    }
)


@pytest.fixture(autouse=True)
def reset_state():
    STATE.update(refunds=[], real_gateway_calls=0, simulator_calls=0, by_run={})


def record_source(llm=None) -> str:
    llm = llm or smart_genai()[0]
    result = run_agent(
        AGENT,
        llm=llm,
        model="m",
        user_message=TASK.input,
        task_id=TASK.id,
        retry=RetryPolicy(sleep=lambda _: None),
    )
    STATE.update(refunds=[])  # the next run's world starts fresh, as the demo backend does
    return result.run_id


def step_span(store, run_id, index):
    return next(
        s
        for s in store.spans(run_id)
        if s.kind == "step" and s.attributes[semconv.STEP_INDEX] == index
    )


def fork_once(store, run_id, span_id, override, llm):
    point = resolve_fork_point(store, run_id, span_id)
    session = ForkSession.for_fork(
        run_id,
        store.run_recordings(run_id),
        live_from_seq=point.live_from_seq,
        override=override,
        run_id="fork-1",
        fork_id="f1",
        fork_span_id=point.span_id,
        tool_override_seq=point.tool_override_seq if override.tool_output is not None else None,
    )
    from agentlab.replay.runner import run_in_session

    error = run_in_session(
        store,
        store.get_run(run_id),
        session,
        agents={"shop": AGENT},
        entry=None,
        llm=llm,
        sleep=lambda _: None,
    )
    return session, error


def test_fork_replays_the_prefix_then_goes_live_with_the_new_prompt(store):
    source = record_source()
    llm, seen = smart_genai()

    session, error = fork_once(
        store, source, step_span(store, source, 3).id, Override(system_prompt=FIXED_PROMPT), llm
    )

    assert error is None
    # Steps 1 and 2 came from the recording; only step 3's model call went out, with the new prompt.
    assert len(seen) == 1
    assert seen[0].config.system_instruction == FIXED_PROMPT
    fork = store.get_run("fork-1")
    assert (fork.mode, fork.parent_run_id, fork.fork_id) == ("fork", source, "f1")
    assert fork.fork_override == {"system_prompt": FIXED_PROMPT, "model": None, "tool_output": None}
    assert fork.output == {"answer": "Refunded. Your refund ID is RF-1001."}
    served = [s for s in store.spans("fork-1") if s.attributes.get(semconv.REPLAYED)]
    assert [s.name for s in served] == [
        "chat m",
        "execute_tool get_payments",
        "chat m",
        "execute_tool refund_payment",
    ]


def test_recorded_writes_are_reapplied_so_the_live_part_sees_the_same_world(store):
    source = record_source()
    llm, _ = smart_genai()
    fork_once(store, source, step_span(store, source, 3).id, Override(), llm)
    # The step-2 refund was served from the recording AND re-applied to the simulated backend once.
    assert STATE["refunds"] == [{"payment_id": "P-2"}]


def test_forking_at_a_tool_call_replaces_its_result(store):
    source = record_source()
    llm, seen = smart_genai()
    tool_span = next(s for s in store.spans(source) if s.name == "execute_tool refund_payment")

    fork_once(store, source, tool_span.id, Override(tool_output={"refund_id": "RF-9999"}), llm)

    # The next model call is live and sees the substituted result.
    (call,) = seen
    assert call.contents[-1].parts[0].function_response.response == {"refund_id": "RF-9999"}
    tool = next(s for s in store.spans("fork-1") if s.name == "execute_tool refund_payment")
    assert tool.output == {"refund_id": "RF-9999"}


def test_a_live_write_tool_without_a_simulator_stops_the_fork(store):
    source = record_source(smart_genai("charge_card", {"amount": 5})[0])
    llm, _ = smart_genai("charge_card", {"amount": 5})
    STATE["real_gateway_calls"] = 0

    _, error = fork_once(store, source, step_span(store, source, 2).id, Override(), llm)

    assert type(error).__name__ == "ForkBlocked"
    assert STATE["real_gateway_calls"] == 0
    assert store.get_run("fork-1").status == "error"


def test_a_live_write_tool_runs_its_simulator_not_the_real_function(store):
    source = record_source(smart_genai("send_email", {"to": "a@b.c"})[0])
    llm, _ = smart_genai("send_email", {"to": "a@b.c"})
    STATE.update(real_gateway_calls=0, simulator_calls=0)

    _, error = fork_once(store, source, step_span(store, source, 2).id, Override(), llm)

    assert error is None
    assert (STATE["real_gateway_calls"], STATE["simulator_calls"]) == (0, 1)
    email = next(s for s in store.spans("fork-1") if s.name == "execute_tool send_email")
    assert email.attributes[semconv.SIMULATED] is True


def test_model_override_changes_the_live_model_only(store):
    source = record_source()
    llm, seen = smart_genai()
    fork_once(store, source, step_span(store, source, 3).id, Override(model="bigger"), llm)
    assert [c.model for c in seen] == ["bigger"]
    llm_spans = [s for s in store.spans("fork-1") if s.kind == "llm"]
    assert [s.attributes[semconv.REQUEST_MODEL] for s in llm_spans] == ["m", "m", "bigger"]


def test_live_clock_continues_the_recorded_timeline():
    session = ForkSession.for_fork("r", [], live_from_seq=0, override=Override(), run_id="x")
    session._last_clock["monotonic"] = 1000.0
    assert session.continue_clock("monotonic", 5.0) == 1000.0  # pinned to the last recorded read
    assert session.continue_clock("monotonic", 7.5) == 1002.5  # then moves forward from it
    assert session.continue_clock("time", 42.0) == 42.0  # nothing recorded: the live value


def test_fork_points(store):
    source = record_source()
    spans = store.spans(source)
    step3 = step_span(store, source, 3)
    llm3 = next(s for s in spans if s.kind == "llm" and s.parent_span_id == step3.id)
    assert resolve_fork_point(store, source, llm3.id).span_id == step3.id
    assert resolve_fork_point(store, source, step3.id).label == "step 3"
    tool = next(s for s in spans if s.name == "execute_tool refund_payment")
    point = resolve_fork_point(store, source, tool.id)
    assert point.label == "refund_payment in step 2"
    assert point.tool_override_seq is not None and point.live_from_seq > point.tool_override_seq


def test_a_fork_job_compares_n_forks_with_n_controls(store):
    source = record_source()
    span = step_span(store, source, 3).id
    fork_id = store.create_fork(
        source_run_id=source,
        span_id=span,
        label="step 3",
        override={"system_prompt": FIXED_PROMPT},
        n=5,
        control=True,
    )
    llm, _ = smart_genai()

    summary = execute_fork(
        store, store.get_fork(fork_id), llm=llm, agents={"shop": AGENT}, tasks={TASK.id: TASK}
    )

    assert (summary["fork"]["passed"], summary["control"]["passed"]) == (5, 0)
    assert summary["p_value"] == pytest.approx(2 / 252)
    assert summary["verdict"].startswith("The change fixes it")
    assert len(store.fork_runs(fork_id)) == 10
    results = store.eval_results(fork_id)  # each fork run is scored like an eval task
    assert sum(r.passed for r in results) == 5


def test_claiming_is_atomic_and_filtered_by_agent(store):
    source = record_source()
    span = step_span(store, source, 3).id
    fork_id = store.create_fork(
        source_run_id=source, span_id=span, label="step 3", override={}, n=1, control=False
    )
    assert store.claim_fork(["other-agent"], worker="w0") is None
    assert store.claim_fork(["shop"], worker="w1").id == fork_id
    assert store.claim_fork(["shop"], worker="w2") is None  # already taken
    assert store.get_fork(fork_id).worker == "w1"


def test_the_worker_runs_queued_jobs(store):
    source = record_source()
    span = step_span(store, source, 3).id
    fork_id = store.create_fork(
        source_run_id=source,
        span_id=span,
        label="step 3",
        override={"system_prompt": FIXED_PROMPT},
        n=2,
        control=False,
    )
    llm, _ = smart_genai()
    lines = []

    ran = work(
        store, llm=llm, agents={"shop": AGENT}, tasks={TASK.id: TASK}, once=True, log=lines.append
    )

    fork = store.get_fork(fork_id)
    assert (ran, fork.status, fork.summary["fork"]["passed"]) == (1, "done", 2)
    assert "no control" in fork.summary["verdict"]
    assert any("✓" in line for line in lines)


def test_fisher_exact_and_verdicts():
    assert fisher_exact(5, 0, 0, 5) == pytest.approx(0.00794, abs=1e-5)
    assert fisher_exact(5, 0, 1, 4) == pytest.approx(0.0476, abs=1e-4)
    assert fisher_exact(3, 2, 3, 2) == pytest.approx(1.0)
    assert verdict(4, 5, 4, 1.0).startswith("No difference")
    assert verdict(3, 5, 1, 0.5).startswith("Better")
    assert verdict(1, 5, 4, 0.2) == "Worse than without the change"


def test_old_runs_without_call_order_cannot_be_forked(store):
    import sqlite3

    source = record_source()
    with sqlite3.connect(store.engine.url.database) as db:
        db.execute("UPDATE recordings SET seq = NULL")
    with pytest.raises(ValueError, match="before Phase 3"):
        resolve_fork_point(store, source, step_span(store, source, 3).id)


def test_controls_keep_the_recorded_prompt_even_after_the_code_changed(store):
    source = record_source()
    # The agent's prompt is "fixed" in code after the run was recorded.
    fixed_agent = Agent("shop", FIXED_PROMPT, AGENT.tools)
    llm, seen = smart_genai()
    fork_id = store.create_fork(
        source_run_id=source,
        span_id=step_span(store, source, 3).id,
        label="step 3",
        override={},
        n=1,
        control=False,
    )
    summary = execute_fork(
        store, store.get_fork(fork_id), llm=llm, agents={"shop": fixed_agent}, tasks={TASK.id: TASK}
    )
    # The live call was sent the prompt the run was recorded with, so the fork still fails:
    # it changed nothing, as a control should.
    assert seen[0].config.system_instruction == PROMPT
    assert summary["fork"]["passed"] == 0
