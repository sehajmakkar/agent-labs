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
    # Seeded-bug variants are included, so their runs can be replayed, forked and blamed.
    agents = demo_agents(seeded=True)
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
    ev.add_argument(
        "--gate",
        type=float,
        help="CI gate: exit 1 if the success rate is below this (0–1) or any regression test fails",
    )

    sn = commands.add_parser("snapshot", help="copy the trace store, compressed, to seed a host")
    sn.add_argument("--out", default="deploy/seed.db.gz")

    lk = commands.add_parser("lock-in", help="save a failed run as a regression test")
    lk.add_argument("run_id", help="a failed run from an eval task (an ID prefix is enough)")

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

    bl = commands.add_parser(
        "blame", help="find the step that made a failed run fail, and prove it"
    )
    bl.add_argument("run_id", help="a failed run from an eval task (an ID prefix is enough)")
    bl.add_argument("-n", type=int, default=5, help="runs per verification fork and control")
    bl.add_argument("-k", type=int, default=2, help="verify at most this many candidates")
    bl.add_argument("--judge-model", choices=TIERS, default="flash-lite")

    bb = commands.add_parser("blame-bench", help="blame accuracy on the seeded failures")
    bb.add_argument("--judges", default="flash-lite,flash", help="judge models to compare")
    bb.add_argument(
        "--verify", type=int, default=0, help="also run full blame on this many failures"
    )
    bb.add_argument("-n", type=int, default=3, help="runs per fork when verifying")
    bb.add_argument(
        "--no-prompt", action="store_true", help="hide the agent's system prompt from the judge"
    )

    sd = commands.add_parser("seed-failures", help="run the seeded bugs to make failures to blame")
    sd.add_argument("--runs", type=int, default=5, help="runs per seeded bug")
    sd.add_argument("--bugs", help="only these bug IDs, comma-separated")

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
    if args.command == "snapshot":
        return _snapshot(settings, args.out)
    if args.command == "lock-in":
        return _lock_in(Store(settings.db_path), settings, args.run_id)
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
    if args.command == "seed-failures":
        return _seed(llm, settings, agents, args)
    if args.command == "blame":
        return _blame(llm, settings, agents, args)
    if args.command == "blame-bench":
        return _blame_bench(llm, settings, agents, args)
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
    _report(store, eval_id)
    if args.gate is None:
        return 0
    from agentlab.evals.regressions import check_gate

    gate = check_gate(store.eval_results(eval_id), {t.id: t for t in tasks}, args.gate)
    print()
    if gate.passed:
        print(f"GATE PASSED: {gate.success_rate:.0%} ≥ {gate.threshold:.0%}, no regressions")
        return 0
    print("GATE FAILED:")
    for reason in gate.reasons:
        print(f"  ✗ {reason}")
    return 1


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


def _snapshot(settings: Settings, out: str) -> int:
    from agentlab.hosting import snapshot

    try:
        size = snapshot(settings.db_path, out)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"wrote {out} ({size / 1e6:.1f} MB): the hosted lab starts from it (deploy/start.sh)")
    return 0


def _lock_in(store: Store, settings: Settings, run_id: str) -> int:
    from agentlab.evals.regressions import REGRESSIONS_FILE, lock_in
    from agentlab.evals.tasks import load_tasks

    try:
        run = store.find_run(run_id)
        task, created = lock_in(
            store,
            run.id,
            tasks=load_tasks(settings.datasets_dir),
            datasets_dir=settings.datasets_dir,
        )
    except (LookupError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1
    where = f"{settings.datasets_dir}/{REGRESSIONS_FILE}"
    print(f"{'saved' if created else 'already saved'}: {task.id} in {where}")
    if task.origin and task.origin.get("correction"):
        print(
            f"  extra check from blame (step {task.origin['blamed_step']}): "
            f"{task.origin['correction']}"
        )
    print(f"  run it in CI: lab eval {settings.datasets_dir}/*.jsonl --gate 0.9")
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

    from agentlab.fork.point import recorded_system_prompt, resolve_fork_point
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
        prompt = (recorded_system_prompt(store, source.id) or "") + "\n" + args.append_prompt
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


def _seed(
    llm: GeminiClient, settings: Settings, agents: dict[str, Agent], args: argparse.Namespace
) -> int:
    from agentlab.blame.bench import seed_failures, seeded_failures
    from agentlab.blame.catalog import BUGS, BUGS_BY_ID
    from agentlab.evals import LLMJudge
    from agentlab.evals.tasks import load_tasks

    store = tracing.init(settings.db_path)
    bugs = [BUGS_BY_ID[b] for b in args.bugs.split(",")] if args.bugs else BUGS
    print(f"seeding {len(bugs)} bugs × {args.runs} runs on {settings.flash_lite_model} …\n")

    def progress(bug, outcome) -> None:
        mark = "✓ passed anyway" if outcome.passed else f"✗ {outcome.category}"
        print(f"  {bug.id:18} {outcome.run_id[:8]}  {mark}", flush=True)

    seed_failures(
        store,
        llm=llm,
        model=settings.flash_lite_model,
        agents=agents,
        tasks=load_tasks(settings.datasets_dir),
        judge=LLMJudge(llm, settings.flash_lite_model),
        runs=args.runs,
        bugs=bugs,
        on_result=progress,
    )
    failures = seeded_failures(store)
    print(f"\n{len(failures)} seeded failures with a known guilty step are ready to blame")
    return 0


def _blame(
    llm: GeminiClient, settings: Settings, agents: dict[str, Agent], args: argparse.Namespace
) -> int:
    from agentlab.blame.propose import BlameJudge
    from agentlab.blame.runner import execute_blame

    store = tracing.init(settings.db_path)
    try:
        source = store.find_run(args.run_id)
    except LookupError as e:
        print(e, file=sys.stderr)
        return 1
    judge_model = settings.model_for(args.judge_model)
    blame_id = store.create_blame(
        source_run_id=source.id,
        judge_model=judge_model,
        n=args.n,
        max_candidates=args.k,
        status="running",
        worker="cli",
    )
    context = _fork_context(llm, settings, agents, judge=True)
    shown: set = set()

    def progress(report: dict) -> None:
        if "proposal" not in shown:
            shown.add("proposal")
            print(f"judge ({report['judge_model']}): {report['analysis']}\n")
            for c in report["candidates"]:
                print(f"  #{c['rank']} step {c['step']}: {c['reasoning']}")
                print(f"      correction: {c['correction']}")
            print()
        for c in report["candidates"]:
            v = c["verification"]
            if v and c["rank"] not in shown:
                shown.add(c["rank"])
                later = (
                    f", one step later {v['later_passed']}/{v['n']}"
                    if v["later_passed"] is not None
                    else ""
                )
                print(
                    f"  verify step {c['step']}: corrected {v['passed']}/{v['n']} vs control "
                    f"{v['control_passed']}/{v['n']}{later} → {v['status']}"
                )

    print(f"blaming {source.id[:8]} ({source.task_id}) …\n")
    try:
        report = execute_blame(
            store,
            store.get_blame(blame_id),
            blame_judge=BlameJudge(llm, judge_model),
            tasks=context["tasks"],
            fork_context=context,
            on_progress=progress,
        )
    except Exception as e:
        store.finish_blame(blame_id, error=f"{type(e).__name__}: {e}")
        print(e, file=sys.stderr)
        return 1
    store.finish_blame(blame_id, report=report)
    print(f"\nblame {blame_id[:8]} · confidence {report['confidence'] or 'none'}")
    print(report["verdict"])
    return 0


def _blame_bench(
    llm: GeminiClient, settings: Settings, agents: dict[str, Agent], args: argparse.Namespace
) -> int:
    from agentlab.blame.bench import benchmark_proposals, benchmark_verification, seeded_failures
    from agentlab.blame.propose import BlameJudge
    from agentlab.blame.runner import execute_blame

    store = tracing.init(settings.db_path)
    failures = seeded_failures(store)
    if not failures:
        print("No seeded failures yet. Run: lab seed-failures", file=sys.stderr)
        return 1
    context = _fork_context(llm, settings, agents, judge=True)
    judges = {tier: BlameJudge(llm, settings.model_for(tier)) for tier in args.judges.split(",")}
    print(
        f"{len(failures)} seeded failures; judges: {', '.join(j.model for j in judges.values())}\n"
    )
    proposals = benchmark_proposals(
        store,
        failures,
        judges={j.model: j for j in judges.values()},
        tasks=context["tasks"],
        with_prompt=not args.no_prompt,
        on_result=lambda judge, f, rank: print(
            f"  {judge:24} {f.bug.id:18} guilty step {f.guilty_step}: "
            + (f"ranked #{rank}" if rank else "missed"),
            flush=True,
        ),
    )
    results: dict = {
        "failures": len(failures),
        "judge_sees_prompt": not args.no_prompt,
        "proposals": proposals,
    }

    if args.verify:
        sample = _one_per_bug(failures)[: args.verify]
        judge_model = settings.flash_lite_model
        print(f"\nverifying {len(sample)} failures by forking (n={args.n}) …")
        results["verification"] = benchmark_verification(
            store,
            sample,
            judge_model=judge_model,
            n=args.n,
            max_candidates=2,
            run_blame=lambda blame_id: execute_blame(
                store,
                store.get_blame(blame_id),
                blame_judge=BlameJudge(llm, judge_model),
                tasks=context["tasks"],
                fork_context=context,
            ),
            on_result=lambda f, c: print(
                f"  {f.bug.id:18} guilty {f.guilty_step} · proposed {c['proposed']} · "
                f"verified {_or_none(c['blamed'])} ({c['confidence'] or '-'})",
                flush=True,
            ),
        )
    bench_id = store.save_benchmark("blame", results)
    print(f"\nbenchmark {bench_id[:8]} on {len(failures)} seeded failures")
    for model, r in proposals.items():
        print(
            f"  {model:24} top-1 {r['top1']:.0%} · top-3 {r['top3']:.0%} · within one step "
            f"{r['within1']:.0%} · (always-last-step baseline {r['last_step_baseline']:.0%})"
        )
    if "verification" in results:
        v = results["verification"]
        precision = "–" if v["precision"] is None else f"{v['precision']:.0%}"
        print(
            f"  verified ({v['cases']} cases, n={v['n']}): accuracy {v['verified_accuracy']:.0%} · "
            f"precision {precision} · abstained {v['abstained']:.0%}"
        )
    return 0


def _or_none(value: object) -> str:
    return "none" if value is None else str(value)


def _one_per_bug(failures: list) -> list:
    """Round-robin across bugs, so a small sample covers as many bugs as possible."""
    by_bug: dict[str, list] = {}
    for f in failures:
        by_bug.setdefault(f.bug.id, []).append(f)
    ordered = []
    while any(by_bug.values()):
        for bug_failures in by_bug.values():
            if bug_failures:
                ordered.append(bug_failures.pop(0))
    return ordered


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
