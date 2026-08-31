"""Concurrent V2 sessions, cooperative controls, replayable events, and artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from comsol_agent.v2.kernel import CancellationToken

from .contracts import (
    ArtifactView,
    EvidenceGate,
    FailureView,
    SessionSnapshot,
    SessionStatus,
    V2Event,
    V2EventKind,
)
from .projection import apply_event, new_snapshot, public_snapshot

Emit = Callable[[V2EventKind, str, str, str, str, dict[str, Any]], Awaitable[V2Event]]


@dataclass(frozen=True, slots=True)
class TurnRequest:
    session_id: str
    turn_id: str
    requirement: str
    mode: str
    current_specification: dict[str, Any] | None
    checkpoint: str | None


@dataclass(slots=True)
class TurnResult:
    specification: dict[str, Any] | None = None
    checkpoint: str | None = None
    manifest: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)


class V2RunDriver(Protocol):
    async def run(
        self,
        request: TurnRequest,
        control: RunControl,
        emit: Emit,
    ) -> TurnResult: ...


class SessionStore(Protocol):
    """Durable boundary for replayable V2 session facts."""

    def load(self) -> list[tuple[SessionSnapshot, list[V2Event]]]: ...

    def save(self, snapshot: SessionSnapshot, events: list[V2Event]) -> None: ...


class JsonSessionStore:
    """Atomic JSON store; one independently recoverable file per session."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def load(self) -> list[tuple[SessionSnapshot, list[V2Event]]]:
        if not self.root.exists():
            return []
        loaded: list[tuple[SessionSnapshot, list[V2Event]]] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                snapshot = SessionSnapshot.model_validate(payload["snapshot"])
                events = [V2Event.model_validate(item) for item in payload["events"]]
                if any(
                    event.session_id != snapshot.session_id
                    or event.sequence != index
                    for index, event in enumerate(events, start=1)
                ):
                    raise ValueError("session event sequence or owner mismatch")
                loaded.append((snapshot, events))
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                # A corrupt session is isolated; it cannot poison other recoverable sessions.
                continue
        return loaded

    def save(self, snapshot: SessionSnapshot, events: list[V2Event]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{snapshot.session_id}.json"
        temporary = self.root / f".{snapshot.session_id}.{uuid4().hex}.tmp"
        payload = {
            "schema_version": "1.0.0",
            "snapshot": snapshot.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in events],
        }
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


class RunControl:
    """Pause at declared safe points; cancellation is end-to-end and cooperative."""

    def __init__(self) -> None:
        self.cancellation = CancellationToken()
        self._resume = asyncio.Event()
        self._resume.set()
        self.pause_requested = False
        self.paused = False
        self.termination_confirmed: bool | None = None

    def request_pause(self) -> None:
        self.pause_requested = True
        self._resume.clear()

    def resume(self) -> None:
        self.pause_requested = False
        self.paused = False
        self._resume.set()

    def cancel(self, reason: str) -> None:
        self.cancellation.cancel(reason)
        self._resume.set()

    def report_termination(self, confirmed: bool | None) -> None:
        if confirmed is not None:
            self.termination_confirmed = confirmed

    async def safe_point(self) -> bool:
        self.cancellation.raise_if_cancelled()
        if not self.pause_requested:
            return False
        self.paused = True
        await self._resume.wait()
        self.cancellation.raise_if_cancelled()
        self.paused = False
        return True


@dataclass(slots=True)
class _Session:
    snapshot: SessionSnapshot
    events: list[V2Event] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    control: RunControl | None = None
    task: asyncio.Task[None] | None = None


class V2SessionManager:
    def __init__(self, driver: V2RunDriver, *, store: SessionStore | None = None) -> None:
        self.driver = driver
        self._sessions: dict[str, _Session] = {}
        self.store = store
        if store is not None:
            for snapshot, events in store.load():
                session = _Session(snapshot=snapshot, events=events)
                self._sessions[snapshot.session_id] = session
                if snapshot.status in {
                    SessionStatus.RUNNING,
                    SessionStatus.PAUSE_REQUESTED,
                    SessionStatus.PAUSED,
                    SessionStatus.CANCELLING,
                }:
                    self._mark_interrupted_by_restart(session)

    async def create(self, requirement: str, *, mode: str = "live") -> dict[str, Any]:
        if not requirement.strip():
            raise ValueError("requirement must not be empty")
        if mode not in {"live", "plan_only"}:
            raise ValueError("mode must be live or plan_only")
        session_id = uuid4().hex
        session = _Session(snapshot=new_snapshot(session_id))
        self._sessions[session_id] = session
        self._persist(session)
        await self._start_turn(session, requirement, mode)
        return public_snapshot(session.snapshot)

    async def submit_turn(
        self, session_id: str, requirement: str, *, mode: str = "live"
    ) -> dict[str, Any]:
        session = self._get(session_id)
        if not requirement.strip():
            raise ValueError("requirement must not be empty")
        if session.task is not None and not session.task.done():
            raise RuntimeError("session already has an active turn")
        await self._start_turn(session, requirement, mode)
        return public_snapshot(session.snapshot)

    def snapshot(self, session_id: str) -> dict[str, Any]:
        return public_snapshot(self._get(session_id).snapshot)

    async def pause(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        if session.control is None or session.task is None or session.task.done():
            raise RuntimeError("session has no active run to pause")
        session.control.request_pause()
        await self._emit(
            session,
            V2EventKind.SESSION,
            "control",
            SessionStatus.PAUSE_REQUESTED,
            "user",
            "Pause requested; it becomes effective at the next safe checkpoint.",
            {"safe_checkpoint_required": True},
        )
        return public_snapshot(session.snapshot)

    async def resume(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        if session.control is None or not (
            session.control.pause_requested or session.control.paused
        ):
            raise RuntimeError("session is not paused")
        session.control.resume()
        await self._emit(
            session,
            V2EventKind.SESSION,
            "control",
            SessionStatus.RUNNING,
            "user",
            "Run resumed.",
            {},
        )
        return public_snapshot(session.snapshot)

    async def cancel(self, session_id: str, reason: str = "cancelled by user") -> dict[str, Any]:
        session = self._get(session_id)
        if session.control is None or session.task is None or session.task.done():
            raise RuntimeError("session has no active run to cancel")
        session.control.cancel(reason)
        await self._emit(
            session,
            V2EventKind.SESSION,
            "control",
            SessionStatus.CANCELLING,
            "user",
            "Cancellation requested; termination is not claimed until confirmed.",
            {"reason": reason, "termination_confirmed": None},
        )
        return public_snapshot(session.snapshot)

    async def events(
        self, session_id: str, *, after: int = 0
    ) -> AsyncIterator[V2Event]:
        session = self._get(session_id)
        cursor = max(0, after)
        while True:
            async with session.condition:
                await session.condition.wait_for(
                    lambda: len(session.events) > cursor
                    or self._is_terminal(session)
                )
                pending = session.events[cursor:]
                cursor = len(session.events)
            for event in pending:
                yield event
            if self._is_terminal(session) and cursor == len(session.events):
                return

    def artifact(self, session_id: str, artifact_id: str) -> tuple[ArtifactView, Path]:
        session = self._get(session_id)
        item = next(
            (
                artifact
                for artifact in session.snapshot.artifacts
                if artifact.artifact_id == artifact_id
            ),
            None,
        )
        if item is None:
            raise KeyError(artifact_id)
        path = Path(item.uri).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if item.sha256 and _sha256(path) != item.sha256:
            raise RuntimeError("artifact hash no longer matches recorded evidence")
        return item, path

    async def _start_turn(self, session: _Session, requirement: str, mode: str) -> None:
        turn_id = uuid4().hex
        session.snapshot.turn_count += 1
        session.snapshot.failure = None
        session.snapshot.repairs = []
        session.snapshot.plan = None
        session.snapshot.previous_specification = session.snapshot.specification
        session.snapshot.gates = {
            name: EvidenceGate()
            for name in ("static_validation", "model_build", "solve", "physical_audit")
        }
        session.control = RunControl()
        request = TurnRequest(
            session_id=session.snapshot.session_id,
            turn_id=turn_id,
            requirement=requirement,
            mode=mode,
            current_specification=session.snapshot.specification,
            checkpoint=session.snapshot.checkpoint,
        )
        session.task = asyncio.create_task(self._run_turn(session, request))
        self._persist(session)
        await asyncio.sleep(0)

    async def _run_turn(self, session: _Session, request: TurnRequest) -> None:
        assert session.control is not None
        await self._emit(
            session,
            V2EventKind.SESSION,
            "intake",
            SessionStatus.RUNNING,
            "v2_session",
            "Turn started.",
            {"mode": request.mode, "requirement": request.requirement},
            turn_id=request.turn_id,
        )

        async def emit(
            kind: V2EventKind,
            phase: str,
            status: str,
            source: str,
            message: str,
            data: dict[str, Any],
        ) -> V2Event:
            terminal_runtime_evidence = bool(
                session.control.cancellation.cancelled
                and kind == V2EventKind.COMSOL_STAGE
                and status in {"cancelled", "timed_out", "failed"}
            )
            if kind != V2EventKind.SESSION and not terminal_runtime_evidence:
                if session.control.pause_requested:
                    await self._emit(
                        session,
                        V2EventKind.SESSION,
                        "control",
                        SessionStatus.PAUSED,
                        "v2_session",
                        "Run paused at a safe checkpoint.",
                        {"safe_checkpoint": phase},
                        turn_id=request.turn_id,
                    )
                    await session.control.safe_point()
                    await self._emit(
                        session,
                        V2EventKind.SESSION,
                        "control",
                        SessionStatus.RUNNING,
                        "v2_session",
                        "Safe-checkpoint pause ended.",
                        {},
                        turn_id=request.turn_id,
                    )
                else:
                    await session.control.safe_point()
            return await self._emit(
                session,
                kind,
                phase,
                status,
                source,
                message,
                data,
                turn_id=request.turn_id,
            )

        try:
            result = await self.driver.run(request, session.control, emit)
            if result.specification is not None:
                session.snapshot.specification = result.specification
            if result.checkpoint:
                session.snapshot.checkpoint = result.checkpoint
            for raw in result.artifacts:
                await emit(
                    V2EventKind.ARTIFACT,
                    str(raw.get("stage") or "artifact"),
                    "available",
                    "run_manifest",
                    str(raw.get("name") or "Artifact available"),
                    _artifact_payload(session.snapshot.session_id, raw),
                )
            await emit(
                V2EventKind.SESSION,
                "complete",
                SessionStatus.COMPLETED,
                "v2_session",
                "Turn completed; inspect the independent evidence gates for verification level.",
                {"manifest": result.manifest},
            )
        except Exception as exc:
            cancelled = session.control.cancellation.cancelled
            failure = session.snapshot.failure or FailureView(
                error_class="cancelled" if cancelled else "adapter_error",
                message=session.control.cancellation.reason if cancelled else str(exc),
                stage="control" if cancelled else "adapter",
                retryable=False,
                termination_confirmed=(
                    session.control.termination_confirmed if cancelled else None
                ),
                evidence={"exception_type": type(exc).__name__},
            )
            if session.snapshot.failure is None:
                await self._emit(
                    session,
                    V2EventKind.FAILURE,
                    failure.stage or "adapter",
                    "failed",
                    "v2_session",
                    failure.message,
                    failure.model_dump(mode="json"),
                    turn_id=request.turn_id,
                )
            await self._emit(
                session,
                V2EventKind.SESSION,
                failure.stage or "adapter",
                SessionStatus.CANCELLED if cancelled else SessionStatus.FAILED,
                "v2_session",
                failure.message,
                {"termination_confirmed": failure.termination_confirmed},
                turn_id=request.turn_id,
            )

    async def _emit(
        self,
        session: _Session,
        kind: V2EventKind,
        phase: str,
        status: str,
        source: str,
        message: str,
        data: dict[str, Any],
        *,
        turn_id: str | None = None,
    ) -> V2Event:
        async with session.lock:
            event = V2Event(
                sequence=len(session.events) + 1,
                session_id=session.snapshot.session_id,
                turn_id=turn_id or session.snapshot.active_turn_id or "pending",
                kind=kind,
                phase=phase,
                status=str(status),
                source=source,
                message=message,
                data=data,
            )
            session.events.append(event)
            apply_event(session.snapshot, event)
            self._persist(session)
        async with session.condition:
            session.condition.notify_all()
        return event

    @staticmethod
    def _is_terminal(session: _Session) -> bool:
        return session.snapshot.status in {
            SessionStatus.CANCELLED,
            SessionStatus.FAILED,
            SessionStatus.COMPLETED,
        } and (session.task is None or session.task.done())

    def _persist(self, session: _Session) -> None:
        if self.store is not None:
            try:
                self.store.save(session.snapshot, session.events)
            except OSError as exc:
                # Storage is an independent evidence gate. Preserve the runtime/
                # physics truth already projected in memory instead of replacing
                # it with an adapter failure. Restart recovery will still fail
                # honestly when the latest state was not durable.
                session.snapshot.budget["session_store"] = {
                    "degraded": True,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "failed_event_sequence": session.snapshot.event_count,
                }

    def _mark_interrupted_by_restart(self, session: _Session) -> None:
        turn_id = session.snapshot.active_turn_id or "recovery"
        failure = V2Event(
            sequence=len(session.events) + 1,
            session_id=session.snapshot.session_id,
            turn_id=turn_id,
            kind=V2EventKind.FAILURE,
            phase="service_restart",
            status="failed",
            source="v2_session_store",
            message="Active turn was interrupted by service restart and was not resumed.",
            data={
                "error_class": "runtime_unavailable",
                "code": "SERVICE_RESTART_INTERRUPTED",
                "message": "Active turn was interrupted by service restart and was not resumed.",
                "stage": "service_restart",
                "retryable": True,
                "termination_confirmed": None,
                "evidence": {"recovered_event_count": len(session.events)},
            },
        )
        session.events.append(failure)
        apply_event(session.snapshot, failure)
        terminal = V2Event(
            sequence=len(session.events) + 1,
            session_id=session.snapshot.session_id,
            turn_id=turn_id,
            kind=V2EventKind.SESSION,
            phase="service_restart",
            status=SessionStatus.FAILED,
            source="v2_session_store",
            message="Recovered session is terminal; submit a new turn to retry safely.",
            data={"termination_confirmed": None, "automatic_resume": False},
        )
        session.events.append(terminal)
        apply_event(session.snapshot, terminal)
        self._persist(session)

    def _get(self, session_id: str) -> _Session:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"unknown V2 session: {session_id}") from exc


def _artifact_payload(session_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    uri = str(raw.get("uri") or raw.get("path") or "")
    digest = str(raw.get("sha256") or "") or None
    artifact_id = str(raw.get("artifact_id") or digest or uuid4().hex)
    path = Path(uri)
    return {
        "artifact_id": artifact_id,
        "name": str(raw.get("name") or path.name or artifact_id),
        "uri": uri,
        "media_type": raw.get("media_type"),
        "sha256": digest,
        "stage": raw.get("stage"),
        "size_bytes": raw.get("size_bytes") if raw.get("size_bytes") is not None else (
            path.stat().st_size if path.is_file() else None
        ),
        "download_url": f"/api/v2/sessions/{session_id}/artifacts/{artifact_id}",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
