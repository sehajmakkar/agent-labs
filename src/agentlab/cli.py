"""Command line.

- `lab run AGENT MESSAGE`: run a demo agent, save the run, print its tree
- `lab runs`: list recent runs
- `lab show RUN_ID`: print a saved run's tree (an ID prefix is enough)
- `lab models`: list the Gemini models your API key can use
"""

import argparse
import sys
from datetime import UTC

from google.genai import errors

from agentlab import tracing
from agentlab.config import Settings, load_settings
from agentlab.llm.base import TransientLLMError
from agentlab.llm.gemini import GeminiClient
from agentlab.loop import Agent, run_agent
from agentlab.render import render_run
from agentlab.store import Store


def _demo_agents() -> dict[str, Agent]:
    from agents.support import AGENT as support

    return {support.name: support}


def main(argv: list[str] | None = None) -> int:
    agents = _demo_agents()
    parser = argparse.ArgumentParser(prog="lab", description="Agent Reliability Lab")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run a demo agent on one message and print its trace")
    run.add_argument("agent", choices=sorted(agents))
    run.add_argument("message")
    # Flash-Lite by default: Flash is sometimes unavailable (decisions.md D-014).
    run.add_argument("--model", choices=["flash", "flash-lite"], default="flash-lite")
    run.add_argument("--max-steps", type=int, default=10)
    run.add_argument("--timeout", type=float, default=120, help="seconds for the whole run")

    runs = commands.add_parser("runs", help="list recent runs")
    runs.add_argument("--limit", type=int, default=20)

    show = commands.add_parser("show", help="print the trace of a saved run")
    show.add_argument("run_id", help="a run ID, or the start of one")

    commands.add_parser("models", help="list the Gemini Flash models your API key can use")

    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "runs":
        return _runs(Store(settings.db_path), args.limit)
    if args.command == "show":
        return _show(Store(settings.db_path), args.run_id)

    if not settings.gemini_api_key:
        print(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        return 2
    llm = GeminiClient(api_key=settings.gemini_api_key)
    if args.command == "models":
        return _models(llm, settings)
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


def _runs(store: Store, limit: int) -> int:
    rows = store.runs(limit)
    if not rows:
        print('No runs yet. Try: lab run support "Was I charged twice for order 4417?"')
        return 0
    for run in rows:
        # SQLite drops the timezone; stored times are UTC, shown in local time.
        started = run.started_at.replace(tzinfo=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        message = (run.input or {}).get("message", "")
        print(f"{run.id[:8]}  {started}  {run.agent_name:10} {run.status:10} {message[:60]}")
    return 0


def _show(store: Store, run_id: str) -> int:
    try:
        run = store.find_run(run_id)
    except LookupError as e:
        print(e, file=sys.stderr)
        return 1
    print(render_run(run, store.spans(run.id)))
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


if __name__ == "__main__":
    sys.exit(main())
