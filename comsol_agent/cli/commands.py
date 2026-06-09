"""Slash command handlers for the COMSOL Agent CLI."""

from __future__ import annotations

from enum import Enum

from comsol_agent.agent.loop import AgentLoop
from comsol_agent.cli.config import Config, save_config


class CommandResult(Enum):
    """Result of processing a slash command."""

    CONTINUE = "continue"  # Normal: continue the REPL loop
    EXIT = "exit"  # User wants to exit
    CLEAR = "clear"  # Clear conversation and continue


async def handle_command(
    command: str,
    agent: AgentLoop,
    config: Config,
) -> CommandResult:
    """Process a slash command.

    Args:
        command: The full command string (including leading /).
        agent: The active AgentLoop instance.
        config: The current configuration.

    Returns:
        CommandResult indicating what the REPL should do next.
    """
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd in ("/exit", "/quit"):
        return CommandResult.EXIT

    elif cmd == "/help":
        from comsol_agent.cli.renderer import render_help

        render_help()

    elif cmd == "/clear":
        agent.reset()
        from comsol_agent.cli.renderer import render_info

        render_info("Conversation history cleared. Starting fresh session.")
        return CommandResult.CLEAR

    elif cmd == "/compact":
        from comsol_agent.cli.renderer import render_info

        result = agent.compact_context(manual=True)
        if result["changed"]:
            render_info(
                "Context compacted: "
                f"{result['original_tokens']} → {result['compacted_tokens']} tokens, "
                f"compressed {result['compressed_message_count']} messages."
            )
        else:
            render_info("No compaction needed; recent context is already compact.")

    elif cmd == "/models":
        from comsol_agent.tools.comsol.client import COMSOLClient
        from comsol_agent.cli.renderer import render_info

        client = COMSOLClient.get_instance()
        if client.is_running:
            models = client.models
            if models:
                from rich.table import Table
                from rich.console import Console

                table = Table(title="Loaded Models", border_style="dim")
                table.add_column("Name", style="cyan")
                table.add_column("File", style="dim")
                table.add_column("Modified")

                for name, handle in models.items():
                    table.add_row(
                        name,
                        handle.path or "(new model)",
                        "✓" if handle.is_modified else "",
                    )
                Console().print(table)
            else:
                render_info("No models currently loaded.")
        else:
            render_info("COMSOL session not started. Models are loaded on demand.")

    elif cmd == "/config":
        from rich.table import Table
        from rich.console import Console
        from comsol_agent.llm.router import plan_route

        route_plan = plan_route(
            "text_response",
            preferred_provider=config.llm.provider,
            preferred_model=config.llm.model,
        )

        table = Table(title="Current Configuration", border_style="dim")
        table.add_column("Section", style="cyan")
        table.add_column("Setting")
        table.add_column("Value")

        table.add_row("LLM", "Provider", config.llm.provider)
        table.add_row("LLM", "Model", config.llm.model)
        table.add_row("LLM", "Route Tier", route_plan.model_tier)
        table.add_row("LLM", "Fallback Chain", " → ".join(route_plan.provider_chain))
        table.add_row("LLM", "Max Tokens", str(config.llm.max_tokens))
        table.add_row("COMSOL", "Executable", config.comsol.executable_path or "auto-detect")
        table.add_row("COMSOL", "Version", config.comsol.version or "auto-detect")
        table.add_row("Agent", "LLM Retries", str(config.agent.llm_max_retries))
        table.add_row("Agent", "Auto Repair", str(config.agent.auto_repair))
        table.add_row("Agent", "Max Repair", str(config.agent.max_repair_attempts))
        table.add_row("Memory", "Context Window", f"{config.memory.context_window_tokens} tokens")
        table.add_row("Memory", "Core Memory", f"{config.memory.core_memory_max_tokens} tokens")
        table.add_row("Memory", "Buffer Size", f"{config.memory.buffer_max_rounds} rounds")
        table.add_row("Memory", "Compaction", f"{config.memory.compaction_threshold*100:.0f}%")

        Console().print(table)

        if args == "edit":
            from comsol_agent.cli.renderer import render_info
            render_info(
                "Use the config file at ~/.comsol_agent/config.yaml to make "
                "persistent changes. Environment variables can override settings."
            )

    elif cmd == "/doctor":
        from rich.console import Console
        from rich.table import Table
        from comsol_agent.diagnostics import run_deep_doctor, run_doctor

        doctor_parts = args.split()
        deep = "--deep" in doctor_parts
        llm_only = "--llm-only" in doctor_parts
        comsol_only = "--comsol-only" in doctor_parts
        create_smoke = "--create-smoke" in doctor_parts
        cores = _option_int(doctor_parts, "--cores", default=1)
        timeout = float(_option_value(doctor_parts, "--timeout", default="30"))
        if deep or llm_only or comsol_only:
            result = await run_deep_doctor(
                config,
                check_llm=deep or llm_only,
                check_comsol=deep or comsol_only,
                comsol_cores=cores,
                create_smoke=create_smoke,
                timeout_seconds=timeout,
            )
        else:
            result = run_doctor(config)
        table = Table(title=f"COMSOL Agent Doctor: {result['status'].upper()}", border_style="dim")
        table.add_column("Check", style="cyan")
        table.add_column("Status")
        table.add_column("Message")
        for check in result["checks"]:
            status = check["status"]
            style = {"ok": "green", "warn": "yellow", "fail": "red"}.get(status, "")
            table.add_row(check["name"], f"[{style}]{status}[/{style}]", check["message"])
        Console().print(table)

    elif cmd == "/memory":
        from rich.console import Console
        from rich.table import Table
        from comsol_agent.cli.renderer import render_info

        archive_store = getattr(agent, "archive_store", None)
        if archive_store is None:
            render_info("Archive memory is not configured for this session.")
        else:
            memories = (
                archive_store.search_memories(args, limit=10)
                if args
                else archive_store.list_memories(limit=10)
            )
            if not memories:
                render_info("No archived memories found.")
            else:
                table = Table(title="Archived Memories", border_style="dim")
                table.add_column("ID", style="cyan")
                table.add_column("Type")
                table.add_column("Session", style="dim")
                table.add_column("Content")
                for memory in memories:
                    content = memory.content
                    if len(content) > 90:
                        content = content[:87] + "..."
                    table.add_row(str(memory.id), memory.type, memory.session_id, content)
                Console().print(table)

    elif cmd == "/sessions":
        from rich.console import Console
        from rich.table import Table
        from comsol_agent.cli.renderer import render_info
        from comsol_agent.memory.session_timeline import build_session_timeline, summarize_timeline

        archive_store = getattr(agent, "archive_store", None)
        if archive_store is None:
            render_info("Session archive is not configured for this session.")
        else:
            session_parts = args.split()
            subcommand = session_parts[0].lower() if session_parts else "list"

            if subcommand == "search":
                query = " ".join(session_parts[1:]).strip()
                if not query:
                    render_info("Usage: /sessions search <query>")
                else:
                    sessions = archive_store.search_sessions(query, limit=10)
                    _render_sessions_table(sessions, title=f"Sessions matching '{query}'")
            elif subcommand == "show":
                if len(session_parts) < 2:
                    render_info("Usage: /sessions show <session_id> [max_events]")
                else:
                    session_id = session_parts[1]
                    max_events = int(session_parts[2]) if len(session_parts) > 2 and session_parts[2].isdigit() else 30
                    try:
                        overview = archive_store.get_session_overview(session_id)
                    except Exception as exc:
                        render_info(f"Could not load session: {exc}")
                    else:
                        session = overview["session"]
                        snapshot = _load_session_snapshot(agent, session.id)

                        table = Table(title="Session", border_style="dim")
                        table.add_column("Field", style="cyan")
                        table.add_column("Value")
                        table.add_row("id", session.id)
                        table.add_row("name", session.name or "")
                        table.add_row("created_at", session.created_at)
                        table.add_row("updated_at", session.updated_at)
                        table.add_row("summary", session.summary or "")
                        table.add_row("memory_count", str(overview["memory_count"]))
                        table.add_row("last_memory_at", str(overview["last_memory_at"] or ""))
                        memory_types = ", ".join(
                            f"{name}={count}" for name, count in overview["memory_types"].items()
                        )
                        table.add_row("memory_types", memory_types)
                        if snapshot:
                            stats = snapshot.get("stats") or {}
                            table.add_row("snapshot_turns", str(stats.get("turn_count", "")))
                            table.add_row("snapshot_messages", str(stats.get("message_count", "")))
                            table.add_row("snapshot_tokens", str(stats.get("total_tokens_used", "")))
                            timeline = build_session_timeline(snapshot, max_events=max_events)
                            timeline_summary = summarize_timeline(timeline)
                            table.add_row("timeline_events", str(timeline_summary["event_count"]))
                        Console().print(table)

                        memories = archive_store.list_memories(session_id=session.id, limit=10)
                        if memories:
                            memory_table = Table(title="Recent Session Memories", border_style="dim")
                            memory_table.add_column("ID", style="cyan")
                            memory_table.add_column("Type")
                            memory_table.add_column("Created")
                            memory_table.add_column("Content")
                            for memory in memories:
                                content = memory.content
                                if len(content) > 90:
                                    content = content[:87] + "..."
                                memory_table.add_row(
                                    str(memory.id),
                                    memory.type,
                                    memory.created_at,
                                    content,
                                )
                            Console().print(memory_table)
                        if snapshot:
                            timeline = build_session_timeline(snapshot, max_events=max_events)
                            _render_session_timeline(timeline)
                        else:
                            render_info("No memories or JSON snapshot found for this session.")
            else:
                query = " ".join(session_parts[1:]).strip() if subcommand == "list" else args
                sessions = (
                    archive_store.search_sessions(query, limit=10)
                    if query
                    else archive_store.list_sessions(limit=10)
                )
                _render_sessions_table(sessions)

    elif cmd == "/archive":
        from rich.console import Console
        from rich.table import Table
        from comsol_agent.cli.renderer import render_info
        from comsol_agent.memory.archive_cleanup import cleanup_missing_artifact_indexes
        from comsol_agent.memory.archive_export import export_archive_bundle

        archive_store = getattr(agent, "archive_store", None)
        if archive_store is None:
            render_info("Archive is not configured for this session.")
        else:
            archive_parts = args.split()
            subcommand = archive_parts[0].lower() if archive_parts else "summary"
            if subcommand == "export":
                output_path = archive_parts[1] if len(archive_parts) > 1 else None
                limit = int(archive_parts[2]) if len(archive_parts) > 2 and archive_parts[2].isdigit() else 100
                include_timelines = len(archive_parts) > 3 and archive_parts[3].lower() in {
                    "timeline",
                    "timelines",
                    "true",
                    "yes",
                }
                session_store = getattr(agent, "session_store", None)
                session_dir = getattr(session_store, "session_dir", None)
                try:
                    result = export_archive_bundle(
                        archive_store,
                        output_path=output_path,
                        session_dir=session_dir,
                        limit=limit,
                        include_timelines=include_timelines,
                    )
                except Exception as exc:
                    render_info(f"Could not export archive: {exc}")
                else:
                    render_info(f"Archive export written: {result['path']}")
                    table = Table(title="Archive Export", border_style="dim")
                    table.add_column("Record", style="cyan")
                    table.add_column("Count")
                    for name, count in result["counts"].items():
                        table.add_row(name, str(count))
                    Console().print(table)
            elif subcommand == "cleanup":
                limit = int(archive_parts[1]) if len(archive_parts) > 1 and archive_parts[1].isdigit() else 100
                apply_cleanup = len(archive_parts) > 2 and archive_parts[2].lower() == "apply"
                result = cleanup_missing_artifact_indexes(
                    archive_store,
                    limit=limit,
                    apply=apply_cleanup,
                )
                table = Table(
                    title="Archive Cleanup" + (" (applied)" if apply_cleanup else " (dry-run)"),
                    border_style="dim",
                )
                table.add_column("Field", style="cyan")
                table.add_column("Value")
                table.add_row("scanned", str(result["scanned"]))
                table.add_row("stale_count", str(result["stale_count"]))
                table.add_row("deleted_count", str(result["deleted_count"]))
                table.add_row("archive_path", result["archive_path"])
                Console().print(table)
                if result["stale"]:
                    stale_table = Table(title="Stale Artifact Indexes", border_style="dim")
                    stale_table.add_column("Run ID", style="cyan")
                    stale_table.add_column("Kind")
                    stale_table.add_column("Missing")
                    for item in result["stale"][:10]:
                        missing = ", ".join(
                            f"{path['field']}={path['path']}" for path in item["missing_paths"]
                        )
                        stale_table.add_row(item["run_id"], item["kind"], _truncate_text(missing, 100))
                    Console().print(stale_table)
                if not apply_cleanup and result["stale_count"]:
                    render_info("Dry-run only. Use /archive cleanup <limit> apply to delete stale index rows.")
            else:
                sessions = archive_store.list_sessions(limit=1)
                memories = archive_store.list_memories(limit=1)
                templates = archive_store.list_templates(limit=1)
                artifacts = archive_store.list_simulation_artifacts(kind=None, limit=1)
                table = Table(title="Archive Summary", border_style="dim")
                table.add_column("Record", style="cyan")
                table.add_column("Has records")
                table.add_row("sessions", str(bool(sessions)))
                table.add_row("memories", str(bool(memories)))
                table.add_row("templates", str(bool(templates)))
                table.add_row("simulation_artifacts", str(bool(artifacts)))
                Console().print(table)
                render_info("Use /archive export [path] [limit] [timelines] to write a JSON export.")
                render_info("Use /archive cleanup [limit] [apply] to remove stale artifact index rows.")

    elif cmd == "/artifacts":
        from rich.console import Console
        from rich.table import Table
        from comsol_agent.cli.renderer import render_info
        from comsol_agent.simulation.comparison import compare_archived_sweeps
        from comsol_agent.simulation.artifact_reader import read_archived_artifact
        from comsol_agent.simulation.reporting import (
            write_comparison_report,
            write_template_execution_report,
        )

        archive_store = getattr(agent, "archive_store", None)
        if archive_store is None:
            render_info("Simulation artifact archive is not configured for this session.")
        else:
            artifact_parts = args.split()
            subcommand = artifact_parts[0].lower() if artifact_parts else "list"

            if subcommand == "search":
                query = " ".join(artifact_parts[1:]).strip()
                if not query:
                    render_info("Usage: /artifacts search <query>")
                else:
                    artifacts = archive_store.search_simulation_artifacts(query, limit=10)
                    _render_artifacts_table(artifacts, title=f"Simulation Artifacts matching '{query}'")
            elif subcommand == "show":
                if len(artifact_parts) < 2:
                    render_info("Usage: /artifacts show <run_id>")
                else:
                    run_id = artifact_parts[1]
                    max_lines = int(artifact_parts[2]) if len(artifact_parts) > 2 and artifact_parts[2].isdigit() else 20
                    try:
                        artifact_preview = read_archived_artifact(
                            archive_store,
                            run_id=run_id,
                            max_lines=max_lines,
                        )
                    except Exception as exc:
                        render_info(f"Could not read artifact: {exc}")
                    else:
                        _render_artifact_preview(artifact_preview)
            elif subcommand == "template-runs":
                query = " ".join(artifact_parts[1:]).strip()
                artifacts = (
                    [
                        artifact
                        for artifact in archive_store.search_simulation_artifacts(query, limit=10)
                        if artifact.kind == "template_execution"
                    ]
                    if query
                    else archive_store.list_simulation_artifacts(kind="template_execution", limit=10)
                )
                _render_template_execution_artifacts(artifacts)
            elif subcommand == "compare":
                if len(artifact_parts) < 2:
                    render_info("Usage: /artifacts compare <query> [metric] [expression] [max|min]")
                else:
                    query = artifact_parts[1]
                    metric = artifact_parts[2] if len(artifact_parts) > 2 else "mean"
                    expression = artifact_parts[3] if len(artifact_parts) > 3 else None
                    direction = artifact_parts[4] if len(artifact_parts) > 4 else "max"
                    if direction not in {"max", "min"}:
                        render_info("Direction must be 'max' or 'min'.")
                    else:
                        try:
                            comparison = compare_archived_sweeps(
                                archive_store,
                                query=query,
                                metric=metric,
                                expression=expression,
                                direction=direction,
                                limit=10,
                            )
                        except Exception as exc:
                            render_info(f"No comparable artifacts found: {exc}")
                        else:
                            table = Table(title="Sweep Artifact Comparison", border_style="dim")
                            table.add_column("Rank", style="cyan")
                            table.add_column("Run ID")
                            table.add_column("Case")
                            table.add_column("Expression")
                            table.add_column(metric)
                            table.add_column("Parameters")
                            for index, row in enumerate(comparison["ranked"][:10], start=1):
                                table.add_row(
                                    str(index),
                                    row.get("run_id", ""),
                                    str(row.get("case_index", "")),
                                    row.get("expression") or "",
                                    str(row.get("metric_raw", "")),
                                    _format_parameters(row.get("parameters") or {}),
                                )
                            Console().print(table)
                            if comparison.get("notes"):
                                render_info(" ".join(comparison["notes"]))
            elif subcommand == "report":
                if len(artifact_parts) < 2:
                    render_info("Usage: /artifacts report <query> [metric] [expression] [max|min] [markdown|html|both]")
                else:
                    query = artifact_parts[1]
                    metric = artifact_parts[2] if len(artifact_parts) > 2 else "mean"
                    expression = artifact_parts[3] if len(artifact_parts) > 3 else None
                    direction = artifact_parts[4] if len(artifact_parts) > 4 else "max"
                    output_format = artifact_parts[5] if len(artifact_parts) > 5 else "markdown"
                    if direction not in {"max", "min"}:
                        render_info("Direction must be 'max' or 'min'.")
                    elif output_format not in {"markdown", "html", "both"}:
                        render_info("Output format must be 'markdown', 'html', or 'both'.")
                    else:
                        try:
                            comparison = compare_archived_sweeps(
                                archive_store,
                                query=query,
                                metric=metric,
                                expression=expression,
                                direction=direction,
                                limit=20,
                            )
                            report = write_comparison_report(
                                comparison,
                                report_name=f"{query}_{metric}_{expression or 'all'}",
                                output_format=output_format,
                                archive_path=archive_store.db_path,
                            )
                        except Exception as exc:
                            render_info(f"Could not generate report: {exc}")
                        else:
                            render_info(f"Report written: {report['path']}")
                            if report.get("html_path"):
                                render_info(f"HTML written: {report['html_path']}")
            elif subcommand == "report-template":
                if len(artifact_parts) < 2:
                    render_info("Usage: /artifacts report-template <query> [markdown|html|both]")
                else:
                    query = artifact_parts[1]
                    output_format = artifact_parts[2] if len(artifact_parts) > 2 else "markdown"
                    if output_format not in {"markdown", "html", "both"}:
                        render_info("Output format must be 'markdown', 'html', or 'both'.")
                    else:
                        try:
                            report = write_template_execution_report(
                                archive_store,
                                query=query,
                                report_name=f"{query}_template_runs",
                                output_format=output_format,
                                archive_path=archive_store.db_path,
                            )
                        except Exception as exc:
                            render_info(f"Could not generate template execution report: {exc}")
                        else:
                            render_info(f"Template execution report written: {report['path']}")
                            if report.get("html_path"):
                                render_info(f"HTML written: {report['html_path']}")
            else:
                query = " ".join(artifact_parts[1:]).strip() if subcommand == "list" else args
                artifacts = (
                    archive_store.search_simulation_artifacts(query, limit=10)
                    if query
                    else archive_store.list_simulation_artifacts(kind="parameter_sweep", limit=10)
                )
                _render_artifacts_table(artifacts)

    elif cmd == "/repairs":
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from comsol_agent.cli.renderer import render_info

        reports = list(getattr(getattr(agent, "state", None), "repair_reports", []) or [])
        if not reports:
            render_info("No repair reports recorded in this session.")
        else:
            repair_parts = args.split()
            if repair_parts and repair_parts[0].lower() == "show":
                if len(repair_parts) < 2 or not repair_parts[1].isdigit():
                    render_info("Usage: /repairs show <index>")
                else:
                    index = int(repair_parts[1]) - 1
                    if index < 0 or index >= len(reports):
                        render_info(f"Repair report index out of range: {index + 1}")
                    else:
                        report = reports[index]
                        plan = report.get("repair_plan") or {}
                        diagnosis = report.get("diagnosis") or {}
                        content = (
                            f"[bold]Tool[/bold]: {report.get('tool_name') or 'unknown'}\n"
                            f"[bold]Error type[/bold]: {report.get('error_type')}\n"
                            f"[bold]Message[/bold]: {report.get('message')}\n\n"
                            f"[bold]Root cause[/bold]: {diagnosis.get('root_cause', '')}\n"
                            f"[bold]Fix strategy[/bold]: {diagnosis.get('fix_strategy', '')}\n\n"
                            f"[bold]Action[/bold]: {plan.get('action', '')}\n"
                            f"[bold]Risk[/bold]: {plan.get('risk_level', '')}\n"
                            f"[bold]Auto retry[/bold]: {plan.get('can_auto_retry', '')}\n"
                            f"[bold]Confirm[/bold]: {plan.get('requires_user_confirmation', '')}\n"
                            f"[bold]Suggested tools[/bold]: {', '.join(plan.get('suggested_tools') or [])}\n"
                        )
                        Console().print(Panel(content, title=f"Repair Report #{index + 1}", border_style="dim"))
            else:
                table = Table(title="Repair Reports", border_style="dim")
                table.add_column("#", style="cyan")
                table.add_column("Type")
                table.add_column("Tool")
                table.add_column("Action")
                table.add_column("Risk")
                table.add_column("Auto")
                table.add_column("Error")
                for index, report in enumerate(reports[-10:], start=max(1, len(reports) - 9)):
                    plan = report.get("repair_plan") or {}
                    message = str(report.get("message", ""))
                    if len(message) > 70:
                        message = message[:67] + "..."
                    table.add_row(
                        str(index),
                        str(report.get("error_type", "")),
                        str(report.get("tool_name") or ""),
                        str(plan.get("action", "")),
                        str(plan.get("risk_level", "")),
                        str(plan.get("can_auto_retry", "")),
                        message,
                    )
                Console().print(table)

    elif cmd == "/skills":
        from rich.console import Console
        from rich.table import Table
        from comsol_agent.simulation.skills import list_skills

        table = Table(title="Simulation Skills", border_style="dim")
        table.add_column("Name", style="cyan")
        table.add_column("Domain")
        table.add_column("Template")
        table.add_column("Description")
        for skill in list_skills():
            table.add_row(
                skill.name,
                skill.domain,
                skill.template_name,
                skill.description,
            )
        Console().print(table)

    elif cmd == "/templates":
        import json
        from pathlib import Path
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from comsol_agent.cli.renderer import render_info
        from comsol_agent.tools.simulation import (
            simulation_export_template,
            simulation_run_template,
            simulation_save_template,
            simulation_validate_template,
        )

        archive_store = getattr(agent, "archive_store", None)
        if archive_store is None:
            render_info("Template archive is not configured for this session.")
        else:
            template_parts = args.split()
            subcommand = template_parts[0].lower() if template_parts else "list"
            if subcommand == "show":
                if len(template_parts) < 2:
                    render_info("Usage: /templates show <template_name>")
                else:
                    try:
                        template = archive_store.get_template(template_parts[1])
                    except Exception as exc:
                        render_info(f"Could not load template: {exc}")
                    else:
                        table = Table(title="Simulation Template", border_style="dim")
                        table.add_column("Field", style="cyan")
                        table.add_column("Value")
                        table.add_row("name", template.name)
                        table.add_row("domain", template.domain or "")
                        table.add_row("params", str(template.params))
                        table.add_row("updated_at", template.updated_at)
                        Console().print(table)
                        Console().print(Panel(template.java_code, title="Java/API Seed Code", border_style="dim"))
            elif subcommand == "save":
                if len(template_parts) < 4:
                    render_info("Usage: /templates save <name> <domain> <java_file> [params_json_file]")
                else:
                    name = template_parts[1]
                    domain = template_parts[2]
                    java_file = Path(template_parts[3]).expanduser()
                    params_file = Path(template_parts[4]).expanduser() if len(template_parts) > 4 else None
                    try:
                        java_code = java_file.read_text(encoding="utf-8")
                        params = (
                            json.loads(params_file.read_text(encoding="utf-8"))
                            if params_file is not None
                            else {}
                        )
                        result = simulation_save_template(
                            name=name,
                            domain=domain if domain != "-" else None,
                            java_code=java_code,
                            params=params,
                            archive_path=str(archive_store.db_path),
                        )
                    except Exception as exc:
                        render_info(f"Could not save template: {exc}")
                    else:
                        if result.get("success"):
                            render_info(f"Template saved: {result['template']['name']}")
                        else:
                            render_info(f"Could not save template: {result.get('error')}")
            elif subcommand == "export":
                if len(template_parts) < 2:
                    render_info("Usage: /templates export <template_name> [output_path]")
                else:
                    output_path = template_parts[2] if len(template_parts) > 2 else None
                    result = simulation_export_template(
                        template_parts[1],
                        output_path=output_path,
                        archive_path=str(archive_store.db_path),
                    )
                    if result.get("success"):
                        render_info(f"Template exported: {result['output_path']}")
                    else:
                        render_info(f"Could not export template: {result.get('error')}")
            elif subcommand == "validate":
                if len(template_parts) < 2:
                    render_info("Usage: /templates validate <template_name>")
                else:
                    result = simulation_validate_template(
                        name=template_parts[1],
                        archive_path=str(archive_store.db_path),
                    )
                    if not result.get("success") and "validation" not in result:
                        render_info(f"Could not validate template: {result.get('error')}")
                    else:
                        validation = result["validation"]
                        table = Table(
                            title=f"Template Validation: {template_parts[1]}",
                            border_style="dim",
                        )
                        table.add_column("Field", style="cyan")
                        table.add_column("Value")
                        table.add_row("status", validation["status"])
                        table.add_row("errors", str(len(validation["errors"])))
                        table.add_row("warnings", str(len(validation["warnings"])))
                        table.add_row("lines", str(validation["line_count"]))
                        Console().print(table)
                        messages = (
                            validation["errors"]
                            + validation["warnings"]
                            + validation["notes"]
                        )
                        if messages:
                            Console().print(Panel("\n".join(messages), title="Findings", border_style="dim"))
            elif subcommand == "run":
                if len(template_parts) < 4 or template_parts[2] not in {"create", "model"}:
                    render_info("Usage: /templates run <template_name> create <model_name> | model <model_name>")
                else:
                    target_key = "create_model_name" if template_parts[2] == "create" else "model_name"
                    result = simulation_run_template(
                        name=template_parts[1],
                        archive_path=str(archive_store.db_path),
                        **{target_key: template_parts[3]},
                    )
                    if result.get("success"):
                        artifact = result.get("artifacts") or {}
                        suffix = f" Artifact: {artifact.get('run_id')}" if artifact else ""
                        render_info(f"Template executed: {result.get('model_name')}.{suffix}")
                    else:
                        render_info(f"Could not run template: {result.get('error') or result.get('stage')}")
            elif subcommand == "search":
                if len(template_parts) < 2:
                    render_info("Usage: /templates search <query> [domain]")
                else:
                    query = template_parts[1]
                    domain = template_parts[2] if len(template_parts) > 2 else None
                    templates = archive_store.search_templates(query=query, domain=domain, limit=20)
                    if not templates:
                        render_info("No matching simulation templates found.")
                    else:
                        _render_templates_table(templates, title=f"Simulation Templates matching '{query}'")
            else:
                domain = template_parts[1] if subcommand == "domain" and len(template_parts) > 1 else None
                templates = archive_store.list_templates(domain=domain, limit=20)
                if not templates:
                    render_info("No simulation templates found.")
                else:
                    _render_templates_table(templates)

    elif cmd == "/log":
        # Show the last few messages in the conversation
        from rich.console import Console
        from rich.panel import Panel
        import json

        console = Console()
        messages = agent.state.messages

        # Show last 10 messages (skip system message)
        for msg in messages[-10:]:
            if msg["role"] == "system":
                console.print("[dim](system prompt)[/dim]")
                continue

            role_style = {"user": "bold green", "assistant": "bold cyan", "tool": "yellow"}.get(
                msg["role"], ""
            )
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 300:
                content = content[:297] + "..."

            if msg["role"] == "tool":
                content = f"[{msg.get('name', '?')}] {content}"

            console.print(Panel(
                str(content),
                title=f"[{role_style}]{msg['role']}[/{role_style}]",
                border_style="dim",
            ))

    else:
        from comsol_agent.cli.renderer import render_error
        render_error(f"Unknown command: {cmd}. Type /help for available commands.")

    return CommandResult.CONTINUE


def _render_artifacts_table(artifacts, title: str = "Simulation Artifacts") -> None:
    """Render archived simulation artifacts as a compact table."""
    from rich.console import Console
    from rich.table import Table
    from comsol_agent.cli.renderer import render_info

    if not artifacts:
        render_info("No simulation artifacts found.")
        return

    table = Table(title=title, border_style="dim")
    table.add_column("Run ID", style="cyan")
    table.add_column("Kind")
    table.add_column("Model")
    table.add_column("Cases")
    table.add_column("CSV")
    for artifact in artifacts:
        csv_path = artifact.csv_path or ""
        if len(csv_path) > 48:
            csv_path = "..." + csv_path[-45:]
        table.add_row(
            artifact.run_id,
            artifact.kind,
            artifact.model_name or "",
            str(artifact.executed_cases),
            csv_path,
        )
    Console().print(table)


def _render_template_execution_artifacts(artifacts, title: str = "Template Execution Runs") -> None:
    """Render template execution artifacts as a compact table."""
    from rich.console import Console
    from rich.table import Table
    from comsol_agent.cli.renderer import render_info

    if not artifacts:
        render_info("No template execution artifacts found.")
        return

    table = Table(title=title, border_style="dim")
    table.add_column("Run ID", style="cyan")
    table.add_column("Model")
    table.add_column("Template")
    table.add_column("Success")
    table.add_column("Validation")
    table.add_column("Error Type")
    for artifact in artifacts:
        metadata = artifact.metadata or {}
        table.add_row(
            artifact.run_id,
            artifact.model_name or "",
            str(metadata.get("template_name") or (artifact.source or {}).get("name") or ""),
            str(metadata.get("execution_success", "")),
            str(metadata.get("validation_status") or ""),
            str(metadata.get("execution_error_type") or metadata.get("execution_exception_type") or ""),
        )
    Console().print(table)


def _render_sessions_table(sessions, title: str = "Archived Sessions") -> None:
    """Render archived sessions as a compact table."""
    from rich.console import Console
    from rich.table import Table
    from comsol_agent.cli.renderer import render_info

    if not sessions:
        render_info("No archived sessions found.")
        return

    table = Table(title=title, border_style="dim")
    table.add_column("Session ID", style="cyan")
    table.add_column("Name")
    table.add_column("Updated")
    table.add_column("Summary")
    for session in sessions:
        table.add_row(
            session.id,
            session.name or "",
            session.updated_at,
            _truncate_text(session.summary or "", 90),
        )
    Console().print(table)


def _render_session_timeline(events: list[dict]) -> None:
    """Render a compact session event timeline."""
    from rich.console import Console
    from rich.table import Table
    from comsol_agent.cli.renderer import render_info

    if not events:
        render_info("No timeline events found in the session snapshot.")
        return

    table = Table(title="Session Timeline", border_style="dim")
    table.add_column("#", style="cyan")
    table.add_column("Message")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Detail")
    for event in events:
        table.add_row(
            str(event.get("index") or ""),
            str(event.get("message_index") or ""),
            str(event.get("type") or ""),
            str(event.get("title") or ""),
            str(event.get("status") or ""),
            _truncate_text(str(event.get("detail") or ""), 120),
        )
    Console().print(table)


def _render_templates_table(templates, title: str = "Simulation Templates") -> None:
    """Render archived simulation templates."""
    from rich.console import Console
    from rich.table import Table

    table = Table(title=title, border_style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("Domain")
    table.add_column("Params")
    table.add_column("Code Preview")
    for template in templates:
        table.add_row(
            template.name,
            template.domain or "",
            _truncate_text(str(template.params), 70),
            _truncate_text(template.java_code, 90),
        )
    Console().print(table)


def _render_artifact_preview(artifact_preview: dict) -> None:
    """Render a compact preview for one archived artifact."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    artifact = artifact_preview["artifact"]
    preview = artifact_preview.get("preview") or {}
    table = Table(title="Simulation Artifact", border_style="dim")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    for key in ("run_id", "kind", "model_name", "executed_cases", "json_path", "csv_path", "manifest_path"):
        table.add_row(key, str(artifact.get(key)))
    console.print(table)

    if "markdown" in preview:
        markdown = preview["markdown"]
        lines = "\n".join(markdown.get("lines", []))
        console.print(Panel(lines or "(empty)", title="Markdown Preview", border_style="dim"))
    elif "csv" in preview:
        summary = preview.get("summary") or {}
        csv_preview = preview["csv"]
        console.print(Panel(str(summary), title="Sweep Summary", border_style="dim"))
        rows = csv_preview.get("rows", [])
        if rows:
            row_table = Table(title="CSV Preview", border_style="dim")
            columns = list(rows[0].keys())[:8]
            for column in columns:
                row_table.add_column(column)
            for row in rows[:10]:
                row_table.add_row(*(str(row.get(column, "")) for column in columns))
            console.print(row_table)
    elif "summary" in preview:
        console.print(Panel(str(preview["summary"]), title="Artifact Summary", border_style="dim"))


def _format_parameters(parameters: dict) -> str:
    """Format parameter dict for compact table cells."""
    if not parameters:
        return ""
    text = ", ".join(f"{name}={value}" for name, value in parameters.items())
    return text if len(text) <= 80 else text[:77] + "..."


def _option_value(parts: list[str], option: str, *, default: str) -> str:
    """Return the token after an option flag in a slash command."""
    if option not in parts:
        return default
    index = parts.index(option)
    if index + 1 >= len(parts):
        return default
    return parts[index + 1]


def _option_int(parts: list[str], option: str, *, default: int) -> int:
    """Parse an integer option from slash command tokens."""
    value = _option_value(parts, option, default=str(default))
    try:
        return int(value)
    except ValueError:
        return default


def _load_session_snapshot(agent: AgentLoop, session_id: str) -> dict | None:
    """Load a JSON session snapshot when the current app knows the session dir."""
    import json
    from pathlib import Path

    session_store = getattr(agent, "session_store", None)
    session_dir = getattr(session_store, "session_dir", None)
    if session_dir is None:
        return None

    snapshot_path = Path(session_dir) / f"{session_id}.json"
    if not snapshot_path.exists():
        return None

    try:
        return json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _truncate_text(text: str, max_chars: int) -> str:
    """Trim long table/panel text without changing short values."""
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)] + "..."
