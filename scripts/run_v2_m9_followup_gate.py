"""Run one real HTTP follow-up turn against a persisted M9 V2 session."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx


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
    async with httpx.AsyncClient(timeout=2.0) as client:
        for _ in range(300):
            if process.returncode is not None:
                output = await process.stdout.read() if process.stdout else b""
                raise RuntimeError(output.decode(errors="replace"))
            try:
                response = await client.get(f"http://127.0.0.1:{port}/")
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


def _plan_arguments(snapshot: dict) -> dict:
    try:
        return snapshot["plan"]["steps"][0]["action"]["arguments"]
    except (KeyError, IndexError, TypeError):
        return {}


def _compact_failure(failure: object) -> object:
    if not isinstance(failure, dict):
        return failure
    return {
        key: failure.get(key)
        for key in (
            "error_class",
            "code",
            "message",
            "stage",
            "retryable",
            "termination_confirmed",
        )
        if key in failure
    }


def _compact_gates(gates: object) -> object:
    if not isinstance(gates, dict):
        return gates
    compact: dict[str, object] = {}
    for name, gate in gates.items():
        if not isinstance(gate, dict):
            compact[name] = gate
            continue
        item = {
            key: gate.get(key)
            for key in ("state", "source", "passed", "updated_at")
            if key in gate
        }
        checks = gate.get("checks")
        if isinstance(checks, list):
            item["checks"] = [
                {key: check.get(key) for key in ("name", "passed") if key in check}
                for check in checks
                if isinstance(check, dict)
            ]
        compact[name] = item
    return compact


def _compact_event(event: dict) -> dict:
    data = event.get("data") or {}
    kind = event.get("kind")
    if kind == "comsol_stage":
        compact_data = {
            key: data.get(key)
            for key in ("run_id", "model_id", "detail", "started_at", "finished_at")
        }
    elif kind == "audit":
        compact_data = {
            "kind": data.get("kind"),
            "passed": data.get("passed"),
            "errors": data.get("errors") or [],
            "contract_version": data.get("contract_version"),
        }
    elif kind == "artifact":
        compact_data = {"artifacts": data.get("artifacts") or []}
    elif kind == "specification":
        compact_data = {"specification": data.get("specification")}
    elif kind == "plan":
        plan = data.get("plan") or {}
        compact_data = {
            "route": plan.get("route"),
            "policy_validated": plan.get("policy_validated"),
            "cited_context_ids": plan.get("cited_context_ids") or [],
        }
    elif kind == "session":
        compact_data = {
            key: data.get(key)
            for key in ("mode", "requirement", "termination_confirmed")
            if key in data
        }
    elif kind == "tool":
        compact_data = {
            key: data.get(key)
            for key in ("observation_id", "action_id", "success", "error_class", "retryable")
            if key in data
        }
    elif kind == "failure":
        compact_data = _compact_failure(data)
    else:
        compact_data = data
    return {**event, "data": compact_data}


def _compact_snapshot(snapshot: dict) -> dict:
    return {
        "session_id": snapshot.get("session_id"),
        "status": snapshot.get("status"),
        "verification_level": snapshot.get("verification_level"),
        "turn_count": snapshot.get("turn_count"),
        "event_count": snapshot.get("event_count"),
        "specification": snapshot.get("specification"),
        "previous_specification": snapshot.get("previous_specification"),
        "checkpoint": snapshot.get("checkpoint"),
        "gates": _compact_gates(snapshot.get("gates")),
        "artifacts": snapshot.get("artifacts"),
        "repairs": snapshot.get("repairs"),
        "failure": _compact_failure(snapshot.get("failure")),
        "budget": snapshot.get("budget"),
        "plan_arguments": _plan_arguments(snapshot),
    }


async def run(arguments: argparse.Namespace) -> dict:
    gate_root = Path(arguments.gate_root).resolve(strict=True)
    session_store = gate_root / "session_store"
    material_root = gate_root / "material"
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
    server = await _start_server(port, environment)
    log = ""
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            before_response = await client.get(
                f"{base_url}/api/v2/sessions/{arguments.session_id}"
            )
            before_response.raise_for_status()
            before = before_response.json()
            old_event_count = int(before["event_count"])
            turn_response = await client.post(
                f"{base_url}/api/v2/sessions/{arguments.session_id}/turns",
                json={"requirement": arguments.requirement, "mode": "live"},
            )
            turn_response.raise_for_status()
            events = await _sse(
                client,
                (
                    f"{base_url}/api/v2/sessions/{arguments.session_id}/events"
                    f"?after={old_event_count}"
                ),
            )
            after_response = await client.get(
                f"{base_url}/api/v2/sessions/{arguments.session_id}"
            )
            after_response.raise_for_status()
            after = after_response.json()
    finally:
        log = await _stop_server(server)

    plan_arguments = _plan_arguments(after)
    stages = {
        event["phase"]: event["status"]
        for event in events
        if event.get("kind") == "comsol_stage"
    }
    expected_sequences = list(
        range(old_event_count + 1, old_event_count + len(events) + 1)
    )
    checks = {
        "turn_accepted": bool(events),
        "new_event_sequences_contiguous": [event["sequence"] for event in events]
        == expected_sequences,
        "route": plan_arguments.get("route"),
        "route_expected": plan_arguments.get("route") == arguments.expected_route,
        "checkpoint_reused": plan_arguments.get("resume_checkpoint")
        == before.get("checkpoint"),
        "logical_model_id_reused": plan_arguments.get("model_id")
        == _plan_arguments(before).get("model_id"),
        "previous_specification_preserved": after.get("previous_specification")
        == before.get("specification"),
        "target_load_matches": float(
            (after.get("specification") or {}).get("target_radial_load_n", -1)
        )
        == arguments.expected_target_load_n,
        "a_skipped": stages.get("A_input_validation") == "skipped",
        "b_skipped": stages.get("B_build") == "skipped",
        "c_passed": stages.get("C_solve") == "passed",
        "d_passed": stages.get("D_results_audit") == "passed",
        "strict_audit_passed": after.get("verification_level")
        == "physical_audit_passed",
        "session_completed": after.get("status") == "completed",
    }
    success = all(
        value is True
        for key, value in checks.items()
        if key != "route"
    )
    evidence = {
        "gate": "v2_m9_real_http_followup_checkpoint_reuse",
        "created_at": datetime.now(UTC).isoformat(),
        "success": success,
        "requirement": arguments.requirement,
        "checks": checks,
        "stages": stages,
        "before": _compact_snapshot(before),
        "after": _compact_snapshot(after),
        "events": [_compact_event(event) for event in events],
        "server_log_tail": log[-12000:],
    }
    output = gate_root / arguments.output_name
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence["evidence_path"] = str(output)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-root", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--requirement", required=True)
    parser.add_argument("--expected-route", default="parameter_override")
    parser.add_argument("--expected-target-load-n", type=float, required=True)
    parser.add_argument("--output-name", default="v2_m9_followup_gate.json")
    parser.add_argument("--comsol-version", default="6.2")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=2400)
    result = asyncio.run(run(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
