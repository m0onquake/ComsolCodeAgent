"""CLI renderer and entry point for the same V2 session/event adapter as Web."""

from __future__ import annotations

import argparse
import asyncio
import signal
from typing import Any

from rich.console import Console
from rich.table import Table

from .bearing import BearingV2Driver
from .contracts import V2Event, V2EventKind
from .session import V2SessionManager

console = Console()


def render_event(event: V2Event, *, output: Console = console) -> None:
    """Render the shared event contract without inventing success states."""
    color = {
        "passed": "green",
        "completed": "green",
        "failed": "red",
        "timed_out": "red",
        "cancelled": "yellow",
        "running": "cyan",
        "paused": "yellow",
    }.get(event.status, "white")
    prefix = {
        V2EventKind.SPECIFICATION: "SPEC",
        V2EventKind.RETRIEVAL: "RAG",
        V2EventKind.PLAN: "PLAN",
        V2EventKind.TOOL: "TOOL",
        V2EventKind.COMSOL_STAGE: "COMSOL",
        V2EventKind.REPAIR: "REPAIR",
        V2EventKind.BUDGET: "BUDGET",
        V2EventKind.AUDIT: "AUDIT",
        V2EventKind.ARTIFACT: "ARTIFACT",
        V2EventKind.FAILURE: "FAIL",
        V2EventKind.SESSION: "RUN",
    }[event.kind]
    output.print(
        f"[{color}][{prefix}] {event.phase}: {event.status}[/{color}]"
        + (f" — {event.message}" if event.message else "")
    )


def render_snapshot(snapshot: dict[str, Any], *, output: Console = console) -> None:
    table = Table(title=f"V2 evidence · {snapshot['verification_level']}")
    table.add_column("Gate")
    table.add_column("State")
    table.add_column("Source")
    for name, gate in snapshot["gates"].items():
        table.add_row(name, gate["state"], gate.get("source") or "—")
    output.print(table)


async def _run(requirement: str, *, mode: str) -> int:
    manager = V2SessionManager(BearingV2Driver())
    snapshot = await manager.create(requirement, mode=mode)
    session_id = snapshot["session_id"]
    loop = asyncio.get_running_loop()

    async def cancel() -> None:
        try:
            await manager.cancel(session_id, "cancelled from CLI")
        except RuntimeError:
            pass

    async def toggle_pause() -> None:
        current = manager.snapshot(session_id)["status"]
        try:
            if current in {"paused", "pause_requested"}:
                await manager.resume(session_id)
            elif current == "running":
                await manager.pause(session_id)
        except RuntimeError:
            pass

    loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(cancel()))
    if hasattr(signal, "SIGTSTP"):
        loop.add_signal_handler(
            signal.SIGTSTP,
            lambda: asyncio.create_task(toggle_pause()),
        )
    try:
        async for event in manager.events(session_id):
            render_event(event)
    except KeyboardInterrupt:
        await cancel()
    final = manager.snapshot(session_id)
    render_snapshot(final)
    return 0 if final["status"] == "completed" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="COMSOL Agent V2 observable runner")
    parser.add_argument("requirement", help="Natural-language cylindrical bearing requirement")
    parser.add_argument("--plan-only", action="store_true", help="Stop before COMSOL")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(_run(args.requirement, mode="plan_only" if args.plan_only else "live"))
    )
