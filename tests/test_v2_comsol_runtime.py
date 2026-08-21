"""M5 contract and deterministic integration tests for the V2 COMSOL runtime."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from comsol_agent.v2.contracts import Action
from comsol_agent.v2.extensions import (
    API_VERSION,
    CompatibilityPolicy,
    ExtensionKind,
    ExtensionLoader,
    ExtensionManifest,
    ExtensionRegistry,
    HealthReport,
    HealthStatus,
    PermissionPolicy,
    PermissionSet,
    RegistryToolExecutor,
)
from comsol_agent.v2.kernel import CancellationToken
from comsol_agent.v2.runtime.comsol import (
    ArtifactStore,
    BackendCapabilities,
    CheckpointCompatibilityError,
    CheckpointCreateRequest,
    ComsolRuntime,
    ErrorClass,
    FakeWorkerExecutor,
    ModelCreateRequest,
    MphBackendAdapter,
    ParameterPatchRequest,
    PinnedExecutionCatalog,
    RegisteredHandlerBinding,
    RuntimeOperation,
    RuntimeRunRequest,
    RuntimeStage,
    SnapshotBindingError,
    StageState,
    build_mcp_tools,
    classify_backend_error,
)


class FakeFlError(RuntimeError):
    pass


class FakeBackend:
    """Deterministic typed backend; no legacy dict tool is used by the runtime."""

    capabilities = BackendCapabilities(
        backend="fake-mph",
        backend_version="1.0",
        comsol_version="6.3",
        hard_cancel=True,
    )

    def __init__(self) -> None:
        self.started = False
        self.models: set[str] = set()
        self.build_calls = 0
        self.solve_calls = 0
        self.active_calls = 0
        self.max_active_calls = 0
        self.release_event = asyncio.Event()
        self.block_build = False
        self.block_solve = False
        self.fail_solve: BaseException | None = None

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False
        self.models.clear()

    async def status(self) -> dict[str, Any]:
        return {"started": self.started, "models": sorted(self.models)}

    async def create_model(self, model_name: str) -> None:
        self.models.add(model_name)

    async def load_model(self, model_name: str, path: Path) -> None:
        assert path.read_bytes().startswith(b"fake-mph")
        self.models.add(model_name)

    async def save_model(self, model_name: str, path: Path) -> None:
        assert model_name in self.models
        path.write_bytes(f"fake-mph:{model_name}".encode())

    async def close_model(self, model_name: str) -> None:
        self.models.discard(model_name)

    async def apply_parameters(self, model_name: str, parameters: dict[str, str]) -> None:
        assert model_name in self.models
        assert parameters

    async def execute_registered(
        self,
        model_name: str,
        extension_id: str,
        extension_version: str,
        extension_kind: str,
        capability: str,
        specification: dict[str, Any],
    ) -> dict[str, Any]:
        assert model_name in self.models
        return {
            "extension_id": extension_id,
            "extension_version": extension_version,
            "extension_kind": extension_kind,
            "capability": capability,
            "specification": specification,
        }

    async def build(self, model_name: str) -> dict[str, Any]:
        self.build_calls += 1
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            if self.block_build:
                await self.release_event.wait()
            return {"model_summary": {"features": self.build_calls}}
        finally:
            self.active_calls -= 1

    async def mesh(self, model_name: str) -> dict[str, Any]:
        return {"meshed": True}

    async def solve(self, model_name: str) -> dict[str, Any]:
        self.solve_calls += 1
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            if self.block_solve:
                await self.release_event.wait()
            if self.fail_solve:
                raise self.fail_solve
            return {"converged": True}
        finally:
            self.active_calls -= 1

    async def evaluate(self, model_name: str, expressions: tuple[str, ...]) -> dict[str, Any]:
        return {expression: 1.0 for expression in expressions}

    async def export(self, model_name: str, target: Path) -> None:
        target.write_text("result\n", encoding="utf-8")

    async def audit(self, model_name: str) -> dict[str, Any]:
        return {"passed": True, "checks": ["finite"]}


def run_request(**overrides: Any) -> RuntimeRunRequest:
    values: dict[str, Any] = {
        "run_id": "run-001",
        "model_id": "model-001",
        "builder_id": "fixture.builder",
        "builder_capability": "fixture.build",
        "builder_version": "2.1.0",
        "extension_versions": {"fixture.builder": "2.1.0"},
        "parameters": {"load": "10[N]"},
        "specification": {"domain": "fixture", "topology": "simple"},
        "expressions": ["u"],
        "timeout_seconds": 1.0,
    }
    values.update(overrides)
    return RuntimeRunRequest(**values)


def runtime(
    tmp_path: Path, backend: FakeBackend | None = None
) -> tuple[ComsolRuntime, FakeBackend]:
    selected = backend or FakeBackend()
    return (
        ComsolRuntime(
            backend=selected,
            artifacts=ArtifactStore(tmp_path),
            worker=FakeWorkerExecutor(selected),
        ),
        selected,
    )


def test_runtime_contracts_are_strict_and_publish_json_schema() -> None:
    schema = RuntimeRunRequest.model_json_schema()
    assert schema["additionalProperties"] is False
    assert "builder_version" in schema["required"]
    with pytest.raises(ValidationError):
        RuntimeRunRequest(**run_request().model_dump(), arbitrary_java="model.reset()")
    with pytest.raises(ValidationError):
        ModelCreateRequest(run_id="../escape", model_id="model")
    assert RuntimeOperation.EXECUTE_REGISTERED.value == "execute_registered"


def test_known_api_error_is_classified_with_original_cause_chain() -> None:
    root = FakeFlError("Unknown feature: sel_missing")
    try:
        raise RuntimeError("builder failed") from root
    except RuntimeError as error:
        failure = classify_backend_error(error, RuntimeStage.BUILD)
    assert failure.error_class == ErrorClass.API_CODE
    assert failure.code == "UNKNOWN_FEATURE"
    assert [cause.exception_type for cause in failure.causes] == [
        "RuntimeError",
        "FakeFlError",
    ]
    assert "sel_missing" in failure.causes[-1].message


@pytest.mark.asyncio
async def test_same_model_concurrent_execution_is_serialized(tmp_path: Path) -> None:
    service, backend = runtime(tmp_path)
    backend.block_build = True
    token = CancellationToken()
    first = asyncio.create_task(service.run(run_request(run_id="run-one"), token))
    while backend.active_calls == 0:
        await asyncio.sleep(0)
    second = asyncio.create_task(service.run(run_request(run_id="run-two"), token))
    await asyncio.sleep(0.02)
    assert backend.max_active_calls == 1
    backend.release_event.set()
    assert (await first).success
    assert (await second).success
    assert backend.max_active_calls == 1


@pytest.mark.asyncio
async def test_timeout_releases_lock_and_resource_lease(tmp_path: Path) -> None:
    service, backend = runtime(tmp_path)
    backend.block_build = True
    result = await service.run(
        run_request(run_id="timed-out", timeout_seconds=0.01), CancellationToken()
    )
    assert not result.success
    assert result.failure is not None
    assert result.failure.error_class == ErrorClass.TIMEOUT
    assert result.failure.termination_confirmed is True
    assert service.active_resource_leases == 0
    assert not service.is_model_locked("model-001")
    backend.block_build = False
    assert (await service.run(run_request(run_id="after-timeout"), CancellationToken())).success


@pytest.mark.asyncio
async def test_cancellation_releases_resources_and_preserves_checkpoint(tmp_path: Path) -> None:
    service, backend = runtime(tmp_path)
    backend.block_build = True
    token = CancellationToken()
    task = asyncio.create_task(service.run(run_request(run_id="cancelled"), token))
    while backend.active_calls == 0:
        await asyncio.sleep(0)
    token.cancel("operator request")
    result = await task
    assert result.failure is not None
    assert result.failure.error_class == ErrorClass.CANCELLED
    assert service.active_resource_leases == 0
    assert not service.is_model_locked("model-001")
    assert all(artifact.provenance.run_id == "cancelled" for artifact in result.artifacts)


@pytest.mark.asyncio
async def test_stage_b_checkpoint_resumes_stage_c_without_rebuild(tmp_path: Path) -> None:
    service, backend = runtime(tmp_path)
    backend.fail_solve = RuntimeError("Failed to find a solution; nonlinear solver")
    failed = await service.run(run_request(run_id="first"), CancellationToken())
    checkpoint = failed.checkpoint
    assert checkpoint is not None
    assert checkpoint.stage == RuntimeStage.BUILD
    assert backend.build_calls == 1
    backend.fail_solve = None
    resumed = await service.run(
        run_request(run_id="second", resume_checkpoint=checkpoint.manifest_path),
        CancellationToken(),
    )
    assert resumed.success
    assert backend.build_calls == 1
    assert resumed.stage_records[RuntimeStage.BUILD].state == StageState.SKIPPED
    assert resumed.stage_records[RuntimeStage.SOLVE].state == StageState.PASSED


@pytest.mark.asyncio
async def test_incompatible_or_corrupted_checkpoint_is_rejected(tmp_path: Path) -> None:
    service, _ = runtime(tmp_path)
    failed_backend = FakeBackend()
    failed_backend.fail_solve = RuntimeError("non convergence")
    service = ComsolRuntime(
        backend=failed_backend,
        artifacts=ArtifactStore(tmp_path),
        worker=FakeWorkerExecutor(failed_backend),
    )
    failed = await service.run(run_request(run_id="source"), CancellationToken())
    assert failed.checkpoint is not None
    with pytest.raises(CheckpointCompatibilityError):
        await service.restore_checkpoint(
            run_request(
                run_id="bad-version",
                builder_version="9.0.0",
                extension_versions={"fixture.builder": "9.0.0"},
                resume_checkpoint=failed.checkpoint.manifest_path,
            )
        )
    Path(failed.checkpoint.artifact.path).write_bytes(b"corrupt")
    with pytest.raises(CheckpointCompatibilityError):
        await service.restore_checkpoint(
            run_request(run_id="bad-hash", resume_checkpoint=failed.checkpoint.manifest_path)
        )


@pytest.mark.asyncio
async def test_artifacts_are_isolated_hashed_and_provenanced(tmp_path: Path) -> None:
    service, _ = runtime(tmp_path)
    result = await service.run(run_request(), CancellationToken())
    assert result.success
    assert result.artifacts
    root = tmp_path.resolve()
    for artifact in result.artifacts:
        path = Path(artifact.path).resolve()
        assert path.is_relative_to(root / "run-001" / "model-001")
        assert len(artifact.sha256) == 64
        assert artifact.provenance.run_id == "run-001"
        assert artifact.provenance.backend == "fake-mph"


@pytest.mark.asyncio
async def test_parameter_patch_and_checkpoint_tools_are_typed(tmp_path: Path) -> None:
    service, backend = runtime(tmp_path)
    created = await service.create_model(
        ModelCreateRequest(run_id="ops", model_id="parameter-model")
    )
    assert created.success
    patched = await service.apply_parameters(
        ParameterPatchRequest(
            run_id="ops",
            model_id="parameter-model",
            parameters={"load": "20[N]"},
        )
    )
    assert patched.success
    checkpoint = await service.create_checkpoint(
        CheckpointCreateRequest(
            run_id="ops",
            model_id="parameter-model",
            stage=RuntimeStage.BUILD,
            builder_id="fixture.builder",
            builder_capability="fixture.build",
            builder_version="1.0.0",
            extension_versions={"fixture.builder": "1.0.0"},
            parameters={"load": "20[N]"},
            specification={"topology": "fixture"},
            model_summary={"kind": "empty"},
        )
    )
    assert checkpoint.artifact.sha256
    assert "parameter-model" in backend.models


def test_mcp_surface_is_minimal_typed_and_has_no_arbitrary_execution(tmp_path: Path) -> None:
    service, _ = runtime(tmp_path)
    tools = build_mcp_tools(service)
    names = {tool.manifest.capabilities[0] for tool in tools}
    assert {
        "comsol.runtime_status",
        "comsol.create_model",
        "comsol.load_model",
        "comsol.save_model",
        "comsol.close_model",
        "comsol.apply_parameters",
        "comsol.execute_registered",
        "comsol.build",
        "comsol.mesh",
        "comsol.solve",
        "comsol.evaluate",
        "comsol.export_results",
        "comsol.create_checkpoint",
        "comsol.inspect_checkpoint",
        "comsol.restore_checkpoint",
        "comsol.cancel_run",
        "comsol.inspect_failure",
    } <= names
    assert not any("java" in name or "shell" in name or "python" in name for name in names)
    for tool in tools:
        assert tool.input_schema["additionalProperties"] is False
        assert tool.output_schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_mcp_tool_runs_through_pinned_extension_snapshot(tmp_path: Path) -> None:
    service, backend = runtime(tmp_path)
    tool = next(
        item for item in build_mcp_tools(service) if item.capability == "comsol.create_model"
    )
    loader = ExtensionLoader(
        compatibility=CompatibilityPolicy(agent_version="2.0.0", comsol_version="6.3"),
        permissions=PermissionPolicy(
            PermissionSet(
                filesystem="write",
                shell="none",
                comsol="solve",
                network="none",
            )
        ),
        trusted_manifest_roots=(tmp_path,),
        trusted_code_roots=(Path(__file__).parents[1],),
    )
    registry = ExtensionRegistry(loader)
    await registry.register(tool)
    assert (await registry.enable(tool.manifest.id)).error is None
    async with registry.snapshot() as snapshot:
        executor = RegistryToolExecutor(snapshot)
        action = Action(
            tool="comsol.create_model",
            arguments={"run_id": "registry", "model_id": "typed-model"},
            permissions=frozenset({"comsol:model_write"}),
        )
        observation = await executor.execute(action, CancellationToken())
        invalid_action = Action(
            tool="comsol.create_model",
            arguments={
                "run_id": "registry",
                "model_id": "typed-model",
                "java": "model.reset()",
            },
            permissions=frozenset({"comsol:model_write"}),
        )
        rejected = await executor.execute(invalid_action, CancellationToken())
    assert observation.success
    assert "typed-model" in backend.models
    assert rejected.error_class == "contract_violation"


@pytest.mark.asyncio
async def test_public_mcp_solve_is_cancelled_by_cancel_run_tool(tmp_path: Path) -> None:
    service, backend = runtime(tmp_path)
    backend.models.add("cancel-model")
    backend.block_solve = True
    tools = {tool.capability: tool for tool in build_mcp_tools(service)}
    solve_action = Action(
        tool="comsol.solve",
        arguments={
            "run_id": "public-solve",
            "model_id": "cancel-model",
            "timeout_seconds": 1.0,
        },
    )
    solve_task = asyncio.create_task(
        tools["comsol.solve"].execute(solve_action, CancellationToken())
    )
    while backend.active_calls == 0:
        await asyncio.sleep(0)
    cancel_observation = await tools["comsol.cancel_run"].execute(
        Action(
            tool="comsol.cancel_run",
            arguments={
                "run_id": "cancel-command",
                "target_run_id": "public-solve",
                "reason": "MCP operator cancellation",
            },
        ),
        CancellationToken(),
    )
    solve_observation = await solve_task
    assert cancel_observation.data["data"]["cancel_requested"] is True
    assert solve_observation.success is False
    assert solve_observation.error_class == ErrorClass.CANCELLED
    assert service.active_resource_leases == 0
    assert not service.is_model_locked("cancel-model")


@pytest.mark.asyncio
async def test_mcp_restore_loads_model_and_can_continue_solving(tmp_path: Path) -> None:
    service, backend = runtime(tmp_path)
    backend.fail_solve = RuntimeError("non convergence")
    failed = await service.run(run_request(run_id="checkpoint-source"), CancellationToken())
    assert failed.checkpoint is not None
    backend.fail_solve = None
    tools = {tool.capability: tool for tool in build_mcp_tools(service)}
    restored = await tools["comsol.restore_checkpoint"].execute(
        Action(
            tool="comsol.restore_checkpoint",
            arguments={
                "run_id": "restore-command",
                "model_id": "model-001",
                "manifest_path": failed.checkpoint.manifest_path,
                "builder_id": "fixture.builder",
                "builder_capability": "fixture.build",
                "builder_version": "2.1.0",
                "extension_versions": {"fixture.builder": "2.1.0"},
                "parameters": {"load": "10[N]"},
                "specification": {"domain": "fixture", "topology": "simple"},
                "timeout_seconds": 1.0,
            },
        ),
        CancellationToken(),
    )
    solved = await tools["comsol.solve"].execute(
        Action(
            tool="comsol.solve",
            arguments={
                "run_id": "solve-restored",
                "model_id": "model-001",
                "timeout_seconds": 1.0,
            },
        ),
        CancellationToken(),
    )
    assert restored.success
    assert restored.data["checkpoint"]["checkpoint_id"] == failed.checkpoint.checkpoint_id
    assert "model-001" in backend.models
    assert solved.success


@pytest.mark.asyncio
async def test_unconfirmed_in_process_cancellation_is_not_reported_as_termination(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    backend.block_build = True
    worker = FakeWorkerExecutor(backend, hard_cancel=False)
    service = ComsolRuntime(
        backend=backend,
        artifacts=ArtifactStore(tmp_path),
        worker=worker,
    )
    result = await service.run(
        run_request(run_id="unconfirmed", timeout_seconds=0.01), CancellationToken()
    )
    assert worker.capabilities.hard_cancel is False
    assert worker.quarantined is True
    assert result.failure is not None
    assert result.failure.termination_confirmed is False
    assert result.cleanup_complete is False
    assert service.active_resource_leases == 0
    assert not service.is_model_locked("model-001")


@pytest.mark.asyncio
async def test_mph_adapter_reuses_typed_client_without_legacy_dict_tools(
    tmp_path: Path,
) -> None:
    class MphModel:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}

        def parameter(self, name: str, value: str) -> None:
            self.values[name] = value

        def save(self, path: str) -> None:
            Path(path).write_bytes(b"typed-adapter")

    class Handle:
        name = "client-name"
        mph_model = MphModel()
        is_modified = False

    class Client:
        is_running = False

        def __init__(self) -> None:
            self.handle = Handle()
            self.started_with: dict[str, Any] = {}

        def start(self, **kwargs: Any) -> None:
            self.started_with = kwargs
            self.is_running = True

        def stop(self) -> None:
            self.is_running = False

        def create(self, name: str) -> Handle:
            return self.handle

        def get_model(self, name: str) -> Handle:
            return self.handle

        def save(self, name: str, path: Path) -> None:
            self.handle.mph_model.save(str(path))

        def close(self, name: str) -> None:
            pass

    class Builder:
        def __init__(self) -> None:
            self.active = False
            self.manifest = ExtensionManifest(
                api_version=API_VERSION,
                kind=ExtensionKind.BUILDER,
                id="fixture.builder",
                version="2.1.0",
                enabled=True,
                entrypoint="fixture:Builder",
                description="snapshot-bound builder",
                capabilities=["fixture.build"],
                compatibility={"agent_api": ">=2.0,<3", "comsol": ["6.x"]},
                permissions={
                    "filesystem": "none",
                    "shell": "none",
                    "comsol": "model_write",
                    "network": "none",
                },
            )

        async def activate(self) -> None:
            self.active = True

        async def deactivate(self) -> None:
            self.active = False

        async def health(self) -> HealthReport:
            return HealthReport(
                extension_id=self.manifest.id,
                status=HealthStatus.HEALTHY if self.active else HealthStatus.DISABLED,
            )

        def supports(self, context: Any) -> bool:
            return True

        async def build(self, specification: dict[str, Any]) -> dict[str, Any]:
            return specification

        def execute_model(self, handle: Any, specification: dict[str, Any]) -> dict[str, Any]:
            return {"built": specification["kind"]}

    loader = ExtensionLoader(
        compatibility=CompatibilityPolicy(agent_version="2.0.0", comsol_version="6.2"),
        permissions=PermissionPolicy(
            PermissionSet(
                filesystem="none",
                shell="none",
                comsol="model_write",
                network="none",
            )
        ),
        trusted_manifest_roots=(tmp_path,),
        trusted_code_roots=(Path(__file__).parents[1],),
    )
    registry = ExtensionRegistry(loader)
    builder = Builder()
    await registry.register(builder)
    await registry.enable("fixture.builder")
    client = Client()
    async with registry.snapshot() as snapshot:
        catalog = PinnedExecutionCatalog(
            snapshot,
            [
                RegisteredHandlerBinding(
                    extension=builder,
                    extension_id="fixture.builder",
                    extension_version="2.1.0",
                    extension_kind=ExtensionKind.BUILDER,
                    capability="fixture.build",
                    handler=builder.execute_model,
                )
            ],
        )
        with pytest.raises(SnapshotBindingError, match="handler owner"):
            PinnedExecutionCatalog(
                snapshot,
                [
                    RegisteredHandlerBinding(
                        extension=Builder(),
                        extension_id="fixture.builder",
                        extension_version="2.1.0",
                        extension_kind=ExtensionKind.BUILDER,
                        capability="fixture.build",
                        handler=lambda handle, spec: spec,
                    )
                ],
            )
        adapter = MphBackendAdapter(
            client=client,
            version="6.2",
            cores=1,
            port=0,
            execution_catalog=catalog,
        )
        await adapter.start()
        await adapter.create_model("typed")
        await adapter.apply_parameters("typed", {"load": "10[N]"})
        runtime_service = ComsolRuntime(
            backend=adapter,
            artifacts=ArtifactStore(tmp_path / "mcp-artifacts"),
            worker=FakeWorkerExecutor(adapter),
        )
        execute_tool = next(
            tool
            for tool in build_mcp_tools(runtime_service)
            if tool.capability == "comsol.execute_registered"
        )
        action_arguments = {
            "run_id": "pinned-builder",
            "model_id": "typed",
            "extension_id": "fixture.builder",
            "extension_version": "2.1.0",
            "extension_kind": "builder",
            "capability": "fixture.build",
            "specification": {"kind": "deterministic"},
        }
        executed = await execute_tool.execute(
            Action(tool="comsol.execute_registered", arguments=action_arguments),
            CancellationToken(),
        )
        rejected = await execute_tool.execute(
            Action(
                tool="comsol.execute_registered",
                arguments={**action_arguments, "extension_version": "9.0.0"},
            ),
            CancellationToken(),
        )
        await adapter.save_model("typed", tmp_path / "typed.mph")
    assert client.started_with == {"cores": 1, "version": "6.2", "port": 0}
    assert client.handle.mph_model.values == {"load": "10[N]"}
    assert executed.data["data"] == {"built": "deterministic"}
    assert rejected.success is False
    assert rejected.exception_type == SnapshotBindingError.__name__
    assert (tmp_path / "typed.mph").read_bytes() == b"typed-adapter"
