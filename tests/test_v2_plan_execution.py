"""M7.5.1: Planner Plan must close through Kernel, Registry and M5 Runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from comsol_agent.v2.contracts import GoalSpec, Observation, RunStatus, SourceRef, StepStatus
from comsol_agent.v2.domains.bearing import (
    BearingPlanner,
    BearingSpec,
    BearingWorkflowTool,
    LoadDirection,
    bearing_extensions,
)
from comsol_agent.v2.extensions import (
    CompatibilityPolicy,
    ExtensionLoader,
    ExtensionRegistry,
    PermissionPolicy,
    PermissionSet,
    RegistryToolExecutor,
)
from comsol_agent.v2.kernel import AgentKernel
from comsol_agent.v2.model_gateway import FakeBackend as FakeModelBackend
from comsol_agent.v2.model_gateway import ModelGateway
from comsol_agent.v2.repair import ObservationRepairRouter, RepairStatus
from comsol_agent.v2.runtime.comsol import (
    ArtifactStore,
    BackendCapabilities,
    ComsolRuntime,
    FakeWorkerExecutor,
)


class WorkflowBackend:
    capabilities = BackendCapabilities(
        backend="fake-workflow", backend_version="1", comsol_version="6.2", hard_cancel=True
    )

    def __init__(self) -> None:
        self.execution_catalog = None
        self.models: set[str] = set()
        self.calls: list[tuple[str, Any]] = []
        self.build_calls = 0
        self.spec = _SPEC

    async def start(self) -> None:
        self.calls.append(("start", None))

    async def stop(self) -> None:
        self.models.clear()

    async def status(self) -> dict[str, Any]:
        return {"models": sorted(self.models)}

    async def create_model(self, model_name: str) -> None:
        self.calls.append(("create", model_name))
        self.models.add(model_name)

    async def load_model(self, model_name: str, path: Path) -> None:
        assert path.is_file()
        self.calls.append(("restore", model_name))
        self.models.add(model_name)

    async def save_model(self, model_name: str, path: Path) -> None:
        path.write_bytes(b"fake-mph:" + model_name.encode())

    async def close_model(self, model_name: str) -> None:
        self.models.discard(model_name)

    async def apply_parameters(self, model_name: str, parameters: dict[str, str]) -> None:
        self.calls.append(("parameters", dict(parameters)))

    async def execute_registered(
        self,
        model_name: str,
        extension_id: str,
        extension_version: str,
        extension_kind: str,
        capability: str,
        specification: dict[str, Any],
    ) -> dict[str, Any]:
        assert self.execution_catalog is not None
        self.calls.append(
            (
                "registered",
                (extension_id, extension_version, extension_kind, capability, specification),
            )
        )
        if capability == "bearing.cylindrical-roller.build":
            self.spec = BearingSpec.model_validate(specification)
        elif capability == "bearing.parameter-override":
            self.spec = BearingSpec.model_validate(specification["requested"])
        return {"capability": capability, "pinned": True}

    async def build(self, model_name: str) -> dict[str, Any]:
        self.build_calls += 1
        self.calls.append(("build", model_name))
        return {"built": True}

    async def mesh(self, model_name: str) -> dict[str, Any]:
        self.calls.append(("mesh", model_name))
        return {"meshed": True}

    async def solve(self, model_name: str) -> dict[str, Any]:
        self.calls.append(("solve", model_name))
        return {"converged": True}

    async def evaluate(self, model_name: str, expressions: tuple[str, ...]) -> dict[str, Any]:
        return {expression: 1.0 for expression in expressions}

    async def export(self, model_name: str, target: Path) -> None:
        target.write_text("result\n", encoding="utf-8")

    async def audit(self, model_name: str) -> dict[str, Any]:
        spec = self.spec
        selections = {
            tag: {"entity_count": 1}
            for tag in (
                "sel_inner_raceway_contact",
                "sel_outer_raceway_contact",
                "sel_all_roller_inner_contacts",
                "sel_all_roller_outer_contacts",
                "sel_inner_bore_load_surface",
                "sel_outer_support_surface",
                *[f"sel_roller_{index}_body" for index in range(1, spec.roller_count + 1)],
            )
        }
        dataset = "dset-target"
        stress = {
            "success": True,
            "value": 45000.0,
            "expression": "solid.mises/1[Pa]",
            "base_expression": "solid.mises",
            "unit": "Pa",
            "dataset": dataset,
            "solution_number": 1,
            "node_kind": "MaxVolume",
            "source": "java:MaxVolume.getReal",
            "solution_bindings": [{"property": "solnum", "value": "1"}],
        }
        return {
            "passed": True,
            "selections": selections,
            "pairs": {
                "cp_all_rollers_inner": {
                    "source_named": "sel_all_roller_inner_contacts",
                    "destination_named": "sel_inner_raceway_contact",
                    "source_entity_count": 1,
                    "destination_entity_count": 1,
                },
                "cp_all_rollers_outer": {
                    "source_named": "sel_all_roller_outer_contacts",
                    "destination_named": "sel_outer_raceway_contact",
                    "source_entity_count": 1,
                    "destination_entity_count": 1,
                },
            },
            "metrics": {
                "returned_target_load_n": spec.target_radial_load_n,
                "applied_load_n": spec.target_radial_load_n,
                "support_reaction_n": spec.target_radial_load_n,
                "outer_contact_resultant_n": spec.target_radial_load_n,
                "stabilization_force_n": 0,
                "loaded_zone_direction": spec.load_direction.value,
            },
            "result_evidence": {
                "success": True,
                "dataset": dataset,
                "parameter_name": "radial_load",
                "parameter_expression": "radial_load/1[N]",
                "parameter_unit": "N",
                "selected_parameter_value_n": spec.target_radial_load_n,
                "solution_number": 1,
                "stress": stress,
                "displacement": {
                    **stress,
                    "value": 1e-7,
                    "expression": "solid.disp/1[m]",
                    "base_expression": "solid.disp",
                    "unit": "m",
                },
            },
            "native_plot": "plot.png",
            "native_plot_evidence": {
                "success": True,
                "expression": "solid.mises",
                "unit": "Pa",
                "dataset": dataset,
                "solution_number": 1,
                "numerical_max_pa": 45000.0,
            },
            "solver_evidence": {
                "requested": spec.solver_relative_tolerance,
                "bindings": [
                    {
                        "property": "stol",
                        "actual": spec.solver_relative_tolerance,
                    }
                ],
            },
            "solved_mph": "solved.mph",
        }


_SPEC = BearingSpec(
    roller_count=10,
    inner_diameter_mm=45,
    outer_diameter_mm=90,
    bearing_width_mm=20,
    roller_diameter_mm=7.5,
    roller_length_mm=17,
    pitch_radius_mm=34,
    inner_race_outer_radius_mm=29.5,
    outer_race_inner_radius_mm=38.5,
    cage_inner_radius_mm=29.8,
    cage_outer_radius_mm=38.2,
    cage_pocket_clearance_mm=0.3,
    radial_clearance_mm=1.5,
    roller_phase_deg=7.5,
    load_direction=LoadDirection.POSITIVE_X,
    target_radial_load_n=1.0,
)


def _registry() -> ExtensionRegistry:
    root = Path(__file__).resolve().parents[1]
    return ExtensionRegistry(
        ExtensionLoader(
            compatibility=CompatibilityPolicy(agent_version="2.0", comsol_version="6.2"),
            permissions=PermissionPolicy(
                PermissionSet(
                    filesystem="write", shell="none", comsol="solve", network="none"
                )
            ),
            trusted_manifest_roots=(root,),
            trusted_code_roots=(root,),
        )
    )


async def _setup(tmp_path: Path):
    backend = WorkflowBackend()
    runtime = ComsolRuntime(
        backend=backend,
        artifacts=ArtifactStore(tmp_path),
        worker=FakeWorkerExecutor(backend),
    )
    registry = _registry()
    for extension in bearing_extensions():
        await registry.register(extension)
    workflow = BearingWorkflowTool(runtime)
    await registry.register(workflow)
    snapshot = registry.snapshot()
    workflow.bind_snapshot(snapshot)
    return backend, snapshot


async def _plan(snapshot, goal: GoalSpec, current: BearingSpec | None, requested: BearingSpec):
    route = "deterministic_rebuild" if current is None else "parameter_override"
    capability = (
        "bearing.cylindrical-roller.build"
        if current is None
        else "bearing.parameter-override"
    )
    output = {
        "route": route,
        "rationale": "deterministic policy",
        "cited_context_ids": [],
        "requested_capabilities": [capability],
    }
    return await BearingPlanner(ModelGateway(FakeModelBackend([output]))).plan(
        goal=goal,
        requested=requested,
        current=current,
        registry_snapshot=snapshot,
        budget={"max_solves": 3},
    )


@pytest.mark.asyncio
async def test_fake_runtime_rebuild_closes_through_kernel_and_strict_audits(
    tmp_path: Path,
) -> None:
    backend, snapshot = await _setup(tmp_path)
    try:
        goal = GoalSpec(objective="build bearing", constraints={"model_id": "bearing-e2e"})
        planned = await _plan(snapshot, goal, None, _SPEC)
        manifest = await AgentKernel(RegistryToolExecutor(snapshot)).run(goal, planned.plan)
    finally:
        await snapshot.close()
    assert manifest.status == RunStatus.COMPLETED
    assert manifest.plan.steps[0].status == StepStatus.COMPLETE
    observation = manifest.action_records[0].observation
    assert observation.data["strict_audit_passed"] is True
    assert set(observation.data["audits"]) == {
        "bearing.geometry.audit",
        "bearing.selection.audit",
        "bearing.contact.audit",
        "bearing.physics.audit",
    }
    assert backend.build_calls == 1
    assert any(call[0] == "registered" for call in backend.calls)
    assert manifest.checkpoints


@pytest.mark.asyncio
async def test_override_carries_full_specs_restores_b_and_skips_rebuild(tmp_path: Path) -> None:
    backend, snapshot = await _setup(tmp_path)
    try:
        first_goal = GoalSpec(objective="build", constraints={"model_id": "bearing-stable"})
        first_plan = await _plan(snapshot, first_goal, None, _SPEC)
        first = await AgentKernel(RegistryToolExecutor(snapshot)).run(
            first_goal, first_plan.plan
        )
        checkpoint = first.checkpoints[0]
        requested = _SPEC.model_copy(
            update={"target_radial_load_n": 10.0, "load_direction": LoadDirection.NEGATIVE_Y}
        )
        second_goal = GoalSpec(
            objective="change load",
            constraints={
                "model_id": "bearing-stable",
                "resume_checkpoint": checkpoint,
            },
        )
        second_plan = await _plan(snapshot, second_goal, _SPEC, requested)
        action = second_plan.plan.steps[0].action
        assert action.arguments["previous"]["target_radial_load_n"] == 1.0
        assert action.arguments["requested"]["target_radial_load_n"] == 10.0
        second = await AgentKernel(RegistryToolExecutor(snapshot)).run(
            second_goal, second_plan.plan
        )
    finally:
        await snapshot.close()
    assert second.status == RunStatus.COMPLETED
    assert backend.build_calls == 1
    registered = [value for name, value in backend.calls if name == "registered"]
    assert any(value[3] == "bearing.parameter-override" for value in registered)
    assert any(name == "restore" for name, _ in backend.calls)


@pytest.mark.asyncio
async def test_forged_binding_and_permission_fail_before_comsol(tmp_path: Path) -> None:
    backend, snapshot = await _setup(tmp_path)
    try:
        goal = GoalSpec(objective="build")
        planned = await _plan(snapshot, goal, None, _SPEC)
        action = planned.plan.steps[0].action
        calls_before = len(backend.calls)
        forged = action.model_copy(deep=True)
        forged.arguments["bindings"][0]["extension_version"] = "9.0.0"
        denied = action.model_copy(update={"permissions": frozenset({"shell:execute"})})
        executor = RegistryToolExecutor(snapshot)
        forged_observation = await executor.execute(forged, AgentKernel(executor).cancellation)
        denied_observation = await executor.execute(denied, AgentKernel(executor).cancellation)
    finally:
        await snapshot.close()
    assert not forged_observation.success
    assert forged_observation.error_class == "extension_failure"
    assert denied_observation.error_class == "permission_denied"
    assert len(backend.calls) == calls_before


@pytest.mark.asyncio
async def test_noop_executes_plan_without_any_comsol_call(tmp_path: Path) -> None:
    backend, snapshot = await _setup(tmp_path)
    try:
        output = {
            "route": "noop",
            "rationale": "unchanged",
            "cited_context_ids": [],
            "requested_capabilities": ["bearing.workflow.execute"],
        }
        goal = GoalSpec(objective="keep model")
        planned = await BearingPlanner(
            ModelGateway(FakeModelBackend([output]))
        ).plan(
            goal=goal,
            requested=_SPEC,
            current=_SPEC,
            registry_snapshot=snapshot,
            budget={},
        )
        manifest = await AgentKernel(RegistryToolExecutor(snapshot)).run(
            goal, planned.plan
        )
    finally:
        await snapshot.close()
    assert manifest.status == RunStatus.COMPLETED
    assert manifest.action_records[0].observation.data["comsol_called"] is False
    assert backend.calls == []


@pytest.mark.asyncio
async def test_invalid_action_schema_and_capability_fail_before_comsol(
    tmp_path: Path,
) -> None:
    backend, snapshot = await _setup(tmp_path)
    try:
        goal = GoalSpec(objective="build")
        planned = await _plan(snapshot, goal, None, _SPEC)
        action = planned.plan.steps[0].action
        malformed = action.model_copy(deep=True)
        del malformed.arguments["requested"]
        forged = action.model_copy(deep=True)
        forged.arguments["bindings"][1]["capability"] = "bearing.forged.build"
        executor = RegistryToolExecutor(snapshot)
        malformed_observation = await executor.execute(
            malformed, AgentKernel(executor).cancellation
        )
        forged_observation = await executor.execute(
            forged, AgentKernel(executor).cancellation
        )
    finally:
        await snapshot.close()
    assert malformed_observation.error_class == "contract_violation"
    assert malformed_observation.exception_type == "InvalidExtensionInput"
    assert not forged_observation.success
    assert len(backend.calls) == 0


def test_llm_gate_has_no_legacy_subprocess_bypass() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "run_v2_llm_gate.py"
    ).read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "subprocess.run" not in source
    assert "run_v2_bearing_gate.py" not in source
    assert "AgentKernel(RegistryToolExecutor(snapshot)).run" in source


@pytest.mark.asyncio
async def test_failed_observation_enters_bounded_m6_without_raw_retry(
    tmp_path: Path,
) -> None:
    _, snapshot = await _setup(tmp_path)
    try:
        observation = Observation(
            action_id="failed-action",
            success=False,
            status="timed_out",
            stage="bearing_workflow",
            error_class="timeout",
            retryable=False,
            data={
                "failure": {
                    "error_class": "timeout",
                    "code": "TIMEOUT",
                    "message": "solve exceeded 1200s",
                    "stage": "C_solve",
                    "retryable": True,
                    "termination_confirmed": False,
                    "causes": [
                        {
                            "exception_type": "WorkerTimeoutError",
                            "message": "solve exceeded 1200s",
                        }
                    ],
                }
            },
            source=SourceRef(kind="function", identifier="bearing.workflow.execute"),
        )
        routed = await ObservationRepairRouter(snapshot).route(
            observation, AgentKernel(RegistryToolExecutor(snapshot)).cancellation
        )
    finally:
        await snapshot.close()
    assert routed["bounded"] is True
    assert routed["raw_action_retry"] is False
    assert routed["diagnosis"]["error_code"] == "TIMEOUT"
    assert routed["diagnosis"]["allowed_repair_kinds"] == []
    assert routed["result"]["status"] == RepairStatus.USER_DECISION_REQUIRED.value
