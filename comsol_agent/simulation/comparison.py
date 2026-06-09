"""Compare archived COMSOL sweep artifacts."""

from __future__ import annotations

import csv
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

from comsol_agent.memory.archive_store import ArchiveStore, SimulationArtifact


def compare_archived_sweeps(
    archive_store: ArchiveStore,
    *,
    run_ids: list[str] | None = None,
    query: str | None = None,
    metric: str = "mean",
    expression: str | None = None,
    direction: str = "max",
    limit: int = 20,
) -> dict[str, Any]:
    """Compare archived parameter sweep artifacts using their CSV summaries."""
    artifacts = _select_artifacts(
        archive_store,
        run_ids=run_ids,
        query=query,
        limit=limit,
    )
    if not artifacts:
        raise ValueError("No archived sweep artifacts matched the request.")

    rows = []
    missing_files = []
    for artifact in artifacts:
        csv_path = Path(artifact.csv_path or "")
        if not csv_path.exists():
            missing_files.append({"run_id": artifact.run_id, "csv_path": str(csv_path)})
            continue
        for row in _read_csv(csv_path):
            if expression and row.get("expression") != expression:
                continue
            value = _as_float(row.get(metric))
            rows.append({
                "run_id": artifact.run_id,
                "model_name": artifact.model_name,
                "source": artifact.source,
                "case_index": row.get("case_index"),
                "case_label": row.get("case_label"),
                "expression": row.get("expression"),
                "metric": metric,
                "metric_value": value,
                "metric_raw": row.get(metric, ""),
                "parameters": _parameter_columns(row),
                "json_path": artifact.json_path,
                "csv_path": artifact.csv_path,
                "manifest_path": artifact.manifest_path,
            })

    comparable_rows = [row for row in rows if row["metric_value"] is not None]
    ranked = _rank_rows(comparable_rows, direction=direction)
    best = ranked[0] if ranked else None
    worst = ranked[-1] if ranked else None

    return {
        "artifacts": [asdict(artifact) for artifact in artifacts],
        "metric": metric,
        "expression": expression,
        "direction": direction,
        "row_count": len(rows),
        "comparable_row_count": len(comparable_rows),
        "missing_files": missing_files,
        "best": best,
        "worst": worst,
        "ranked": ranked[:limit],
        "parameter_differences": _parameter_differences(ranked),
        "notes": _notes(rows, comparable_rows, metric),
    }


def _select_artifacts(
    archive_store: ArchiveStore,
    *,
    run_ids: list[str] | None,
    query: str | None,
    limit: int,
) -> list[SimulationArtifact]:
    if run_ids:
        return [archive_store.get_simulation_artifact(run_id) for run_id in run_ids]
    if query:
        return archive_store.search_simulation_artifacts(query, limit=limit)
    return archive_store.list_simulation_artifacts(kind="parameter_sweep", limit=limit)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _parameter_columns(row: dict[str, Any]) -> dict[str, Any]:
    parameters = {}
    for key, value in row.items():
        if key.startswith("param_"):
            parameters[key.removeprefix("param_")] = value
    return parameters


def _rank_rows(rows: list[dict[str, Any]], *, direction: str) -> list[dict[str, Any]]:
    reverse = direction != "min"
    return sorted(
        rows,
        key=lambda row: row["metric_value"],
        reverse=reverse,
    )


def _parameter_differences(rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
    values_by_parameter: dict[str, list[Any]] = {}
    for row in rows:
        for name, value in row["parameters"].items():
            values = values_by_parameter.setdefault(name, [])
            if value not in values:
                values.append(value)
    return {
        name: values
        for name, values in values_by_parameter.items()
        if len(values) > 1
    }


def _notes(
    rows: list[dict[str, Any]],
    comparable_rows: list[dict[str, Any]],
    metric: str,
) -> list[str]:
    notes = []
    if not rows:
        notes.append("No CSV rows matched the requested expression filter.")
    elif not comparable_rows:
        notes.append(f"No rows had numeric values for metric '{metric}'.")
    elif len(comparable_rows) < len(rows):
        notes.append(
            f"{len(rows) - len(comparable_rows)} rows were skipped because metric '{metric}' was not numeric."
        )
    return notes
