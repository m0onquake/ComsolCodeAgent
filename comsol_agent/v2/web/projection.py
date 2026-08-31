"""Project append-only V2 events into an honest user-facing run snapshot."""

from __future__ import annotations

from typing import Any

from comsol_agent.v2.contracts.models import utc_now

from .contracts import (
    ArtifactView,
    EvidenceGate,
    EvidenceState,
    FailureView,
    SessionSnapshot,
    SessionStatus,
    V2Event,
    V2EventKind,
    VerificationLevel,
)

GATE_NAMES = ("static_validation", "model_build", "solve", "physical_audit")


def new_snapshot(session_id: str) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=session_id,
        status=SessionStatus.CREATED,
        gates={name: EvidenceGate() for name in GATE_NAMES},
    )


def apply_event(snapshot: SessionSnapshot, event: V2Event) -> None:
    snapshot.active_turn_id = event.turn_id
    snapshot.event_count = event.sequence
    snapshot.updated_at = utc_now()
    if event.kind == V2EventKind.SESSION:
        _session(snapshot, event)
    elif event.kind == V2EventKind.SPECIFICATION:
        if "specification" in event.data:
            snapshot.previous_specification = snapshot.specification
            snapshot.specification = event.data["specification"]
        _gate(snapshot, "static_validation", event)
    elif event.kind == V2EventKind.PLAN:
        snapshot.plan = event.data.get("plan", event.data)
    elif event.kind == V2EventKind.COMSOL_STAGE:
        gate = {
            "A_input_validation": "static_validation",
            "B_build": "model_build",
            "C_solve": "solve",
            "D_results_audit": "physical_audit",
        }.get(event.phase)
        if gate:
            _gate(snapshot, gate, event)
    elif event.kind == V2EventKind.AUDIT:
        if event.data.get("selected_for_acceptance", True):
            _gate(snapshot, "physical_audit", event)
    elif event.kind == V2EventKind.REPAIR:
        snapshot.repairs.append(dict(event.data))
    elif event.kind == V2EventKind.BUDGET:
        _budget(snapshot, event)
    elif event.kind == V2EventKind.ARTIFACT:
        item = ArtifactView.model_validate(event.data)
        snapshot.artifacts = [
            existing for existing in snapshot.artifacts if existing.artifact_id != item.artifact_id
        ]
        snapshot.artifacts.append(item)
    elif event.kind == V2EventKind.FAILURE:
        snapshot.failure = FailureView.model_validate(event.data)
    snapshot.verification_level = verification_level(snapshot)


def verification_level(snapshot: SessionSnapshot) -> VerificationLevel:
    if snapshot.failure is not None or snapshot.status in {
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    }:
        return VerificationLevel.FAILED
    states = {name: gate.state for name, gate in snapshot.gates.items()}
    if states["physical_audit"] == EvidenceState.PASSED:
        if (
            snapshot.gates["physical_audit"].evidence.get("kind")
            == "bearing_engineering_stress_preview"
        ):
            return VerificationLevel.ENGINEERING_PREVIEW_ACCEPTED
        return VerificationLevel.PHYSICAL_AUDIT_PASSED
    if states["solve"] == EvidenceState.PASSED:
        return VerificationLevel.SOLVE_PASSED
    if states["model_build"] == EvidenceState.PASSED:
        return VerificationLevel.MODEL_BUILT
    if snapshot.plan is not None:
        return VerificationLevel.PLANNED
    if states["static_validation"] == EvidenceState.PASSED:
        return VerificationLevel.SPECIFICATION_VALIDATED
    if any(gate.source == "static_demo" for gate in snapshot.gates.values()):
        return VerificationLevel.STATIC_DEMO
    return VerificationLevel.NONE


def _session(snapshot: SessionSnapshot, event: V2Event) -> None:
    try:
        snapshot.status = SessionStatus(event.status)
    except ValueError:
        return


def _gate(snapshot: SessionSnapshot, name: str, event: V2Event) -> None:
    try:
        state = EvidenceState(event.status)
    except ValueError:
        return
    snapshot.gates[name] = EvidenceGate(
        state=state,
        source=event.source,
        evidence=dict(event.data),
    )


def _budget(snapshot: SessionSnapshot, event: V2Event) -> None:
    data = dict(event.data)
    if event.phase != "llm":
        snapshot.budget.update(data)
        return
    token_keys = (
        "llm_prompt_tokens",
        "llm_completion_tokens",
        "llm_total_tokens",
    )
    for key in token_keys:
        snapshot.budget[key] = int(snapshot.budget.get(key, 0)) + int(data.pop(key, 0))
    requests = list(snapshot.budget.get("llm_requests", []))
    requests.append(
        {
            key: data.get(key)
            for key in ("provider", "model", "request_id")
            if data.get(key) is not None
        }
    )
    snapshot.budget["llm_requests"] = requests
    snapshot.budget.update(data)


def public_snapshot(snapshot: SessionSnapshot) -> dict[str, Any]:
    return snapshot.model_dump(mode="json")
