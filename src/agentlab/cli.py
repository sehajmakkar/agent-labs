"""Command line: `lab models` lists the Gemini models you can use; `lab run` runs a demo agent."""

import argparse
import json
import sys

from google.genai import errors

from agentlab.config import Settings, load_settings
from agentlab.llm.gemini import GeminiClient
from agentlab.loop import Agent, Step, run_agent


def _demo_agents() -> dict[str, Agent]:
    from agents.support import AGENT as support

    return {support.name: support}


def main(argv: list[str] | None = None) -> int:
    agents = _demo_agents()
    parser = argparse.ArgumentParser(prog="lab", description="Agent Reliability Lab")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("models", help="list the Gemini Flash models your API key can use")

    run = commands.add_parser("run", help="run a demo agent on one message")
    run.add_argument("agent", choices=sorted(agents))
    run.add_argument("message")
    # Flash-Lite by default: Flash is sometimes unavailable (decisions.md D-014).
    run.add_argument("--model", choices=["flash", "flash-lite"], default="flash-lite")
    run.add_argument("--max-steps", type=int, default=10)

    args = parser.parse_args(argv)
    settings = load_settings()
    if not settings.gemini_api_key:
        print(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        return 2
    llm = GeminiClient(api_key=settings.gemini_api_key)

    try:
        if args.command == "models":
            return _models(llm, settings)
        return _run(llm, settings, agents[args.agent], args)
    except errors.APIError as e:
        print(f"Gemini API error {e.code}: {e.message}", file=sys.stderr)
        if e.code == 404:
            print("The model ID may be wrong: run `lab models` and update .env.", file=sys.stderr)
        return 1


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


def _run(llm: GeminiClient, settings: Settings, agent: Agent, args: argparse.Namespace) -> int:
    model = settings.model_for(args.model)
    print(f"agent: {agent.name}   model: {model}\n")
    result = run_agent(
        agent,
        llm=llm,
        model=model,
        user_message=args.message,
        max_steps=args.max_steps,
        on_step=_print_step,
    )

    usage = result.usage
    print(f"\n{result.answer or '(no answer)'}\n")
    print(
        f"{result.status} · {len(result.steps)} model calls · {usage.input_tokens} input tokens · "
        f"{usage.output_tokens} output tokens · {usage.thinking_tokens} thinking tokens"
    )
    return 0 if result.status == "completed" else 1


def _print_step(step: Step) -> None:
    print(f"step {step.index}: model")
    for result in step.tool_results:
        marker = "✗" if result.is_error else "←"
        print(f"  → {result.call.name}({json.dumps(result.call.args)})")
        print(f"  {marker} {json.dumps(result.output)}")


if __name__ == "__main__":
    sys.exit(main())
