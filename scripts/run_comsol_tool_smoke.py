"""Smoke-test COMSOL tool functions against a real local COMSOL session."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.comsol.model_ops import (
    comsol_close_model,
    comsol_create_model,
    comsol_list_models,
    comsol_list_parameters,
    comsol_save_model,
    comsol_set_parameter,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a real COMSOL tool-layer smoke test.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit.")
    parser.add_argument("--version", default=None, help="Override configured COMSOL version.")
    parser.add_argument("--output-dir", default="runtime_smoke", help="Output directory.")
    args = parser.parse_args()

    config = load_config()
    version = args.version or config.comsol.version
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    client = COMSOLClient.get_instance()
    try:
        print("Starting COMSOL tool-layer smoke test...")
        client.start(
            cores=args.cores,
            version=version,
            executable_path=config.comsol.executable_path,
        )
        print(f"COMSOL client started: version={getattr(client._mph_client, 'version', 'unknown')}")

        model_name = "comsol_agent_tool_smoke"
        create_result = comsol_create_model(model_name)
        _require_success("create", create_result)
        actual_name = create_result["model_name"]

        parameter_result = comsol_set_parameter(actual_name, "L_smoke", "1[mm]")
        _require_success("set_parameter", parameter_result)

        parameter_list_result = comsol_list_parameters(actual_name)
        _require_success("list_parameters", parameter_list_result)
        if not any(item["name"] == "L_smoke" for item in parameter_list_result["parameters"]):
            raise RuntimeError(f"Parameter L_smoke was not listed: {parameter_list_result}")

        list_result = comsol_list_models()
        _require_success("list_models", list_result)
        if actual_name not in {item["name"] for item in list_result["models"]}:
            raise RuntimeError(f"Created model {actual_name!r} was not listed: {list_result}")

        save_path = output_dir / f"{actual_name}.mph"
        save_result = comsol_save_model(actual_name, str(save_path))
        _require_success("save", save_result)

        close_result = comsol_close_model(actual_name, save=False)
        _require_success("close", close_result)

        print(f"Tool-layer smoke test succeeded. Saved model: {save_path.resolve()}")
    finally:
        if client.is_running:
            client.stop()


def _require_success(step: str, result: dict) -> None:
    print(f"{step}: {result}")
    if not result.get("success"):
        raise RuntimeError(f"{step} failed: {result}")


if __name__ == "__main__":
    main()
