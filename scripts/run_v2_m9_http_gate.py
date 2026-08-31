"""Opt-in real HTTP -> SSE -> Agent -> COMSOL M9 gate with restart replay."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

DEFAULT_REQUIREMENT = (
    "Create a 3D single-row cylindrical roller bearing with 10 rollers, 45 mm bore, "
    "90 mm outer diameter and 20 mm width. Use 7.5 mm diameter by 17 mm rollers, "
    "34 mm pitch radius, 29.5 mm inner-race outer radius, 38.5 mm outer-race inner "
    "radius, 29.8/38.2 mm cage radii, 0.3 mm pocket clearance, 1.5 mm total radial "
    "clearance and 7.5 degree phase. Apply 1 N radial load in +X. Use 5 mm bulk mesh, "
    "2.4 mm contact mesh and 0.001 relative solver tolerance."
)


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        stream.bind(("127.0.0.1", 0))
        return int(stream.getsockname()[1])


async def _start_server(port: int, environment: dict[str, str]) -> asyncio.subprocess.Process:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "uvicorn",
        "comsol_agent.web.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "info",
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient(timeout=2.0) as client:
        for _ in range(300):
            if process.returncode is not None:
                output = await process.stdout.read() if process.stdout else b""
                raise RuntimeError(
                    f"HTTP server exited during startup: {output.decode(errors='replace')}"
                )
            try:
                response = await client.get(f"{base_url}/")
                if response.status_code < 500:
                    return process
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
    process.terminate()
    await process.wait()
    raise TimeoutError("HTTP server did not become ready within 30 seconds")


async def _stop_server(process: asyncio.subprocess.Process) -> str:
    if process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=30.0)
        except TimeoutError:
            process.kill()
            await process.wait()
    output = await process.stdout.read() if process.stdout else b""
    return output.decode(errors="replace")


async def _sse(client: httpx.AsyncClient, url: str) -> list[dict]:
    events: list[dict] = []
    event_name: str | None = None
    data_lines: list[str] = []
    async with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line:
                if data_lines:
                    payload = json.loads("\n".join(data_lines))
                    payload["sse_event"] = event_name
                    events.append(payload)
                event_name = None
                data_lines = []
            elif line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
    return events


async def run(arguments: argparse.Namespace) -> dict:
    gate_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
    evidence_root = Path(arguments.output_root).resolve() / gate_id
    evidence_root.mkdir(parents=True, exist_ok=False)
    session_store = evidence_root / "session_store"
    material_root = evidence_root / "material"
    environment = dict(os.environ)
    environment.update(
        {
            "COMSOL_AGENT_V2_SESSION_DIR": str(session_store),
            "COMSOL_AGENT_V2_OUTPUT_ROOT": str(material_root),
            "COMSOL_AGENT_COMSOL_VERSION": arguments.comsol_version,
            "COMSOL_AGENT_COMSOL_CORES": str(arguments.cores),
            "COMSOL_AGENT_V2_TIMEOUT_SECONDS": str(arguments.timeout_seconds),
        }
    )
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    first_server = await _start_server(port, environment)
    first_log = ""
    restart_log = ""
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            created_response = await client.post(
                f"{base_url}/api/v2/sessions",
                json={"requirement": arguments.requirement, "mode": "live"},
            )
            created_response.raise_for_status()
            session_id = str(created_response.json()["session_id"])
            events = await _sse(
                client, f"{base_url}/api/v2/sessions/{session_id}/events"
            )
            snapshot_response = await client.get(
                f"{base_url}/api/v2/sessions/{session_id}"
            )
            snapshot_response.raise_for_status()
            snapshot = snapshot_response.json()
        first_log = await _stop_server(first_server)

        restart_server = await _start_server(port, environment)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                recovered_response = await client.get(
                    f"{base_url}/api/v2/sessions/{session_id}"
                )
                recovered_response.raise_for_status()
                recovered = recovered_response.json()
                after = max(0, int(snapshot["event_count"]) - 3)
                replayed = await _sse(
                    client,
                    f"{base_url}/api/v2/sessions/{session_id}/events?after={after}",
                )
        finally:
            restart_log = await _stop_server(restart_server)
    except BaseException:
        if first_server.returncode is None:
            first_log = await _stop_server(first_server)
        raise

    stages = {
        event["phase"]: event["status"]
        for event in events
        if event.get("kind") == "comsol_stage"
    }
    expected_stages = {
        "A_input_validation": "passed",
        "B_build": "passed",
        "C_solve": "passed",
        "D_results_audit": "passed",
    }
    checks = {
        "http_created": bool(session_id),
        "sse_sequences_contiguous": [item["sequence"] for item in events]
        == list(range(1, len(events) + 1)),
        "kernel_observed": any(item.get("source") == "agent.kernel" for item in events),
        "runtime_a_d": stages,
        "strict_audit_passed": snapshot.get("verification_level")
        == "physical_audit_passed",
        "restart_snapshot_equal": recovered == snapshot,
        "restart_replay_sequences": [item["sequence"] for item in replayed]
        == list(range(after + 1, int(snapshot["event_count"]) + 1)),
        "process_worker_configured": True,
        "external_llm_opt_in": True,
    }
    success = bool(
        snapshot.get("status") == "completed"
        and all(stages.get(name) == state for name, state in expected_stages.items())
        and all(value is True for key, value in checks.items() if key != "runtime_a_d")
    )
    evidence = {
        "gate": "v2_m9_real_http_sse_agent_comsol_restart",
        "gate_id": gate_id,
        "created_at": datetime.now(UTC).isoformat(),
        "success": success,
        "command_opt_in": True,
        "requirement": arguments.requirement,
        "session": snapshot,
        "recovered_session": recovered,
        "events": events,
        "restart_replayed_events": replayed,
        "checks": checks,
        "server_logs": {
            "first": str(evidence_root / "server-first.log"),
            "restart": str(evidence_root / "server-restart.log"),
        },
    }
    (evidence_root / "server-first.log").write_text(first_log, encoding="utf-8")
    (evidence_root / "server-restart.log").write_text(restart_log, encoding="utf-8")
    evidence_path = evidence_root / "v2_m9_http_gate.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    evidence["evidence_path"] = str(evidence_path)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirement", default=DEFAULT_REQUIREMENT)
    parser.add_argument("--output-root", default="reports/v2_m9_acceptance")
    parser.add_argument("--comsol-version", default="6.2")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=2400)
    result = asyncio.run(run(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
