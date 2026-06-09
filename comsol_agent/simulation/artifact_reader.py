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

    if artifact.kind == "comparison_report":
        result["preview"]["markdown"] = _read_text_preview(Path(artifact.json_path), max_lines=max_lines)
    elif artifact.kind == "parameter_sweep":
        result["preview"]["summary"] = _sweep_json_summary(Path(artifact.json_path))
        if artifact.csv_path:
            result["preview"]["csv"] = _read_csv_preview(Path(artifact.csv_path), max_rows=max_lines)
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
