"""Simulation planning and example runtime tools."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from comsol_agent.cli.config import get_config_dir
from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.simulation.artifact_reader import read_archived_artifact
from comsol_agent.simulation.artifacts import persist_sweep_result
from comsol_agent.simulation.artifacts import persist_template_execution_result
from comsol_agent.simulation.bearing_contact import plan_bearing_contact_setup
from comsol_agent.simulation.comparison import compare_archived_sweeps
from comsol_agent.simulation.examples import get_example, list_examples
from comsol_agent.simulation.local_docs import build_index_from_directory
from comsol_agent.simulation.replay import build_replay_request, build_template_replay_request
from comsol_agent.simulation.reporting import (
    write_comparison_report,
    write_template_execution_report,
)
from comsol_agent.simulation.sweeps import plan_parameter_sweep
from comsol_agent.tools.comsol.model_ops import (
    comsol_close_model,
    comsol_create_model,
    comsol_load_model,
    comsol_save_model,
    comsol_set_parameter,
)
from comsol_agent.tools.comsol.solve import (
    comsol_evaluate,
    comsol_execute_java,
    comsol_get_model_summary,
    comsol_solve,
)


def simulation_plan_parameter_sweep(
    model_name: str,
    parameters: dict[str, list[str]],
    output_expressions: list[str] | None = None,
    max_cases: int = 100,
) -> dict:
    """Plan a parameter sweep without executing COMSOL."""
    try:
        plan = plan_parameter_sweep(
            model_name=model_name,
            parameters=parameters,
            output_expressions=output_expressions,
            max_cases=max_cases,
        )
        return {"success": True, "plan": plan.to_dict()}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def simulation_plan_bearing_contact(
    user_request: str,
    provided_params: dict | None = None,
    allow_defaults: bool = False,
) -> dict:
    """Plan bearing-contact parameters, defaults, and follow-up questions."""
    try:
        plan = plan_bearing_contact_setup(
            user_request=user_request,
            provided_params=provided_params or {},
            allow_defaults=allow_defaults,
        )
        return {
            "success": True,
            "plan": plan.to_dict(),
            "note": (
                "Use this plan before running bearing_contact_hertz_seed. "
                "If ready_to_run is false, ask follow-up questions instead of starting COMSOL."
            ),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def simulation_export_bearing_contact_package(
    model_name: str,
    template_run_id: str | None = None,
    plot_path: str | None = None,
    output_dir: str | None = None,
    package_name: str = "bearing_contact_result",
    archive_path: str | None = None,
    save_model: bool = True,
    model_output_path: str | None = None,
) -> dict:
    """Export a bearing-contact result package with model, plot, metrics, and report."""
    try:
        target_dir = Path(output_dir or "runtime_smoke/bearing_contact_results").expanduser().resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        run_id = _bearing_contact_package_run_id(package_name, model_name)
        package_dir = target_dir / run_id
        package_dir.mkdir(parents=True, exist_ok=True)

        model_save = None
        if save_model:
            mph_path = Path(model_output_path).expanduser().resolve() if model_output_path else package_dir / f"{model_name}.mph"
            model_save = comsol_save_model(model_name, str(mph_path))
            if not model_save.get("success"):
                return {
                    "success": False,
                    "stage": "save_model",
                    "model_name": model_name,
                    "error": model_save.get("error"),
                    "model_save": model_save,
                }

        evaluations = [
            comsol_evaluate(model_name, "solid.mises"),
            comsol_evaluate(model_name, "contact_pressure_guess"),
        ]
        failed_eval = [item for item in evaluations if not item.get("success")]
        if failed_eval:
            return {
                "success": False,
                "stage": "evaluate",
                "model_name": model_name,
                "evaluations": evaluations,
                "error": failed_eval[0].get("error"),
            }

        template_artifact = None
        if template_run_id:
            try:
                template_artifact = read_archived_artifact(
                    _archive_store(archive_path),
                    run_id=template_run_id,
                    max_lines=40,
                )
            except Exception as exc:
                template_artifact = {"error": str(exc), "run_id": template_run_id}

        plot = _package_plot_info(plot_path)
        summary = {
            "success": True,
            "kind": "bearing_contact_package",
            "run_id": run_id,
            "model_name": model_name,
            "template_run_id": template_run_id,
            "model_save": model_save,
            "plot": plot,
            "evaluations": evaluations,
            "metrics": _bearing_contact_metrics(evaluations),
            "template_artifact": template_artifact,
            "assumptions": [
                "2D single-ball/raceway workflow unless the template states otherwise.",
                "Inspect the template execution record to distinguish Hertz-style pressure and explicit COMSOL contact-pair models.",
                "Use the package for workflow review; inspect boundary selections, mesh, and contact convergence before production bearing design.",
            ],
        }

        json_path = package_dir / "summary.json"
        markdown_path = package_dir / "report.md"
        manifest_path = package_dir / "manifest.json"
        json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(_bearing_contact_package_markdown(summary), encoding="utf-8")
        manifest = {
            "run_id": run_id,
            "created_at": _utc_now_for_package(),
            "kind": "bearing_contact_package",
            "model_name": model_name,
            "source": {"type": "bearing_contact_package", "template_run_id": template_run_id},
            "executed_cases": 1,
            "truncated": False,
            "json_path": str(json_path),
            "csv_path": None,
            "manifest_path": str(manifest_path),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        archive_record = None
        archive_error = None
        try:
            archive_record = _archive_store(archive_path).index_simulation_artifact(
                manifest,
                metadata={
                    "template_run_id": template_run_id,
                    "model_path": (model_save or {}).get("saved_to"),
                    "plot_path": plot.get("path"),
                    "markdown_path": str(markdown_path),
                    "metrics": summary["metrics"],
                },
            )
        except Exception as exc:
            archive_error = str(exc)

        result = {
            "success": True,
            "run_id": run_id,
            "model_name": model_name,
            "directory": str(package_dir),
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "manifest_path": str(manifest_path),
            "model_path": (model_save or {}).get("saved_to"),
            "plot_path": plot.get("path"),
            "metrics": summary["metrics"],
        }
        if archive_record is not None:
            result["archive"] = {
                "db_path": str(_archive_store(archive_path).db_path),
                "id": archive_record.id,
                "run_id": archive_record.run_id,
                "kind": archive_record.kind,
            }
        if archive_error:
            result["archive_error"] = archive_error
        return result
    except Exception as exc:
        return {"success": False, "error": str(exc), "model_name": model_name}


def simulation_search_local_docs(
    query: str,
    directory: str = "docs",
    pattern: str = "*.md",
    max_results: int = 5,
) -> dict:
    """Search local markdown docs without embeddings or network access."""
    try:
        index = build_index_from_directory(directory, pattern=pattern)
        results = index.search(query, limit=max_results)
        return {
            "success": True,
            "query": query,
            "count": len(results),
            "results": [result.to_dict() for result in results],
            "note": "Offline keyword search; replace with vector RAG when embeddings are configured.",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def simulation_retrieve_api_docs(
    query: str,
    directory: str = "docs",
    pattern: str = "*.md",
    max_results: int = 5,
    domain: str | None = None,
    snippet_chars: int = 700,
) -> dict:
    """Retrieve compact, cited local API/documentation snippets for offline RAG."""
    try:
        index = build_index_from_directory(directory, pattern=pattern)
        snippets = index.retrieve_api_docs(
            query,
            limit=max_results,
            domain=domain,
            snippet_chars=snippet_chars,
        )
        return {
            "success": True,
            "query": query,
            "domain": domain,
            "count": len(snippets),
            "snippets": snippets,
            "note": "Offline local retrieval with source citations; no network or embeddings required.",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def simulation_list_example_models(domain: str | None = None) -> dict:
    """List built-in COMSOL example models known to this project."""
    try:
        examples = [example.to_dict() for example in list_examples(domain)]
        return {"success": True, "count": len(examples), "examples": examples}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def simulation_list_templates(
    domain: str | None = None,
    limit: int = 20,
    archive_path: str | None = None,
) -> dict:
    """List archived simulation/code templates."""
    try:
        store = _archive_store(archive_path)
        templates = store.list_templates(domain=domain, limit=limit)
        return {
            "success": True,
            "archive_path": str(store.db_path),
            "count": len(templates),
            "templates": [
                {
                    "id": template.id,
                    "name": template.name,
                    "domain": template.domain,
                    "params": template.params,
                    "created_at": template.created_at,
                    "updated_at": template.updated_at,
                    "code_preview": _preview(template.java_code, 220),
                }
                for template in templates
            ],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def simulation_search_templates(
    query: str,
    domain: str | None = None,
    limit: int = 20,
    archive_path: str | None = None,
) -> dict:
    """Search archived simulation/code templates by keyword."""
    try:
        store = _archive_store(archive_path)
        templates = store.search_templates(query=query, domain=domain, limit=limit)
        return {
            "success": True,
            "archive_path": str(store.db_path),
            "query": query,
            "domain": domain,
            "count": len(templates),
            "templates": [
                {
                    "id": template.id,
                    "name": template.name,
                    "domain": template.domain,
                    "params": template.params,
                    "created_at": template.created_at,
                    "updated_at": template.updated_at,
                    "code_preview": _preview(template.java_code, 220),
                }
                for template in templates
            ],
            "note": "Offline keyword search over template name, domain, code, and params.",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "query": query}


def simulation_read_template(
    name: str,
    archive_path: str | None = None,
) -> dict:
    """Read one archived simulation/code template by name."""
    try:
        store = _archive_store(archive_path)
        template = store.get_template(name)
        return {
            "success": True,
            "archive_path": str(store.db_path),
            "template": asdict(template),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "name": name}


def simulation_save_template(
    name: str,
    java_code: str,
    domain: str | None = None,
    params: dict | None = None,
    archive_path: str | None = None,
) -> dict:
    """Save or update a reusable simulation/code template."""
    try:
        if not name.strip():
            return {"success": False, "error": "Template name is required."}
        if not java_code.strip():
            return {"success": False, "error": "Template java_code is required."}
        validation = _validate_template_code(name=name.strip(), java_code=java_code, params=params or {})
        if validation["errors"]:
            return {
                "success": False,
                "error": "Template validation failed.",
                "name": name,
                "validation": validation,
            }
        store = _archive_store(archive_path)
        template = store.add_template(
            name=name.strip(),
            domain=domain.strip() if isinstance(domain, str) and domain.strip() else None,
            java_code=java_code,
            params=params or {},
        )
        return {
            "success": True,
            "archive_path": str(store.db_path),
            "template": asdict(template),
            "validation": validation,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "name": name}


def simulation_validate_template(
    name: str | None = None,
    java_code: str | None = None,
    params: dict | None = None,
    archive_path: str | None = None,
) -> dict:
    """Validate an archived template or raw Java/API seed code without starting COMSOL."""
    try:
        source = "raw"
        template = None
        code = java_code
        effective_params = params or {}
        archive_db_path = None
        if name and java_code is None:
            store = _archive_store(archive_path)
            template = store.get_template(name)
            archive_db_path = str(store.db_path)
            source = "archive"
            code = template.java_code
            effective_params = template.params if params is None else params
        if code is None:
            return {"success": False, "error": "Either name or java_code is required."}
        validation = _validate_template_code(name=name, java_code=code, params=effective_params)
        return {
            "success": not validation["errors"],
            "source": source,
            "archive_path": archive_db_path,
            "template": asdict(template) if template is not None else None,
            "validation": validation,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "name": name}


def simulation_export_template(
    name: str,
    output_path: str | None = None,
    include_params_header: bool = True,
    overwrite: bool = True,
    archive_path: str | None = None,
) -> dict:
    """Export an archived template's Java/API seed code to a local file."""
    try:
        store = _archive_store(archive_path)
        template = store.get_template(name)
        target = _template_export_path(template.name, output_path)
        error = _validate_export_path(target)
        if error:
            return {"success": False, "error": error, "name": name}
        if target.exists() and not overwrite:
            return {"success": False, "error": f"Output file already exists: {target}", "name": name}

        content = template.java_code
        if include_params_header:
            params_json = json.dumps(template.params, ensure_ascii=False, sort_keys=True)
            header = (
                f"// COMSOL Agent template: {template.name}\n"
                f"// Domain: {template.domain or ''}\n"
                f"// Params: {params_json}\n\n"
            )
            content = header + content
            if not content.endswith("\n"):
                content += "\n"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "archive_path": str(store.db_path),
            "template": asdict(template),
            "output_path": str(target),
            "size_bytes": target.stat().st_size,
            "overwrite": overwrite,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "name": name}


def simulation_run_template(
    name: str | None = None,
    java_code: str | None = None,
    params: dict | None = None,
    model_name: str | None = None,
    create_model_name: str | None = None,
    validate_first: bool = True,
    close_model: bool | None = None,
    persist_results: bool = True,
    artifact_dir: str | None = None,
    artifact_name: str | None = None,
    archive_results: bool = True,
    archive_path: str | None = None,
) -> dict:
    """Validate and execute a template's Java/API seed code against COMSOL."""
    active_model_name: str | None = None
    created_by_tool = False
    try:
        source_count = sum(bool(value) for value in (model_name, create_model_name))
        if source_count != 1:
            return {
                "success": False,
                "error": "Provide exactly one of model_name or create_model_name.",
            }
        if not name and java_code is None:
            return {"success": False, "error": "Either name or java_code is required."}

        template = None
        effective_code = java_code
        effective_params = params or {}
        source = {"type": "raw_template"}
        if name and java_code is None:
            store = _archive_store(archive_path)
            template = store.get_template(name)
            effective_code = template.java_code
            effective_params = template.params if params is None else params
            source = {"type": "template", "name": template.name, "domain": template.domain}
        elif name:
            source = {"type": "raw_template", "name": name}

        assert effective_code is not None
        validation = _validate_template_code(
            name=name or (template.name if template else None),
            java_code=effective_code,
            params=effective_params,
        )
        template_snapshot = _template_execution_snapshot(
            name=name or (template.name if template else None),
            domain=template.domain if template else None,
            java_code=effective_code,
            params=effective_params,
        )
        if validate_first and validation["errors"]:
            result = {
                "success": False,
                "executed": False,
                "error": "Template validation failed.",
                "template_name": name or (template.name if template else None),
                "model_name": model_name or create_model_name,
                "source": source,
                "params": effective_params,
                "template": template_snapshot,
                "validation": validation,
            }
            if persist_results:
                result["artifacts"] = persist_template_execution_result(
                    result,
                    output_dir=artifact_dir,
                    run_name=artifact_name or _template_run_name(name, create_model_name or model_name),
                    archive_results=archive_results,
                    archive_path=archive_path,
                )
            return result

        create_result = None
        if create_model_name:
            create_result = comsol_create_model(create_model_name)
            if not create_result.get("success"):
                result = {
                    "success": False,
                    "executed": False,
                    "stage": "create_model",
                    "template_name": name or (template.name if template else None),
                    "model_name": create_model_name,
                    "source": source,
                    "params": effective_params,
                    "template": template_snapshot,
                    "validation": validation,
                    "create": create_result,
                }
                if persist_results:
                    result["artifacts"] = persist_template_execution_result(
                        result,
                        output_dir=artifact_dir,
                        run_name=artifact_name or _template_run_name(name, create_model_name),
                        archive_results=archive_results,
                        archive_path=archive_path,
                    )
                return result
            active_model_name = create_result["model_name"]
            created_by_tool = True
        else:
            active_model_name = model_name

        execution = comsol_execute_java(effective_code, active_model_name)
        close_result = _close_after_template_run(
            active_model_name,
            close_model=close_model,
            created_by_tool=created_by_tool,
        )
        result = {
            "success": bool(execution.get("success")),
            "executed": True,
            "template_name": name or (template.name if template else None),
            "model_name": active_model_name,
            "source": source,
            "params": effective_params,
            "template": template_snapshot,
            "validation": validation,
            "create": create_result,
            "execution": execution,
            "close": close_result,
            "tool_sequence": [
                *(["comsol_create_model"] if create_result else []),
                "simulation_validate_template" if validate_first else "template_validation_inline",
                "comsol_execute_java",
                *(["comsol_close_model"] if close_result else []),
            ],
        }
        if persist_results:
            result["artifacts"] = persist_template_execution_result(
                result,
                output_dir=artifact_dir,
                run_name=artifact_name or _template_run_name(name, active_model_name),
                archive_results=archive_results,
                archive_path=archive_path,
            )
        return result
    except Exception as exc:
        return {
            "success": False,
            "executed": False,
            "error": str(exc),
            "template_name": name,
            "model_name": active_model_name or model_name or create_model_name,
        }


def simulation_list_artifacts(
    kind: str | None = "parameter_sweep",
    model_name: str | None = None,
    limit: int = 20,
    archive_path: str | None = None,
) -> dict:
    """List recent simulation artifacts from the archive index."""
    try:
        store = _archive_store(archive_path)
        artifacts = store.list_simulation_artifacts(
            kind=kind,
            model_name=model_name,
            limit=limit,
        )
        return {
            "success": True,
            "archive_path": str(store.db_path),
            "count": len(artifacts),
            "artifacts": [_artifact_to_dict(artifact) for artifact in artifacts],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def simulation_search_artifacts(
    query: str,
    limit: int = 20,
    archive_path: str | None = None,
) -> dict:
    """Search archived simulation artifacts by run id, model, source, path, or metadata."""
    try:
        store = _archive_store(archive_path)
        artifacts = store.search_simulation_artifacts(query, limit=limit)
        return {
            "success": True,
            "archive_path": str(store.db_path),
            "query": query,
            "count": len(artifacts),
            "artifacts": [_artifact_to_dict(artifact) for artifact in artifacts],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def simulation_read_artifact(
    run_id: str,
    max_lines: int = 80,
    archive_path: str | None = None,
) -> dict:
    """Read a compact preview of an archived simulation artifact."""
    try:
        store = _archive_store(archive_path)
        artifact = read_archived_artifact(
            store,
            run_id=run_id,
            max_lines=max_lines,
        )
        return {
            "success": True,
            "archive_path": str(store.db_path),
            **artifact,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "run_id": run_id}


def simulation_compare_artifacts(
    run_ids: list[str] | None = None,
    query: str | None = None,
    metric: str = "mean",
    expression: str | None = None,
    direction: str = "max",
    limit: int = 20,
    archive_path: str | None = None,
) -> dict:
    """Compare archived parameter sweep artifacts by a numeric CSV metric."""
    try:
        if direction not in {"max", "min"}:
            return {"success": False, "error": "direction must be 'max' or 'min'."}
        store = _archive_store(archive_path)
        comparison = compare_archived_sweeps(
            store,
            run_ids=run_ids,
            query=query,
            metric=metric,
            expression=expression,
            direction=direction,
            limit=limit,
        )
        return {
            "success": True,
            "archive_path": str(store.db_path),
            "comparison": comparison,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def simulation_export_artifact_report(
    run_ids: list[str] | None = None,
    query: str | None = None,
    metric: str = "mean",
    expression: str | None = None,
    direction: str = "max",
    limit: int = 20,
    output_dir: str | None = None,
    report_name: str | None = None,
    title: str | None = None,
    output_format: str = "markdown",
    kind: str = "parameter_sweep",
    archive_path: str | None = None,
) -> dict:
    """Generate a Markdown and optionally HTML report from archived simulation artifacts."""
    try:
        if direction not in {"max", "min"}:
            return {"success": False, "error": "direction must be 'max' or 'min'."}
        if output_format not in {"markdown", "html", "both"}:
            return {"success": False, "error": "output_format must be 'markdown', 'html', or 'both'."}
        if kind not in {"parameter_sweep", "template_execution"}:
            return {"success": False, "error": "kind must be 'parameter_sweep' or 'template_execution'."}
        store = _archive_store(archive_path)
        if kind == "template_execution":
            report = write_template_execution_report(
                store,
                run_ids=run_ids,
                query=query,
                limit=limit,
                output_dir=output_dir,
                report_name=report_name,
                title=title,
                output_format=output_format,
                archive_path=archive_path,
            )
            return {
                "success": True,
                "archive_path": str(store.db_path),
                "kind": kind,
                "report": report,
                "summary": report["summary"],
            }

        comparison = compare_archived_sweeps(
            store,
            run_ids=run_ids,
            query=query,
            metric=metric,
            expression=expression,
            direction=direction,
            limit=limit,
        )
        report = write_comparison_report(
            comparison,
            output_dir=output_dir,
            report_name=report_name,
            title=title,
            output_format=output_format,
            archive_path=archive_path,
        )
        return {
            "success": True,
            "archive_path": str(store.db_path),
            "kind": kind,
            "report": report,
            "comparison": {
                "metric": comparison["metric"],
                "expression": comparison["expression"],
                "direction": comparison["direction"],
                "row_count": comparison["row_count"],
                "comparable_row_count": comparison["comparable_row_count"],
                "best": comparison["best"],
                "worst": comparison["worst"],
            },
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def simulation_rerun_artifact(
    run_id: str,
    parameter_overrides: dict[str, list[str]] | None = None,
    expression_overrides: list[str] | None = None,
    params_overrides: dict[str, str] | None = None,
    model_name: str | None = None,
    create_model_name: str | None = None,
    max_cases: int | None = None,
    validate_first: bool | None = None,
    artifact_name: str | None = None,
    artifact_dir: str | None = None,
    archive_path: str | None = None,
    close_model: bool | None = None,
) -> dict:
    """Replay an archived sweep or template execution artifact."""
    try:
        store = _archive_store(archive_path)
        artifact = store.get_simulation_artifact(run_id)
        if artifact.kind == "template_execution":
            replay = build_template_replay_request(
                store,
                run_id=run_id,
                params_overrides=params_overrides,
                model_name=model_name,
                create_model_name=create_model_name,
                validate_first=validate_first,
            )
            request = dict(replay["request"])
            result = simulation_run_template(
                **request,
                close_model=close_model,
                artifact_dir=artifact_dir,
                artifact_name=artifact_name or f"rerun_{run_id}",
                archive_path=archive_path,
            )
            result["replay"] = replay
            return result
        if artifact.kind != "parameter_sweep":
            return {
                "success": False,
                "error": f"Artifact kind {artifact.kind!r} is not replayable.",
                "source_run_id": run_id,
            }
        replay = build_replay_request(
            store,
            run_id=run_id,
            parameter_overrides=parameter_overrides,
            expression_overrides=expression_overrides,
            model_name=model_name,
            max_cases=max_cases,
        )
        request = dict(replay["request"])
        result = simulation_run_parameter_sweep(
            **request,
            close_model=close_model,
            artifact_dir=artifact_dir,
            artifact_name=artifact_name or f"rerun_{run_id}",
            archive_path=archive_path,
        )
        result["replay"] = replay
        return result
    except Exception as exc:
        return {"success": False, "error": str(exc), "source_run_id": run_id}


def simulation_run_example_model(
    example_name: str = "thermal_slab",
    expression: str | None = None,
    expressions: list[str] | None = None,
    parameters: dict[str, str] | None = None,
    study_name: str | None = None,
    solve: bool = True,
    close_model: bool = True,
) -> dict:
    """Run a built-in COMSOL example through the standard tool chain."""
    model_name: str | None = None
    try:
        example = get_example(example_name)
        if not Path(example.model_path).exists():
            return {
                "success": False,
                "error": f"Example model file not found: {example.model_path}",
                "example": example.to_dict(),
            }

        load_result = comsol_load_model(example.model_path)
        if not load_result.get("success"):
            return _example_failure(example, "load_model", load_result, model_name)
        model_name = load_result["model_name"]

        summary_result = comsol_get_model_summary(model_name)
        if not summary_result.get("success"):
            return _example_failure(example, "get_model_summary", summary_result, model_name)

        parameter_results = []
        for name, value in (parameters or {}).items():
            parameter_result = comsol_set_parameter(model_name, name, value)
            parameter_results.append(parameter_result)
            if not parameter_result.get("success"):
                return _example_failure(example, "set_parameter", parameter_result, model_name)

        solve_result = None
        if solve:
            solve_result = comsol_solve(model_name, study_name=study_name)
            if not solve_result.get("success"):
                return _example_failure(example, "solve", solve_result, model_name)

        evaluated_expressions = _normalize_expressions(
            expression=expression,
            expressions=expressions,
            default_expression=example.default_expression,
        )
        evaluation_results = []
        for evaluated_expression in evaluated_expressions:
            evaluation_result = comsol_evaluate(model_name, evaluated_expression)
            evaluation_results.append(evaluation_result)
            if not evaluation_result.get("success"):
                return _example_failure(example, "evaluate", evaluation_result, model_name)

        close_result = None
        if close_model:
            close_result = comsol_close_model(model_name, save=False)

        return {
            "success": True,
            "example": example.to_dict(),
            "model_name": model_name,
            "load": load_result,
            "summary": summary_result,
            "parameters": parameter_results,
            "solve": solve_result,
            "evaluation": evaluation_results[0],
            "evaluations": evaluation_results,
            "close": close_result,
            "tool_sequence": [
                "comsol_load_model",
                "comsol_get_model_summary",
                *(["comsol_set_parameter"] if parameters else []),
                *(["comsol_solve"] if solve else []),
                "comsol_evaluate",
                *(["comsol_close_model"] if close_model else []),
            ],
        }
    except KeyError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc), "model_name": model_name}


def simulation_run_parameter_sweep(
    parameters: dict[str, list[str]],
    model_name: str | None = None,
    example_name: str | None = None,
    model_file: str | None = None,
    expression: str | None = None,
    expressions: list[str] | None = None,
    study_name: str | None = None,
    max_cases: int = 25,
    solve: bool = True,
    close_model: bool | None = None,
    persist_results: bool = True,
    artifact_dir: str | None = None,
    artifact_name: str | None = None,
    archive_results: bool = True,
    archive_path: str | None = None,
) -> dict:
    """Run a bounded COMSOL parameter sweep and return compact per-case results."""
    active_model_name: str | None = None
    loaded_by_tool = False
    example = None
    try:
        source_count = sum(bool(value) for value in (model_name, example_name, model_file))
        if source_count != 1:
            return {
                "success": False,
                "error": "Provide exactly one of model_name, example_name, or model_file.",
            }

        if example_name:
            example = get_example(example_name)
            if not Path(example.model_path).exists():
                return {
                    "success": False,
                    "error": f"Example model file not found: {example.model_path}",
                    "example": example.to_dict(),
                }
            load_result = comsol_load_model(example.model_path)
            if not load_result.get("success"):
                return _sweep_failure("load_model", load_result, active_model_name)
            active_model_name = load_result["model_name"]
            loaded_by_tool = True
        elif model_file:
            if not Path(model_file).exists():
                return {"success": False, "error": f"Model file not found: {model_file}"}
            load_result = comsol_load_model(model_file)
            if not load_result.get("success"):
                return _sweep_failure("load_model", load_result, active_model_name)
            active_model_name = load_result["model_name"]
            loaded_by_tool = True
        else:
            active_model_name = model_name

        assert active_model_name is not None
        evaluated_expressions = _normalize_expressions(
            expression=expression,
            expressions=expressions,
            default_expression=example.default_expression if example else "",
        )
        plan = plan_parameter_sweep(
            model_name=active_model_name,
            parameters=parameters,
            output_expressions=evaluated_expressions,
            max_cases=max_cases,
        )

        case_results = []
        for case in plan.cases:
            case_result = _run_sweep_case(
                model_name=active_model_name,
                case_index=case.index,
                case_label=case.label,
                parameters=case.parameters,
                expressions=evaluated_expressions,
                study_name=study_name,
                solve=solve,
            )
            case_results.append(case_result)
            if not case_result.get("success"):
                close_result = _close_after_sweep(
                    active_model_name,
                    close_model=close_model,
                    loaded_by_tool=loaded_by_tool,
                )
                return {
                    "success": False,
                    "stage": "case",
                    "model_name": active_model_name,
                    "failed_case_index": case.index,
                    "plan": plan.to_dict(),
                    "cases": case_results,
                    "close": close_result,
                }

        close_result = _close_after_sweep(
            active_model_name,
            close_model=close_model,
            loaded_by_tool=loaded_by_tool,
        )
        result = {
            "success": True,
            "model_name": active_model_name,
            "source": _sweep_source(
                model_name=model_name,
                example_name=example_name,
                model_file=model_file,
            ),
            "example": example.to_dict() if example else None,
            "plan": plan.to_dict(),
            "executed_cases": len(case_results),
            "truncated": plan.estimated_runs > len(plan.cases),
            "cases": case_results,
            "close": close_result,
            "tool_sequence": [
                *(["comsol_load_model"] if loaded_by_tool else []),
                "comsol_set_parameter",
                *(["comsol_solve"] if solve else []),
                *(["comsol_evaluate"] if evaluated_expressions else []),
                *(["comsol_close_model"] if close_result else []),
            ],
        }
        if persist_results:
            result["artifacts"] = persist_sweep_result(
                result,
                output_dir=artifact_dir,
                run_name=artifact_name,
                archive_results=archive_results,
                archive_path=archive_path,
            )
        return result
    except KeyError as exc:
        return {"success": False, "error": str(exc), "model_name": active_model_name}
    except Exception as exc:
        close_result = _close_after_sweep(
            active_model_name,
            close_model=close_model,
            loaded_by_tool=loaded_by_tool,
        )
        return {
            "success": False,
            "error": str(exc),
            "model_name": active_model_name,
            "close": close_result,
        }


def _example_failure(example, stage: str, result: dict, model_name: str | None) -> dict:
    close_result = None
    if model_name:
        close_result = comsol_close_model(model_name, save=False)
    return {
        "success": False,
        "stage": stage,
        "example": example.to_dict(),
        "model_name": model_name,
        "result": result,
        "close": close_result,
    }


def _normalize_expressions(
    *,
    expression: str | None,
    expressions: list[str] | None,
    default_expression: str,
) -> list[str]:
    """Normalize legacy single expression and new multi-expression input."""
    values: list[str] = []
    if expressions:
        values.extend(item for item in expressions if item)
    if expression:
        values.append(expression)
    if not values and default_expression:
        values.append(default_expression)

    unique_values: list[str] = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    return unique_values


def _run_sweep_case(
    *,
    model_name: str,
    case_index: int,
    case_label: str,
    parameters: dict[str, str],
    expressions: list[str],
    study_name: str | None,
    solve: bool,
) -> dict:
    parameter_results = []
    for name, value in parameters.items():
        parameter_result = comsol_set_parameter(model_name, name, value)
        parameter_results.append(parameter_result)
        if not parameter_result.get("success"):
            return {
                "success": False,
                "case_index": case_index,
                "label": case_label,
                "parameters": parameters,
                "stage": "set_parameter",
                "result": parameter_result,
            }

    solve_result = None
    if solve:
        solve_result = comsol_solve(model_name, study_name=study_name)
        if not solve_result.get("success"):
            return {
                "success": False,
                "case_index": case_index,
                "label": case_label,
                "parameters": parameters,
                "stage": "solve",
                "parameter_results": parameter_results,
                "result": solve_result,
            }

    evaluation_results = []
    for evaluated_expression in expressions:
        evaluation_result = comsol_evaluate(model_name, evaluated_expression)
        evaluation_results.append(_compact_evaluation(evaluation_result))
        if not evaluation_result.get("success"):
            return {
                "success": False,
                "case_index": case_index,
                "label": case_label,
                "parameters": parameters,
                "stage": "evaluate",
                "parameter_results": parameter_results,
                "solve": solve_result,
                "result": evaluation_result,
                "evaluations": evaluation_results,
            }

    return {
        "success": True,
        "case_index": case_index,
        "label": case_label,
        "parameters": parameters,
        "parameter_results": parameter_results,
        "solve": solve_result,
        "evaluations": evaluation_results,
    }


def _compact_evaluation(result: dict) -> dict:
    keys = (
        "success",
        "model_name",
        "expression",
        "shape",
        "statistics",
        "value",
        "data_sample",
        "error",
    )
    return {key: result[key] for key in keys if key in result}


def _sweep_failure(stage: str, result: dict, model_name: str | None) -> dict:
    close_result = None
    if model_name:
        close_result = comsol_close_model(model_name, save=False)
    return {
        "success": False,
        "stage": stage,
        "model_name": model_name,
        "result": result,
        "close": close_result,
    }


def _close_after_sweep(
    model_name: str | None,
    *,
    close_model: bool | None,
    loaded_by_tool: bool,
) -> dict | None:
    if not model_name:
        return None
    should_close = loaded_by_tool if close_model is None else close_model
    if not should_close:
        return None
    return comsol_close_model(model_name, save=False)


def _close_after_template_run(
    model_name: str | None,
    *,
    close_model: bool | None,
    created_by_tool: bool,
) -> dict | None:
    if not model_name:
        return None
    should_close = created_by_tool if close_model is None else close_model
    if not should_close:
        return None
    return comsol_close_model(model_name, save=False)


def _package_plot_info(plot_path: str | None) -> dict:
    if not plot_path:
        return {"path": None, "exists": False}
    path = Path(plot_path).expanduser().resolve()
    info = {"path": str(path), "exists": path.exists()}
    if path.exists():
        info["size_bytes"] = path.stat().st_size
    return info


def _bearing_contact_metrics(evaluations: list[dict]) -> dict:
    metrics = {}
    for evaluation in evaluations:
        expression = evaluation.get("expression")
        stats = evaluation.get("statistics") or {}
        if expression == "solid.mises":
            metrics["von_mises_min"] = stats.get("min")
            metrics["von_mises_max"] = stats.get("max")
            metrics["von_mises_mean"] = stats.get("mean")
        elif expression == "contact_pressure_guess":
            metrics["contact_pressure_guess"] = stats.get("mean", evaluation.get("value"))
    return metrics


def _bearing_contact_package_markdown(summary: dict) -> str:
    metrics = summary.get("metrics") or {}
    model_save = summary.get("model_save") or {}
    plot = summary.get("plot") or {}
    lines = [
        "# Bearing Contact Result Package",
        "",
        f"- Package run id: `{summary.get('run_id')}`",
        f"- Model: `{summary.get('model_name')}`",
        f"- Template execution run id: `{summary.get('template_run_id') or ''}`",
        f"- Saved model: `{model_save.get('saved_to') or ''}`",
        f"- Stress plot: `{plot.get('path') or ''}`",
        "",
        "## Metrics",
        "",
        f"- von Mises min: `{metrics.get('von_mises_min')}`",
        f"- von Mises max: `{metrics.get('von_mises_max')}`",
        f"- von Mises mean: `{metrics.get('von_mises_mean')}`",
        f"- Contact pressure estimate: `{metrics.get('contact_pressure_guess')}`",
        "",
        "## Assumptions",
        "",
    ]
    lines.extend(f"- {item}" for item in summary.get("assumptions") or [])
    lines.extend([
        "",
        "## Reuse Notes",
        "",
        "- Open the saved `.mph` model to inspect geometry, physics, mesh, study, and result plot groups.",
        "- Use the template execution JSON for exact setup parameters and Java/API seed code.",
        "- Treat this package as a workflow smoke record until mesh/contact convergence and boundary selections are reviewed for the target bearing.",
        "",
    ])
    return "\n".join(lines)


def _utc_now_for_package() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bearing_contact_package_run_id(package_name: str | None, model_name: str | None) -> str:
    raw = "_".join(part for part in (package_name or "bearing_contact_package", model_name or "model") if part)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw.strip()).strip("._-") or "bearing_contact_package"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return f"{slug}_{timestamp}"


def _sweep_source(
    *,
    model_name: str | None,
    example_name: str | None,
    model_file: str | None,
) -> dict:
    if model_name:
        return {"type": "loaded_model", "model_name": model_name}
    if example_name:
        return {"type": "example", "example_name": example_name}
    return {"type": "model_file", "model_file": model_file}


def _template_run_name(template_name: str | None, model_name: str | None) -> str:
    raw = "_".join(part for part in (template_name or "template", model_name or "model") if part)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw.strip()).strip("._-")
    return slug or "template_execution"


def _template_execution_snapshot(
    *,
    name: str | None,
    domain: str | None,
    java_code: str,
    params: dict,
) -> dict:
    return {
        "name": name,
        "domain": domain,
        "params": params,
        "java_code": java_code,
    }


def _archive_store(archive_path: str | None) -> ArchiveStore:
    db_path = Path(archive_path).expanduser() if archive_path else (
        get_config_dir() / "archive" / "archive.sqlite3"
    )
    return ArchiveStore(db_path)


def _artifact_to_dict(artifact) -> dict:
    return asdict(artifact)


def _preview(text: str, max_chars: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)] + "..."


def _template_export_path(name: str, output_path: str | None) -> Path:
    if output_path:
        return Path(output_path).expanduser().resolve()
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("._-") or "template"
    return (Path("runtime_smoke/templates") / f"{slug}.java").resolve()


def _validate_export_path(path: Path) -> str | None:
    roots = [Path.cwd().resolve(), (Path.home() / ".comsol_agent").resolve()]
    extra = os.environ.get("COMSOL_AGENT_ALLOWED_PATHS", "")
    for raw_path in extra.split(os.pathsep):
        if raw_path.strip():
            roots.append(Path(raw_path).expanduser().resolve())
    if not any(_is_relative_to(path, root) or path == root for root in roots):
        return (
            f"Output path is outside allowed roots: {path}. "
            f"Allowed roots: {', '.join(str(root) for root in roots)}"
        )
    return None


def _validate_template_code(
    *,
    name: str | None,
    java_code: str,
    params: dict | None,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    params = params or {}

    if name is not None and not str(name).strip():
        errors.append("Template name is empty.")
    if not java_code.strip():
        errors.append("Template java_code is empty.")

    code_without_line_comments = _strip_java_line_comments(java_code)
    code_for_balance, string_error = _mask_java_strings(code_without_line_comments)
    if string_error:
        errors.append(string_error)

    for blocked in (
        "System.exit",
        "Runtime.getRuntime",
        "ProcessBuilder",
        "java.io.File",
        "Files.delete",
        ".delete(",
    ):
        if blocked in code_without_line_comments:
            errors.append(f"Disallowed Java operation in template: {blocked}")

    for symbol, label in (("(", "parentheses"), ("[", "brackets"), ("{", "braces")):
        close_symbol = {"(": ")", "[": "]", "{": "}"}[symbol]
        delta = code_for_balance.count(symbol) - code_for_balance.count(close_symbol)
        if delta != 0:
            errors.append(f"Unbalanced {label}: {symbol}/{close_symbol} count differs by {abs(delta)}.")

    effective_lines = [
        line.strip()
        for line in code_without_line_comments.splitlines()
        if line.strip()
    ]
    if java_code.strip() and not effective_lines:
        warnings.append("Template contains only comments; add executable COMSOL Java/API calls before running it.")
    if effective_lines and "model." not in code_without_line_comments:
        warnings.append("Template does not reference `model.`; COMSOL execution may have no target model.")

    for line_no, line in enumerate(code_without_line_comments.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.endswith((";", "{", "}", ",")):
            continue
        warnings.append(f"Line {line_no} may be missing a semicolon.")

    for param_name in sorted(str(key) for key in params.keys()):
        quoted_single = f"'{param_name}'"
        quoted_double = f'"{param_name}"'
        if quoted_single not in java_code and quoted_double not in java_code:
            warnings.append(f"Param `{param_name}` is declared but not referenced in the Java/API code.")

    param_sets = len(re.findall(r"\bmodel\.param\(\)\.set\s*\(", code_without_line_comments))
    if param_sets:
        notes.append(f"Detected {param_sets} model.param().set(...) call(s).")
    notes.append("Offline validation only; run a COMSOL smoke check before trusting physics setup.")

    status = "fail" if errors else "warn" if warnings else "ok"
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "notes": notes,
        "line_count": len(java_code.splitlines()),
        "params_checked": sorted(str(key) for key in params.keys()),
    }


def _strip_java_line_comments(java_code: str) -> str:
    cleaned_lines = []
    for line in java_code.splitlines():
        in_single = False
        in_double = False
        escaped = False
        comment_at = None
        for index, char in enumerate(line):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == "'" and not in_double:
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double
            elif char == "/" and index + 1 < len(line) and line[index + 1] == "/" and not in_single and not in_double:
                comment_at = index
                break
        cleaned_lines.append(line[:comment_at] if comment_at is not None else line)
    return "\n".join(cleaned_lines)


def _mask_java_strings(java_code: str) -> tuple[str, str | None]:
    chars = list(java_code)
    in_quote: str | None = None
    escaped = False
    for index, char in enumerate(chars):
        if escaped:
            chars[index] = " "
            escaped = False
            continue
        if char == "\\" and in_quote:
            chars[index] = " "
            escaped = True
            continue
        if char in {"'", '"'}:
            if in_quote is None:
                in_quote = char
                chars[index] = " "
                continue
            if in_quote == char:
                in_quote = None
                chars[index] = " "
                continue
        if in_quote:
            chars[index] = " "
    if in_quote:
        return "".join(chars), "Unclosed string literal in Java/API template."
    return "".join(chars), None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
