"""Run a real DeepSeek -> AgentLoop -> COMSOL tool-call smoke test."""

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


async def _run(cores: int, model_name: str, output_dir: Path) -> int:
    config = load_config()
    config.agent.max_tool_iterations = 12
    config.agent.auto_repair = True
    output_dir.mkdir(parents=True, exist_ok=True)
    save_path = output_dir / f"{model_name}.mph"

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
        prompt = (
            "Use only COMSOL tools to perform this exact smoke test. "
            f"Create a new COMSOL model named {model_name}. "
            "Set parameter L_agent to 2[mm]. "
            "List the parameters to confirm L_agent exists. "
            f"Save the model to {save_path}. "
            "Close the model without saving again. "
            "After the tools finish, summarize the completed actions in one sentence."
        )
        response = await agent.run(prompt)
        print("Agent response:")
        print(response)
        print("Tool events:")
        for name, args in tool_events:
            print(f"- {name}: {args}")

        tool_results = _collect_tool_results(agent.state.messages)
        _print_tool_results(tool_results)

        required_tools = {
            "comsol_create_model",
            "comsol_set_parameter",
            "comsol_list_parameters",
            "comsol_save_model",
            "comsol_close_model",
        }
        observed_tools = {name for name, _ in tool_events}
        missing = sorted(required_tools - observed_tools)
        if missing:
            print(f"Missing required tool calls: {missing}")
            return 1

        successful_tools = {
            result["name"]
            for result in tool_results
            if result["payload"].get("success") is True
        }
        missing_successes = sorted(required_tools - successful_tools)
        if missing_successes:
            print(f"Missing successful required tool results: {missing_successes}")
            return 1

        recovered_failures = [
            result
            for result in tool_results
            if result["payload"].get("success") is False
            and result["name"] in successful_tools
        ]
        if recovered_failures:
            print(f"Recovered intermediate tool failures: {recovered_failures}")

        if not save_path.exists():
            print(f"Expected saved model was not created: {save_path}")
            return 1

        print(f"Agent+COMSOL smoke test succeeded. Saved model: {save_path.resolve()}")
        return 0
    finally:
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def _collect_tool_results(messages: list[dict]) -> list[dict]:
    results: list[dict] = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        payload = json.loads(message.get("content") or "{}")
        results.append({"name": message.get("name"), "payload": payload})
    return results


def _print_tool_results(results: list[dict]) -> None:
    print("Tool results:")
    for result in results:
        payload = result["payload"]
        compact = {
            "success": payload.get("success"),
            "model_name": payload.get("model_name"),
            "error": payload.get("error"),
            "saved_to": payload.get("saved_to"),
        }
        print(f"- {result['name']}: {compact}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a real Agent+COMSOL smoke test.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit.")
    parser.add_argument("--model-name", default="agent_comsol_smoke", help="New COMSOL model name.")
    parser.add_argument("--output-dir", default="runtime_smoke", help="Output directory.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.cores, args.model_name, Path(args.output_dir))))


if __name__ == "__main__":
    main()
