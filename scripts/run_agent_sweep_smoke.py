"""Run DeepSeek -> AgentLoop -> high-level parameter sweep smoke test."""

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
    parameters: dict[str, list[str]],
    expressions: list[str],
    max_cases: int,
    artifact_dir: str | None,
    archive_path: str | None,
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
            "Run a bounded COMSOL parameter sweep using the high-level "
            "simulation_run_parameter_sweep tool. "
            f"Use example_name={example_name}, parameters={parameters}, "
            f"expressions={expressions}, max_cases={max_cases}, solve=true, "
            "persist_results=true, artifact_name='agent_sweep_smoke'"
            f"{', artifact_dir=' + artifact_dir if artifact_dir else ''}"
            f"{', archive_path=' + archive_path if archive_path else ''}. "
            "Do not call lower-level COMSOL tools unless the high-level sweep tool fails. "
            "Afterward, summarize every executed case's evaluation statistics."
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
                "executed_cases": payload.get("executed_cases"),
                "artifacts": payload.get("artifacts"),
                "error": payload.get("error"),
            }
            print(f"- {result['name']}: {compact}")

        if not any(name == "simulation_run_parameter_sweep" for name, _ in tool_events):
            print("Agent did not call simulation_run_parameter_sweep.")
            return 1
        if not any(
            result["name"] == "simulation_run_parameter_sweep"
            and result["payload"].get("success") is True
            for result in tool_results
        ):
            print("simulation_run_parameter_sweep did not succeed.")
            return 1

        print("Agent sweep smoke test succeeded.")
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
    parser = argparse.ArgumentParser(description="Run high-level parameter sweep agent smoke.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit.")
    parser.add_argument("--example-name", default="thermal_slab", help="Built-in example name.")
    parser.add_argument(
        "--parameter",
        action="append",
        default=[],
        metavar="NAME=VALUE1,VALUE2",
        help="Sweep axis. Can be repeated.",
    )
    parser.add_argument(
        "--expression",
        action="append",
        dest="expressions",
        default=None,
        help="Expression to evaluate. Can be repeated. Defaults to T.",
    )
    parser.add_argument("--max-cases", type=int, default=2, help="Maximum cases to execute.")
    parser.add_argument("--artifact-dir", default=None, help="Optional artifact output directory.")
    parser.add_argument("--archive-path", default=None, help="Optional archive SQLite path.")
    args = parser.parse_args()

    parameters = _parse_sweep_parameters(args.parameter) or {"L": ["0.5[mm]"]}
    expressions = args.expressions or ["T"]
    raise SystemExit(asyncio.run(
        _run(
            args.cores,
            args.example_name,
            parameters,
            expressions,
            args.max_cases,
            args.artifact_dir,
            args.archive_path,
        )
    ))


def _parse_sweep_parameters(assignments: list[str]) -> dict[str, list[str]]:
    parameters = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"Invalid sweep parameter assignment: {assignment!r}")
        name, values = assignment.split("=", 1)
        value_list = [value.strip() for value in values.split(",") if value.strip()]
        if not name or not value_list:
            raise ValueError(f"Invalid sweep parameter assignment: {assignment!r}")
        parameters[name] = value_list
    return parameters


if __name__ == "__main__":
    main()
