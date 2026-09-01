"""Lifecycle, locking, staged recovery, and cleanup for V2 COMSOL runs."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from comsol_agent.v2.kernel import CancellationToken

from .artifacts import ArtifactStore, canonical_sha256
from .backend import BackendWorker, ComsolBackend, SnapshotBindingError
from .contracts import (
    CancelRunRequest,
    Checkpoint,
    CheckpointCreateRequest,
    CheckpointRestoreRequest,
    ErrorClass,
    EvaluateRequest,
    ExportRequest,
    FailureInspectRequest,
    ModelActionRequest,
    ModelCloseRequest,
    ModelCreateRequest,
    ModelLoadRequest,
    ModelRequestBase,
    ModelSaveRequest,
    ParameterPatchRequest,
    RegisteredExecutionRequest,
    RuntimeFailure,
    RuntimeOperation,
    RuntimeProvenance,
    RuntimeResult,
    RuntimeRunRequest,
    RuntimeStage,
    RuntimeStageEvent,
    SessionStatus,
    StageRecord,
    StageState,
    utc_now,
)
from .errors import (
    CheckpointCompatibilityError,
    PhysicalAuditError,
    ResourceLeaseError,
    WorkerTimeoutError,
    classify_backend_error,
)

RUNTIME_VERSION = "0.5.0"


class ComsolRuntime:
    """One long-lived COMSOL client with serialized model and resource leases."""

    def __init__(
        self,
        *,
        backend: ComsolBackend,
        artifacts: ArtifactStore,
        worker: BackendWorker,
        resource_capacity: int = 1,
        stage_sink: Callable[[RuntimeStageEvent], None | Awaitable[None]] | None = None,
    ) -> None:
        if resource_capacity < 1:
            raise ValueError("resource_capacity must be positive")
        self.backend = backend
        self.artifacts = artifacts
        self.worker = worker
        self._resource = asyncio.Semaphore(resource_capacity)
        self._model_locks: dict[str, asyncio.Lock] = {}
        self._model_lock_guard = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._started = False
        self._active_resource_leases = 0
        self._models: set[str] = set()
        self._running: dict[str, CancellationToken] = {}
        self._failures: dict[str, RuntimeFailure] = {}
        self._stage_sink = stage_sink

    @property
    def active_resource_leases(self) -> int:
        return self._active_resource_leases

    def is_model_locked(self, model_id: str) -> bool:
        lock = self._model_locks.get(model_id)
        return bool(lock and lock.locked())

    async def start(self) -> None:
        async with self._session_lock:
            if not self._started:
                await self.backend.start()
                self._started = True

    async def stop(self) -> None:
        async with self._session_lock:
            if self._started:
                await self.backend.stop()
                self._models.clear()
                self._started = False

    async def status(self) -> SessionStatus:
        backend_status = await self.backend.status() if self._started else {}
        return SessionStatus(
            started=self._started,
            healthy=self._started and not self.worker.quarantined,
            quarantined=self.worker.quarantined,
            active_models=sorted(self._models),
            active_resource_leases=self._active_resource_leases,
            capabilities={
                **self.worker.capabilities.__dict__,
                "single_client_per_process": True,
                "backend_status": backend_status,
            },
        )

    async def _model_lock(self, model_id: str) -> asyncio.Lock:
        async with self._model_lock_guard:
            return self._model_locks.setdefault(model_id, asyncio.Lock())

    async def _acquire_cancellable(
        self,
        acquire: Callable[[], Awaitable[bool]],
        *,
        cancellation: CancellationToken,
        deadline: float,
        label: str,
    ) -> None:
        while True:
            cancellation.raise_if_cancelled()
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise WorkerTimeoutError(
                    f"timed out while waiting for {label}", termination_confirmed=True
                )
            try:
                await asyncio.wait_for(acquire(), timeout=min(0.01, remaining))
                return
            except TimeoutError:
                continue

    @asynccontextmanager
    async def _execution_slot(
        self,
        lock: asyncio.Lock,
        *,
        cancellation: CancellationToken,
        timeout_seconds: float,
    ) -> AsyncIterator[None]:
        deadline = monotonic() + timeout_seconds
        lock_acquired = False
        resource_acquired = False
        try:
            await self._acquire_cancellable(
                lock.acquire,
                cancellation=cancellation,
                deadline=deadline,
                label="model lock",
            )
            lock_acquired = True
            await self._acquire_cancellable(
                self._resource.acquire,
                cancellation=cancellation,
                deadline=deadline,
                label="COMSOL resource lease",
            )
            resource_acquired = True
            self._active_resource_leases += 1
            if self.worker.quarantined:
                raise ResourceLeaseError("COMSOL worker is quarantined")
            yield
        finally:
            if resource_acquired:
                self._active_resource_leases -= 1
                self._resource.release()
            if lock_acquired:
                lock.release()

    async def _call(
        self,
        operation: RuntimeOperation,
        call: Callable[[], Awaitable[Any]],
        *,
        timeout_seconds: float,
        cancellation: CancellationToken,
    ) -> Any:
        return await self.worker.execute(
            operation,
            call,
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
        )

    def _provenance(self, run_id: str, model_id: str, source: str) -> RuntimeProvenance:
        capabilities = self.backend.capabilities
        return RuntimeProvenance(
            run_id=run_id,
            model_id=model_id,
            backend=capabilities.backend,
            backend_version=capabilities.backend_version,
            comsol_version=capabilities.comsol_version,
            source=source,
        )

    async def run(
        self, request: RuntimeRunRequest, cancellation: CancellationToken
    ) -> RuntimeResult:
        """Execute A-D, retaining a compatible B checkpoint on later failure."""
        records = {stage: StageRecord(stage=stage) for stage in RuntimeStage}
        artifacts = []
        checkpoint: Checkpoint | None = None
        physical_name = f"{request.model_id}-{request.run_id}"
        lock = await self._model_lock(request.model_id)
        if request.run_id in self._running:
            failure = classify_backend_error(
                ResourceLeaseError(f"run_id already active: {request.run_id}"),
                RuntimeStage.INPUT_VALIDATION,
            )
            return RuntimeResult(
                run_id=request.run_id,
                model_id=request.model_id,
                success=False,
                status="failed",
                stage_records=records,
                failure=failure,
            )
        self._running[request.run_id] = cancellation
        cleanup_complete = True
        model_open = False
        try:
            async with self._execution_slot(
                lock,
                cancellation=cancellation,
                timeout_seconds=request.timeout_seconds,
            ):
                await self.start()
                if request.resume_checkpoint:
                    await self._record(request, records, self._skipped(
                        RuntimeStage.INPUT_VALIDATION, "validated by compatible checkpoint"
                    ))
                    await self._record(request, records, self._skipped(
                        RuntimeStage.BUILD, "restored compatible B checkpoint"
                    ))
                    compatibility_request = request
                    if request.override_extension_id:
                        compatibility_request = request.model_copy(
                            update={
                                "parameters": request.previous_parameters,
                                "specification": request.previous_specification,
                                "resume_checkpoint": request.resume_checkpoint,
                            }
                        )
                    checkpoint = await self.restore_checkpoint(compatibility_request)
                    await self._call(
                        RuntimeOperation.RESTORE_CHECKPOINT,
                        lambda: self.backend.load_model(
                            physical_name, Path(checkpoint.artifact.path)
                        ),
                        timeout_seconds=request.timeout_seconds,
                        cancellation=cancellation,
                    )
                    model_open = True
                    if request.override_extension_id:
                        await self._call(
                            RuntimeOperation.EXECUTE_REGISTERED,
                            lambda: self.backend.execute_registered(
                                physical_name,
                                request.override_extension_id or "",
                                request.override_extension_version or "",
                                "deterministic_path",
                                request.override_extension_capability or "",
                                {
                                    "previous": request.previous_specification,
                                    "requested": request.specification,
                                },
                            ),
                            timeout_seconds=request.timeout_seconds,
                            cancellation=cancellation,
                        )
                else:
                    await self._record(request, records, self._running_record(
                        RuntimeStage.INPUT_VALIDATION
                    ))
                    cancellation.raise_if_cancelled()
                    execution_catalog = getattr(self.backend, "execution_catalog", None)
                    if (
                        execution_catalog is not None
                        and request.extension_versions != execution_catalog.versions
                    ):
                        raise SnapshotBindingError(
                            "request extension_versions do not match the pinned snapshot"
                        )
                    self.artifacts.run_directory(request.run_id, request.model_id)
                    await self._record(request, records, self._passed(
                        RuntimeStage.INPUT_VALIDATION,
                        {"input_sha256": self._input_hash(request)},
                    ))
                    await self._record(
                        request, records, self._running_record(RuntimeStage.BUILD)
                    )
                    await self._call(
                        RuntimeOperation.CREATE_MODEL,
                        lambda: self.backend.create_model(physical_name),
                        timeout_seconds=request.timeout_seconds,
                        cancellation=cancellation,
                    )
                    model_open = True
                    if request.parameters:
                        await self._call(
                            RuntimeOperation.APPLY_PARAMETERS,
                            lambda: self.backend.apply_parameters(
                                physical_name, request.parameters
                            ),
                            timeout_seconds=request.timeout_seconds,
                            cancellation=cancellation,
                        )
                    builder_detail = await self._call(
                        RuntimeOperation.EXECUTE_REGISTERED,
                        lambda: self.backend.execute_registered(
                            physical_name,
                            request.builder_id,
                            request.builder_version,
                            "builder",
                            request.builder_capability,
                            request.specification,
                        ),
                        timeout_seconds=request.timeout_seconds,
                        cancellation=cancellation,
                    )
                    build_detail = await self._call(
                        RuntimeOperation.BUILD,
                        lambda: self.backend.build(physical_name),
                        timeout_seconds=request.timeout_seconds,
                        cancellation=cancellation,
                    )
                    mesh_detail = await self._call(
                        RuntimeOperation.MESH,
                        lambda: self.backend.mesh(physical_name),
                        timeout_seconds=request.timeout_seconds,
                        cancellation=cancellation,
                    )
                    model_summary = {
                        "builder": builder_detail,
                        "build": build_detail,
                        "mesh": mesh_detail,
                    }
                    checkpoint = await self._create_checkpoint_for_model(
                        request=request,
                        physical_name=physical_name,
                        stage=RuntimeStage.BUILD,
                        model_summary=model_summary,
                        cancellation=cancellation,
                    )
                    artifacts.append(checkpoint.artifact)
                    await self._record(request, records, self._passed(
                        RuntimeStage.BUILD,
                        {"checkpoint_id": checkpoint.checkpoint_id},
                    ))

                if request.continuation_extension_id:
                    await self._call(
                        RuntimeOperation.EXECUTE_REGISTERED,
                        lambda: self.backend.execute_registered(
                            physical_name,
                            request.continuation_extension_id or "",
                            request.continuation_extension_version or "",
                            "deterministic_path",
                            request.continuation_extension_capability or "",
                            {
                                "spec": request.specification,
                                **request.continuation_options,
                            },
                        ),
                        timeout_seconds=request.timeout_seconds,
                        cancellation=cancellation,
                    )
                await self._record(request, records, self._running_record(RuntimeStage.SOLVE))
                solve_detail = await self._call(
                    RuntimeOperation.SOLVE,
                    lambda: self.backend.solve(physical_name),
                    timeout_seconds=request.timeout_seconds,
                    cancellation=cancellation,
                )
                await self._record(
                    request, records, self._passed(RuntimeStage.SOLVE, solve_detail)
                )

                await self._record(request, records, self._running_record(
                    RuntimeStage.RESULTS_AUDIT
                ))
                values = await self._call(
                    RuntimeOperation.EVALUATE,
                    lambda: self.backend.evaluate(physical_name, request.expressions),
                    timeout_seconds=request.timeout_seconds,
                    cancellation=cancellation,
                )
                export_path = self.artifacts.target(request.run_id, request.model_id, "results.csv")
                await self._call(
                    RuntimeOperation.EXPORT_RESULTS,
                    lambda: self.backend.export(physical_name, export_path),
                    timeout_seconds=request.timeout_seconds,
                    cancellation=cancellation,
                )
                artifacts.append(
                    self.artifacts.record(
                        export_path,
                        stage=RuntimeStage.RESULTS_AUDIT,
                        provenance=self._provenance(
                            request.run_id, request.model_id, "runtime:export"
                        ),
                        media_type="text/csv",
                    )
                )
                audit = await self._call(
                    RuntimeOperation.EVALUATE,
                    lambda: self.backend.audit(physical_name),
                    timeout_seconds=request.timeout_seconds,
                    cancellation=cancellation,
                )
                if not audit.get("passed", False):
                    raise PhysicalAuditError(str(audit.get("reason", "physical audit failed")))
                solved_path = self.artifacts.target(request.run_id, request.model_id, "solved.mph")
                await self._call(
                    RuntimeOperation.SAVE_MODEL,
                    lambda: self.backend.save_model(physical_name, solved_path),
                    timeout_seconds=request.timeout_seconds,
                    cancellation=cancellation,
                )
                artifacts.append(
                    self.artifacts.record(
                        solved_path,
                        stage=RuntimeStage.RESULTS_AUDIT,
                        provenance=self._provenance(
                            request.run_id, request.model_id, "runtime:solved_model"
                        ),
                        media_type="application/vnd.comsol.mph",
                    )
                )
                await self._record(request, records, self._passed(
                    RuntimeStage.RESULTS_AUDIT, {"values": values, "audit": audit}
                ))
                await self.backend.close_model(physical_name)
                model_open = False
                return RuntimeResult(
                    run_id=request.run_id,
                    model_id=request.model_id,
                    success=True,
                    status="completed",
                    stage_records=records,
                    artifacts=artifacts,
                    checkpoint=checkpoint,
                    data={"values": values, "audit": audit},
                    cleanup_complete=True,
                )
        except BaseException as error:
            stage = self._active_stage(records)
            failure = classify_backend_error(error, stage)
            if failure.termination_confirmed is False:
                cleanup_complete = False
            elif model_open:
                try:
                    await self.backend.close_model(physical_name)
                    model_open = False
                except Exception:
                    cleanup_complete = False
            self._failures[request.run_id] = failure
            current = records[stage]
            state = (
                StageState.CANCELLED
                if failure.error_class == ErrorClass.CANCELLED
                else StageState.TIMED_OUT
                if failure.error_class == ErrorClass.TIMEOUT
                else StageState.FAILED
            )
            records[stage] = current.model_copy(
                update={
                    "state": state,
                    "finished_at": utc_now(),
                    "detail": {
                        "code": failure.code,
                        "termination_confirmed": failure.termination_confirmed,
                    },
                }
            )
            await self._notify_stage(request, records[stage])
            return RuntimeResult(
                run_id=request.run_id,
                model_id=request.model_id,
                success=False,
                status=state.value,
                stage_records=records,
                artifacts=artifacts,
                checkpoint=checkpoint,
                failure=failure,
                cleanup_complete=cleanup_complete,
            )
        finally:
            if model_open and not self.worker.quarantined:
                try:
                    await self.backend.close_model(physical_name)
                except Exception:
                    pass
            self._running.pop(request.run_id, None)

    async def _record(
        self,
        request: RuntimeRunRequest,
        records: dict[RuntimeStage, StageRecord],
        record: StageRecord,
    ) -> None:
        records[record.stage] = record
        await self._notify_stage(request, record)

    async def _notify_stage(
        self, request: RuntimeRunRequest, record: StageRecord
    ) -> None:
        if self._stage_sink is None:
            return
        try:
            result = self._stage_sink(
                RuntimeStageEvent(
                    run_id=request.run_id,
                    model_id=request.model_id,
                    record=record,
                )
            )
            if inspect.isawaitable(result):
                await result
        except Exception:
            # Observability consumers cannot alter COMSOL execution truth.
            return

    async def _create_checkpoint_for_model(
        self,
        *,
        request: RuntimeRunRequest,
        physical_name: str,
        stage: RuntimeStage,
        model_summary: dict[str, Any],
        cancellation: CancellationToken,
    ) -> Checkpoint:
        checkpoint_id = f"checkpoint-{stage.value.split('_', 1)[0]}-{uuid4().hex}"
        model_path = self.artifacts.target(request.run_id, request.model_id, f"{checkpoint_id}.mph")
        await self._call(
            RuntimeOperation.CREATE_CHECKPOINT,
            lambda: self.backend.save_model(physical_name, model_path),
            timeout_seconds=request.timeout_seconds,
            cancellation=cancellation,
        )
        provenance = self._provenance(request.run_id, request.model_id, "runtime:checkpoint")
        artifact = self.artifacts.record(
            model_path,
            stage=stage,
            provenance=provenance,
            media_type="application/vnd.comsol.mph",
        )
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            stage=stage,
            artifact=artifact,
            manifest_path="pending",
            runtime_version=RUNTIME_VERSION,
            comsol_version=self.backend.capabilities.comsol_version,
            backend_version=self.backend.capabilities.backend_version,
            builder_id=request.builder_id,
            builder_capability=request.builder_capability,
            builder_version=request.builder_version,
            extension_versions=request.extension_versions,
            input_summary={
                "parameters": request.parameters,
                "specification": request.specification,
            },
            input_sha256=self._input_hash(request),
            model_summary=model_summary,
            model_sha256=artifact.sha256,
            provenance=provenance,
        )
        return self.artifacts.persist_checkpoint(checkpoint)

    async def restore_checkpoint(self, request: RuntimeRunRequest) -> Checkpoint:
        if not request.resume_checkpoint:
            raise CheckpointCompatibilityError("resume_checkpoint is required")
        checkpoint = self.artifacts.read_checkpoint(request.resume_checkpoint)
        self.artifacts.verify_schema(checkpoint)
        self.artifacts.verify_artifact(checkpoint.artifact)
        expected = {
            "model_id": request.model_id,
            "stage": RuntimeStage.BUILD,
            "runtime_version": RUNTIME_VERSION,
            "comsol_version": self.backend.capabilities.comsol_version,
            "backend_version": self.backend.capabilities.backend_version,
            "builder_id": request.builder_id,
            "builder_capability": request.builder_capability,
            "builder_version": request.builder_version,
            "extension_versions": request.extension_versions,
        }
        actual = {
            "model_id": checkpoint.provenance.model_id,
            "stage": checkpoint.stage,
            "runtime_version": checkpoint.runtime_version,
            "comsol_version": checkpoint.comsol_version,
            "backend_version": checkpoint.backend_version,
            "builder_id": checkpoint.builder_id,
            "builder_capability": checkpoint.builder_capability,
            "builder_version": checkpoint.builder_version,
            "extension_versions": checkpoint.extension_versions,
        }
        mismatches = [name for name, value in expected.items() if actual[name] != value]
        requested_physical_input = {
            "parameters": request.parameters,
            "specification": _physical_specification(request.specification),
        }
        checkpoint_physical_input = {
            "parameters": checkpoint.input_summary.get("parameters", {}),
            "specification": _physical_specification(
                checkpoint.input_summary.get("specification", {})
            ),
        }
        if requested_physical_input != checkpoint_physical_input:
            mismatches.append("physical_input")
        if mismatches:
            raise CheckpointCompatibilityError(
                f"checkpoint compatibility mismatch: {', '.join(mismatches)}"
            )
        return checkpoint

    async def create_model(
        self,
        request: ModelCreateRequest,
        cancellation: CancellationToken | None = None,
    ) -> RuntimeResult:
        return await self._model_operation(
            request,
            RuntimeOperation.CREATE_MODEL,
            lambda: self.backend.create_model(request.model_id),
            keep_model=True,
            cancellation=cancellation,
        )

    async def load_model(
        self,
        request: ModelLoadRequest,
        cancellation: CancellationToken | None = None,
    ) -> RuntimeResult:
        source = Path(request.source_path).resolve(strict=True)
        return await self._model_operation(
            request,
            RuntimeOperation.LOAD_MODEL,
            lambda: self.backend.load_model(request.model_id, source),
            keep_model=True,
            cancellation=cancellation,
        )

    async def save_model(
        self,
        request: ModelSaveRequest,
        cancellation: CancellationToken | None = None,
    ) -> RuntimeResult:
        target = self.artifacts.target(request.run_id, request.model_id, request.target_name)
        result = await self._model_operation(
            request,
            RuntimeOperation.SAVE_MODEL,
            lambda: self.backend.save_model(request.model_id, target),
            cancellation=cancellation,
        )
        if result.success:
            artifact = self.artifacts.record(
                target,
                stage=RuntimeStage.BUILD,
                provenance=self._provenance(request.run_id, request.model_id, "runtime:save"),
                media_type="application/vnd.comsol.mph",
            )
            result = result.model_copy(update={"artifacts": [artifact]})
        return result

    async def close_model(
        self,
        request: ModelCloseRequest,
        cancellation: CancellationToken | None = None,
    ) -> RuntimeResult:
        result = await self._model_operation(
            request,
            RuntimeOperation.CLOSE_MODEL,
            lambda: self.backend.close_model(request.model_id),
            cancellation=cancellation,
        )
        if result.success:
            self._models.discard(request.model_id)
        return result

    async def apply_parameters(
        self,
        request: ParameterPatchRequest,
        cancellation: CancellationToken | None = None,
    ) -> RuntimeResult:
        return await self._model_operation(
            request,
            RuntimeOperation.APPLY_PARAMETERS,
            lambda: self.backend.apply_parameters(request.model_id, request.parameters),
            cancellation=cancellation,
        )

    async def execute_registered(
        self,
        request: RegisteredExecutionRequest,
        cancellation: CancellationToken | None = None,
    ) -> RuntimeResult:
        return await self._model_operation(
            request,
            RuntimeOperation.EXECUTE_REGISTERED,
            lambda: self.backend.execute_registered(
                request.model_id,
                request.extension_id,
                request.extension_version,
                request.extension_kind,
                request.capability,
                request.specification,
            ),
            cancellation=cancellation,
        )

    async def model_action(
        self,
        request: ModelActionRequest,
        operation: RuntimeOperation,
        cancellation: CancellationToken | None = None,
    ) -> RuntimeResult:
        handlers: dict[RuntimeOperation, Callable[[], Awaitable[Any]]] = {
            RuntimeOperation.BUILD: lambda: self.backend.build(request.model_id),
            RuntimeOperation.MESH: lambda: self.backend.mesh(request.model_id),
            RuntimeOperation.SOLVE: lambda: self.backend.solve(request.model_id),
        }
        return await self._model_operation(
            request,
            operation,
            handlers[operation],
            timeout_seconds=request.timeout_seconds,
            cancellation=cancellation,
        )

    async def evaluate(
        self,
        request: EvaluateRequest,
        cancellation: CancellationToken | None = None,
    ) -> RuntimeResult:
        return await self._model_operation(
            request,
            RuntimeOperation.EVALUATE,
            lambda: self.backend.evaluate(request.model_id, request.expressions),
            cancellation=cancellation,
        )

    async def export_results(
        self,
        request: ExportRequest,
        cancellation: CancellationToken | None = None,
    ) -> RuntimeResult:
        target = self.artifacts.target(request.run_id, request.model_id, request.target_name)
        result = await self._model_operation(
            request,
            RuntimeOperation.EXPORT_RESULTS,
            lambda: self.backend.export(request.model_id, target),
            cancellation=cancellation,
        )
        if result.success:
            artifact = self.artifacts.record(
                target,
                stage=RuntimeStage.RESULTS_AUDIT,
                provenance=self._provenance(request.run_id, request.model_id, "runtime:export"),
                media_type="application/octet-stream",
            )
            result = result.model_copy(update={"artifacts": [artifact]})
        return result

    async def create_checkpoint(
        self,
        request: CheckpointCreateRequest,
        cancellation: CancellationToken | None = None,
    ) -> Checkpoint:
        token = cancellation or CancellationToken()
        if request.run_id in self._running:
            raise ResourceLeaseError(f"run_id already active: {request.run_id}")
        self._running[request.run_id] = token
        try:
            lock = await self._model_lock(request.model_id)
            runtime_request = RuntimeRunRequest(
                run_id=request.run_id,
                model_id=request.model_id,
                builder_id=request.builder_id,
                builder_capability=request.builder_capability,
                builder_version=request.builder_version,
                extension_versions=request.extension_versions,
                parameters=request.parameters,
                specification=request.specification,
            )
            async with self._execution_slot(
                lock, cancellation=token, timeout_seconds=300.0
            ):
                await self.start()
                return await self._create_checkpoint_for_model(
                    request=runtime_request,
                    physical_name=request.model_id,
                    stage=request.stage,
                    model_summary=request.model_summary,
                    cancellation=token,
                )
        finally:
            if self._running.get(request.run_id) is token:
                self._running.pop(request.run_id, None)

    def inspect_checkpoint(self, manifest_path: str) -> Checkpoint:
        checkpoint = self.artifacts.read_checkpoint(manifest_path)
        self.artifacts.verify_schema(checkpoint)
        self.artifacts.verify_artifact(checkpoint.artifact)
        return checkpoint

    async def restore_model(
        self,
        request: CheckpointRestoreRequest,
        cancellation: CancellationToken | None = None,
    ) -> RuntimeResult:
        runtime_request = RuntimeRunRequest(
            run_id=request.run_id,
            model_id=request.model_id,
            builder_id=request.builder_id,
            builder_capability=request.builder_capability,
            builder_version=request.builder_version,
            extension_versions=request.extension_versions,
            parameters=request.parameters,
            specification=request.specification,
            timeout_seconds=request.timeout_seconds,
            resume_checkpoint=request.manifest_path,
        )
        checkpoint = await self.restore_checkpoint(runtime_request)
        result = await self._model_operation(
            request,
            RuntimeOperation.RESTORE_CHECKPOINT,
            lambda: self.backend.load_model(request.model_id, Path(checkpoint.artifact.path)),
            timeout_seconds=request.timeout_seconds,
            keep_model=True,
            cancellation=cancellation,
        )
        if result.success:
            result = result.model_copy(
                update={
                    "checkpoint": checkpoint,
                    "data": {
                        "restored_stage": checkpoint.stage,
                        "checkpoint_id": checkpoint.checkpoint_id,
                    },
                }
            )
        return result

    def cancel_run(self, request: CancelRunRequest) -> bool:
        token = self._running.get(request.target_run_id)
        if token is None:
            return False
        token.cancel(request.reason)
        return True

    def inspect_failure(self, request: FailureInspectRequest) -> RuntimeFailure | None:
        return self._failures.get(request.target_run_id)

    async def _model_operation(
        self,
        request: ModelRequestBase,
        operation: RuntimeOperation,
        call: Callable[[], Awaitable[Any]],
        *,
        timeout_seconds: float = 300.0,
        keep_model: bool = False,
        cancellation: CancellationToken | None = None,
    ) -> RuntimeResult:
        token = cancellation or CancellationToken()
        existing = self._running.get(request.run_id)
        if existing is not None:
            failure = classify_backend_error(
                ResourceLeaseError(f"run_id already active: {request.run_id}"),
                RuntimeStage.BUILD,
                operation,
            )
            return RuntimeResult(
                run_id=request.run_id,
                model_id=request.model_id,
                success=False,
                status="failed",
                failure=failure,
            )
        self._running[request.run_id] = token
        try:
            lock = await self._model_lock(request.model_id)
            async with self._execution_slot(
                lock, cancellation=token, timeout_seconds=timeout_seconds
            ):
                await self.start()
                data = await self._call(
                    operation,
                    call,
                    timeout_seconds=timeout_seconds,
                    cancellation=token,
                )
                if keep_model:
                    self._models.add(request.model_id)
            return RuntimeResult(
                run_id=request.run_id,
                model_id=request.model_id,
                success=True,
                status="completed",
                data=data if isinstance(data, dict) else {},
            )
        except BaseException as error:
            failure = classify_backend_error(error, RuntimeStage.BUILD, operation)
            self._failures[request.run_id] = failure
            return RuntimeResult(
                run_id=request.run_id,
                model_id=request.model_id,
                success=False,
                status="failed",
                failure=failure,
            )
        finally:
            if self._running.get(request.run_id) is token:
                self._running.pop(request.run_id, None)

    @staticmethod
    def _running_record(stage: RuntimeStage) -> StageRecord:
        return StageRecord(stage=stage, state=StageState.RUNNING, started_at=utc_now())

    @staticmethod
    def _passed(stage: RuntimeStage, detail: dict[str, Any]) -> StageRecord:
        now = utc_now()
        return StageRecord(
            stage=stage,
            state=StageState.PASSED,
            started_at=now,
            finished_at=now,
            detail=detail,
        )

    @staticmethod
    def _skipped(stage: RuntimeStage, reason: str) -> StageRecord:
        now = utc_now()
        return StageRecord(
            stage=stage,
            state=StageState.SKIPPED,
            started_at=now,
            finished_at=now,
            detail={"reason": reason},
        )

    @staticmethod
    def _active_stage(records: dict[RuntimeStage, StageRecord]) -> RuntimeStage:
        for stage in reversed(tuple(RuntimeStage)):
            if records[stage].state == StageState.RUNNING:
                return stage
        return RuntimeStage.INPUT_VALIDATION

    @staticmethod
    def _input_hash(request: RuntimeRunRequest) -> str:
        return canonical_sha256(
            {
                "builder_id": request.builder_id,
                "builder_capability": request.builder_capability,
                "builder_version": request.builder_version,
                "extension_versions": request.extension_versions,
                "parameters": request.parameters,
                "specification": request.specification,
            }
        )


def _physical_specification(specification: dict[str, Any]) -> dict[str, Any]:
    """Exclude non-physical provenance from B-checkpoint compatibility."""
    return {
        name: value
        for name, value in specification.items()
        if name not in {"provenance", "build_signature", "topology_signature"}
    }
