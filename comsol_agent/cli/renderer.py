"""Rich terminal rendering for the COMSOL Agent CLI.

Provides Codex-like formatting: headers, tool call indicators,
status messages, token usage bars, and styled output.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich.live import Live
from rich.layout import Layout
from rich.markdown import Markdown

console = Console()


def show_header(version: str, model: str, session_name: str | None = None) -> None:
    """Display the application header."""
    header_text = Text()
    header_text.append("╭", style="bold")
    header_text.append(" COMSOL Agent ", style="bold cyan")
    header_text.append(f"v{version}", style="dim")
    header_text.append(" ╮", style="bold")
    console.print(header_text)
    console.print(
        f"  Model: {model}"
        + (f" | Session: {session_name}" if session_name else "")
    )


def show_goodbye() -> None:
    """Display goodbye message."""
    console.print("\n[dim]Goodbye! 👋[/dim]\n")


def render_goodbye() -> None:
    """Display goodbye message."""
    show_goodbye()


def render_agent_response(text: str) -> None:
    """Render the agent's text response with Markdown support."""
    console.print()
    # Use Markdown rendering for rich output
    try:
        md = Markdown(text, code_theme="monokai")
        console.print(md)
    except Exception:
        console.print(text)
    console.print()


def render_tool_call(name: str, arguments: dict, status: str = "running") -> None:
    """Render a tool call with its arguments.

    Args:
        name: Tool name.
        arguments: Tool arguments dict.
        status: 'running', 'success', or 'error'.
    """
    if status == "running":
        style = "bold yellow"
        prefix = "↳"
    elif status == "success":
        style = "green"
        prefix = "✅"
    else:
        style = "red"
        prefix = "❌"

    # Format arguments for display (keep it compact)
    args_str = ", ".join(
        f"{k}={repr(v)[:50]}" for k, v in arguments.items()
    )
    if len(args_str) > 80:
        args_str = args_str[:77] + "..."

    console.print(f"  {prefix} [{style}]{name}[/{style}]({args_str})")


def render_tool_result(name: str, result: dict, is_error: bool = False) -> None:
    """Render a tool result summary.

    Args:
        name: Tool name.
        result: Result dict.
        is_error: Whether this was an error.
    """
    if is_error:
        error_msg = result.get("error", str(result))
        if len(error_msg) > 200:
            error_msg = error_msg[:197] + "..."
        console.print(f"    [red]Error:[/red] {error_msg}")
    else:
        # Show a compact summary for common operations
        if name == "comsol_solve":
            elapsed = result.get("elapsed_seconds", "?")
            console.print(f"    [green]Solved in {elapsed}s[/green]")
        elif name == "comsol_evaluate":
            stats = result.get("statistics", {})
            if stats:
                console.print(
                    f"    [dim]min={stats.get('min', '?')}, "
                    f"max={stats.get('max', '?')}, "
                    f"mean={stats.get('mean', '?')}[/dim]"
                )
        elif name == "comsol_load_model":
            console.print(f"    [green]Model loaded: {result.get('model_name', '?')}[/green]")


def render_status_bar(
    token_count: int,
    max_tokens: int = 180000,
    tool_iterations: int = 0,
    total_turns: int = 0,
) -> None:
    """Render the bottom status bar with token usage and stats.

    Args:
        token_count: Current estimated token count.
        max_tokens: Context window size.
        tool_iterations: Tool calls this turn.
        total_turns: Total conversation turns.
    """
    usage_pct = min(100, int(token_count / max_tokens * 100))

    # Build a simple text status bar
    bar_width = 20
    filled = int(bar_width * usage_pct / 100)
    bar = "█" * filled + "░" * (bar_width - filled)

    if usage_pct > 80:
        bar_style = "red"
    elif usage_pct > 50:
        bar_style = "yellow"
    else:
        bar_style = "green"

    token_str = ""
    if token_count >= 1000:
        token_str = f"{token_count / 1000:.1f}k"
    else:
        token_str = str(token_count)

    max_str = ""
    if max_tokens >= 1000:
        max_str = f"{max_tokens / 1000:.0f}k"
    else:
        max_str = str(max_tokens)

    console.print(
        "\n" + "─" * console.width,
        style="dim",
    )
    console.print(
        f"  Token: [{bar_style}]{bar}[/{bar_style}] {token_str}/{max_str}"
        + (f" | 本轮工具: {tool_iterations}" if tool_iterations else "")
        + (f" | 对话轮次: {total_turns}" if total_turns else ""),
        style="dim",
    )


def render_help(topic: str | None = None) -> None:
    """Display help information."""
    normalized_topic = (topic or "").strip().lower()
    if normalized_topic in {"templates", "/templates"}:
        _render_templates_help()
        return
    if normalized_topic in {"artifacts", "/artifacts"}:
        _render_artifacts_help()
        return

    help_table = Table(title="COMSOL Agent Commands", show_header=False, border_style="dim")
    help_table.add_column("Command", style="cyan")
    help_table.add_column("Description")

    commands = [
        ("/help", "Show this help"),
        ("/clear", "Clear conversation history"),
        ("/compact", "Manually compact context (free up tokens)"),
        ("/memory", "View/manage agent memory"),
        ("/sessions", "List/search/show archived sessions"),
        ("/archive", "Summarize/export/cleanup archive records"),
        ("/artifacts", "List/search/show/compare/report simulation artifacts"),
        ("/repairs", "List/show auto-repair reports"),
        ("/models", "List loaded COMSOL models"),
        ("/config", "View or modify configuration"),
        ("/doctor", "Check runtime; add --deep for real LLM/COMSOL smoke"),
        ("/skills", "List available agent skills"),
        ("/templates", "List/show/validate/run simulation code templates"),
        ("/log", "Show detailed turn log"),
        ("/exit, /quit", "Exit COMSOL Agent"),
    ]
    for cmd, desc in commands:
        help_table.add_row(cmd, desc)

    console.print(help_table)
    console.print("[dim]Use /help templates or /help artifacts for detailed subcommands.[/dim]")


def _render_templates_help() -> None:
    """Display detailed template command help."""
    table = Table(title="/templates subcommands", show_header=True, border_style="dim")
    table.add_column("Command", style="cyan")
    table.add_column("Purpose")
    table.add_column("Notes")
    rows = [
        ("/templates", "List recent templates", "Shows name, domain, params, and code preview."),
        ("/templates domain <domain>", "List templates by domain", "Example: /templates domain thermal"),
        ("/templates search <query> [domain]", "Search templates", "Searches name, domain, code, and params."),
        ("/templates show <template_name>", "Show template source", "Prints metadata and Java/API seed code."),
        ("/templates validate <template_name>", "Run offline validation", "Shows errors, warnings, and notes."),
        ("/templates export <template_name> [path]", "Export Java seed file", "Writes under allowed project/config roots."),
        ("/templates save <name> <domain> <java_file> [params_json_file]", "Save custom template", "Validates before archiving."),
        (
            "/templates run <template_name> create <model_name>",
            "Create a new model and run",
            "Persists a template_execution artifact.",
        ),
        (
            "/templates run <template_name> model <model_name> --allow-modify-loaded",
            "Run against an existing loaded model",
            "Flag is required because this modifies a loaded COMSOL model.",
        ),
    ]
    for row in rows:
        table.add_row(*row)
    console.print(table)


def _render_artifacts_help() -> None:
    """Display detailed artifact command help."""
    table = Table(title="/artifacts subcommands", show_header=True, border_style="dim")
    table.add_column("Command", style="cyan")
    table.add_column("Purpose")
    table.add_column("Notes")
    rows = [
        ("/artifacts", "List recent sweep artifacts", "Shows run id, kind, model, cases, and CSV path."),
        ("/artifacts search <query>", "Search archived artifacts", "Searches run id, kind, model, source, paths, metadata."),
        ("/artifacts show <run_id> [max_lines]", "Inspect one artifact", "Shows structured preview for sweeps, reports, and template runs."),
        ("/artifacts compare <query> [metric] [expression] [max|min]", "Rank sweep rows", "Uses persisted CSV metrics."),
        ("/artifacts report <query> [metric] [expression] [max|min] [markdown|html|both]", "Export sweep report", "Archives report as comparison_report."),
        ("/artifacts template-runs [query]", "List template execution runs", "Shows success, validation, and error type."),
        ("/artifacts report-template <query> [markdown|html|both]", "Export template run report", "Archives report as template_execution_report."),
    ]
    for row in rows:
        table.add_row(*row)
    console.print(table)


def render_welcome(config_summary: str) -> None:
    """Display welcome message with config summary."""
    console.print(
        Panel.fit(
            f"[bold cyan]COMSOL Agent[/bold cyan] — AI-powered simulation assistant\n"
            f"[dim]{config_summary}[/dim]\n"
            "Type [cyan]/help[/cyan] for commands, [cyan]/exit[/cyan] to quit.",
            border_style="cyan",
        )
    )


def render_startup_status(
    *,
    provider: str,
    model: str,
    comsol_executable: str | None,
    comsol_version: str | None,
    archive_path: str,
    session_dir: str | None = None,
    api_key_present: bool = False,
    base_url: str | None = None,
) -> None:
    """Display a non-secret startup status panel."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("LLM", f"{provider}/{model}")
    table.add_row("API key", "configured" if api_key_present else "missing")
    table.add_row("Base URL", base_url or "provider default")
    table.add_row("COMSOL executable", comsol_executable or "auto-detect")
    table.add_row("COMSOL version", comsol_version or "auto-detect")
    table.add_row("Archive", archive_path)
    if session_dir:
        table.add_row("Sessions", session_dir)
    console.print(
        Panel(
            table,
            title="Startup Status",
            border_style="cyan",
            subtitle="Secrets hidden",
        )
    )


def render_error(message: str) -> None:
    """Display an error message."""
    console.print(f"\n[red bold]Error:[/red bold] {message}")


def render_info(message: str) -> None:
    """Display an info message."""
    console.print(f"[dim]ℹ {message}[/dim]")


def render_warning(message: str) -> None:
    """Display a warning message."""
    console.print(f"[yellow]⚠ {message}[/yellow]")
