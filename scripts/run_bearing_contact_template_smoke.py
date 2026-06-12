"""Run the bearing-contact template directly through local COMSOL tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config
from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.simulation.skills import seed_builtin_templates
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.comsol.evaluate import comsol_plot
from comsol_agent.tools.comsol.model_ops import comsol_close_model
from comsol_agent.tools.comsol.solve import comsol_evaluate, comsol_solve
from comsol_agent.tools.simulation import simulation_run_template


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the bearing-contact template smoke test.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit.")
    parser.add_argument("--template-name", default="bearing_contact_hertz_seed")
    parser.add_argument("--model-name", default="bearing_contact_template_smoke")
    parser.add_argument("--archive-path", default="runtime_smoke/bearing_contact_template_smoke.sqlite3")
    parser.add_argument("--artifact-dir", default="runtime_smoke/bearing_contact_template_smoke")
    parser.add_argument("--plot-path", default="runtime_smoke/bearing_contact_template_smoke/von_mises.png")
    parser.add_argument("--skip-solve", action="store_true", help="Only build the model/template artifact.")
    args = parser.parse_args()

    archive_path = Path(args.archive_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    Path(args.artifact_dir).mkdir(parents=True, exist_ok=True)

    config = load_config()
    client = COMSOLClient.get_instance()
    model_name: str | None = None
    summary: dict[str, object] = {}
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        seed_builtin_templates(ArchiveStore(archive_path))
        template_result = simulation_run_template(
            name=args.template_name,
            create_model_name=args.model_name,
            close_model=False,
            artifact_dir=args.artifact_dir,
            artifact_name="bearing_contact_template_smoke",
            archive_path=str(archive_path),
        )
        summary["template"] = _compact_result(template_result)
        if not template_result.get("success"):
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            raise SystemExit(1)

        model_name = str(template_result["model_name"])
        if not args.skip_solve:
            solve_result = comsol_solve(model_name)
            summary["solve"] = _compact_result(solve_result)
            if solve_result.get("success"):
                summary["evaluations"] = [
                    _compact_result(comsol_evaluate(model_name, "solid.mises")),
                    _compact_result(comsol_evaluate(model_name, "contact_pressure_guess")),
                ]
                summary["plot"] = _compact_result(
                    comsol_plot(
                        model_name,
                        expression="solid.mises",
                        plot_type="surface",
                        filename=args.plot_path,
                    )
                )

        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    finally:
        if model_name:
            close_result = comsol_close_model(model_name, save=False)
            if summary:
                print(json.dumps({"close": _compact_result(close_result)}, ensure_ascii=False, indent=2))
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def _compact_result(result: dict) -> dict:
    keys = (
        "success",
        "model_name",
        "template_name",
        "study",
        "elapsed_seconds",
        "status",
        "expression",
        "shape",
        "statistics",
        "value",
        "plot_type",
        "filepath",
        "export_method",
        "error",
        "message",
    )
    compact = {key: result.get(key) for key in keys if key in result}
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        compact["run_id"] = artifacts.get("run_id")
        compact["json_path"] = artifacts.get("json_path")
    return compact


if __name__ == "__main__":
    main()
