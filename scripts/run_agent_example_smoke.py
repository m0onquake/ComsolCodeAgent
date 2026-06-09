"""Run DeepSeek -> AgentLoop -> high-level simulation example tool smoke test."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.agent.loop import AgentLoop
from comsol_agent.agent.tools_bootstrap import register_all_tools
from comsol_agent.agent.tool_registry import clear as clear_tools
from comsol_agent.cli.config import load_config
from comsol_agent.llm.router import create_provider
from comsol_agent.tools.comsol.client import COMSOLClient


async def _run(
    cores: int,
    example_name: str,
    expressions: list[str],
    parameters: dict[str, str],
) -> int:
    config = load_config()
    config.agent.max_tool_iterations = 8
    clear_tools()
    register_all_tools()

    provider = create_provider(
        config.llm.provider,
        model=config.llm.model,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
    )

    client = COMSOLClient.get_instance()
    tool_events: list[tuple[str, dict]] = []
    try:
        client.start(
            cores=cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        agent = AgentLoop(
            llm_provider=provider,
            config=config,
            on_tool_call=lambda name, args: tool_events.append((name, args)),
        )
        response = await agent.run(
            "Run the built-in COMSOL example model using the high-level "
            f"simulation_run_example_model tool. Use example_name={example_name}, "
            f"expressions={expressions}, parameters={parameters}, solve=true, close_model=true. "
            "Do not call the lower-level COMSOL tools unless the high-level tool fails. "
            "Afterward, summarize the evaluation statistics."
        )
        print("Agent response:")
        print(response)
        print("Tool events:")
        for name, args in tool_events:
            print(f"- {name}: {args}")

        tool_results = _tool_results(agent.state.messages)
        for result in tool_results:
            payload = result["payload"]
            compact = {
                "success": payload.get("success"),
                "model_name": payload.get("model_name"),
                "error": payload.get("error"),
            }
            if "evaluation" in payload:
                compact["statistics"] = [
                    evaluation.get("statistics")
                    for evaluation in payload.get("evaluations", [])
                ]
            print(f"- {result['name']}: {compact}")

        if not any(name == "simulation_run_example_model" for name, _ in tool_events):
            print("Agent did not call simulation_run_example_model.")
            return 1
        if not any(
            result["name"] == "simulation_run_example_model"
            and result["payload"].get("success") is True
            for result in tool_results
        ):
            print("simulation_run_example_model did not succeed.")
            return 1

        print("Agent example smoke test succeeded.")
        return 0
    finally:
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def _tool_results(messages: list[dict]) -> list[dict]:
    results = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        results.append({
            "name": message.get("name"),
            "payload": json.loads(message.get("content") or "{}"),
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run high-level simulation example agent smoke.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit.")
    parser.add_argument("--example-name", default="thermal_slab", help="Built-in example name.")
    parser.add_argument(
        "--expression",
        action="append",
        dest="expressions",
        default=None,
        help="Expression to evaluate. Can be repeated. Defaults to T.",
    )
    parser.add_argument(
        "--parameter",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Parameter assignment to set before solving. Can be repeated.",
    )
    args = parser.parse_args()
    expressions = args.expressions or ["T"]
    raise SystemExit(asyncio.run(
        _run(args.cores, args.example_name, expressions, _parse_parameters(args.parameter))
    ))


def _parse_parameters(assignments: list[str]) -> dict[str, str]:
    parameters = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"Invalid parameter assignment: {assignment!r}")
        name, value = assignment.split("=", 1)
        if not name or not value:
            raise ValueError(f"Invalid parameter assignment: {assignment!r}")
        parameters[name] = value
    return parameters


if __name__ == "__main__":
    main()
