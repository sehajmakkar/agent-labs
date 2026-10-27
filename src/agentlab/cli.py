"""Command line.

- `lab run AGENT MESSAGE`: run a demo agent, save the run, print its tree
- `lab runs`: list recent runs
- `lab show RUN_ID`: print a saved run's tree (an ID prefix is enough)
- `lab eval DATASET...`: run every task in one or more datasets, score them, print a report
- `lab evals`: list recent eval runs
- `lab report EVAL_ID`: print an eval run's report again
- `lab replay RUN_ID`: re-run a recorded run from its recordings (no network) and check it matches
- `lab fidelity`: replay recent runs and report how many reproduce exactly
- `lab ui`: serve the web UI and its API
- `lab models`: list the Gemini models your API key can use
"""

import argparse
import sys
from datetime import UTC

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

    ui = commands.add_parser("ui", help="serve the web UI and its API")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8000)

    commands.add_parser("models", help="list the Gemini Flash models your API key can use")

    args = parser.parse_args(argv)
    settings = load_settings()

    # Commands that only read the store don't need an API key.
    if args.command == "runs":
        return _runs(Store(settings.db_path), args.limit)
    if args.command == "show":
        return _show(Store(settings.db_path), args.run_id)
    if args.command == "evals":
        return _evals(Store(settings.db_path), args.limit)
    if args.command == "report":
        return _report(Store(settings.db_path), args.eval_id)
    if args.command == "ui":
        return _ui(Store(settings.db_path), args.host, args.port)
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


def _ui(store: Store, host: str, port: int) -> int:
    import uvicorn

    from agentlab.server import create_app

    print(f"Agent Reliability Lab UI on http://{host}:{port}")
    uvicorn.run(create_app(store), host=host, port=port, log_level="warning")
    return 0


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
