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


def render_help() -> None:
    """Display help information."""
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


def render_error(message: str) -> None:
    """Display an error message."""
    console.print(f"\n[red bold]Error:[/red bold] {message}")


def render_info(message: str) -> None:
    """Display an info message."""
    console.print(f"[dim]ℹ {message}[/dim]")


def render_warning(message: str) -> None:
    """Display a warning message."""
    console.print(f"[yellow]⚠ {message}[/yellow]")
