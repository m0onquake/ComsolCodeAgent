"""Smoke-test a real COMSOL example model through project tool functions."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.comsol.model_ops import comsol_close_model, comsol_load_model
from comsol_agent.tools.comsol.solve import (
    comsol_evaluate,
    comsol_get_model_summary,
    comsol_solve,
)
from comsol_agent.tools.simulation import simulation_run_example_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a real COMSOL model smoke test.")
    parser.add_argument("--example", default="thermal_slab", help="Built-in example name.")
    parser.add_argument("--model-file", default=None, help="Optional path to a custom .mph model.")
    parser.add_argument("--expression", default="T", help="Expression to evaluate after solve.")
    parser.add_argument(
        "--expressions",
        nargs="*",
        default=None,
        help="Optional list of expressions to evaluate after solve.",
    )
    parser.add_argument(
        "--parameter",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Parameter assignment to set before solving. Can be repeated.",
    )
    parser.add_argument("--study", default=None, help="Optional study name/tag.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit.")
    parser.add_argument("--skip-solve", action="store_true", help="Evaluate without solving first.")
    args = parser.parse_args()

    config = load_config()
    client = COMSOLClient.get_instance()
    model_name: str | None = None
    try:
        print("Starting real COMSOL model smoke test...")
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        print(f"COMSOL client started: version={getattr(client._mph_client, 'version', 'unknown')}")

        if not args.model_file:
            parameters = _parse_parameters(args.parameter)
            result = simulation_run_example_model(
                example_name=args.example,
                expression=args.expression,
                expressions=args.expressions,
                parameters=parameters,
                study_name=args.study,
                solve=not args.skip_solve,
                close_model=True,
            )
            _require_success("simulation_run_example_model", result)
            print("example:")
            print(result["example"])
            print("summary excerpt:")
            print(str(result["summary"]["summary"])[:1200])
            print("evaluation summary:")
            for evaluation in result["evaluations"]:
                print(_compact_evaluation(evaluation))
            print("Real COMSOL model smoke test succeeded.")
            return

        load_result = comsol_load_model(args.model_file)
        _require_success("load_model", load_result)
        model_name = load_result["model_name"]

        summary_result = comsol_get_model_summary(model_name)
        _require_success("get_model_summary", summary_result)
        print("summary excerpt:")
        print(str(summary_result["summary"])[:1200])

        if not args.skip_solve:
            solve_result = comsol_solve(model_name, study_name=args.study)
            _require_success("solve", solve_result)

        evaluate_result = comsol_evaluate(model_name, args.expression)
        _require_success("evaluate", evaluate_result)
        print("evaluation summary:")
        print(_compact_evaluation(evaluate_result))

        print("Real COMSOL custom model smoke test succeeded.")
    finally:
        if model_name:
            close_result = comsol_close_model(model_name, save=False)
            print(f"close_model: {close_result}")
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def _require_success(step: str, result: dict) -> None:
    compact = {key: result.get(key) for key in ("success", "model_name", "error", "message", "status")}
    print(f"{step}: {compact}")
    if not result.get("success"):
        raise RuntimeError(f"{step} failed: {result}")


def _compact_evaluation(result: dict) -> dict:
    keys = ("success", "model_name", "expression", "shape", "statistics", "value", "data_sample")
    return {key: result[key] for key in keys if key in result}


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
