"""Smoke-test the high-level COMSOL parameter sweep runtime tool."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.simulation import simulation_run_parameter_sweep


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a real COMSOL parameter sweep smoke test.")
    parser.add_argument("--example", default="thermal_slab", help="Built-in example name.")
    parser.add_argument("--model-file", default=None, help="Optional path to a custom .mph model.")
    parser.add_argument(
        "--parameter",
        action="append",
        default=[],
        metavar="NAME=VALUE1,VALUE2",
        help="Sweep axis. Can be repeated, e.g. --parameter L=1[mm],2[mm].",
    )
    parser.add_argument(
        "--expression",
        action="append",
        dest="expressions",
        default=None,
        help="Expression to evaluate after each case. Can be repeated.",
    )
    parser.add_argument("--study", default=None, help="Optional study name/tag.")
    parser.add_argument("--max-cases", type=int, default=4, help="Maximum cases to execute.")
    parser.add_argument("--artifact-dir", default=None, help="Optional artifact output directory.")
    parser.add_argument("--artifact-name", default="tool_sweep_smoke", help="Artifact filename prefix.")
    parser.add_argument("--archive-path", default=None, help="Optional archive SQLite path.")
    parser.add_argument("--no-persist", action="store_true", help="Disable JSON/CSV artifact writing.")
    parser.add_argument("--no-archive", action="store_true", help="Disable SQLite artifact indexing.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit.")
    parser.add_argument("--skip-solve", action="store_true", help="Evaluate without solving first.")
    args = parser.parse_args()

    config = load_config()
    client = COMSOLClient.get_instance()
    try:
        print("Starting real COMSOL sweep smoke test...")
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        print(f"COMSOL client started: version={getattr(client._mph_client, 'version', 'unknown')}")

        parameters = _parse_sweep_parameters(args.parameter)
        if not parameters:
            parameters = {"L": ["0.5[mm]", "1[mm]"]}

        result = simulation_run_parameter_sweep(
            example_name=None if args.model_file else args.example,
            model_file=args.model_file,
            parameters=parameters,
            expressions=args.expressions,
            study_name=args.study,
            max_cases=args.max_cases,
            solve=not args.skip_solve,
            persist_results=not args.no_persist,
            artifact_dir=args.artifact_dir,
            artifact_name=args.artifact_name,
            archive_results=not args.no_archive,
            archive_path=args.archive_path,
        )
        _require_success(result)

        print("plan:")
        print({
            "estimated_runs": result["plan"]["estimated_runs"],
            "executed_cases": result["executed_cases"],
            "warnings": result["plan"]["warnings"],
        })
        print("case summaries:")
        for case in result["cases"]:
            print({
                "case_index": case["case_index"],
                "parameters": case["parameters"],
                "evaluations": case["evaluations"],
            })
        if result.get("artifacts"):
            print("artifacts:")
            print(result["artifacts"])
        print("Real COMSOL sweep smoke test succeeded.")
    finally:
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


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


def _require_success(result: dict) -> None:
    compact = {
        "success": result.get("success"),
        "model_name": result.get("model_name"),
        "error": result.get("error"),
        "stage": result.get("stage"),
    }
    print(f"simulation_run_parameter_sweep: {compact}")
    if not result.get("success"):
        raise RuntimeError(f"sweep failed: {result}")


if __name__ == "__main__":
    main()
