"""Run the PCB thermal starter template through offline or real COMSOL smoke checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config
from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.simulation.skills import seed_builtin_templates
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.comsol.evaluate import comsol_plot
from comsol_agent.tools.comsol.model_ops import comsol_close_model, comsol_save_model
from comsol_agent.tools.comsol.solve import (
    comsol_evaluate,
    comsol_execute_java,
    comsol_get_model_summary,
    comsol_solve,
)
from comsol_agent.tools.simulation import (
    simulation_read_template,
    simulation_run_template,
    simulation_validate_template,
)


TEMPLATE_NAME = "pcb_thermal_plate_seed"
DEFAULT_ARCHIVE_PATH = "runtime_smoke/pcb_thermal_real.sqlite3"
DEFAULT_ARTIFACT_DIR = "runtime_smoke/pcb_thermal_real"
DEFAULT_MODEL_NAME = "pcb_thermal_smoke"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the PCB thermal template smoke test.")
    parser.add_argument("--archive-path", default=DEFAULT_ARCHIVE_PATH)
    parser.add_argument("--artifact-dir", default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit.")
    parser.add_argument("--skip-solve", action="store_true", help="Build and audit the model without solving.")
    parser.add_argument("--skip-comsol", action="store_true", help="Only seed, read, and offline-validate the template.")
    parser.add_argument("--keep-model", action="store_true", help="Leave the COMSOL model open after the smoke.")
    parser.add_argument("--print-summary", action="store_true", help="Print the full summary JSON.")
    return parser.parse_args(argv)


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    archive_path = Path(args.archive_path).expanduser()
    artifact_dir = Path(args.artifact_dir).expanduser()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "success": False,
        "stage": "seed_builtin_templates",
        "model_name": args.model_name,
        "template_name": TEMPLATE_NAME,
        "archive_path": str(archive_path.resolve()),
        "artifact_dir": str(artifact_dir.resolve()),
        "skip_comsol": bool(args.skip_comsol),
        "skip_solve": bool(args.skip_solve),
        "setup_success": None,
        "solve_success": None,
        "temperature_evaluations": [],
        "plot_path": None,
        "failure_stage": None,
        "error": None,
    }
    client = COMSOLClient.get_instance()
    active_model_name: str | None = None

    try:
        templates = seed_builtin_templates(ArchiveStore(archive_path))
        summary["seeded_template_count"] = len(templates)
        summary["stage"] = "read_template"
        read_result = simulation_read_template(TEMPLATE_NAME, archive_path=str(archive_path))
        summary["template_read"] = _compact_result(read_result)
        if not read_result.get("success"):
            return _fail(summary, "read_template", read_result.get("error"))

        summary["stage"] = "offline_validate"
        validation = simulation_validate_template(name=TEMPLATE_NAME, archive_path=str(archive_path))
        summary["validation"] = _compact_validation(validation)
        if not validation.get("success"):
            return _fail(summary, "offline_validate", validation.get("error") or "Template validation failed.")

        if args.skip_comsol:
            summary["success"] = True
            summary["stage"] = "offline_validate"
            return _write_smoke_artifacts(summary, artifact_dir)

        summary["stage"] = "start_comsol"
        config = load_config()
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )

        summary["stage"] = "template_setup"
        setup = simulation_run_template(
            name=TEMPLATE_NAME,
            create_model_name=args.model_name,
            close_model=False,
            validate_first=True,
            artifact_dir=str(artifact_dir),
            artifact_name="pcb_thermal_template_setup",
            archive_path=str(archive_path),
        )
        summary["setup"] = _compact_result(setup)
        summary["setup_success"] = bool(setup.get("success"))
        if not setup.get("success"):
            return _fail(summary, "template_setup", _result_error(setup))
        active_model_name = str(setup.get("model_name") or args.model_name)
        summary["model_name"] = active_model_name

        summary["stage"] = "model_summary"
        model_summary = comsol_get_model_summary(active_model_name)
        summary["model_summary"] = _compact_result(model_summary)
        if model_summary.get("success"):
            summary["model_summary_text"] = model_summary.get("summary")

        summary["stage"] = "runtime_audit"
        audit = audit_pcb_runtime_model(active_model_name)
        summary["runtime_audit"] = audit
        structure_check = check_pcb_runtime_audit(audit)
        summary["structure_check"] = structure_check
        summary.update(structure_check["counts"])
        if not structure_check["success"]:
            return _fail(summary, "runtime_audit", "; ".join(structure_check["errors"]))

        summary["stage"] = "save_model"
        model_path = artifact_dir / f"{active_model_name}.mph"
        save_result = comsol_save_model(active_model_name, str(model_path))
        summary["model_save"] = _compact_result(save_result)

        if args.skip_solve:
            summary["success"] = True
            summary["stage"] = "setup_audit_complete"
            return _write_smoke_artifacts(summary, artifact_dir)

        summary["stage"] = "solve"
        solve = comsol_solve(active_model_name)
        summary["solve"] = _compact_result(solve)
        summary["solve_success"] = bool(solve.get("success"))
        if not solve.get("success"):
            return _fail(summary, "solve", _result_error(solve))

        summary["stage"] = "evaluate_temperature"
        evaluations = evaluate_temperature_metrics(active_model_name)
        summary["temperature_evaluations"] = evaluations
        successful_evaluations = [item for item in evaluations if item.get("success")]
        if not successful_evaluations:
            return _fail(summary, "evaluate_temperature", "No temperature expression evaluated successfully.")

        summary["stage"] = "plot_temperature"
        plot_path = artifact_dir / "pcb_temperature.png"
        plot = comsol_plot(
            active_model_name,
            expression="T",
            plot_type="surface",
            filename=str(plot_path),
        )
        summary["plot"] = _compact_result(plot)
        if plot.get("success"):
            summary["plot_path"] = plot.get("filepath")

        summary["success"] = True
        summary["stage"] = "complete"
        return _write_smoke_artifacts(summary, artifact_dir)
    except Exception as exc:
        summary["traceback"] = traceback.format_exc()
        return _fail(summary, summary.get("stage") or "exception", str(exc))
    finally:
        if active_model_name and not args.keep_model:
            close = comsol_close_model(active_model_name, save=False)
            summary["close"] = _compact_result(close)
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def audit_pcb_runtime_model(model_name: str) -> dict[str, Any]:
    execution = comsol_execute_java(_PCB_AUDIT_CODE, model_name)
    audit = parse_audit_stdout(execution.get("stdout") or execution.get("output") or "")
    audit["success"] = bool(execution.get("success")) and not audit["errors"]
    audit["execution"] = _compact_result(execution)
    return audit


def parse_audit_stdout(stdout: str) -> dict[str, Any]:
    sections: dict[str, dict[str, int]] = {}
    errors: list[str] = []
    raw_lines = stdout.splitlines()
    for line in raw_lines:
        if not line.startswith("AUDIT|"):
            continue
        parts = line.split("|", 4)
        if len(parts) != 5:
            errors.append(f"Malformed audit line: {line}")
            continue
        _prefix, kind, tag, count_text, error = parts
        if error:
            errors.append(f"{kind}:{tag}:{error}")
        try:
            count = int(count_text)
        except ValueError:
            count = -1
        sections.setdefault(kind, {})[tag] = count
    return {"sections": sections, "errors": errors, "raw_stdout": stdout, "raw_lines": raw_lines}


def check_pcb_runtime_audit(audit: dict[str, Any]) -> dict[str, Any]:
    sections = audit.get("sections") or {}
    errors: list[str] = []
    required_tags = {
        "component": ("comp1",),
        "geometry": ("geom1",),
        "geometry_feature": ("fr4_board", "copper_top", "copper_bottom", "chip1_pkg", "chip2_pkg"),
        "material": ("mat_fr4", "mat_copper", "mat_chip"),
        "physics": ("ht",),
        "physics_feature": ("chip1_heat", "chip2_heat", "conv_bottom", "conv_sides", "conv_chip_tops"),
        "mesh": ("mesh1",),
        "study": ("std1",),
        "study_feature": ("stat",),
        "result": ("pg_temperature",),
        "numerical": ("max_board_temperature", "chip_hotspot_indicator"),
        "coupling": ("maxop1",),
        "selection": (
            "sel_fr4_board",
            "sel_copper_layers",
            "sel_chip1_pkg",
            "sel_chip2_pkg",
            "sel_conv_bottom",
            "sel_conv_sides",
            "sel_conv_chip_tops",
        ),
    }
    for kind, tags in required_tags.items():
        available = sections.get(kind, {})
        for tag in tags:
            if tag not in available:
                errors.append(f"Missing {kind} tag: {tag}")

    positive_selection_tags = (
        "sel_fr4_board",
        "sel_copper_layers",
        "sel_chip1_pkg",
        "sel_chip2_pkg",
        "sel_conv_bottom",
        "sel_conv_sides",
        "sel_conv_chip_tops",
    )
    selection_counts = sections.get("selection", {})
    for tag in positive_selection_tags:
        if selection_counts.get(tag, 0) <= 0:
            errors.append(f"Selection {tag} has no bound entities.")

    counts = {
        "component_count": len(sections.get("component", {})),
        "geometry_count": len(sections.get("geometry", {})),
        "geometry_feature_count": len(sections.get("geometry_feature", {})),
        "material_count": len(sections.get("material", {})),
        "physics_count": len(sections.get("physics", {})),
        "physics_feature_count": len(sections.get("physics_feature", {})),
        "mesh_count": len(sections.get("mesh", {})),
        "study_count": len(sections.get("study", {})),
        "result_count": len(sections.get("result", {})),
        "numerical_count": len(sections.get("numerical", {})),
        "selection_count": len(sections.get("selection", {})),
    }
    return {"success": not errors and bool(audit.get("success")), "errors": errors + list(audit.get("errors") or []), "counts": counts}


def evaluate_temperature_metrics(model_name: str) -> list[dict[str, Any]]:
    expressions = ("T", "maxop1(T)", "max_board_temperature", "chip_hotspot_indicator")
    return [_compact_result(comsol_evaluate(model_name, expression)) for expression in expressions]


def _write_smoke_artifacts(summary: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    summary_path = artifact_dir / "summary.json"
    report_path = artifact_dir / "report.md"
    manifest_path = artifact_dir / "manifest.json"
    summary["summary_json_path"] = str(summary_path.resolve())
    summary["report_markdown_path"] = str(report_path.resolve())
    summary["manifest_path"] = str(manifest_path.resolve())
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    report_path.write_text(_smoke_markdown(summary), encoding="utf-8")
    manifest = {
        "kind": "pcb_thermal_template_smoke",
        "model_name": summary.get("model_name"),
        "template_name": summary.get("template_name"),
        "success": summary.get("success"),
        "stage": summary.get("stage"),
        "failure_stage": summary.get("failure_stage"),
        "summary_json_path": str(summary_path.resolve()),
        "report_markdown_path": str(report_path.resolve()),
        "plot_path": summary.get("plot_path"),
        "model_path": (summary.get("model_save") or {}).get("saved_to"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def _smoke_markdown(summary: dict[str, Any]) -> str:
    evaluations = summary.get("temperature_evaluations") or []
    eval_lines = [
        f"- `{item.get('expression')}`: success={item.get('success')} value={item.get('value')} stats={item.get('statistics')}"
        for item in evaluations
    ]
    if not eval_lines:
        eval_lines = ["- Not run."]
    return "\n".join(
        [
            "# PCB Thermal Template Smoke",
            "",
            f"- Success: `{summary.get('success')}`",
            f"- Stage: `{summary.get('stage')}`",
            f"- Failure stage: `{summary.get('failure_stage') or ''}`",
            f"- Error: `{summary.get('error') or ''}`",
            f"- Model: `{summary.get('model_name')}`",
            f"- Template: `{summary.get('template_name')}`",
            f"- Setup success: `{summary.get('setup_success')}`",
            f"- Solve success: `{summary.get('solve_success')}`",
            f"- Components/geometries/physics/studies/results: `{summary.get('component_count')}` / `{summary.get('geometry_count')}` / `{summary.get('physics_count')}` / `{summary.get('study_count')}` / `{summary.get('result_count')}`",
            f"- Plot path: `{summary.get('plot_path') or ''}`",
            "",
            "## Temperature Evaluations",
            "",
            *eval_lines,
            "",
        ]
    )


def _fail(summary: dict[str, Any], stage: str, error: Any) -> dict[str, Any]:
    summary["success"] = False
    summary["stage"] = stage
    summary["failure_stage"] = stage
    summary["error"] = str(error or "")
    return _write_smoke_artifacts(summary, Path(summary["artifact_dir"]))


def _compact_validation(result: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_result(result)
    validation = result.get("validation")
    if isinstance(validation, dict):
        compact["validation"] = {
            "status": validation.get("status"),
            "errors": validation.get("errors", []),
            "warnings": validation.get("warnings", []),
            "notes": validation.get("notes", []),
            "line_count": validation.get("line_count"),
            "params_checked": validation.get("params_checked", []),
        }
    return compact


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "success",
        "model_name",
        "template_name",
        "stage",
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
        "saved_to",
        "error",
        "message",
        "exception_type",
        "error_type",
    )
    compact = {key: result.get(key) for key in keys if key in result}
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        compact["run_id"] = artifacts.get("run_id")
        compact["json_path"] = artifacts.get("json_path")
    return compact


def _result_error(result: dict[str, Any]) -> str:
    if result.get("error"):
        return str(result["error"])
    execution = result.get("execution")
    if isinstance(execution, dict) and execution.get("error"):
        return str(execution["error"])
    return json.dumps(_compact_result(result), ensure_ascii=False, default=str)


_PCB_AUDIT_CODE = """
def _audit_tags(node):
    try:
        return [str(tag) for tag in node.tags()]
    except Exception:
        return []

def _audit_emit(kind, tag, count, error='', _output=output):
    _output.write('AUDIT|' + str(kind) + '|' + str(tag) + '|' + str(count) + '|' + str(error).replace('\\n', ' ') + '\\n')

def _audit_emit_tags(kind, tags, _emit=_audit_emit):
    for tag in tags:
        _emit(kind, tag, 1)

try:
    _audit_emit_tags('component', _audit_tags(model.component()))
    comp = model.component('comp1')
    _audit_emit_tags('geometry', _audit_tags(comp.geom()))
    try:
        _audit_emit_tags('geometry_feature', _audit_tags(comp.geom('geom1').feature()))
    except Exception as error:
        _audit_emit('geometry_feature', 'geom1', 0, str(error))
    _audit_emit_tags('material', _audit_tags(comp.material()))
    _audit_emit_tags('physics', _audit_tags(comp.physics()))
    try:
        _audit_emit_tags('physics_feature', _audit_tags(comp.physics('ht').feature()))
    except Exception as error:
        _audit_emit('physics_feature', 'ht', 0, str(error))
    _audit_emit_tags('mesh', _audit_tags(comp.mesh()))
    _audit_emit_tags('study', _audit_tags(model.study()))
    try:
        _audit_emit_tags('study_feature', _audit_tags(model.study('std1').feature()))
    except Exception as error:
        _audit_emit('study_feature', 'std1', 0, str(error))
    _audit_emit_tags('result', _audit_tags(model.result()))
    _audit_emit_tags('numerical', _audit_tags(model.result().numerical()))
    try:
        _audit_emit_tags('coupling', _audit_tags(comp.cpl()))
    except Exception as error:
        _audit_emit('coupling', 'comp1', 0, str(error))
    for tag in _audit_tags(comp.selection()):
        try:
            entities = comp.selection(tag).entities()
            _audit_emit('selection', tag, len(list(entities)))
        except Exception as error:
            _audit_emit('selection', tag, 0, str(error))
except Exception as error:
    _audit_emit('fatal', 'audit', 0, str(error))
"""


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_smoke(args)
    if args.print_summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    else:
        print(
            json.dumps(
                {
                    "success": summary.get("success"),
                    "stage": summary.get("stage"),
                    "failure_stage": summary.get("failure_stage"),
                    "error": summary.get("error"),
                    "summary_json_path": summary.get("summary_json_path"),
                    "report_markdown_path": summary.get("report_markdown_path"),
                    "manifest_path": summary.get("manifest_path"),
                    "plot_path": summary.get("plot_path"),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    return 0 if summary.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
