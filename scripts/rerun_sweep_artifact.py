"""Replay an archived COMSOL sweep or template execution artifact."""

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
    parser = argparse.ArgumentParser(description="Replay an archived COMSOL simulation artifact.")
    parser.add_argument("run_id", help="Archived artifact run ID.")
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
    parser.add_argument("--create-model-name", default=None, help="New model name for template execution replay.")
    parser.add_argument(
        "--template-param",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Override a template parameter when replaying template_execution artifacts. Can be repeated.",
    )
    parser.add_argument("--no-validate-first", action="store_true", help="Skip template validation before replay.")
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
            params_overrides=_parse_template_params(args.template_param) or None,
            model_name=args.model_name,
            create_model_name=args.create_model_name,
            max_cases=args.max_cases,
            validate_first=False if args.no_validate_first else None,
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


def _parse_template_params(assignments: list[str]) -> dict[str, str]:
    parameters = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"Invalid template parameter assignment: {assignment!r}")
        name, value = assignment.split("=", 1)
        if not name.strip() or not value.strip():
            raise ValueError(f"Invalid template parameter assignment: {assignment!r}")
        parameters[name.strip()] = value.strip()
    return parameters


def _compact_result(result: dict) -> dict:
    return {
        "success": result.get("success"),
        "error": result.get("error"),
        "source_run_id": (result.get("replay") or {}).get("source_run_id") or result.get("source_run_id"),
        "model_name": result.get("model_name"),
        "template_name": result.get("template_name"),
        "executed_cases": result.get("executed_cases"),
        "executed": result.get("executed"),
        "validation": result.get("validation"),
        "execution": result.get("execution"),
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
