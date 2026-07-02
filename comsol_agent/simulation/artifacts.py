"""Simulation artifact writers for reproducible experiment records."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from comsol_agent.cli.config import get_config_dir
from comsol_agent.memory.archive_store import ArchiveStore


def persist_sweep_result(
    result: dict[str, Any],
    *,
    output_dir: str | Path | None = None,
    run_name: str | None = None,
    archive_results: bool = True,
    archive_path: str | Path | None = None,
) -> dict[str, Any]:
    """Persist a sweep result as JSON, CSV, and a small manifest."""
    target_dir = Path(output_dir or "runtime_smoke/sweeps").expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    run_id = _make_run_id(run_name)
    json_path = target_dir / f"{run_id}.json"
    csv_path = target_dir / f"{run_id}.csv"
    manifest_path = target_dir / f"{run_id}.manifest.json"

    payload = dict(result)
    payload.pop("artifacts", None)
    payload["artifact_run_id"] = run_id
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    rows = _sweep_csv_rows(payload)
    _write_csv(csv_path, rows)

    manifest = {
        "run_id": run_id,
        "created_at": _utc_now(),
        "kind": "parameter_sweep",
        "model_name": result.get("model_name"),
        "source": result.get("source"),
        "executed_cases": result.get("executed_cases", 0),
        "truncated": result.get("truncated", False),
        "json_path": str(json_path),
        "csv_path": str(csv_path),
        "manifest_path": str(manifest_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    archive_record = None
    archive_error = None
    if archive_results:
        try:
            archive_record = _index_manifest(
                manifest,
                archive_path=archive_path,
                metadata={
                    "artifact_directory": str(target_dir),
                    "csv_rows": len(rows),
                },
            )
        except Exception as exc:
            archive_error = str(exc)

    artifact_result = {
        "run_id": run_id,
        "directory": str(target_dir),
        "json_path": str(json_path),
        "csv_path": str(csv_path),
        "manifest_path": str(manifest_path),
        "csv_rows": len(rows),
    }
    if archive_record is not None:
        artifact_result["archive"] = archive_record
    if archive_error is not None:
        artifact_result["archive_error"] = archive_error
    return artifact_result


def persist_template_execution_result(
    result: dict[str, Any],
    *,
    output_dir: str | Path | None = None,
    run_name: str | None = None,
    archive_results: bool = True,
    archive_path: str | Path | None = None,
    artifact_kind: str = "template_execution",
) -> dict[str, Any]:
    """Persist a template or generated-code execution result as JSON and a small manifest."""
    target_dir = Path(output_dir or "runtime_smoke/template_runs").expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    run_id = _make_run_id(run_name or artifact_kind)
    json_path = target_dir / f"{run_id}.json"
    manifest_path = target_dir / f"{run_id}.manifest.json"

    payload = dict(result)
    payload.pop("artifacts", None)
    payload["artifact_run_id"] = run_id
    payload["artifact_kind"] = artifact_kind
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    manifest = {
        "run_id": run_id,
        "created_at": _utc_now(),
        "kind": artifact_kind,
        "model_name": result.get("model_name"),
        "source": result.get("source") or {},
        "executed_cases": 1 if result.get("executed") else 0,
        "truncated": False,
        "json_path": str(json_path),
        "csv_path": None,
        "manifest_path": str(manifest_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    archive_record = None
    archive_error = None
    if archive_results:
        try:
            execution = result.get("execution") or {}
            validation = result.get("validation") or {}
            template = result.get("template") or {}
            archive_record = _index_manifest(
                manifest,
                archive_path=archive_path,
                metadata={
                    "template_name": result.get("template_name"),
                    "template_domain": template.get("domain"),
                    "params": result.get("params") or template.get("params") or {},
                    "validation_status": validation.get("status"),
                    "validation_errors": len(validation.get("errors") or []),
                    "validation_warnings": len(validation.get("warnings") or []),
                    "execution_success": result.get("success"),
                    "execution_error_type": execution.get("error_type"),
                    "execution_exception_type": execution.get("exception_type"),
                    "artifact_kind": artifact_kind,
                    "tool_sequence": result.get("tool_sequence") or [],
                },
            )
        except Exception as exc:
            archive_error = str(exc)

    artifact_result = {
        "run_id": run_id,
        "directory": str(target_dir),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
    }
    if archive_record is not None:
        artifact_result["archive"] = archive_record
    if archive_error is not None:
        artifact_result["archive_error"] = archive_error
    return artifact_result


def _sweep_csv_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in result.get("cases", []):
        base = {
            "run_id": result.get("artifact_run_id", ""),
            "model_name": result.get("model_name", ""),
            "case_index": case.get("case_index", ""),
            "case_label": case.get("label", ""),
            "case_success": case.get("success", ""),
            "parameters_json": json.dumps(case.get("parameters", {}), ensure_ascii=False),
            "solve_elapsed_seconds": (case.get("solve") or {}).get("elapsed_seconds", ""),
            "solve_status": (case.get("solve") or {}).get("status", ""),
        }
        for name, value in (case.get("parameters") or {}).items():
            base[f"param_{name}"] = value

        evaluations = case.get("evaluations") or []
        if not evaluations:
            rows.append(dict(base))
            continue

        for evaluation in evaluations:
            row = dict(base)
            row.update(_evaluation_columns(evaluation))
            rows.append(row)
    return rows


def _evaluation_columns(evaluation: dict[str, Any]) -> dict[str, Any]:
    stats = evaluation.get("statistics") or {}
    return {
        "expression": evaluation.get("expression", ""),
        "evaluation_success": evaluation.get("success", ""),
        "value": evaluation.get("value", ""),
        "shape": json.dumps(evaluation.get("shape", ""), ensure_ascii=False),
        "min": stats.get("min", ""),
        "max": stats.get("max", ""),
        "mean": stats.get("mean", ""),
        "error": evaluation.get("error", ""),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    if not fieldnames:
        fieldnames = ["run_id", "model_name", "case_index"]

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _make_run_id(run_name: str | None) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    if not run_name:
        return f"sweep_{timestamp}"
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_name.strip()).strip("._-")
    return f"{slug or 'sweep'}_{timestamp}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _index_manifest(
    manifest: dict[str, Any],
    *,
    archive_path: str | Path | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    db_path = Path(archive_path).expanduser() if archive_path else _default_archive_path()
    store = ArchiveStore(db_path)
    artifact = store.index_simulation_artifact(manifest, metadata=metadata)
    return {
        "db_path": str(db_path.resolve()),
        "id": artifact.id,
        "run_id": artifact.run_id,
        "kind": artifact.kind,
    }


def _default_archive_path() -> Path:
    return get_config_dir() / "archive" / "archive.sqlite3"
