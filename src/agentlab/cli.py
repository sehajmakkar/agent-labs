"""Command line.

- `lab run AGENT MESSAGE`: run a demo agent, save the run, print its tree
- `lab runs`: list recent runs
- `lab show RUN_ID`: print a saved run's tree (an ID prefix is enough)
- `lab eval DATASET...`: run every task in one or more datasets, score them, print a report
- `lab evals`: list recent eval runs
- `lab report EVAL_ID`: print an eval run's report again
- `lab replay RUN_ID`: re-run a recorded run from its recordings (no network) and check it matches
- `lab fidelity`: replay recent runs and report how many reproduce exactly
- `lab fork RUN_ID --step N --prompt …`: rerun from a step with one change, N times, vs a control
- `lab worker`: run fork jobs queued from the UI, with this repo's agent code
- `lab diff RUN_A RUN_B`: line two runs up step by step and show where they diverge
- `lab ui`: serve the web UI and its API
- `lab models`: list the Gemini models your API key can use
"""

import argparse
import sys
from datetime import UTC
from pathlib import Path

from google.genai import errors

from agentlab import tracing
from agentlab.config import Settings, load_settings
from agentlab.demo import demo_agents
from agentlab.llm.base import TransientLLMError
from agentlab.llm.gemini import GeminiClient
from agentlab.loop import Agent, run_agent
from agentlab.render import render_eval, render_run
from agentlab.store import Store, run_message

TIERS = ["flash", "flash-lite"]


def main(argv: list[str] | None = None) -> int:
    agents = demo_agents()
    parser = argparse.ArgumentParser(prog="lab", description="Agent Reliability Lab")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run a demo agent on one message and print its trace")
    run.add_argument("agent", choices=sorted(agents))
    run.add_argument("message")
    # Flash-Lite by default: Flash is sometimes unavailable (decisions.md D-014).
    run.add_argument("--model", choices=TIERS, default="flash-lite")
    run.add_argument("--max-steps", type=int, default=10)
    run.add_argument("--timeout", type=float, default=120, help="seconds for the whole run")

    runs = commands.add_parser("runs", help="list recent runs")
    runs.add_argument("--limit", type=int, default=20)

    show = commands.add_parser("show", help="print the trace of a saved run")
    show.add_argument("run_id", help="a run ID, or the start of one")

    ev = commands.add_parser("eval", help="run and score every task in one or more datasets")
    ev.add_argument("datasets", nargs="+", help="JSONL dataset files")
    ev.add_argument("--model", choices=TIERS, default="flash-lite")
    ev.add_argument("--judge-model", choices=TIERS, default="flash-lite")
    ev.add_argument("--no-judge", action="store_true", help="skip LLM-judge checks")
    ev.add_argument("--tasks", help="only these task IDs, comma-separated")
    ev.add_argument("--concurrency", type=int, default=4)
    ev.add_argument("--max-steps", type=int, default=10)
    ev.add_argument("--timeout", type=float, default=120, help="seconds per task")

    evals = commands.add_parser("evals", help="list recent eval runs")
    evals.add_argument("--limit", type=int, default=20)

    report = commands.add_parser("report", help="print the report of a saved eval run")
    report.add_argument("eval_id", help="an eval run ID, or the start of one")

    rp = commands.add_parser("replay", help="replay a run from its recordings, offline")
    rp.add_argument("run_id", help="a run ID, or the start of one")
    rp.add_argument(
        "--entry",
        help="for runs of your own agent: the @lab.agent function, as FILE.py:FUNCTION or "
        "MODULE:FUNCTION",
    )

    fid = commands.add_parser("fidelity", help="replay recent demo-agent runs and score them")
    fid.add_argument("--limit", type=int, default=20)

    fk = commands.add_parser("fork", help="rerun a run from a step with one change, N times")
    fk.add_argument("run_id", help="a run ID, or the start of one")
    where = fk.add_mutually_exclusive_group(required=True)
    where.add_argument(
        "--step",
        type=int,
        help="fork at this step (the model decides it again); for agents with their own loop, "
        "the N-th model call",
    )
    where.add_argument("--tool", help="fork at this tool's first call (change its output)")
    where.add_argument("--span", help="fork at this span ID")
    fk.add_argument("--prompt", help="replace the system prompt from the fork point on")
    fk.add_argument("--append-prompt", help="add this to the end of the recorded system prompt")
    fk.add_argument("--model", help="flash, flash-lite, or a model ID, for the live part")
    fk.add_argument("--tool-output", help="JSON that replaces the forked tool call's result")
    fk.add_argument("-n", type=int, default=5, help="runs with the change (and without it)")
    fk.add_argument("--no-control", action="store_true", help="skip the N runs without the change")
    fk.add_argument("--no-judge", action="store_true", help="skip LLM-judge checks when scoring")
    fk.add_argument("--entry", help="for your own agent: FILE.py:FUNCTION or MODULE:FUNCTION")

    wk = commands.add_parser("worker", help="run fork jobs queued in the lab, with this code")
    wk.add_argument("--server", help="a lab server URL; default: the local database")
    wk.add_argument("--entry", help="your agent's @lab.agent function, FILE.py:FUNCTION")
    wk.add_argument("--once", action="store_true", help="run at most one job, then exit")
    wk.add_argument("--no-judge", action="store_true")

    df = commands.add_parser("diff", help="compare two runs step by step")
    df.add_argument("run_a", help="a run ID, or the start of one")
    df.add_argument("run_b", help="a run ID, or the start of one")

    ui = commands.add_parser("ui", help="serve the web UI and its API")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8000)
    ui.add_argument("--no-worker", action="store_true", help="don't run fork jobs in-process")

    commands.add_parser("models", help="list the Gemini Flash models your API key can use")

    args = parser.parse_args(argv)
    settings = load_settings()

    # Commands that only read the store don't need an API key.
    if args.command == "runs":
        return _runs(Store(settings.db_path), args.limit)
    if args.command == "show":
        return _show(Store(settings.db_path), args.run_id)
    if args.command == "diff":
        return _diff(Store(settings.db_path), args.run_a, args.run_b)
    if args.command == "evals":
        return _evals(Store(settings.db_path), args.limit)
    if args.command == "report":
        return _report(Store(settings.db_path), args.eval_id)
    if args.command == "ui":
        return _ui(settings, agents, args.host, args.port, worker=not args.no_worker)
    # Replays never call Gemini, so they need no API key either.
    if args.command == "replay":
        return _replay(settings, agents, args.run_id, args.entry)
    if args.command == "fidelity":
        return _fidelity(settings, agents, args.limit)

    if not settings.gemini_api_key:
        print(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        return 2
    llm = GeminiClient(
        api_key=settings.gemini_api_key, requests_per_minute=settings.requests_per_minute or None
    )
    if args.command == "models":
        return _models(llm, settings)
    if args.command == "eval":
        return _eval(llm, settings, agents, args)
    if args.command == "fork":
        return _fork(llm, settings, agents, args)
    if args.command == "worker":
        return _worker(llm, settings, agents, args)
    return _run(llm, settings, agents[args.agent], args)


def _run(llm: GeminiClient, settings: Settings, agent: Agent, args: argparse.Namespace) -> int:
    store = tracing.init(settings.db_path)
    model = settings.model_for(args.model)
    print(f"running {agent.name} on {model} …\n")
    try:
        result = run_agent(
            agent,
            llm=llm,
            model=model,
            user_message=args.message,
            max_steps=args.max_steps,
            timeout_s=args.timeout,
        )
    except (errors.APIError, TransientLLMError) as e:
        # The run is saved with status "error"; show its tree so the failed attempts are visible.
        latest = store.runs(limit=1)[0]
        print(render_run(latest, store.spans(latest.id)))
        print(f"\n{e}", file=sys.stderr)
        if isinstance(e, errors.APIError) and e.code == 404:
            print("The model ID may be wrong: run `lab models` and update .env.", file=sys.stderr)
        return 1

    run = store.find_run(result.run_id)
    print(render_run(run, store.spans(run.id)))
    print(f"\n{result.answer or '(no answer)'}")
    return 0 if result.status == "completed" else 1


def _eval(
    llm: GeminiClient, settings: Settings, agents: dict[str, Agent], args: argparse.Namespace
) -> int:
    from agentlab.evals import LLMJudge, load_dataset, run_eval
    from agentlab.evals.runner import TaskOutcome

    try:
        tasks = [t for path in args.datasets for t in load_dataset(path)]
    except (OSError, ValueError) as e:
        print(e, file=sys.stderr)
        return 2
    if args.tasks:
        wanted = set(args.tasks.split(","))
        tasks = [t for t in tasks if t.id in wanted]
    if not tasks:
        print("No tasks to run.", file=sys.stderr)
        return 2

    store = tracing.init(settings.db_path)
    model = settings.model_for(args.model)
    judge = None if args.no_judge else LLMJudge(llm, settings.model_for(args.judge_model))
    print(f"evaluating {len(tasks)} tasks on {model}, judge {judge.model if judge else 'off'} …\n")

    def progress(outcome: TaskOutcome) -> None:
        mark = "✓" if outcome.passed else f"✗ {outcome.category}"
        print(f"  {outcome.task.id:28} {mark}", flush=True)

    eval_id = run_eval(
        tasks,
        agents=agents,
        llm=llm,
        model=model,
        store=store,
        judge=judge,
        datasets=args.datasets,
        concurrency=args.concurrency,
        max_steps=args.max_steps,
        timeout_s=args.timeout,
        on_result=progress,
    )
    print()
    return _report(store, eval_id)


def _replay(settings: Settings, agents: dict[str, Agent], run_id: str, entry: str | None) -> int:
    from agentlab.replay.runner import load_entry, replay_run

    store = tracing.init(settings.db_path)
    try:
        source = store.find_run(run_id)
        result = replay_run(
            store, source.id, agents=agents, entry=load_entry(entry) if entry else None
        )
    except (LookupError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1
    replay = store.get_run(result.run_id)
    print(render_run(replay, store.spans(replay.id)))
    print(f"\nreplay of {source.id[:8]}: {result.report.summary()}")
    for difference in result.report.differences[:10]:
        print(f"  ✗ {difference}")
    print("no model or tool calls were made: every response came from the recording")
    return 0 if result.report.identical else 1


def _fidelity(settings: Settings, agents: dict[str, Agent], limit: int) -> int:
    from agentlab.replay.runner import replay_run

    store = tracing.init(settings.db_path)
    sources = [r for r in store.runs(500) if r.mode != "replay" and r.agent_name in agents][:limit]
    if not sources:
        print("No recorded runs of the demo agents yet.")
        return 0
    identical = 0
    for source in sources:
        result = replay_run(store, source.id, agents=agents)
        identical += result.report.identical
        mark = "✓" if result.report.identical else "✗"
        line = f"{mark} {source.id[:8]}  {source.agent_name:8} {source.task_id or '':28} "
        first = result.report.differences[0] if result.report.differences else ""
        print(line + (result.report.summary() if result.report.identical else first)[:110])
    print(
        f"\nreplay fidelity: {identical}/{len(sources)} runs reproduced exactly "
        f"({identical / len(sources):.0%})"
    )
    return 0


def _runs(store: Store, limit: int) -> int:
    rows = store.runs(limit)
    if not rows:
        print('No runs yet. Try: lab run support "Was I charged twice for order 4417?"')
        return 0
    for run in rows:
        message = run_message(run)
        if run.mode == "replay":
            message = f"↺ replay of {run.parent_run_id[:8]}"
        print(
            f"{run.id[:8]}  {_local(run.started_at)}  {run.agent_name:10} {run.status:10} "
            f"{message[:60]}"
        )
    return 0


def _show(store: Store, run_id: str) -> int:
    try:
        run = store.find_run(run_id)
    except LookupError as e:
        print(e, file=sys.stderr)
        return 1
    print(render_run(run, store.spans(run.id)))
    return 0


def _diff(store: Store, run_a: str, run_b: str) -> int:
    from agentlab.diff import diff_runs
    from agentlab.render import render_diff

    try:
        a, b = store.find_run(run_a), store.find_run(run_b)
    except LookupError as e:
        print(e, file=sys.stderr)
        return 1
    print(render_diff(diff_runs(store, a.id, b.id)))
    return 0


def _evals(store: Store, limit: int) -> int:
    rows = store.eval_runs(limit)
    if not rows:
        print("No eval runs yet. Try: lab eval datasets/support.jsonl datasets/triage.jsonl")
        return 0
    for row in rows:
        m = row.metrics or {}
        score = f"{m['passed']}/{m['tasks']}" if m else row.status
        print(
            f"{row.id[:8]}  {_local(row.started_at)}  {row.model:24} {score:8} "
            f"{', '.join(row.datasets)}"
        )
    return 0


def _report(store: Store, eval_id: str) -> int:
    try:
        eval_run = store.find_eval_run(eval_id)
    except LookupError as e:
        print(e, file=sys.stderr)
        return 1
    results = store.eval_results(eval_run.id)
    run_ids = [r.run_id for r in results]
    runs = {run_id: store.get_run(run_id) for run_id in run_ids}
    print(render_eval(eval_run, results, runs, store.run_totals(run_ids)))
    return 0


def _ui(settings: Settings, agents: dict[str, Agent], host: str, port: int, worker: bool) -> int:
    import threading

    import uvicorn

    from agentlab.server import create_app

    store = tracing.init(settings.db_path)
    stop = threading.Event()
    if worker and settings.gemini_api_key:
        # Fork jobs queued from the UI run in this process, for the demo agents. Customer agents
        # need `lab worker --entry …` in their own repo.
        from agentlab.fork.worker import work

        llm = GeminiClient(
            settings.gemini_api_key, requests_per_minute=settings.requests_per_minute or None
        )
        threading.Thread(
            target=work,
            kwargs=dict(_fork_context(llm, settings, agents, judge=True), store=store, stop=stop),
            daemon=True,
        ).start()
        print("fork worker running for the demo agents")
    elif worker:
        print("No GEMINI_API_KEY: forks will wait in the queue until a `lab worker` runs them")
    print(f"Agent Reliability Lab UI on http://{host}:{port}")
    try:
        uvicorn.run(create_app(store), host=host, port=port, log_level="warning")
    finally:
        stop.set()
    return 0


def _fork_context(
    llm: GeminiClient, settings: Settings, agents: dict[str, Agent], *, judge: bool, entry=None
) -> dict:
    """What a fork needs besides the store: the model client, agents, judge and eval tasks."""
    from agentlab.evals import LLMJudge
    from agentlab.evals.tasks import load_tasks

    return {
        "llm": llm,
        "agents": None if entry else agents,
        "entry": entry,
        "judge": LLMJudge(llm, settings.flash_lite_model) if judge else None,
        "tasks": load_tasks(settings.datasets_dir) if Path(settings.datasets_dir).is_dir() else {},
    }


def _fork(
    llm: GeminiClient, settings: Settings, agents: dict[str, Agent], args: argparse.Namespace
) -> int:
    import json

    from agentlab.fork.point import resolve_fork_point
    from agentlab.fork.runner import execute_fork
    from agentlab.replay.runner import load_entry
    from agentlab.replay.session import Override

    store = tracing.init(settings.db_path)
    try:
        source = store.find_run(args.run_id)
        span_id = args.span or _find_span(store, source.id, step=args.step, tool=args.tool)
        point = resolve_fork_point(store, source.id, span_id)
    except (LookupError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1

    prompt = args.prompt
    if args.append_prompt:
        prompt = (_recorded_prompt(store, source.id) or "") + "\n" + args.append_prompt
    model = settings.model_for(args.model) if args.model in TIERS else args.model
    override = Override(
        system_prompt=prompt,
        model=model,
        tool_output=json.loads(args.tool_output) if args.tool_output else None,
    )
    fork_id = store.create_fork(
        source_run_id=source.id,
        span_id=point.span_id,
        label=point.label,
        override=override.model_dump(exclude_none=True),
        n=args.n,
        control=not args.no_control,
        status="running",
        worker="cli",
    )
    entry = load_entry(args.entry) if args.entry else None
    context = _fork_context(llm, settings, agents, judge=not args.no_judge, entry=entry)
    plan = f"{args.n} with the change" + ("" if args.no_control else f", {args.n} without")
    print(f"forking {source.id[:8]} at {point.label}: {plan} …\n")

    def progress(role: str, result: dict) -> None:
        if result["passed"] is None:
            mark = result["status"]
        else:
            mark = "✓" if result["passed"] else f"✗ {result['category']}"
        print(f"  {role:7} {result['run_id'][:8]}  {mark:22} {(result['answer'] or '')[:70]!r}")

    try:
        summary = execute_fork(store, store.get_fork(fork_id), on_run=progress, **context)
    except Exception as e:
        store.finish_fork(fork_id, error=f"{type(e).__name__}: {e}")
        raise
    store.finish_fork(fork_id, summary=summary)
    print(f"\nfork {fork_id[:8]}")
    for role in ("fork", "control"):
        group = summary[role]
        if group and group["passed"] is not None:
            print(
                f"  {'with the change' if role == 'fork' else 'without (control)':18} "
                f"{group['passed']}/{group['n']} pass"
            )
    if summary["p_value"] is not None:
        print(f"  p = {summary['p_value']:.4f} (Fisher's exact test)")
    print(f"  {summary['verdict']}")
    return 0


def _worker(
    llm: GeminiClient, settings: Settings, agents: dict[str, Agent], args: argparse.Namespace
) -> int:
    from agentlab.fork.worker import work
    from agentlab.replay.runner import load_entry

    store = tracing.init(args.server or settings.db_path)
    entry = load_entry(args.entry) if args.entry else None
    if entry is not None:
        tracing.init(store)  # the entry module may have called lab.init with its own target
    where = args.server or settings.db_path
    names = entry.agent_name if entry else ", ".join(sorted(agents))
    print(f"worker for {names}, taking fork jobs from {where} (Ctrl-C to stop)")
    try:
        work(
            store,
            once=args.once,
            **_fork_context(llm, settings, agents, judge=not args.no_judge, entry=entry),
        )
    except KeyboardInterrupt:
        pass
    return 0


def _find_span(store: Store, run_id: str, *, step: int | None, tool: str | None) -> str:
    spans = store.spans(run_id)
    for s in spans:
        if (
            step is not None
            and s.kind == "step"
            and s.attributes.get("agentlab.step.index") == step
        ):
            return s.id
        if tool and s.kind == "tool" and s.attributes.get("gen_ai.tool.name") == tool:
            return s.id
    # An agent with its own loop has no step spans: then step N means its N-th model call.
    model_calls = [s for s in spans if s.kind == "llm"]
    has_steps = any(s.kind == "step" for s in spans)
    if step is not None and not has_steps and 0 < step <= len(model_calls):
        return model_calls[step - 1].id
    raise LookupError(f"Run {run_id[:8]} has no " + (f"step {step}" if step else f"call to {tool}"))


def _recorded_prompt(store: Store, run_id: str) -> str | None:
    """The system prompt the run's first model call was sent."""
    for r in store.run_recordings(run_id):
        if r.kind == "llm":
            instruction = (r.request.get("config") or {}).get("system_instruction")
            return instruction if isinstance(instruction, str) else None
    return None


def _models(llm: GeminiClient, settings: Settings) -> int:
    configured = {settings.flash_model: "flash", settings.flash_lite_model: "flash-lite"}
    available = set()
    for model in llm.list_models():
        model_id = (model.name or "").removeprefix("models/")
        if "flash" not in model_id or "generateContent" not in (model.supported_actions or []):
            continue
        available.add(model_id)
        tier = configured.get(model_id)
        print(f"{model_id:40} {'<- configured as ' + tier if tier else ''}")

    missing = [model_id for model_id in configured if model_id not in available]
    for model_id in missing:
        print(f"\nConfigured model {model_id!r} is not available. Set it in .env.", file=sys.stderr)
    return 1 if missing else 0


def _local(started_at) -> str:
    # SQLite drops the timezone; stored times are UTC, shown in local time.
    return started_at.replace(tzinfo=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    sys.exit(main())
