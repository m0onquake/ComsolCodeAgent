"""M2 contract and lifecycle acceptance tests for dynamic extensions."""

from __future__ import annotations

import ast
import asyncio
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from comsol_agent.v2.contracts import Action, GoalSpec, Observation, Plan, PlanStep, SourceRef
from comsol_agent.v2.extensions import (
    API_VERSION,
    CompatibilityPolicy,
    DependentExtensionError,
    DuplicateExtensionError,
    ExtensionConflictError,
    ExtensionKind,
    ExtensionLoader,
    ExtensionManifest,
    ExtensionNotFoundError,
    ExtensionRegistry,
    ExtensionStateError,
    ExtensionValidationError,
    HealthReport,
    HealthStatus,
    LifecycleState,
    MissingDependencyError,
    PermissionPolicy,
    PermissionSet,
    RegistryToolExecutor,
    ResolutionContext,
)
from comsol_agent.v2.kernel import AgentKernel, CancellationToken

REPOSITORY_ROOT = Path(__file__).parents[1]


def permissions(**overrides: str) -> PermissionSet:
    values = {"filesystem": "none", "shell": "none", "comsol": "none", "network": "none"}
    values.update(overrides)
    return PermissionSet(**values)


def manifest(
    extension_id: str,
    *,
    kind: ExtensionKind = ExtensionKind.FUNCTION,
    enabled: bool = True,
    version: str = "1.2.0",
    priority: int = 10,
    quality: float = 0.5,
    requested_permissions: PermissionSet | None = None,
    dependencies: list[dict[str, str]] | None = None,
    requires_capabilities: list[dict[str, str]] | None = None,
    entrypoint: str = "fixture_ext:FixtureFunction",
) -> ExtensionManifest:
    specialized: dict[str, Any] = {}
    if kind == ExtensionKind.REPAIR_RULE:
        specialized["repair_contract"] = {
            "error_classes": ["api_code_error"],
            "error_codes": ["UNKNOWN_FEATURE"],
            "stages": ["B_build"],
            "modification_scope": {"kind": "node", "targets": []},
            "required_permissions": [],
            "max_attempts": 1,
            "verifier": "fixture.verify",
            "rollback_required": True,
            "compatibility": {"agent_api": ">=2,<3"},
            "provenance": "tests/test_v2_extensions.py",
        }
    elif kind == ExtensionKind.SOLVER_STRATEGY:
        specialized["solver_strategy_contract"] = {
            "solver_scope": {"kind": "solver", "targets": []},
            "max_solves": 1,
            "core_hour_budget": 1.0,
            "success_criteria": ["converged"],
            "rollback_checkpoint": "B",
            "compatibility": {"agent_api": ">=2,<3"},
            "provenance": "tests/test_v2_extensions.py",
        }
    return ExtensionManifest(
        api_version=API_VERSION,
        kind=kind,
        id=extension_id,
        version=version,
        enabled=enabled,
        entrypoint=entrypoint,
        description="A deterministic test extension",
        capabilities=["fixture.run"],
        compatibility={"agent_api": ">=2.0,<3", "comsol": []},
        permissions=requested_permissions or permissions(),
        priority=priority,
        quality=quality,
        dependencies=dependencies or [],
        requires_capabilities=requires_capabilities or [],
        **specialized,
    )


class FakeFunction:
    input_schema: dict[str, Any] = {"type": "object"}
    output_schema: dict[str, Any] = {"type": "object"}
    read_only = True
    idempotent = True
    timeout_seconds = 1.0
    retryable_errors: frozenset[str] = frozenset()
    side_effects: tuple[str, ...] = ()

    def __init__(
        self,
        extension_manifest: ExtensionManifest,
        *,
        activation_error: bool = False,
        invocation_error: bool = False,
    ) -> None:
        self.manifest = extension_manifest
        self.activation_error = activation_error
        self.invocation_error = invocation_error
        self.active = False

    async def activate(self) -> None:
        if self.activation_error:
            raise RuntimeError("isolated activation failure")
        self.active = True

    async def deactivate(self) -> None:
        self.active = False

    async def health(self) -> HealthReport:
        return HealthReport(
            extension_id=self.manifest.id,
            status=HealthStatus.HEALTHY if self.active else HealthStatus.UNHEALTHY,
            detail="fixture health",
        )

    def supports(self, context: ResolutionContext) -> bool:
        return context.domain in (None, "fixture")

    async def execute(
        self, action: Action, cancellation: CancellationToken
    ) -> Observation:
        cancellation.raise_if_cancelled()
        if self.invocation_error:
            raise LookupError("isolated invocation failure")
        return Observation(
            action_id=action.action_id,
            success=True,
            status="ok",
            stage="execute",
            data={"extension_id": self.manifest.id},
            source=SourceRef(
                kind="extension", identifier=self.manifest.id, version=self.manifest.version
            ),
        )


class UniversalExtension(FakeFunction):
    """Contract fixture implementing every kind-specific interface."""

    repair_contract: dict[str, Any] = {}
    solver_contract: dict[str, Any] = {}

    async def list_tools(self) -> list[dict[str, Any]]:
        return []

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        cancellation: CancellationToken,
    ) -> Observation:
        return await self.execute(Action(tool=name, arguments=arguments), cancellation)

    async def instructions(self, context: ResolutionContext) -> str:
        return "fixture workflow"

    async def handle(self, event: Any) -> dict[str, Any]:
        return {"decision": "allow"}

    def matches(self, observation: Observation, context: ResolutionContext) -> bool:
        return True

    async def propose(self, observation: Observation) -> dict[str, Any]:
        return {"patch": []}

    async def verify(self, observation: Observation) -> bool:
        return observation.success

    def preconditions(self, context: ResolutionContext) -> tuple[str, ...]:
        return ()

    def steps(self) -> tuple[str, ...]:
        return ("fixture.run",)

    def rollback(self) -> dict[str, Any]:
        return {"checkpoint": "fixture"}

    def acceptance(self) -> tuple[str, ...]:
        return ("fixture_passed",)

    async def build(self, specification: dict[str, Any]) -> dict[str, Any]:
        return specification

    async def validate(self, subject: Any) -> dict[str, Any]:
        return {"valid": True}

    async def audit(self, subject: Any) -> dict[str, Any]:
        return {"passed": True}

    async def read(self, record_id: str) -> dict[str, Any] | None:
        return None

    async def write(self, record: dict[str, Any]) -> str:
        return "fixture-record"

    async def delete(self, record_id: str) -> None:
        return None

    async def retrieve(
        self, query: str, filters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return []


def make_loader(
    trusted_root: Path,
    *,
    allowed: PermissionSet | None = None,
    agent_version: str = "2.0.0",
    comsol_version: str | None = None,
) -> ExtensionLoader:
    return ExtensionLoader(
        compatibility=CompatibilityPolicy(
            agent_version=agent_version, comsol_version=comsol_version
        ),
        permissions=PermissionPolicy(allowed or permissions()),
        trusted_manifest_roots=(trusted_root,),
        trusted_code_roots=(trusted_root, REPOSITORY_ROOT),
    )


def write_dynamic_fixture(
    tmp_path: Path,
    module_name: str = "fixture_ext",
    *,
    import_marker: Path | None = None,
) -> None:
    marker_statement = ""
    if import_marker is not None:
        marker_statement = (
            "from pathlib import Path\n"
            f"Path({str(import_marker)!r}).write_text('executed', encoding='utf-8')\n"
        )
    (tmp_path / f"{module_name}.py").write_text(
        marker_statement
        + """
from comsol_agent.v2.contracts import Observation, SourceRef
from comsol_agent.v2.extensions import HealthReport, HealthStatus

class FixtureFunction:
    input_schema = {"type": "object"}
    output_schema = {"type": "object"}
    read_only = True
    idempotent = True
    timeout_seconds = 1.0
    retryable_errors = frozenset()
    side_effects = ()
    def __init__(self, *, manifest, config):
        self.manifest = manifest
        self.config = config
        self.active = False
    async def activate(self): self.active = True
    async def deactivate(self): self.active = False
    async def health(self):
        status = HealthStatus.HEALTHY if self.active else HealthStatus.UNHEALTHY
        return HealthReport(extension_id=self.manifest.id, status=status)
    def supports(self, context): return True
    async def execute(self, action, cancellation):
        return Observation(action_id=action.action_id, success=True, status="ok",
            stage="execute", data=self.config,
            source=SourceRef(kind="extension", identifier=self.manifest.id,
                version=self.manifest.version))
""".strip(),
        encoding="utf-8",
    )


class TestManifestDiscoveryAndValidation:
    def test_manifest_is_strict_and_emits_json_schema(self):
        schema = ExtensionManifest.model_json_schema()
        assert schema["additionalProperties"] is False
        assert {"permissions", "compatibility", "entrypoint", "capabilities"}.issubset(
            schema["required"]
        )
        with pytest.raises(ValidationError):
            ExtensionManifest.model_validate(
                {**manifest("fixture.strict").model_dump(), "unexpected": True}
            )

    def test_discovery_validates_config_schema_then_loads_trusted_entrypoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        write_dynamic_fixture(tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()
        schema_path = tmp_path / "config.schema.json"
        schema_path.write_text(
            json.dumps(
                {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                    "additionalProperties": False,
                }
            ),
            encoding="utf-8",
        )
        raw = manifest("fixture.loaded").model_dump(mode="json")
        raw["config_schema"] = schema_path.name
        raw["config"] = {"message": "validated"}
        (tmp_path / "extension.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")

        loader = make_loader(tmp_path)
        candidates = loader.discover([tmp_path])
        result = loader.validate(candidates[0])
        loaded = loader.load(candidates[0])

        assert len(candidates) == 1
        assert result.valid is True
        assert loaded.manifest.id == "fixture.loaded"
        assert loaded.config == {"message": "validated"}

    def test_invalid_config_compatibility_permission_and_trust_are_hard_rejections(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        write_dynamic_fixture(tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()
        raw = manifest(
            "fixture.rejected",
            requested_permissions=permissions(filesystem="write"),
        ).model_dump(mode="json")
        raw["compatibility"] = {"agent_api": ">=3", "comsol": ["6.x"]}
        raw["entrypoint"] = "comsol_agent.v2.extensions.models:ExtensionManifest"
        raw["config_schema"] = {
            "type": "object",
            "required": ["required_value"],
        }
        manifest_path = tmp_path / "extension.yaml"
        manifest_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        untrusted_root = tmp_path / "different-root"
        untrusted_root.mkdir()
        loader = ExtensionLoader(
            compatibility=CompatibilityPolicy(agent_version="2.0.0"),
            permissions=PermissionPolicy.deny_all(),
            trusted_manifest_roots=(untrusted_root,),
            trusted_code_roots=(tmp_path,),
        )

        result = loader.validate(loader.discover([manifest_path])[0])
        codes = {issue.code for issue in result.issues}

        assert {
            "untrusted_manifest_path",
            "incompatible_agent_api",
            "comsol_version_unknown",
            "permission_denied",
            "invalid_config",
            "untrusted_entrypoint",
        }.issubset(codes)
        with pytest.raises(ExtensionValidationError):
            loader.load(result.candidate)

    def test_effective_sys_path_shadow_is_rejected_without_executing_attacker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        trusted = tmp_path / "trusted"
        attacker = tmp_path / "attacker"
        trusted.mkdir()
        attacker.mkdir()
        marker = tmp_path / "attacker-executed"
        write_dynamic_fixture(trusted, "shadowed_ext")
        write_dynamic_fixture(attacker, "shadowed_ext", import_marker=marker)
        monkeypatch.syspath_prepend(str(trusted))
        monkeypatch.syspath_prepend(str(attacker))
        importlib.invalidate_caches()
        raw = manifest(
            "fixture.shadowed", entrypoint="shadowed_ext:FixtureFunction"
        ).model_dump(mode="json")
        manifest_path = trusted / "extension.yaml"
        manifest_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        loader = ExtensionLoader(
            compatibility=CompatibilityPolicy(agent_version="2.0.0"),
            permissions=PermissionPolicy.deny_all(),
            trusted_manifest_roots=(trusted,),
            trusted_code_roots=(trusted,),
        )

        candidate = loader.discover([manifest_path])[0]
        result = loader.validate(candidate)

        assert "untrusted_entrypoint" in {issue.code for issue in result.issues}
        assert marker.exists() is False
        with pytest.raises(ExtensionValidationError):
            loader.load(candidate)
        assert marker.exists() is False

    def test_cached_untrusted_module_wins_over_later_trusted_sys_path_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        trusted = tmp_path / "trusted"
        attacker = tmp_path / "attacker"
        trusted.mkdir()
        attacker.mkdir()
        module_name = "cached_shadow_ext"
        write_dynamic_fixture(trusted, module_name)
        write_dynamic_fixture(attacker, module_name)
        monkeypatch.syspath_prepend(str(attacker))
        importlib.invalidate_caches()
        imported = importlib.import_module(module_name)
        assert Path(imported.__file__).is_relative_to(attacker)
        monkeypatch.syspath_prepend(str(trusted))
        raw = manifest(
            "fixture.cached-shadow", entrypoint=f"{module_name}:FixtureFunction"
        ).model_dump(mode="json")
        manifest_path = trusted / "extension.yaml"
        manifest_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        loader = ExtensionLoader(
            compatibility=CompatibilityPolicy(agent_version="2.0.0"),
            permissions=PermissionPolicy.deny_all(),
            trusted_manifest_roots=(trusted,),
            trusted_code_roots=(trusted,),
        )
        try:
            result = loader.validate(loader.discover([manifest_path])[0])
        finally:
            sys.modules.pop(module_name, None)

        assert "untrusted_entrypoint" in {issue.code for issue in result.issues}


class TestRegistryLifecycle:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", list(ExtensionKind))
    async def test_every_extension_kind_supports_full_lifecycle(
        self, tmp_path: Path, kind: ExtensionKind
    ):
        registry = ExtensionRegistry(make_loader(tmp_path))
        extension_id = f"fixture.{kind.value}"
        extension = UniversalExtension(manifest(extension_id, kind=kind))

        registration = await registry.register(extension)
        health = await registry.health(extension_id)
        await registry.disable(extension_id)
        registry.unregister(extension_id)

        assert registration.state == LifecycleState.ACTIVE
        assert health.status == HealthStatus.HEALTHY
        assert [event.action for event in registry.events] == [
            "register",
            "enable",
            "health",
            "disable",
            "unregister",
        ]

    @pytest.mark.asyncio
    async def test_register_enable_disable_unregister_and_pinned_snapshot(self, tmp_path: Path):
        registry = ExtensionRegistry(make_loader(tmp_path))
        extension = FakeFunction(manifest("fixture.lifecycle"))

        registration = await registry.register(extension)
        snapshot = registry.snapshot()
        with pytest.raises(ExtensionStateError, match="disable an extension"):
            registry.unregister(extension.manifest.id)
        await registry.disable(extension.manifest.id)

        assert registration.state == LifecycleState.ACTIVE
        assert registry.resolve(ExtensionKind.FUNCTION, "fixture.run") == []
        assert snapshot.resolve(ExtensionKind.FUNCTION, "fixture.run") == [extension]
        observation = await RegistryToolExecutor(snapshot).execute(
            Action(tool="fixture.run"), CancellationToken()
        )
        assert observation.success is True
        assert extension.active is True
        with pytest.raises(ExtensionStateError, match="active snapshot"):
            registry.unregister(extension.manifest.id)
        with pytest.raises(ExtensionNotFoundError):
            await registry.enable("missing")
        await snapshot.close()
        assert extension.active is False
        registry.unregister(extension.manifest.id)
        assert [event.action for event in registry.events] == [
            "register",
            "enable",
            "disable",
            "resolve",
            "snapshot_release",
            "unregister",
        ]

    @pytest.mark.asyncio
    async def test_disable_hides_extension_before_blocking_deactivation_finishes(
        self, tmp_path: Path
    ):
        class BlockingDeactivateFunction(FakeFunction):
            def __init__(self, extension_manifest: ExtensionManifest) -> None:
                super().__init__(extension_manifest)
                self.deactivation_started = asyncio.Event()
                self.allow_deactivation = asyncio.Event()

            async def deactivate(self) -> None:
                self.deactivation_started.set()
                await self.allow_deactivation.wait()
                await super().deactivate()

        registry = ExtensionRegistry(make_loader(tmp_path))
        extension = BlockingDeactivateFunction(manifest("fixture.concurrent-disable"))
        await registry.register(extension)

        disable_task = asyncio.create_task(registry.disable(extension.manifest.id))
        await extension.deactivation_started.wait()

        assert registry.state(extension.manifest.id) == LifecycleState.DISABLED
        assert registry.resolve(ExtensionKind.FUNCTION, "fixture.run") == []
        async with registry.snapshot() as snapshot:
            assert snapshot.versions == {}
        with pytest.raises(ExtensionStateError, match="transition is in progress"):
            registry.unregister(extension.manifest.id)

        extension.allow_deactivation.set()
        await disable_task
        registry.unregister(extension.manifest.id)

    @pytest.mark.asyncio
    async def test_duplicate_missing_dependency_and_dependent_unload_are_rejected(
        self, tmp_path: Path
    ):
        registry = ExtensionRegistry(make_loader(tmp_path))
        base = FakeFunction(manifest("fixture.base"))
        await registry.register(base)
        with pytest.raises(DuplicateExtensionError):
            await registry.register(
                FakeFunction(manifest("fixture.base", version="2.0.0"))
            )
        with pytest.raises(MissingDependencyError):
            await registry.register(
                FakeFunction(
                    manifest(
                        "fixture.missing",
                        dependencies=[{"extension_id": "fixture.unknown", "version": ">=1"}],
                    )
                )
            )
        dependent = FakeFunction(
            manifest(
                "fixture.dependent",
                enabled=False,
                dependencies=[{"extension_id": "fixture.base", "version": ">=1,<2"}],
            )
        )
        await registry.register(dependent)
        await registry.disable("fixture.base")
        with pytest.raises(DependentExtensionError):
            registry.unregister("fixture.base")

    @pytest.mark.asyncio
    async def test_capability_dependencies_guard_path_registration_and_provider_unload(
        self, tmp_path: Path
    ):
        registry = ExtensionRegistry(make_loader(tmp_path))
        missing_path = UniversalExtension(
            manifest(
                "fixture.path-missing",
                kind=ExtensionKind.DETERMINISTIC_PATH,
                enabled=False,
                requires_capabilities=[
                    {"kind": "function", "capability": "missing.run"}
                ],
            )
        )
        with pytest.raises(MissingDependencyError, match="missing.run"):
            await registry.register(missing_path)

        provider = FakeFunction(manifest("fixture.provider"))
        await registry.register(provider)
        path = UniversalExtension(
            manifest(
                "fixture.path",
                kind=ExtensionKind.DETERMINISTIC_PATH,
                enabled=False,
                requires_capabilities=[
                    {"kind": "function", "capability": "fixture.run"}
                ],
            )
        )
        await registry.register(path)
        await registry.disable(provider.manifest.id)

        with pytest.raises(DependentExtensionError, match="fixture.path"):
            registry.unregister(provider.manifest.id)

    @pytest.mark.asyncio
    async def test_resolution_conflict_is_structured_and_explicit_selection_wins(
        self, tmp_path: Path
    ):
        registry = ExtensionRegistry(make_loader(tmp_path))
        first = FakeFunction(manifest("fixture.first"))
        second = FakeFunction(manifest("fixture.second"))
        await registry.register(first)
        await registry.register(second)

        with pytest.raises(ExtensionConflictError) as captured:
            registry.resolve(ExtensionKind.FUNCTION, "fixture.run")

        assert captured.value.report.extension_ids == ["fixture.first", "fixture.second"]
        selected = registry.resolve(
            ExtensionKind.FUNCTION,
            "fixture.run",
            ResolutionContext(selected_extension_id="fixture.second"),
        )
        assert selected == [second]

    @pytest.mark.asyncio
    async def test_permission_and_interface_contracts_are_enforced(self, tmp_path: Path):
        registry = ExtensionRegistry(make_loader(tmp_path))
        with pytest.raises(ExtensionValidationError, match="permission_denied"):
            await registry.register(
                FakeFunction(
                    manifest(
                        "fixture.overprivileged",
                        requested_permissions=permissions(network="client"),
                    )
                )
            )

        class BrokenFunction:
            def __init__(self) -> None:
                self.manifest = manifest("fixture.broken-interface")

            async def activate(self) -> None: ...
            async def deactivate(self) -> None: ...
            async def health(self) -> HealthReport:
                return HealthReport(
                    extension_id=self.manifest.id, status=HealthStatus.HEALTHY
                )

            def supports(self, context: ResolutionContext) -> bool:
                return True

        broken = BrokenFunction()
        with pytest.raises(ExtensionValidationError, match="interface_mismatch"):
            await registry.register(broken)

    @pytest.mark.asyncio
    async def test_activation_and_invocation_failures_are_isolated(self, tmp_path: Path):
        registry = ExtensionRegistry(make_loader(tmp_path))
        broken = FakeFunction(manifest("fixture.broken"), activation_error=True)
        good = FakeFunction(manifest("fixture.good", priority=20))

        broken_registration = await registry.register(broken)
        good_registration = await registry.register(good)

        assert broken_registration.state == LifecycleState.UNHEALTHY
        assert good_registration.state == LifecycleState.ACTIVE
        assert registry.resolve(ExtensionKind.FUNCTION, "fixture.run") == [good]
        good.invocation_error = True
        with pytest.raises(Exception, match="isolated invocation failure"):
            await registry.invoke(
                "fixture.good",
                "execute",
                Action(tool="fixture.run"),
                CancellationToken(),
            )
        assert registry.state("fixture.good") == LifecycleState.UNHEALTHY
        assert registry.events[-1].success is False


class TestKernelIntegrationAndBoundaries:
    @pytest.mark.asyncio
    async def test_kernel_executes_new_function_through_snapshot_without_code_change(
        self, tmp_path: Path
    ):
        registry = ExtensionRegistry(make_loader(tmp_path))
        extension = FakeFunction(manifest("fixture.kernel"))
        await registry.register(extension)
        goal = GoalSpec(objective="Exercise dynamic tool")
        plan = Plan(
            goal_trace_id=goal.trace_id,
            steps=[PlanStep(description="Run extension", action=Action(tool="fixture.run"))],
        )

        async with registry.snapshot() as snapshot:
            run = await AgentKernel(RegistryToolExecutor(snapshot)).run(goal, plan)

        assert run.status == "completed"
        assert run.action_records[0].observation.data == {"extension_id": "fixture.kernel"}

    @pytest.mark.asyncio
    async def test_executor_enforces_action_permissions_and_function_schemas(
        self, tmp_path: Path
    ):
        loader = make_loader(tmp_path, allowed=permissions(filesystem="write"))
        registry = ExtensionRegistry(loader)
        extension = FakeFunction(
            manifest(
                "fixture.contract",
                requested_permissions=permissions(filesystem="write"),
            )
        )
        extension.input_schema = {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        }
        extension.output_schema = {
            "type": "object",
            "required": ["extension_id"],
        }
        await registry.register(extension)
        async with registry.snapshot() as snapshot:
            executor = RegistryToolExecutor(snapshot)
            invalid_input = await executor.execute(
                Action(tool="fixture.run", arguments={}), CancellationToken()
            )
            allowed = await executor.execute(
                Action(
                    tool="fixture.run",
                    arguments={"value": 1},
                    permissions=frozenset({"filesystem:read"}),
                ),
                CancellationToken(),
            )
            denied = await executor.execute(
                Action(
                    tool="fixture.run",
                    arguments={"value": 1},
                    permissions=frozenset({"shell:execute"}),
                ),
                CancellationToken(),
            )

        assert invalid_input.exception_type == "InvalidExtensionInput"
        assert allowed.success is True
        assert denied.error_class == "permission_denied"

    def test_comsol_series_compatibility_uses_documented_x_pattern(self):
        policy = CompatibilityPolicy(agent_version="2.0.0", comsol_version="6.3")
        raw = manifest("fixture.comsol").model_dump()
        raw["compatibility"] = {"agent_api": ">=2,<3", "comsol": ["6.x"]}
        validated = ExtensionManifest.model_validate(raw)

        assert policy.issues(validated) == []

    def test_kernel_contains_no_extension_identity_or_kind_dispatch(self):
        kernel_root = REPOSITORY_ROOT / "comsol_agent" / "v2" / "kernel"
        imported_modules: set[str] = set()
        string_literals: set[str] = set()
        for path in kernel_root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.add(node.module)
            string_literals.update(
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            )
        assert not any(
            module.startswith("comsol_agent.v2.extensions")
            for module in imported_modules
        )
        assert "fixture.run" not in string_literals

    def test_all_required_extension_interfaces_are_public(self):
        module = importlib.import_module("comsol_agent.v2.extensions")
        required = {
            "FunctionExtension",
            "McpServerExtension",
            "McpToolExtension",
            "SkillExtension",
            "HookExtension",
            "RepairRuleExtension",
            "DeterministicPathExtension",
            "BuilderExtension",
            "ValidatorExtension",
            "AuditorExtension",
            "MemoryAdapterExtension",
            "RetrieverExtension",
        }
        assert required.issubset(set(module.__all__))
