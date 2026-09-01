"""Opt-in real M8 event-adapter -> Kernel -> COMSOL -> strict-audit gate."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from comsol_agent.v2.domains.bearing import BearingAcceptanceMode
from comsol_agent.v2.web import BearingV2Driver, V2SessionManager

DEFAULT_REQUIREMENT = (
    "Create a 3D single-row cylindrical roller bearing with 10 rollers, 45 mm bore, "
    "90 mm outer diameter and 20 mm width. Use 7.5 mm diameter by 17 mm rollers, "
    "34 mm pitch radius, 29.5 mm inner-race outer radius, 38.5 mm outer-race inner "
    "radius, 29.8/38.2 mm cage radii, 0.3 mm pocket clearance, 1.5 mm total radial "
    "clearance and 7.5 degree phase. Apply 1 N radial load in +X. Use 5 mm bulk mesh, "
    "2.4 mm contact mesh and 0.001 relative solver tolerance."
)


async def run(arguments: argparse.Namespace) -> dict:
    output_root = Path(arguments.output_root).resolve()
    driver = BearingV2Driver(
        output_root=output_root,
        comsol_version=arguments.comsol_version,
        cores=arguments.cores,
        timeout_seconds=arguments.timeout_seconds,
        acceptance_mode=arguments.acceptance_mode,
    )
    manager = V2SessionManager(driver)
    created = await manager.create(arguments.requirement, mode="live")
    session_id = created["session_id"]
    events = [event async for event in manager.events(session_id)]
    snapshot = manager.snapshot(session_id)
    stages = {
        event.phase: event.status
        for event in events
        if event.kind.value == "comsol_stage"
    }
    expected = {
        "A_input_validation": "passed",
        "B_build": "passed",
        "C_solve": "passed",
        "D_results_audit": "passed",
    }
    expected_verification = (
        "physical_audit_passed"
        if arguments.acceptance_mode == BearingAcceptanceMode.STRICT_VERIFIED.value
        else "engineering_preview_accepted"
    )
    success = bool(
        snapshot["status"] == "completed"
        and snapshot["verification_level"] == expected_verification
        and all(stages.get(stage) == state for stage, state in expected.items())
        and snapshot["artifacts"]
    )
    compact_session = {
        "session_id": snapshot["session_id"],
        "status": snapshot["status"],
        "verification_level": snapshot["verification_level"],
        "gates": {
            name: {"state": gate["state"], "source": gate["source"]}
            for name, gate in snapshot["gates"].items()
        },
        "specification": snapshot["specification"],
        "checkpoint": snapshot["checkpoint"],
        "artifacts": snapshot["artifacts"],
        "repairs": snapshot["repairs"],
        "failure": _compact_failure(snapshot["failure"]),
        "budget": snapshot["budget"],
        "event_count": snapshot["event_count"],
        "turn_count": snapshot["turn_count"],
    }
    evidence = {
        "gate": "v2_m8_web_cli_observability_e2e",
        "success": success,
        "created_at": datetime.now(UTC).isoformat(),
        "requirement": arguments.requirement,
        "session": compact_session,
        "events": [_compact_event(event.model_dump(mode="json")) for event in events],
        "audits": [
            _compact_audit(event.data)
            for event in events
            if event.kind.value == "audit"
        ],
        "checks": {
            "kernel_event_stream": any(event.source == "agent.kernel" for event in events),
            "runtime_a_d": stages,
            "strict_audit_separate": {
                "state": snapshot["gates"]["physical_audit"]["state"],
                "source": snapshot["gates"]["physical_audit"]["source"],
            },
            "static_demo_used": False,
            "legacy_gate_subprocess": False,
        },
    }
    evidence_dir = output_root / session_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / "v2_m8_web_e2e.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    evidence["evidence_path"] = str(evidence_path)
    return evidence


def _compact_event(event: dict) -> dict:
    data = event.get("data") or {}
    kind = event["kind"]
    compact_data = data
    if kind == "session":
        compact_data = {
            key: data[key]
            for key in ("mode", "requirement", "termination_confirmed")
            if key in data
        }
    elif kind == "comsol_stage":
        detail = data.get("detail") or {}
        compact_data = {
            "run_id": data.get("run_id"),
            "model_id": data.get("model_id"),
            "detail_keys": sorted(detail),
            "checkpoint_id": detail.get("checkpoint_id"),
            "input_sha256": detail.get("input_sha256"),
            "code": detail.get("code"),
        }
    elif kind == "audit":
        compact_data = _compact_audit(data)
    elif kind == "specification" and "specification" not in data:
        compact_data = {"utterance": data.get("utterance")}
    return {**event, "data": compact_data}


def _compact_audit(audit: dict) -> dict:
    checks = audit.get("checks") or []
    return {
        "kind": audit.get("kind"),
        "passed": audit.get("passed"),
        "contract_version": audit.get("contract_version"),
        "errors": audit.get("errors") or [],
        "checks": [
            {
                key: check.get(key)
                for key in ("name", "passed", "actual", "expected", "tolerance")
            }
            for check in checks
        ],
    }


def _compact_failure(failure: dict | None) -> dict | None:
    if failure is None:
        return None
    return {
        key: failure.get(key)
        for key in (
            "error_class",
            "message",
            "stage",
            "code",
            "retryable",
            "termination_confirmed",
        )
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirement", default=DEFAULT_REQUIREMENT)
    parser.add_argument("--output-root", default="reports/v2_m8_web_evidence")
    parser.add_argument("--comsol-version", default="6.2")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=5400)
    parser.add_argument(
        "--acceptance-mode",
        choices=[mode.value for mode in BearingAcceptanceMode],
        default=BearingAcceptanceMode.ENGINEERING_PREVIEW.value,
    )
    result = asyncio.run(run(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
