"""Replay an archived COMSOL sweep artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.simulation import simulation_rerun_artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay an archived COMSOL sweep artifact.")
    parser.add_argument("run_id", help="Archived sweep run ID.")
    parser.add_argument(
        "--parameter",
        action="append",
        default=[],
        metavar="NAME=VALUE1,VALUE2",
        help="Override or add a sweep axis. Can be repeated.",
    )
    parser.add_argument(
        "--expression",
        action="append",
        dest="expressions",
        default=None,
        help="Replacement expression to evaluate. Can be repeated.",
    )
    parser.add_argument("--model-name", default=None, help="Loaded model name for loaded-model artifacts.")
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--artifact-name", default=None)
    parser.add_argument("--artifact-dir", default=None)
    parser.add_argument("--archive-path", default=None)
    parser.add_argument("--cores", type=int, default=1)
    args = parser.parse_args()

    config = load_config()
    client = COMSOLClient.get_instance()
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        result = simulation_rerun_artifact(
            run_id=args.run_id,
            parameter_overrides=_parse_sweep_parameters(args.parameter) or None,
            expression_overrides=args.expressions,
            model_name=args.model_name,
            max_cases=args.max_cases,
            artifact_name=args.artifact_name,
            artifact_dir=args.artifact_dir,
            archive_path=args.archive_path,
        )
        print(json.dumps(_compact_result(result), ensure_ascii=False, indent=2, default=str))
        if not result.get("success"):
            raise SystemExit(1)
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


def _compact_result(result: dict) -> dict:
    return {
        "success": result.get("success"),
        "error": result.get("error"),
        "source_run_id": (result.get("replay") or {}).get("source_run_id") or result.get("source_run_id"),
        "model_name": result.get("model_name"),
        "executed_cases": result.get("executed_cases"),
        "artifacts": result.get("artifacts"),
        "cases": [
            {
                "case_index": case.get("case_index"),
                "parameters": case.get("parameters"),
                "evaluations": case.get("evaluations"),
            }
            for case in result.get("cases", [])
        ],
    }


if __name__ == "__main__":
    main()
