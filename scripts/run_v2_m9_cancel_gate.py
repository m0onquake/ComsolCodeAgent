"""Opt-in real C-solve cancellation gate for the recyclable COMSOL worker."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from run_v2_m9_http_gate import (
    DEFAULT_REQUIREMENT,
    _available_port,
    _start_server,
    _stop_server,
)


async def _stream_and_cancel(
    client: httpx.AsyncClient,
    base_url: str,
    session_id: str,
    delay_seconds: float,
) -> tuple[list[dict], dict | None]:
    events: list[dict] = []
    cancel_response: dict | None = None
    event_name: str | None = None
    data_lines: list[str] = []
    url = f"{base_url}/api/v2/sessions/{session_id}/events"
    async with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line:
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].lstrip())
                continue
            if not data_lines:
                continue
            event = json.loads("\n".join(data_lines))
            event["sse_event"] = event_name
            events.append(event)
            event_name = None
            data_lines = []
            if (
                cancel_response is None
                and event.get("kind") == "comsol_stage"
                and event.get("phase") == "C_solve"
                and event.get("status") == "running"
            ):
                await asyncio.sleep(delay_seconds)
                cancelled = await client.post(
                    f"{base_url}/api/v2/sessions/{session_id}/cancel",
                    json={"reason": "M9 real blocking solve hard-cancel gate"},
                )
                cancelled.raise_for_status()
                cancel_response = cancelled.json()
    return events, cancel_response


async def run(arguments: argparse.Namespace) -> dict:
    gate_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
    evidence_root = Path(arguments.output_root).resolve() / gate_id
    evidence_root.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ)
    environment.update(
        {
            "COMSOL_AGENT_V2_SESSION_DIR": str(evidence_root / "session_store"),
            "COMSOL_AGENT_V2_OUTPUT_ROOT": str(evidence_root / "material"),
            "COMSOL_AGENT_COMSOL_VERSION": arguments.comsol_version,
            "COMSOL_AGENT_COMSOL_CORES": str(arguments.cores),
            "COMSOL_AGENT_V2_TIMEOUT_SECONDS": str(arguments.timeout_seconds),
        }
    )
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    server = await _start_server(port, environment)
    server_log = ""
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            created = await client.post(
                f"{base_url}/api/v2/sessions",
                json={"requirement": arguments.requirement, "mode": "live"},
            )
            created.raise_for_status()
            session_id = str(created.json()["session_id"])
            events, cancel_response = await _stream_and_cancel(
                client, base_url, session_id, arguments.cancel_delay_seconds
            )
            snapshot_response = await client.get(
                f"{base_url}/api/v2/sessions/{session_id}"
            )
            snapshot_response.raise_for_status()
            snapshot = snapshot_response.json()
    finally:
        server_log = await _stop_server(server)

    post_cancel_path = evidence_root / "post_cancel_lifecycle.json"
    post_cancel = await asyncio.create_subprocess_exec(
        sys.executable,
        "scripts/run_v2_comsol_smoke.py",
        "--version",
        arguments.comsol_version,
        "--cores",
        str(arguments.cores),
        "--evidence-path",
        str(post_cancel_path),
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    post_output, _ = await post_cancel.communicate()
    stages = {
        event["phase"]: event["status"]
        for event in events
        if event.get("kind") == "comsol_stage"
    }
    solved_files = [
        str(path.relative_to(evidence_root))
        for path in evidence_root.rglob("*.mph")
        if "solved" in path.name.lower()
    ]
    checks = {
        "cancel_requested_after_c_solve_running": cancel_response is not None,
        "a_passed": stages.get("A_input_validation") == "passed",
        "b_passed": stages.get("B_build") == "passed",
        "c_cancelled": stages.get("C_solve") == "cancelled",
        "session_cancelled": snapshot.get("status") == "cancelled",
        "termination_confirmed": (snapshot.get("failure") or {}).get(
            "termination_confirmed"
        )
        is True,
        "no_solved_artifact": not solved_files,
        "post_cancel_new_comsol_lifecycle": post_cancel.returncode == 0
        and post_cancel_path.is_file(),
    }
    success = all(checks.values())
    evidence = {
        "gate": "v2_m9_real_blocking_comsol_process_cancel",
        "gate_id": gate_id,
        "created_at": datetime.now(UTC).isoformat(),
        "success": success,
        "command_opt_in": True,
        "cancel_delay_seconds": arguments.cancel_delay_seconds,
        "session": snapshot,
        "events": events,
        "cancel_response": cancel_response,
        "checks": checks,
        "solved_files": solved_files,
        "post_cancel_lifecycle": {
            "returncode": post_cancel.returncode,
            "evidence_path": str(post_cancel_path),
            "output_tail": post_output.decode(errors="replace")[-4000:],
        },
    }
    (evidence_root / "server.log").write_text(server_log, encoding="utf-8")
    evidence_path = evidence_root / "v2_m9_cancel_gate.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    evidence["evidence_path"] = str(evidence_path)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirement", default=DEFAULT_REQUIREMENT)
    parser.add_argument("--output-root", default="reports/v2_m9_cancel_evidence")
    parser.add_argument("--comsol-version", default="6.2")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=2400)
    parser.add_argument("--cancel-delay-seconds", type=float, default=2.0)
    result = asyncio.run(run(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
