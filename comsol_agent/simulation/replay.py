"""Replay helpers for archived COMSOL simulation artifacts."""

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


def build_template_replay_request(
    archive_store: ArchiveStore,
    *,
    run_id: str,
    params_overrides: dict[str, Any] | None = None,
    model_name: str | None = None,
    create_model_name: str | None = None,
    validate_first: bool | None = None,
) -> dict[str, Any]:
    """Build a `simulation_run_template` request from an archived template run."""
    artifact = archive_store.get_simulation_artifact(run_id)
    if artifact.kind not in {"template_execution", "generated_code_execution"}:
        raise ValueError(
            f"Artifact {run_id!r} is {artifact.kind!r}, not a replayable execution artifact."
        )

    payload = _load_payload(artifact)
    source = payload.get("source") or artifact.source or {}
    template_snapshot = payload.get("template") or {}
    template_name = payload.get("template_name") or template_snapshot.get("name") or source.get("name")
    java_code = template_snapshot.get("java_code")
    params = dict(template_snapshot.get("params") or payload.get("params") or {})
    if params_overrides:
        params.update(params_overrides)

    request: dict[str, Any] = {
        "params": params,
        "validate_first": validate_first if validate_first is not None else True,
    }
    if java_code:
        request["java_code"] = java_code
        if template_name:
            request["name"] = template_name
    elif template_name:
        request["name"] = template_name
    else:
        raise ValueError(
            "Archived template execution has no template name or java_code snapshot to replay."
        )

    target_kwargs = _template_target_kwargs(
        payload,
        model_name=model_name,
        create_model_name=create_model_name,
    )
    request.update(target_kwargs)

    return {
        "source_run_id": run_id,
        "source_artifact": _artifact_summary(artifact),
        "source_payload_summary": {
            "model_name": payload.get("model_name"),
            "template_name": template_name,
            "source": source,
            "validation_status": (payload.get("validation") or {}).get("status"),
            "execution_success": (payload.get("execution") or {}).get("success"),
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


def _template_target_kwargs(
    payload: dict[str, Any],
    *,
    model_name: str | None,
    create_model_name: str | None,
) -> dict[str, str]:
    if model_name and create_model_name:
        raise ValueError("Provide at most one of model_name or create_model_name for replay.")
    if create_model_name:
        return {"create_model_name": create_model_name}
    if model_name:
        return {"model_name": model_name}

    original_model_name = payload.get("model_name")
    if payload.get("create") or "comsol_create_model" in (payload.get("tool_sequence") or []):
        if not original_model_name:
            raise ValueError("Archived template run did not record a created model name.")
        return {"create_model_name": original_model_name}
    if original_model_name:
        return {"model_name": original_model_name}
    raise ValueError("Archived template run has no recoverable model target.")


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
