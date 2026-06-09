"""Markdown report generation for archived COMSOL sweep comparisons."""

from __future__ import annotations

import re
import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from comsol_agent.cli.config import get_config_dir
from comsol_agent.memory.archive_store import ArchiveStore, SimulationArtifact


def write_comparison_report(
    comparison: dict[str, Any],
    *,
    output_dir: str | Path | None = None,
    report_name: str | None = None,
    title: str | None = None,
    output_format: str = "markdown",
    archive_results: bool = True,
    archive_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write a Markdown report for a sweep artifact comparison."""
    if output_format not in {"markdown", "html", "both"}:
        raise ValueError("output_format must be 'markdown', 'html', or 'both'.")

    target_dir = Path(output_dir or "runtime_smoke/reports").expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    report_id = _make_report_id(report_name)
    path = target_dir / f"{report_id}.md"
    html_path = target_dir / f"{report_id}.html"
    manifest_path = target_dir / f"{report_id}.manifest.json"
    markdown = render_comparison_report(comparison, title=title, report_id=report_id)
    path.write_text(markdown, encoding="utf-8")
    wrote_html = output_format in {"html", "both"}
    if wrote_html:
        html = render_comparison_report_html(comparison, title=title, report_id=report_id)
        html_path.write_text(html, encoding="utf-8")

    manifest = _report_manifest(
        comparison,
        report_id=report_id,
        report_path=path,
        manifest_path=manifest_path,
        html_path=html_path if wrote_html else None,
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    archive_record = None
    archive_error = None
    if archive_results:
        try:
            archive_record = _index_report_manifest(
                manifest,
                archive_path=archive_path,
                metadata={
                    "report_path": str(path),
                    "report_size_bytes": path.stat().st_size,
                    "html_path": str(html_path) if wrote_html else None,
                    "html_size_bytes": html_path.stat().st_size if wrote_html else None,
                    "output_format": output_format,
                },
            )
        except Exception as exc:
            archive_error = str(exc)

    report = {
        "report_id": report_id,
        "path": str(path),
        "manifest_path": str(manifest_path),
        "size_bytes": path.stat().st_size,
        "row_count": comparison.get("row_count", 0),
        "comparable_row_count": comparison.get("comparable_row_count", 0),
        "output_format": output_format,
    }
    if wrote_html:
        report["html_path"] = str(html_path)
        report["html_size_bytes"] = html_path.stat().st_size
    if archive_record is not None:
        report["archive"] = archive_record
    if archive_error is not None:
        report["archive_error"] = archive_error
    return report


def write_template_execution_report(
    archive_store: ArchiveStore,
    *,
    run_ids: list[str] | None = None,
    query: str | None = None,
    limit: int = 20,
    output_dir: str | Path | None = None,
    report_name: str | None = None,
    title: str | None = None,
    output_format: str = "markdown",
    archive_results: bool = True,
    archive_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write a report for archived template execution artifacts."""
    if output_format not in {"markdown", "html", "both"}:
        raise ValueError("output_format must be 'markdown', 'html', or 'both'.")

    artifacts = _select_template_execution_artifacts(
        archive_store,
        run_ids=run_ids,
        query=query,
        limit=limit,
    )
    if not artifacts:
        raise ValueError("No template_execution artifacts found for report export.")

    summary = _template_execution_summary(artifacts)
    target_dir = Path(output_dir or "runtime_smoke/reports").expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    report_id = _make_report_id(report_name, default_prefix="template_execution_report")
    path = target_dir / f"{report_id}.md"
    html_path = target_dir / f"{report_id}.html"
    manifest_path = target_dir / f"{report_id}.manifest.json"
    markdown = render_template_execution_report(summary, title=title, report_id=report_id)
    path.write_text(markdown, encoding="utf-8")
    wrote_html = output_format in {"html", "both"}
    if wrote_html:
        html = render_template_execution_report_html(summary, title=title, report_id=report_id)
        html_path.write_text(html, encoding="utf-8")

    manifest = _template_report_manifest(
        summary,
        report_id=report_id,
        report_path=path,
        manifest_path=manifest_path,
        html_path=html_path if wrote_html else None,
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    archive_record = None
    archive_error = None
    if archive_results:
        try:
            archive_record = _index_report_manifest(
                manifest,
                archive_path=archive_path,
                metadata={
                    "report_path": str(path),
                    "report_size_bytes": path.stat().st_size,
                    "html_path": str(html_path) if wrote_html else None,
                    "html_size_bytes": html_path.stat().st_size if wrote_html else None,
                    "output_format": output_format,
                    "source_kind": "template_execution",
                    "success_count": summary["success_count"],
                    "failure_count": summary["failure_count"],
                },
            )
        except Exception as exc:
            archive_error = str(exc)

    report = {
        "report_id": report_id,
        "path": str(path),
        "manifest_path": str(manifest_path),
        "size_bytes": path.stat().st_size,
        "output_format": output_format,
        "summary": {
            "run_count": summary["run_count"],
            "success_count": summary["success_count"],
            "failure_count": summary["failure_count"],
            "source_run_ids": summary["source_run_ids"],
        },
    }
    if wrote_html:
        report["html_path"] = str(html_path)
        report["html_size_bytes"] = html_path.stat().st_size
    if archive_record is not None:
        report["archive"] = archive_record
    if archive_error is not None:
        report["archive_error"] = archive_error
    return report


def render_comparison_report(
    comparison: dict[str, Any],
    *,
    title: str | None = None,
    report_id: str | None = None,
) -> str:
    """Render a sweep comparison as Markdown."""
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metric = comparison.get("metric", "")
    expression = comparison.get("expression") or "(all expressions)"
    direction = comparison.get("direction", "")
    best = comparison.get("best")
    worst = comparison.get("worst")

    lines = [
        f"# {title or 'COMSOL Sweep Comparison Report'}",
        "",
        f"- Report ID: `{report_id or 'ad-hoc'}`",
        f"- Created: `{created_at}`",
        f"- Metric: `{metric}`",
        f"- Expression: `{expression}`",
        f"- Direction: `{direction}`",
        f"- Rows: `{comparison.get('comparable_row_count', 0)}` comparable / `{comparison.get('row_count', 0)}` total",
        "",
    ]

    if best:
        lines.extend([
            "## Best Case",
            "",
            _case_summary(best),
            "",
        ])
    if worst and worst != best:
        lines.extend([
            "## Worst Case",
            "",
            _case_summary(worst),
            "",
        ])

    lines.extend([
        "## Ranked Cases",
        "",
        "| Rank | Run ID | Case | Expression | Metric | Parameters |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for index, row in enumerate(comparison.get("ranked", []), start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _md_code(row.get("run_id", "")),
                    _md_code(str(row.get("case_index", ""))),
                    _md_code(row.get("expression") or ""),
                    _md_code(str(row.get("metric_raw", ""))),
                    _md_code(_format_parameters(row.get("parameters") or {})),
                ]
            )
            + " |"
        )
    lines.append("")

    parameter_differences = comparison.get("parameter_differences") or {}
    if parameter_differences:
        lines.extend(["## Parameter Differences", ""])
        for name, values in parameter_differences.items():
            lines.append(f"- `{name}`: {', '.join(_md_code(str(value)) for value in values)}")
        lines.append("")

    artifacts = comparison.get("artifacts") or []
    if artifacts:
        lines.extend([
            "## Source Artifacts",
            "",
            "| Run ID | Model | JSON | CSV | Manifest |",
            "| --- | --- | --- | --- | --- |",
        ])
        for artifact in artifacts:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_code(artifact.get("run_id", "")),
                        _md_code(artifact.get("model_name") or ""),
                        _md_code(artifact.get("json_path") or ""),
                        _md_code(artifact.get("csv_path") or ""),
                        _md_code(artifact.get("manifest_path") or ""),
                    ]
                )
                + " |"
            )
        lines.append("")

    notes = comparison.get("notes") or []
    missing_files = comparison.get("missing_files") or []
    if notes or missing_files:
        lines.extend(["## Notes", ""])
        for note in notes:
            lines.append(f"- {note}")
        for item in missing_files:
            lines.append(f"- Missing CSV for `{item.get('run_id')}`: `{item.get('csv_path')}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_template_execution_report(
    summary: dict[str, Any],
    *,
    title: str | None = None,
    report_id: str | None = None,
) -> str:
    """Render template execution artifacts as Markdown."""
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        f"# {title or 'COMSOL Template Execution Report'}",
        "",
        f"- Report ID: `{report_id or 'ad-hoc'}`",
        f"- Created: `{created_at}`",
        f"- Runs: `{summary.get('run_count', 0)}`",
        f"- Successful: `{summary.get('success_count', 0)}`",
        f"- Failed: `{summary.get('failure_count', 0)}`",
        "",
        "## Runs",
        "",
        "| Run ID | Template | Model | Success | Validation | Error Type | Params |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in summary.get("runs", []):
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_code(run.get("run_id", "")),
                    _md_code(run.get("template_name") or ""),
                    _md_code(run.get("model_name") or ""),
                    _md_code(str(run.get("success"))),
                    _md_code(run.get("validation_status") or ""),
                    _md_code(run.get("execution_error_type") or run.get("execution_exception_type") or ""),
                    _md_code(_format_parameters(run.get("params") or {})),
                ]
            )
            + " |"
        )
    lines.append("")

    failures = [run for run in summary.get("runs", []) if not run.get("success")]
    if failures:
        lines.extend(["## Failures", ""])
        for run in failures:
            lines.append(f"### `{run.get('run_id')}`")
            lines.extend([
                "",
                f"- Template: `{run.get('template_name') or ''}`",
                f"- Model: `{run.get('model_name') or ''}`",
                f"- Stage/Error: `{run.get('stage') or run.get('error') or ''}`",
                f"- Execution Error: `{run.get('execution_error') or ''}`",
                "",
            ])

    lines.extend([
        "## Source Artifacts",
        "",
        "| Run ID | JSON | Manifest |",
        "| --- | --- | --- |",
    ])
    for run in summary.get("runs", []):
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_code(run.get("run_id", "")),
                    _md_code(run.get("json_path") or ""),
                    _md_code(run.get("manifest_path") or ""),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_comparison_report_html(
    comparison: dict[str, Any],
    *,
    title: str | None = None,
    report_id: str | None = None,
) -> str:
    """Render a sweep comparison as a self-contained HTML report."""
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    page_title = title or "COMSOL Sweep Comparison Report"
    metric = comparison.get("metric", "")
    expression = comparison.get("expression") or "(all expressions)"
    direction = comparison.get("direction", "")

    sections = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(page_title)}</title>",
        "<style>",
        _html_css(),
        "</style>",
        "</head>",
        "<body>",
        "<main>",
        f"<h1>{escape(page_title)}</h1>",
        '<section class="summary">',
        _html_metric("Report ID", report_id or "ad-hoc"),
        _html_metric("Created", created_at),
        _html_metric("Metric", metric),
        _html_metric("Expression", expression),
        _html_metric("Direction", direction),
        _html_metric(
            "Rows",
            f"{comparison.get('comparable_row_count', 0)} comparable / "
            f"{comparison.get('row_count', 0)} total",
        ),
        "</section>",
    ]

    best = comparison.get("best")
    worst = comparison.get("worst")
    if best:
        sections.extend(["<section>", "<h2>Best Case</h2>", _html_case_summary(best), "</section>"])
    if worst and worst != best:
        sections.extend(["<section>", "<h2>Worst Case</h2>", _html_case_summary(worst), "</section>"])

    sections.extend([
        "<section>",
        "<h2>Ranked Cases</h2>",
        '<div class="table-wrap">',
        "<table>",
        "<thead><tr><th>Rank</th><th>Run ID</th><th>Case</th><th>Expression</th><th>Metric</th><th>Parameters</th></tr></thead>",
        "<tbody>",
    ])
    for index, row in enumerate(comparison.get("ranked", []), start=1):
        sections.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td><code>{escape(str(row.get('run_id', '')))}</code></td>"
            f"<td><code>{escape(str(row.get('case_index', '')))}</code></td>"
            f"<td><code>{escape(str(row.get('expression') or ''))}</code></td>"
            f"<td><code>{escape(str(row.get('metric_raw', '')))}</code></td>"
            f"<td><code>{escape(_format_parameters(row.get('parameters') or {}))}</code></td>"
            "</tr>"
        )
    sections.extend(["</tbody>", "</table>", "</div>", "</section>"])

    parameter_differences = comparison.get("parameter_differences") or {}
    if parameter_differences:
        sections.extend(["<section>", "<h2>Parameter Differences</h2>", "<ul>"])
        for name, values in parameter_differences.items():
            value_text = ", ".join(f"<code>{escape(str(value))}</code>" for value in values)
            sections.append(f"<li><code>{escape(str(name))}</code>: {value_text}</li>")
        sections.extend(["</ul>", "</section>"])

    artifacts = comparison.get("artifacts") or []
    if artifacts:
        sections.extend([
            "<section>",
            "<h2>Source Artifacts</h2>",
            '<div class="table-wrap">',
            "<table>",
            "<thead><tr><th>Run ID</th><th>Model</th><th>JSON</th><th>CSV</th><th>Manifest</th></tr></thead>",
            "<tbody>",
        ])
        for artifact in artifacts:
            sections.append(
                "<tr>"
                f"<td><code>{escape(str(artifact.get('run_id', '')))}</code></td>"
                f"<td><code>{escape(str(artifact.get('model_name') or ''))}</code></td>"
                f"<td><code>{escape(str(artifact.get('json_path') or ''))}</code></td>"
                f"<td><code>{escape(str(artifact.get('csv_path') or ''))}</code></td>"
                f"<td><code>{escape(str(artifact.get('manifest_path') or ''))}</code></td>"
                "</tr>"
            )
        sections.extend(["</tbody>", "</table>", "</div>", "</section>"])

    notes = comparison.get("notes") or []
    missing_files = comparison.get("missing_files") or []
    if notes or missing_files:
        sections.extend(["<section>", "<h2>Notes</h2>", "<ul>"])
        for note in notes:
            sections.append(f"<li>{escape(str(note))}</li>")
        for item in missing_files:
            sections.append(
                f"<li>Missing CSV for <code>{escape(str(item.get('run_id')))}</code>: "
                f"<code>{escape(str(item.get('csv_path')))}</code></li>"
            )
        sections.extend(["</ul>", "</section>"])

    sections.extend(["</main>", "</body>", "</html>"])
    return "\n".join(sections) + "\n"


def render_template_execution_report_html(
    summary: dict[str, Any],
    *,
    title: str | None = None,
    report_id: str | None = None,
) -> str:
    """Render a template execution report as self-contained HTML."""
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    page_title = title or "COMSOL Template Execution Report"
    sections = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(page_title)}</title>",
        "<style>",
        _html_css(),
        "</style>",
        "</head>",
        "<body>",
        "<main>",
        f"<h1>{escape(page_title)}</h1>",
        '<section class="summary">',
        _html_metric("Report ID", report_id or "ad-hoc"),
        _html_metric("Created", created_at),
        _html_metric("Runs", summary.get("run_count", 0)),
        _html_metric("Successful", summary.get("success_count", 0)),
        _html_metric("Failed", summary.get("failure_count", 0)),
        "</section>",
        "<section>",
        "<h2>Runs</h2>",
        '<div class="table-wrap">',
        "<table>",
        "<thead><tr><th>Run ID</th><th>Template</th><th>Model</th><th>Success</th><th>Validation</th><th>Error Type</th><th>Params</th></tr></thead>",
        "<tbody>",
    ]
    for run in summary.get("runs", []):
        error_type = run.get("execution_error_type") or run.get("execution_exception_type") or ""
        sections.append(
            "<tr>"
            f"<td><code>{escape(str(run.get('run_id', '')))}</code></td>"
            f"<td><code>{escape(str(run.get('template_name') or ''))}</code></td>"
            f"<td><code>{escape(str(run.get('model_name') or ''))}</code></td>"
            f"<td><code>{escape(str(run.get('success')))}</code></td>"
            f"<td><code>{escape(str(run.get('validation_status') or ''))}</code></td>"
            f"<td><code>{escape(str(error_type))}</code></td>"
            f"<td><code>{escape(_format_parameters(run.get('params') or {}))}</code></td>"
            "</tr>"
        )
    sections.extend(["</tbody>", "</table>", "</div>", "</section>"])

    failures = [run for run in summary.get("runs", []) if not run.get("success")]
    if failures:
        sections.extend(["<section>", "<h2>Failures</h2>", "<ul>"])
        for run in failures:
            detail = run.get("execution_error") or run.get("stage") or run.get("error") or ""
            sections.append(
                f"<li><code>{escape(str(run.get('run_id')))}</code>: {escape(str(detail))}</li>"
            )
        sections.extend(["</ul>", "</section>"])

    sections.extend(["</main>", "</body>", "</html>"])
    return "\n".join(sections) + "\n"


def _case_summary(row: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"- Run ID: `{row.get('run_id', '')}`",
            f"- Model: `{row.get('model_name') or ''}`",
            f"- Case: `{row.get('case_index', '')}` (`{row.get('case_label', '')}`)",
            f"- Expression: `{row.get('expression') or ''}`",
            f"- {row.get('metric')}: `{row.get('metric_raw', '')}`",
            f"- Parameters: `{_format_parameters(row.get('parameters') or {})}`",
        ]
    )


def _format_parameters(parameters: dict[str, Any]) -> str:
    if not parameters:
        return ""
    return ", ".join(f"{name}={value}" for name, value in parameters.items())


def _md_code(value: str) -> str:
    escaped = value.replace("`", "\\`").replace("|", "\\|")
    return f"`{escaped}`"


def _make_report_id(report_name: str | None, *, default_prefix: str = "sweep_report") -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    if not report_name:
        return f"{default_prefix}_{timestamp}"
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", report_name.strip()).strip("._-")
    return f"{slug or default_prefix}_{timestamp}"


def _select_template_execution_artifacts(
    archive_store: ArchiveStore,
    *,
    run_ids: list[str] | None,
    query: str | None,
    limit: int,
) -> list[SimulationArtifact]:
    if run_ids:
        artifacts = [archive_store.get_simulation_artifact(run_id) for run_id in run_ids]
    elif query:
        artifacts = archive_store.search_simulation_artifacts(query, limit=limit)
    else:
        artifacts = archive_store.list_simulation_artifacts(kind="template_execution", limit=limit)
    return [artifact for artifact in artifacts if artifact.kind == "template_execution"][:limit]


def _template_execution_summary(artifacts: list[SimulationArtifact]) -> dict[str, Any]:
    runs = [_template_execution_run_summary(artifact) for artifact in artifacts]
    success_count = sum(1 for run in runs if run.get("success"))
    return {
        "run_count": len(runs),
        "success_count": success_count,
        "failure_count": len(runs) - success_count,
        "source_run_ids": [run["run_id"] for run in runs],
        "runs": runs,
    }


def _template_execution_run_summary(artifact: SimulationArtifact) -> dict[str, Any]:
    payload = _read_json_file(Path(artifact.json_path))
    validation = payload.get("validation") or {}
    execution = payload.get("execution") or {}
    template = payload.get("template") or {}
    return {
        "run_id": artifact.run_id,
        "model_name": payload.get("model_name") or artifact.model_name,
        "template_name": payload.get("template_name") or template.get("name") or artifact.source.get("name"),
        "template_domain": template.get("domain") or artifact.source.get("domain"),
        "success": payload.get("success"),
        "executed": payload.get("executed"),
        "stage": payload.get("stage"),
        "error": payload.get("error"),
        "params": payload.get("params") or template.get("params") or {},
        "validation_status": validation.get("status"),
        "validation_errors": len(validation.get("errors") or []),
        "validation_warnings": len(validation.get("warnings") or []),
        "execution_error": execution.get("error"),
        "execution_error_type": execution.get("error_type"),
        "execution_exception_type": execution.get("exception_type"),
        "source": payload.get("source") or artifact.source,
        "json_path": artifact.json_path,
        "manifest_path": artifact.manifest_path,
        "created_at": artifact.created_at,
    }


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _report_manifest(
    comparison: dict[str, Any],
    *,
    report_id: str,
    report_path: Path,
    manifest_path: Path,
    html_path: Path | None = None,
) -> dict[str, Any]:
    artifacts = comparison.get("artifacts") or []
    model_names = sorted({artifact.get("model_name") for artifact in artifacts if artifact.get("model_name")})
    source_run_ids = [artifact.get("run_id") for artifact in artifacts if artifact.get("run_id")]
    return {
        "run_id": report_id,
        "kind": "comparison_report",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_name": model_names[0] if len(model_names) == 1 else None,
        "source": {
            "type": "comparison_report",
            "source_run_ids": source_run_ids,
            "metric": comparison.get("metric"),
            "expression": comparison.get("expression"),
            "direction": comparison.get("direction"),
            "html_path": str(html_path) if html_path is not None else None,
        },
        "executed_cases": comparison.get("comparable_row_count", 0),
        "truncated": False,
        "json_path": str(report_path),
        "csv_path": None,
        "manifest_path": str(manifest_path),
    }


def _template_report_manifest(
    summary: dict[str, Any],
    *,
    report_id: str,
    report_path: Path,
    manifest_path: Path,
    html_path: Path | None = None,
) -> dict[str, Any]:
    model_names = sorted({run.get("model_name") for run in summary["runs"] if run.get("model_name")})
    return {
        "run_id": report_id,
        "kind": "template_execution_report",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_name": model_names[0] if len(model_names) == 1 else None,
        "source": {
            "type": "template_execution_report",
            "source_run_ids": summary["source_run_ids"],
            "success_count": summary["success_count"],
            "failure_count": summary["failure_count"],
            "html_path": str(html_path) if html_path is not None else None,
        },
        "executed_cases": summary["run_count"],
        "truncated": False,
        "json_path": str(report_path),
        "csv_path": None,
        "manifest_path": str(manifest_path),
    }


def _html_metric(label: str, value: Any) -> str:
    return (
        '<div class="metric">'
        f"<span>{escape(label)}</span>"
        f"<strong>{escape(str(value))}</strong>"
        "</div>"
    )


def _html_case_summary(row: dict[str, Any]) -> str:
    items = [
        ("Run ID", row.get("run_id", "")),
        ("Model", row.get("model_name") or ""),
        ("Case", f"{row.get('case_index', '')} ({row.get('case_label', '')})"),
        ("Expression", row.get("expression") or ""),
        (str(row.get("metric")), row.get("metric_raw", "")),
        ("Parameters", _format_parameters(row.get("parameters") or {})),
    ]
    lines = ['<dl class="case-summary">']
    for label, value in items:
        lines.append(f"<dt>{escape(str(label))}</dt><dd><code>{escape(str(value))}</code></dd>")
    lines.append("</dl>")
    return "\n".join(lines)


def _html_css() -> str:
    return """
:root {
  color-scheme: light;
  --bg: #f7f8fb;
  --text: #18202a;
  --muted: #5b6775;
  --line: #d9dee7;
  --panel: #ffffff;
  --accent: #0f766e;
  --code: #eef2f7;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5;
}
main {
  width: min(1120px, calc(100% - 32px));
  margin: 32px auto 56px;
}
h1 { margin: 0 0 20px; font-size: 32px; line-height: 1.15; }
h2 { margin: 0 0 14px; font-size: 20px; }
section {
  margin: 18px 0;
  padding: 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}
.metric {
  border-left: 3px solid var(--accent);
  padding-left: 10px;
}
.metric span {
  display: block;
  color: var(--muted);
  font-size: 12px;
  text-transform: uppercase;
}
.metric strong {
  display: block;
  margin-top: 4px;
  overflow-wrap: anywhere;
}
.table-wrap { overflow-x: auto; }
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
th, td {
  padding: 9px 10px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}
th { color: var(--muted); font-weight: 600; }
code {
  padding: 2px 5px;
  border-radius: 5px;
  background: var(--code);
  overflow-wrap: anywhere;
}
.case-summary {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 8px 14px;
  margin: 0;
}
.case-summary dt { color: var(--muted); }
.case-summary dd { margin: 0; }
ul { margin: 0; padding-left: 20px; }
""".strip()


def _index_report_manifest(
    manifest: dict[str, Any],
    *,
    archive_path: str | Path | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    db_path = Path(archive_path).expanduser() if archive_path else (
        get_config_dir() / "archive" / "archive.sqlite3"
    )
    store = ArchiveStore(db_path)
    artifact = store.index_simulation_artifact(manifest, metadata=metadata)
    return {
        "db_path": str(db_path.resolve()),
        "id": artifact.id,
        "run_id": artifact.run_id,
        "kind": artifact.kind,
    }
