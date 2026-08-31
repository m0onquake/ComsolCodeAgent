"""M8 API/event/control/CLI acceptance tests without external LLM or COMSOL."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from comsol_agent.v2.runtime.comsol import (
    Checkpoint,
    RuntimeArtifact,
    RuntimeProvenance,
    RuntimeStage,
)
from comsol_agent.v2.web import (
    JsonSessionStore,
    RunControl,
    TurnRequest,
    TurnResult,
    V2Event,
    V2EventKind,
    V2SessionManager,
)
from comsol_agent.v2.web.bearing import (
    _model_id_for_checkpoint,
    _native_plot_artifact,
    _runtime_artifact_index,
)
from comsol_agent.v2.web.cli import render_event, render_snapshot
from comsol_agent.v2.web.projection import apply_event, new_snapshot


def test_web_checkpoint_reuses_typed_logical_model_id(tmp_path: Path) -> None:
    provenance = RuntimeProvenance(
        run_id="run-1",
        model_id="m8-bearing-stable",
        backend="MPh-process",
        backend_version="spawn-rpc-1",
        comsol_version="6.2",
        source="runtime:checkpoint",
    )
    artifact = RuntimeArtifact(
        artifact_id="artifact-1",
        path=str(tmp_path / "checkpoint.mph"),
        relative_path="checkpoint.mph",
        media_type="application/vnd.comsol.mph",
        sha256="a" * 64,
        size_bytes=1,
        stage=RuntimeStage.BUILD,
        provenance=provenance,
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = Checkpoint(
        checkpoint_id="checkpoint-1",
        stage=RuntimeStage.BUILD,
        artifact=artifact,
        manifest_path=str(checkpoint_path),
        runtime_version="1.0.0",
        comsol_version="6.2",
        backend_version="spawn-rpc-1",
        builder_id="bearing.builder",
        builder_capability="bearing.build",
        builder_version="1.0.0",
        extension_versions={"bearing.builder": "1.0.0"},
        input_summary={},
        input_sha256="b" * 64,
        model_summary={},
        model_sha256="a" * 64,
        provenance=provenance,
    )
    checkpoint_path.write_text(checkpoint.model_dump_json(), encoding="utf-8")

    assert _model_id_for_checkpoint(str(checkpoint_path)) == "m8-bearing-stable"


class FakeObservableDriver:
    def __init__(self, artifact: Path | None = None) -> None:
        self.artifact = artifact
        self.requests: list[TurnRequest] = []

    async def run(self, request, control, emit):
        self.requests.append(request)
        load = (
            1
            if request.current_specification is None
            else request.current_specification["load"] + 1
        )
        specification = {"family": "cylindrical_roller", "load": load}
        await emit(
            V2EventKind.SPECIFICATION,
            "intake",
            "passed",
            "fake.intake",
            "validated",
            {"specification": specification, "provenance": {"load": "explicit"}},
        )
        await emit(
            V2EventKind.RETRIEVAL,
            "retrieve",
            "passed",
            "fake.memory",
            "one compatible record",
            {"record_ids": ["verified-1"]},
        )
        await emit(
            V2EventKind.PLAN,
            "plan",
            "passed",
            "fake.planner",
            "deterministic route",
            {"plan": {"route": "deterministic_rebuild", "full_model_rewrite": False}},
        )
        await emit(
            V2EventKind.BUDGET,
            "llm",
            "recorded",
            "fake.gateway",
            "usage",
            {"llm_total_tokens": 20, "max_actions": 4},
        )
        await emit(
            V2EventKind.BUDGET,
            "llm",
            "recorded",
            "fake.gateway",
            "second usage",
            {
                "llm_prompt_tokens": 7,
                "llm_completion_tokens": 3,
                "llm_total_tokens": 10,
                "request_id": "planner-request",
            },
        )
        await emit(
            V2EventKind.TOOL,
            "execute",
            "running",
            "fake.kernel",
            "bearing.workflow.execute",
            {"tool": "bearing.workflow.execute"},
        )
        for phase in (
            "A_input_validation",
            "B_build",
            "C_solve",
            "D_results_audit",
        ):
            await emit(
                V2EventKind.COMSOL_STAGE,
                phase,
                "passed",
                "fake.comsol",
                phase,
                {"real_runtime": False},
            )
        await emit(
            V2EventKind.REPAIR,
            "repair",
            "recorded",
            "fake.repair",
            "no repair required",
            {"attempt": 0, "outcome": "not_needed"},
        )
        await emit(
            V2EventKind.AUDIT,
            "D_results_audit",
            "passed",
            "fake.physics_auditor",
            "strict gates passed",
            {"passed": True, "actual_load_n": load},
        )
        artifacts = []
        if self.artifact is not None:
            artifacts.append(
                {
                    "artifact_id": "summary",
                    "name": self.artifact.name,
                    "uri": str(self.artifact),
                    "media_type": "application/json",
                    "sha256": hashlib.sha256(self.artifact.read_bytes()).hexdigest(),
                    "stage": "D_results_audit",
                }
            )
        return TurnResult(
            specification=specification,
            checkpoint=f"checkpoint-B-{load}",
            manifest={"status": "completed"},
            artifacts=artifacts,
        )


class PausableDriver:
    def __init__(self) -> None:
        self.ready = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, request, control, emit):
        self.ready.set()
        await self.release.wait()
        await emit(
            V2EventKind.SPECIFICATION,
            "intake",
            "passed",
            "fake.intake",
            "safe point",
            {"specification": {"load": 1}},
        )
        return TurnResult(specification={"load": 1})


class CancellableDriver:
    async def run(self, request, control: RunControl, emit):
        while not control.cancellation.cancelled:
            await asyncio.sleep(0.001)
        control.report_termination(True)
        control.cancellation.raise_if_cancelled()
        raise AssertionError("unreachable")


class UnconfirmedCancellableDriver:
    async def run(self, request, control: RunControl, emit):
        while not control.cancellation.cancelled:
            await asyncio.sleep(0.001)
        control.cancellation.raise_if_cancelled()
        raise AssertionError("unreachable")


class TerminalStageAfterCancelDriver:
    async def run(self, request, control: RunControl, emit):
        while not control.cancellation.cancelled:
            await asyncio.sleep(0.001)
        control.report_termination(True)
        await emit(
            V2EventKind.COMSOL_STAGE,
            "C_solve",
            "cancelled",
            "fake.process_worker",
            "worker terminated",
            {"termination_confirmed": True},
        )
        control.cancellation.raise_if_cancelled()
        raise AssertionError("unreachable")


class FailingDriver:
    async def run(self, request, control, emit):
        await emit(
            V2EventKind.COMSOL_STAGE,
            "B_build",
            "passed",
            "fake.comsol",
            "model configured",
            {"checkpoint": "B"},
        )
        await emit(
            V2EventKind.COMSOL_STAGE,
            "C_solve",
            "failed",
            "fake.comsol",
            "non-convergence",
            {"code": "NON_CONVERGENCE"},
        )
        await emit(
            V2EventKind.REPAIR,
            "repair",
            "failed",
            "fake.repair",
            "solver strategy exhausted",
            {"attempt": 2, "rolled_back": True},
        )
        await emit(
            V2EventKind.FAILURE,
            "C_solve",
            "failed",
            "fake.comsol",
            "target step did not converge",
            {
                "error_class": "solve_or_convergence_error",
                "code": "NON_CONVERGENCE",
                "message": "target step did not converge",
                "stage": "C_solve",
                "retryable": False,
                "termination_confirmed": True,
                "evidence": {"last_parameter_step": 0.5},
            },
        )
        raise RuntimeError("target step did not converge")


class AlwaysFailingSessionStore:
    def load(self):
        return []

    def save(self, snapshot, events):
        raise OSError(28, "No space left on device")


async def _collect(manager: V2SessionManager, session_id: str):
    return [event async for event in manager.events(session_id)]


@pytest.mark.asyncio
async def test_v2_event_stream_keeps_all_evidence_gates_distinct(tmp_path):
    artifact = tmp_path / "audit.json"
    artifact.write_text('{"passed": true}', encoding="utf-8")
    manager = V2SessionManager(FakeObservableDriver(artifact))

    created = await manager.create("complete bearing", mode="live")
    events = await _collect(manager, created["session_id"])
    snapshot = manager.snapshot(created["session_id"])
    replayed = [
        event async for event in manager.events(created["session_id"], after=5)
    ]

    expected = set(V2EventKind) - {V2EventKind.FAILURE}
    assert {event.kind for event in events} >= expected
    assert replayed == events[5:]
    assert snapshot["status"] == "completed"
    assert snapshot["verification_level"] == "physical_audit_passed"
    assert {name: gate["state"] for name, gate in snapshot["gates"].items()} == {
        "static_validation": "passed",
        "model_build": "passed",
        "solve": "passed",
        "physical_audit": "passed",
    }
    assert snapshot["budget"]["llm_total_tokens"] == 30
    assert len(snapshot["budget"]["llm_requests"]) == 2
    item, path = manager.artifact(created["session_id"], "summary")
    assert item.sha256 == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert path == artifact
    json.dumps([event.model_dump(mode="json") for event in events])


def test_projection_distinguishes_preview_acceptance_from_strict_verification() -> None:
    snapshot = new_snapshot("preview-session")
    strict = V2Event(
        sequence=1,
        session_id=snapshot.session_id,
        turn_id="turn-preview",
        kind=V2EventKind.AUDIT,
        phase="D_results_audit",
        status="failed",
        source="bearing.physics.auditor",
        data={
            "kind": "bearing_strict_physics",
            "passed": False,
            "selected_for_acceptance": False,
        },
    )
    preview = V2Event(
        sequence=2,
        session_id=snapshot.session_id,
        turn_id="turn-preview",
        kind=V2EventKind.AUDIT,
        phase="D_results_audit",
        status="passed",
        source="bearing.engineering-preview.auditor",
        data={
            "kind": "bearing_engineering_stress_preview",
            "passed": True,
            "selected_for_acceptance": True,
        },
    )

    apply_event(snapshot, strict)
    apply_event(snapshot, preview)

    assert snapshot.verification_level.value == "engineering_preview_accepted"
    assert snapshot.gates["physical_audit"].state.value == "passed"
    assert snapshot.gates["physical_audit"].source == (
        "bearing.engineering-preview.auditor"
    )


@pytest.mark.asyncio
async def test_v2_pause_is_effective_only_at_safe_point_and_can_resume():
    driver = PausableDriver()
    manager = V2SessionManager(driver)
    created = await manager.create("pause me")
    await driver.ready.wait()

    requested = await manager.pause(created["session_id"])
    assert requested["status"] == "pause_requested"
    driver.release.set()
    for _ in range(100):
        if manager.snapshot(created["session_id"])["status"] == "paused":
            break
        await asyncio.sleep(0.001)
    assert manager.snapshot(created["session_id"])["status"] == "paused"
    await manager.resume(created["session_id"])
    await _collect(manager, created["session_id"])
    assert manager.snapshot(created["session_id"])["status"] == "completed"


@pytest.mark.asyncio
async def test_v2_cancel_reports_confirmed_terminal_state():
    manager = V2SessionManager(CancellableDriver())
    created = await manager.create("cancel me")

    cancelling = await manager.cancel(created["session_id"], "test cancellation")
    assert cancelling["status"] == "cancelling"
    await _collect(manager, created["session_id"])
    snapshot = manager.snapshot(created["session_id"])
    assert snapshot["status"] == "cancelled"
    assert snapshot["failure"]["error_class"] == "cancelled"
    assert snapshot["failure"]["termination_confirmed"] is True


@pytest.mark.asyncio
async def test_v2_cancel_does_not_invent_backend_termination_confirmation():
    manager = V2SessionManager(UnconfirmedCancellableDriver())
    created = await manager.create("cancel without backend truth")
    await manager.cancel(created["session_id"], "unconfirmed cancellation")
    await _collect(manager, created["session_id"])

    snapshot = manager.snapshot(created["session_id"])
    assert snapshot["status"] == "cancelled"
    assert snapshot["failure"]["termination_confirmed"] is None


@pytest.mark.asyncio
async def test_v2_cancel_keeps_terminal_runtime_stage_evidence():
    manager = V2SessionManager(TerminalStageAfterCancelDriver())
    created = await manager.create("cancel with terminal stage")
    await manager.cancel(created["session_id"], "confirmed process kill")
    events = await _collect(manager, created["session_id"])

    terminal = next(
        event
        for event in events
        if event.kind == V2EventKind.COMSOL_STAGE and event.status == "cancelled"
    )
    snapshot = manager.snapshot(created["session_id"])
    assert terminal.data["termination_confirmed"] is True
    assert snapshot["gates"]["solve"]["state"] == "cancelled"
    assert snapshot["failure"]["termination_confirmed"] is True


@pytest.mark.asyncio
async def test_v2_failure_preserves_model_solve_and_audit_truth():
    manager = V2SessionManager(FailingDriver())
    created = await manager.create("fail solve")
    await _collect(manager, created["session_id"])
    snapshot = manager.snapshot(created["session_id"])

    assert snapshot["status"] == "failed"
    assert snapshot["gates"]["model_build"]["state"] == "passed"
    assert snapshot["gates"]["solve"]["state"] == "failed"
    assert snapshot["gates"]["physical_audit"]["state"] == "pending"
    assert snapshot["failure"]["code"] == "NON_CONVERGENCE"
    assert snapshot["repairs"][0]["rolled_back"] is True


@pytest.mark.asyncio
async def test_session_store_failure_does_not_replace_runtime_failure_truth():
    manager = V2SessionManager(FailingDriver(), store=AlwaysFailingSessionStore())
    created = await manager.create("fail solve with degraded storage")
    await _collect(manager, created["session_id"])
    snapshot = manager.snapshot(created["session_id"])

    assert snapshot["status"] == "failed"
    assert snapshot["failure"]["code"] == "NON_CONVERGENCE"
    assert snapshot["failure"]["error_class"] == "solve_or_convergence_error"
    assert snapshot["budget"]["session_store"]["degraded"] is True
    assert snapshot["budget"]["session_store"]["error_type"] == "OSError"


@pytest.mark.asyncio
async def test_v2_multi_turn_carries_specification_and_checkpoint():
    driver = FakeObservableDriver()
    manager = V2SessionManager(driver)
    first = await manager.create("load 1")
    await _collect(manager, first["session_id"])
    second = await manager.submit_turn(first["session_id"], "increase load")
    await _collect(manager, second["session_id"],)

    assert driver.requests[1].current_specification["load"] == 1
    assert driver.requests[1].checkpoint == "checkpoint-B-1"
    snapshot = manager.snapshot(first["session_id"])
    assert snapshot["turn_count"] == 2
    assert snapshot["specification"]["load"] == 2
    assert snapshot["previous_specification"]["load"] == 1


@pytest.mark.asyncio
async def test_v2_completed_session_and_events_survive_manager_restart(tmp_path):
    store = JsonSessionStore(tmp_path / "sessions")
    first = V2SessionManager(FakeObservableDriver(), store=store)
    created = await first.create("persist me")
    original = await _collect(first, created["session_id"])

    restarted = V2SessionManager(FakeObservableDriver(), store=store)
    snapshot = restarted.snapshot(created["session_id"])
    replayed = [event async for event in restarted.events(created["session_id"], after=3)]

    assert snapshot["status"] == "completed"
    assert snapshot["verification_level"] == "physical_audit_passed"
    assert replayed == original[3:]
    assert snapshot["event_count"] == len(original)


def test_v2_restart_marks_inflight_session_failed_without_fake_resume(tmp_path):
    store = JsonSessionStore(tmp_path / "sessions")
    session_id = "restart-interrupted"
    snapshot = new_snapshot(session_id)
    event = V2Event(
        sequence=1,
        session_id=session_id,
        turn_id="turn-1",
        kind=V2EventKind.SESSION,
        phase="intake",
        status="running",
        source="test",
    )
    apply_event(snapshot, event)
    store.save(snapshot, [event])

    restarted = V2SessionManager(FakeObservableDriver(), store=store)
    recovered = restarted.snapshot(session_id)

    assert recovered["status"] == "failed"
    assert recovered["failure"]["code"] == "SERVICE_RESTART_INTERRUPTED"
    assert recovered["failure"]["termination_confirmed"] is None
    payload = json.loads((store.root / f"{session_id}.json").read_text(encoding="utf-8"))
    assert [item["sequence"] for item in payload["events"]] == [1, 2, 3]


def test_v2_fastapi_routes_stream_and_download(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import comsol_agent.web.app as web_app

    artifact = tmp_path / "summary.json"
    artifact.write_text('{"audit": "passed"}', encoding="utf-8")
    monkeypatch.setattr(
        web_app,
        "v2_manager",
        V2SessionManager(FakeObservableDriver(artifact)),
    )
    with TestClient(web_app.app) as client:
        created = client.post(
            "/api/v2/sessions",
            json={"requirement": "complete bearing", "mode": "live"},
        )
        assert created.status_code == 202
        session_id = created.json()["session_id"]
        stream = client.get(f"/api/v2/sessions/{session_id}/events")
        assert stream.status_code == 200
        assert "event: comsol_stage" in stream.text
        snapshot = client.get(f"/api/v2/sessions/{session_id}").json()
        assert snapshot["verification_level"] == "physical_audit_passed"
        download = client.get(f"/api/v2/sessions/{session_id}/artifacts/summary")
        assert download.status_code == 200
        assert download.content == artifact.read_bytes()


@pytest.mark.asyncio
async def test_v2_cli_renders_shared_events_and_evidence_table():
    manager = V2SessionManager(FakeObservableDriver())
    created = await manager.create("render")
    events = await _collect(manager, created["session_id"])
    output = Console(record=True, width=120)
    for event in events:
        render_event(event, output=output)
    render_snapshot(manager.snapshot(created["session_id"]), output=output)
    rendered = output.export_text()
    assert "[COMSOL] C_solve: passed" in rendered
    assert "physical_audit" in rendered
    assert "physical_audit_passed" in rendered


def test_bearing_driver_preserves_runtime_artifact_stage_and_native_plot(tmp_path):
    plot = tmp_path / "native.png"
    plot.write_bytes(b"native-plot")
    manifest = SimpleNamespace(
        action_records=[
            SimpleNamespace(
                observation=SimpleNamespace(
                    data={
                        "runtime": {
                            "artifacts": [
                                {"path": "/run/checkpoint.mph", "stage": "B_build"},
                                {"path": "/run/solved.mph", "stage": "D_results_audit"},
                            ]
                        }
                    }
                )
            )
        ],
        audits=[
            {
                "kind": "bearing_strict_physics",
                "evidence": {"native_plot_evidence": {"filepath": str(plot)}},
            }
        ],
    )

    index = _runtime_artifact_index(manifest)
    native = _native_plot_artifact(manifest)

    assert index["/run/checkpoint.mph"]["stage"] == "B_build"
    assert index["/run/solved.mph"]["stage"] == "D_results_audit"
    assert native is not None
    assert native["media_type"] == "image/png"
    assert native["stage"] == "D_results_audit"
