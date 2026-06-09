"""Replay helpers for archived COMSOL sweep artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from comsol_agent.memory.archive_store import ArchiveStore, SimulationArtifact


def build_replay_request(
    archive_store: ArchiveStore,
    *,
    run_id: str,
    parameter_overrides: dict[str, list[str]] | None = None,
    expression_overrides: list[str] | None = None,
    model_name: str | None = None,
    max_cases: int | None = None,
) -> dict[str, Any]:
    """Build a `simulation_run_parameter_sweep` request from an archived run."""
    artifact = archive_store.get_simulation_artifact(run_id)
    payload = _load_payload(artifact)
    parameters = _parameters_from_payload(payload)
    if parameter_overrides:
        parameters.update(_normalize_parameter_overrides(parameter_overrides))

    expressions = list(expression_overrides) if expression_overrides else _expressions_from_payload(payload)
    source_kwargs = _source_kwargs(payload, artifact, model_name=model_name)
    request = {
        **source_kwargs,
        "parameters": parameters,
        "expressions": expressions,
        "max_cases": max_cases or int(payload.get("executed_cases") or 25),
        "solve": True,
    }
    return {
        "source_run_id": run_id,
        "source_artifact": _artifact_summary(artifact),
        "source_payload_summary": {
            "model_name": payload.get("model_name"),
            "executed_cases": payload.get("executed_cases"),
            "source": payload.get("source"),
            "expressions": _expressions_from_payload(payload),
        },
        "request": request,
    }


def _load_payload(artifact: SimulationArtifact) -> dict[str, Any]:
    path = Path(artifact.json_path)
    if not path.exists():
        raise FileNotFoundError(f"Archived sweep JSON not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _parameters_from_payload(payload: dict[str, Any]) -> dict[str, list[str]]:
    axes = (payload.get("plan") or {}).get("axes") or []
    parameters = {
        axis["parameter"]: [str(value) for value in axis.get("values", [])]
        for axis in axes
        if axis.get("parameter")
    }
    if parameters:
        return parameters

    for case in payload.get("cases", []):
        for name, value in (case.get("parameters") or {}).items():
            values = parameters.setdefault(name, [])
            if str(value) not in values:
                values.append(str(value))
    if not parameters:
        raise ValueError("Archived sweep has no recoverable parameter axes.")
    return parameters


def _normalize_parameter_overrides(
    parameter_overrides: dict[str, list[str]],
) -> dict[str, list[str]]:
    normalized = {}
    for name, values in parameter_overrides.items():
        if isinstance(values, str):
            normalized[name] = [values]
        else:
            normalized[name] = [str(value) for value in values]
    return normalized


def _expressions_from_payload(payload: dict[str, Any]) -> list[str]:
    expressions = list((payload.get("plan") or {}).get("output_expressions") or [])
    if expressions:
        return expressions

    for case in payload.get("cases", []):
        for evaluation in case.get("evaluations") or []:
            expression = evaluation.get("expression")
            if expression and expression not in expressions:
                expressions.append(expression)
    return expressions


def _source_kwargs(
    payload: dict[str, Any],
    artifact: SimulationArtifact,
    *,
    model_name: str | None,
) -> dict[str, str]:
    source = payload.get("source") or artifact.source or {}
    source_type = source.get("type")
    if source_type == "example" and source.get("example_name"):
        return {"example_name": source["example_name"]}
    if source_type == "model_file" and source.get("model_file"):
        return {"model_file": source["model_file"]}
    if model_name:
        return {"model_name": model_name}
    if source_type == "loaded_model" and source.get("model_name"):
        return {"model_name": source["model_name"]}
    raise ValueError(
        "Archived sweep source cannot be replayed automatically; provide model_name for a loaded model."
    )


def _artifact_summary(artifact: SimulationArtifact) -> dict[str, Any]:
    return {
        "run_id": artifact.run_id,
        "kind": artifact.kind,
        "model_name": artifact.model_name,
        "source": artifact.source,
        "json_path": artifact.json_path,
        "csv_path": artifact.csv_path,
        "manifest_path": artifact.manifest_path,
    }
