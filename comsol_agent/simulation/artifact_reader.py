"""Read compact previews of archived simulation artifacts."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from comsol_agent.memory.archive_store import ArchiveStore, SimulationArtifact


def read_archived_artifact(
    archive_store: ArchiveStore,
    *,
    run_id: str,
    max_lines: int = 80,
) -> dict[str, Any]:
    """Read a compact preview of an archived artifact."""
    artifact = archive_store.get_simulation_artifact(run_id)
    manifest = _read_json(Path(artifact.manifest_path))
    result = {
        "artifact": asdict(artifact),
        "manifest": manifest,
        "preview": {},
    }

    if artifact.kind in {"comparison_report", "template_execution_report", "generated_code_execution_report"}:
        result["preview"]["markdown"] = _read_text_preview(Path(artifact.json_path), max_lines=max_lines)
    elif artifact.kind == "parameter_sweep":
        result["preview"]["summary"] = _sweep_json_summary(Path(artifact.json_path))
        if artifact.csv_path:
            result["preview"]["csv"] = _read_csv_preview(Path(artifact.csv_path), max_rows=max_lines)
    elif artifact.kind in {"template_execution", "generated_code_execution"}:
        result["preview"]["summary"] = _template_execution_summary(Path(artifact.json_path))
    elif artifact.kind == "bearing_contact_package":
        result["preview"]["summary"] = _bearing_contact_package_summary(Path(artifact.json_path))
    else:
        result["preview"]["content"] = _read_text_preview(Path(artifact.json_path), max_lines=max_lines)

    return result


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc), "path": str(path)}


def _read_text_preview(path: Path, *, max_lines: int) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "lines": []}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {
        "exists": True,
        "path": str(path),
        "total_lines": len(lines),
        "truncated": len(lines) > max_lines,
        "lines": lines[:max_lines],
    }


def _read_csv_preview(path: Path, *, max_rows: int) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "rows": []}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for index, row in enumerate(reader):
            if index >= max_rows:
                break
            rows.append(dict(row))
    return {
        "exists": True,
        "path": str(path),
        "fieldnames": reader.fieldnames or [],
        "rows": rows,
        "truncated": len(rows) >= max_rows,
    }


def _sweep_json_summary(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload is None:
        return {"exists": False, "path": str(path)}
    if "error" in payload:
        return payload

    return {
        "exists": True,
        "path": str(path),
        "success": payload.get("success"),
        "model_name": payload.get("model_name"),
        "source": payload.get("source"),
        "executed_cases": payload.get("executed_cases"),
        "truncated": payload.get("truncated"),
        "plan": {
            "estimated_runs": (payload.get("plan") or {}).get("estimated_runs"),
            "output_expressions": (payload.get("plan") or {}).get("output_expressions"),
            "axes": (payload.get("plan") or {}).get("axes"),
        },
        "artifacts": payload.get("artifacts"),
    }


def _template_execution_summary(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload is None:
        return {"exists": False, "path": str(path)}
    if "error" in payload:
        return payload

    validation = payload.get("validation") or {}
    execution = payload.get("execution") or {}
    template = payload.get("template") or {}
    execution_context = payload.get("execution_context") or {}
    repair_history = execution_context.get("repair_history") or []
    draft_quality = execution_context.get("draft_quality") or {}
    selection_binding_audit = execution_context.get("selection_binding_audit") or {}
    physical_result_audit = execution_context.get("physical_result_audit") or {}
    contact_convergence_report = execution_context.get("contact_convergence_report") or {}
    return {
        "exists": True,
        "path": str(path),
        "success": payload.get("success"),
        "kind": payload.get("artifact_kind") or payload.get("kind") or "template_execution",
        "executed": payload.get("executed"),
        "model_name": payload.get("model_name"),
        "template_name": payload.get("template_name") or template.get("name"),
        "source": payload.get("source"),
        "params": payload.get("params") or template.get("params") or {},
        "validation": {
            "status": validation.get("status"),
            "errors": validation.get("errors") or [],
            "warnings": validation.get("warnings") or [],
        },
        "execution": {
            "success": execution.get("success"),
            "error": execution.get("error"),
            "error_type": execution.get("error_type"),
            "exception_type": execution.get("exception_type"),
            "modified": execution.get("modified"),
        },
        "execution_context": execution_context,
        "selection_binding_audit": selection_binding_audit,
        "physical_result_audit": physical_result_audit,
        "contact_convergence_report": contact_convergence_report,
        "execution_audit": {
            "workflow": execution_context.get("workflow"),
            "repair_history_count": len(repair_history),
            "last_repair_stage": repair_history[-1].get("stage") if repair_history else None,
            "quality_gate_success": draft_quality.get("success"),
            "quality_gate_level": draft_quality.get("quality_level"),
            "selection_binding_success": selection_binding_audit.get("success"),
            "selection_binding_runtime_checked": selection_binding_audit.get("runtime_checked"),
            "physical_result_success": physical_result_audit.get("success"),
            "physical_result_quality_level": physical_result_audit.get("quality_level"),
            "physical_result_production_ready": physical_result_audit.get("production_ready"),
            "contact_convergence_level": contact_convergence_report.get("quality_level"),
            "contact_runtime_verified": contact_convergence_report.get("runtime_verified"),
            "require_free_generated_code": execution_context.get("require_free_generated_code"),
        },
        "artifacts": payload.get("artifacts"),
    }


def _bearing_contact_package_summary(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload is None:
        return {"exists": False, "path": str(path)}
    if "error" in payload:
        return payload

    selection_binding_audit = payload.get("selection_binding_audit") or {}
    physical_result_audit = payload.get("physical_result_audit") or {}
    contact_convergence_report = payload.get("contact_convergence_report") or {}
    return {
        "exists": True,
        "path": str(path),
        "success": payload.get("success"),
        "kind": payload.get("kind"),
        "run_id": payload.get("run_id"),
        "model_name": payload.get("model_name"),
        "template_run_id": payload.get("template_run_id"),
        "metrics": payload.get("metrics") or {},
        "max_von_mises_pa": payload.get("max_von_mises_pa"),
        "contact_pressure_estimate_pa": payload.get("contact_pressure_estimate_pa"),
        "result_interpretation": payload.get("result_interpretation") or {},
        "highest_risk_roller": payload.get("highest_risk_roller"),
        "roller_risk_ranking": payload.get("roller_risk_ranking") or [],
        "risk_ranking_method": payload.get("risk_ranking_method"),
        "selection_status": payload.get("selection_status"),
        "selection_plan": payload.get("selection_plan") or {},
        "selection_binding_audit": selection_binding_audit,
        "physical_result_audit": physical_result_audit,
        "contact_convergence_report": contact_convergence_report,
        "quality_audit": {
            "selection_binding_success": selection_binding_audit.get("success"),
            "selection_binding_runtime_checked": selection_binding_audit.get("runtime_checked"),
            "physical_result_success": physical_result_audit.get("success"),
            "physical_result_quality_level": physical_result_audit.get("quality_level"),
            "physical_result_production_ready": physical_result_audit.get("production_ready"),
            "contact_convergence_level": contact_convergence_report.get("quality_level"),
            "contact_runtime_verified": contact_convergence_report.get("runtime_verified"),
        },
        "probe_scope_status": payload.get("probe_scope_status"),
        "repair_history": payload.get("repair_history") or [],
        "cage_model": payload.get("cage_model"),
        "model_parameters": payload.get("model_parameters") or {},
        "model_path": (payload.get("model_save") or {}).get("saved_to"),
        "plot_path": (payload.get("plot") or {}).get("path"),
        "assumptions": payload.get("assumptions") or [],
    }
