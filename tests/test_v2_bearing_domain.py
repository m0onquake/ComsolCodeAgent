"""M7 contracts, deterministic paths, builders, auditors and extensions."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from comsol_agent.v2.domains.bearing import (
    BearingContactAuditor,
    BearingEngineeringPreviewAuditor,
    BearingGeometryAuditor,
    BearingPhysicalAuditor,
    BearingSelectionAuditor,
    BearingSpec,
    ChangeRoute,
    ContinuationProfile,
    DynamicLoadContinuation,
    LoadDirection,
    ParameterOverridePath,
    bearing_extensions,
    classify_changes,
)
from comsol_agent.v2.domains.bearing.builder import build_plan, deterministic_model_code
from comsol_agent.v2.domains.bearing.results import evaluate_target_results
from comsol_agent.v2.domains.bearing.solver import apply_solver_relative_tolerance
from comsol_agent.v2.domains.bearing.verified_asset import ASSET_SHA256, reviewed_asset_code
from comsol_agent.v2.extensions import (
    CompatibilityPolicy,
    ExtensionKind,
    ExtensionLoader,
    ExtensionRegistry,
    PermissionPolicy,
    PermissionSet,
    ResolutionContext,
)


def variant(**changes: object) -> BearingSpec:
    values = BearingSpec().model_dump(exclude={"topology_signature", "build_signature"})
    values.update(changes)
    if {"pitch_radius_mm", "roller_diameter_mm", "radial_clearance_mm"} & changes.keys():
        pitch = float(values["pitch_radius_mm"])
        radius = float(values["roller_diameter_mm"]) / 2
        clearance = float(values["radial_clearance_mm"]) / 2
        if "inner_race_outer_radius_mm" not in changes:
            values["inner_race_outer_radius_mm"] = pitch - radius - clearance
        if "outer_race_inner_radius_mm" not in changes:
            values["outer_race_inner_radius_mm"] = pitch + radius + clearance
    return BearingSpec.model_validate(values)


def spec_input(spec: BearingSpec) -> dict[str, object]:
    return spec.model_dump(exclude={"topology_signature", "build_signature"})


def result_evidence(spec: BearingSpec) -> dict[str, object]:
    dataset = "dset7"
    solution_number = 2
    stress = {
        "success": True,
        "value": 4.5e4,
        "expression": "solid.mises/1[Pa]",
        "base_expression": "solid.mises",
        "unit": "Pa",
        "dataset": dataset,
        "solution_number": solution_number,
        "node_tag": "v2_target_max_mises",
        "node_kind": "MaxVolume",
        "source": "java:MaxVolume.getReal",
        "solution_bindings": [{"property": "solnum", "value": "2"}],
    }
    return {
        "success": True,
        "dataset": dataset,
        "parameter_name": "radial_load",
        "parameter_expression": "radial_load/1[N]",
        "parameter_unit": "N",
        "selected_parameter_value_n": spec.target_radial_load_n,
        "solution_number": solution_number,
        "stress": stress,
        "displacement": {
            **stress,
            "value": 1e-7,
            "expression": "solid.disp/1[m]",
            "base_expression": "solid.disp",
            "unit": "m",
            "node_tag": "v2_target_max_displacement",
        },
    }


def test_bearing_spec_is_strict_versioned_and_rejects_impossible_geometry() -> None:
    schema = BearingSpec.model_json_schema()
    assert schema["additionalProperties"] is False
    assert BearingSpec().domain == "bearing"
    with pytest.raises(ValidationError, match="inner race radius"):
        BearingSpec(inner_race_outer_radius_mm=26)
    with pytest.raises(ValidationError, match="overlap"):
        BearingSpec(roller_count=24, cage_pocket_clearance_mm=2)


@pytest.mark.parametrize(
    ("changes", "route"),
    [
        ({"target_radial_load_n": 101.0}, ChangeRoute.PARAMETER_OVERRIDE),
        ({"roller_phase_deg": 15.0}, ChangeRoute.DETERMINISTIC_REBUILD),
        ({"load_direction": LoadDirection.NEGATIVE_Y}, ChangeRoute.PARAMETER_OVERRIDE),
        ({"mesh_contact_size_mm": 1.8}, ChangeRoute.PARAMETER_OVERRIDE),
        ({"roller_count": 10}, ChangeRoute.DETERMINISTIC_REBUILD),
    ],
)
def test_supported_changes_never_route_to_full_llm(
    changes: dict[str, object], route: ChangeRoute
) -> None:
    change_set = classify_changes(BearingSpec(), variant(**changes))
    assert change_set.route == route
    assert change_set.topology_unchanged
    assert change_set.requires_llm is False


def test_geometry_change_is_typed_parameter_override() -> None:
    changed = variant(
        inner_diameter_mm=42,
        outer_diameter_mm=82,
        bearing_width_mm=20,
        roller_length_mm=18,
    )
    plan = ParameterOverridePath().plan(BearingSpec(), changed)
    assert plan["route"] == "deterministic_rebuild"
    assert plan["parameter_patch"]["inner_diameter"] == "42[mm]"
    assert plan["parameter_patch"]["roller_length"] == "18[mm]"
    assert plan["llm_calls"] == 0
    assert plan["restore_checkpoint"] is None


def test_roller_count_uses_deterministic_rebuild_not_parameter_patch_or_llm() -> None:
    plan = ParameterOverridePath().plan(BearingSpec(), variant(roller_count=10))
    assert plan["route"] == "deterministic_rebuild"
    assert plan["requires_builder"] is True
    assert plan["llm_calls"] == 0


def test_solver_tolerance_plan_is_not_an_empty_parameter_override() -> None:
    changed = variant(solver_relative_tolerance=0.01)
    plan = ParameterOverridePath().plan(BearingSpec(), changed)
    assert plan["route"] == "parameter_override"
    assert plan["parameter_patch"] == {}
    assert plan["solver_patch"] == {"stationary.stol": 0.01}


def test_builder_has_exact_a_d_plan_and_specializes_reviewed_asset() -> None:
    spec = BearingSpec(
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
        target_radial_load_n=1.0,
    )
    plan = build_plan(spec)
    assert [stage.stage[0] for stage in plan.stages] == ["A", "B", "C", "D"]
    assert plan.llm_calls == 0
    code = deterministic_model_code(spec)
    assert "contact_all_rollers_inner.selection().named" not in code
    assert "contact_all_rollers_outer.selection().named" not in code
    assert ".set('data', 'dset1')" not in code
    assert "model.param().set('roller_count', '10')" in code
    assert "for i in range(roller_count)" in code
    assert "model.param().set('roller_angular_offset_deg', '7.5[deg]')" in code
    assert "model.param().set('radial_load', '1[N]')" in code


def test_bundled_reviewed_asset_is_content_addressed() -> None:
    raw = reviewed_asset_code().encode("utf-8")
    assert hashlib.sha256(raw).hexdigest() == ASSET_SHA256


def test_builder_specializes_reviewed_strict_asset_for_roller_count_and_geometry() -> None:
    spec = variant(
        roller_count=12,
        pitch_radius_mm=35,
        roller_diameter_mm=8,
        roller_length_mm=16,
        cage_inner_radius_mm=31.2,
        cage_outer_radius_mm=38.8,
        roller_phase_deg=15,
    )
    code = deterministic_model_code(spec)
    assert "model.param().set('roller_count', '12')" in code
    assert "num_rollers = 12" in code
    assert "roller_count = 12" in code
    assert "for i in range(12):" in code
    assert code.count("pitch_radius_mm = 35") == 2
    assert code.count("roller_diameter_mm = 8") == 2
    assert code.count("roller_length_mm = 16") == 2
    assert code.count("offset_deg = 15") == 2
    assert "comp.selection('box_inner_raceway').set('xmin', '30.9[mm]')" in code
    assert "comp.selection('box_inner_raceway').set('xmax', '31.1[mm]')" in code
    assert "comp.selection('box_outer_raceway').set('xmin', '38.9[mm]')" in code
    assert "comp.selection('box_outer_raceway').set('xmax', '39.1[mm]')" in code
    assert "comp.selection('box_outer_support').set('xmin', '39.9[mm]')" in code
    assert "comp.selection('box_outer_support').set('xmax', '40.1[mm]')" in code
    assert "comp.selection('box_inner_bore').set('xmin', '-20.1[mm]')" in code
    assert "comp.selection('box_inner_bore').set('zmax', '9.1[mm]')" in code
    assert "comp.selection(box_inner_tag).set('zmin', '-7.4[mm]')" in code
    assert "comp.selection(box_outer_tag).set('zmax', '7.4[mm]')" in code
    for stale in ("29.4[mm]", "29.6[mm]", "38.4[mm]", "38.6[mm]", "44.9[mm]", "45.1[mm]"):
        assert stale not in code
    assert "sel_all_roller_boundaries" in code
    assert "cp_all_rollers_inner" in code
    assert "contact_all_rollers_inner" in code
    assert "sel_roller_{n}_boundary" in code
    assert "intop_roller_{n}" in code


@pytest.mark.parametrize("direction", list(LoadDirection))
def test_builder_direction_and_continuation_are_deterministic(direction: LoadDirection) -> None:
    spec = variant(load_direction=direction, roller_phase_deg=15)
    code = deterministic_model_code(spec)
    axis = 0 if direction.value.endswith("X") else 1
    sign = "-" if direction.value.startswith("-") else ""
    vector = ["0", "0", "0"]
    direction_vector = ["0", "0", "0"]
    guidance_vector = ["1[N/m^3]", "1[N/m^3]", "1[N/m^3]"]
    vector[axis] = sign + "radial_load/(pi*inner_diameter*bearing_width)"
    direction_vector[axis] = "1"
    guidance_vector[axis] = "1e4[N/m^3]"
    assert f"set('FperArea', {vector!r})" in code
    assert f"preload_inner_radial.set('Direction', {direction_vector!r})" in code
    assert f"spring_inner_ring_guidance.set('kPerArea', {guidance_vector!r})" in code
    continuation = DynamicLoadContinuation().plan(spec)
    assert continuation.target_n == spec.target_radial_load_n
    assert continuation.chunks[-1].values_n[-1] == spec.target_radial_load_n
    assert continuation.max_solves == len(continuation.chunks)
    assert continuation.max_solves <= 2


class _FakeNode:
    def __init__(self, values: list[float] | None = None) -> None:
        self.properties: dict[str, object] = {}
        self.values = values or []

    def set(self, name: str, value: object) -> None:
        self.properties[name] = value

    def selection(self) -> _FakeNode:
        return self

    def all(self) -> None:
        self.properties["selection"] = "all"

    def getDouble(self, name: str) -> float:  # noqa: N802 - mirrors COMSOL Java API
        return float(self.properties[name])

    def getReal(self) -> list[list[float]]:  # noqa: N802 - mirrors COMSOL Java API
        if {"looplevel", "solnum", "outersolnum"} & self.properties.keys():
            return [[self.values[-1]]]
        return [self.values]


class _FakeNumerical:
    def __init__(self) -> None:
        self.nodes: dict[str, _FakeNode] = {}

    def tags(self) -> list[str]:
        return list(self.nodes)

    def remove(self, tag: str) -> None:
        self.nodes.pop(tag, None)

    def create(self, tag: str, kind: str) -> None:
        values = {
            "EvalGlobal": [0.5, 1.0],
            "MaxVolume": [100.0, 4.5e4],
        }[kind]
        self.nodes[tag] = _FakeNode(values)


class _FakeResult:
    def __init__(self) -> None:
        self.container = _FakeNumerical()

    def numerical(self, tag: str | None = None) -> object:
        return self.container if tag is None else self.container.nodes[tag]


class _FakeSolution:
    def __init__(self) -> None:
        self.stationary = _FakeNode()

    def feature(self, tag: str) -> _FakeNode:
        assert tag == "s1"
        return self.stationary


class _FakeSolutionContainer:
    def __init__(self, solutions: dict[str, _FakeSolution]) -> None:
        self.solutions = solutions

    def tags(self) -> list[str]:
        return list(self.solutions)


class _FakeJavaModel:
    def __init__(self) -> None:
        self.results = _FakeResult()
        self.solutions = {"sol1": _FakeSolution()}

    def result(self) -> _FakeResult:
        return self.results

    def sol(self, tag: str | None = None) -> object:
        return (
            _FakeSolutionContainer(self.solutions)
            if tag is None
            else self.solutions[tag]
        )


def test_solver_tolerance_execution_changes_and_reads_back_stationary_node() -> None:
    java = _FakeJavaModel()
    bindings = apply_solver_relative_tolerance(java, 0.01)
    assert bindings == (
        {
            "solution_tag": "sol1",
            "feature_tag": "s1",
            "property": "stol",
            "requested": 0.01,
            "actual": 0.01,
            "source": "java:Solution/Stationary.set+readback",
        },
    )
    assert java.solutions["sol1"].stationary.properties["stol"] == 0.01


@pytest.mark.parametrize("invalid", [0.0, -1.0, float("inf"), 0.100001])
def test_solver_tolerance_execution_rejects_invalid_values(invalid: float) -> None:
    with pytest.raises(ValueError, match="relative tolerance"):
        apply_solver_relative_tolerance(_FakeJavaModel(), invalid)


def test_target_results_bind_dataset_parameter_step_units_and_solution() -> None:
    evidence = evaluate_target_results(
        _FakeJavaModel(), dataset="dset7", target_load_n=1.0
    )
    assert evidence["selected_parameter_value_n"] == 1.0
    assert evidence["solution_number"] == 2
    assert evidence["stress"]["expression"] == "solid.mises/1[Pa]"
    assert evidence["stress"]["value"] == 4.5e4
    assert evidence["displacement"]["expression"] == "solid.disp/1[m]"


class _FakeFeatureOwner:
    def __init__(self) -> None:
        self.nodes: dict[str, _FakeNode] = {}

    def feature(self, tag: str) -> _FakeNode:
        return self.nodes.setdefault(tag, _FakeNode())


class _FakeComponent:
    def __init__(self) -> None:
        self.physics_owner = _FakeFeatureOwner()

    def physics(self, tag: str) -> _FakeFeatureOwner:
        assert tag == "solid"
        return self.physics_owner


class _FakeExecutionJava(_FakeJavaModel):
    def __init__(self) -> None:
        super().__init__()
        self.component_owner = _FakeComponent()
        self.study_owner = _FakeFeatureOwner()

    def component(self, tag: str) -> _FakeComponent:
        assert tag == "comp1"
        return self.component_owner

    def study(self, tag: str) -> _FakeFeatureOwner:
        assert tag == "std1"
        return self.study_owner


class _FakeMphModel:
    def __init__(self) -> None:
        self.java = _FakeExecutionJava()
        self.parameters: dict[str, str] = {}

    def parameter(self, name: str, value: str) -> None:
        self.parameters[name] = value


@pytest.mark.parametrize("direction", list(LoadDirection))
def test_parameter_override_executes_load_mesh_direction_and_tolerance(
    direction: LoadDirection,
) -> None:
    previous = BearingSpec()
    requested = variant(
        load_direction=direction,
        target_radial_load_n=25.0,
        mesh_bulk_size_mm=4.0,
        mesh_contact_size_mm=2.0,
        solver_relative_tolerance=0.01,
    )
    mph_model = _FakeMphModel()
    handle = SimpleNamespace(mph_model=mph_model, is_modified=False)
    result = ParameterOverridePath().execute_model(
        handle,
        {
            "previous": spec_input(previous),
            "requested": spec_input(requested),
        },
    )
    assert mph_model.parameters == {
        "radial_load": "25[N]",
        "mesh_bulk_size": "4[mm]",
        "mesh_contact_size": "2[mm]",
    }
    assert result["solver_bindings"][0]["actual"] == 0.01
    axis = 0 if direction.value.endswith("X") else 1
    sign = "-" if direction.value.startswith("-") else ""
    expected_load = ["0", "0", "0"]
    expected_load[axis] = sign + "radial_load/(pi*inner_diameter*bearing_width)"
    if direction != previous.load_direction:
        physics = mph_model.java.component_owner.physics_owner
        assert physics.nodes["load_inner_bore"].properties["FperArea"] == expected_load
    assert handle.is_modified


def test_dynamic_continuation_execute_binds_all_values_and_inheritance() -> None:
    spec = variant(target_radial_load_n=2.0)
    mph_model = _FakeMphModel()
    handle = SimpleNamespace(mph_model=mph_model, is_modified=False)
    result = DynamicLoadContinuation().execute_model(
        handle, {"spec": spec_input(spec)}
    )
    stat = mph_model.java.study_owner.nodes["stat"].properties
    assert stat["pname"] == ["radial_load"]
    assert stat["punit"] == ["N"]
    assert stat["preusesol"] == "yes"
    assert float(stat["plistarr"][0].split()[-1]) == spec.target_radial_load_n
    assert result["target_n"] == 2.0


def test_engineering_preview_uses_one_sparse_scaled_solve_and_preview_tolerance() -> None:
    spec = variant(
        target_radial_load_n=5.0,
        load_direction=LoadDirection.POSITIVE_Y,
        solver_relative_tolerance=1.0e-3,
    )
    mph_model = _FakeMphModel()
    handle = SimpleNamespace(mph_model=mph_model, is_modified=False)
    result = DynamicLoadContinuation().execute_model(
        handle,
        {
            "spec": spec_input(spec),
            "profile": ContinuationProfile.ENGINEERING_PREVIEW,
        },
    )
    assert result["profile"] == "engineering_preview"
    assert result["max_solves"] == 1
    assert result["chunks"] == [
        {
            "values_n": [0.0001, 0.05, 0.5, 5.0],
            "reuse_previous_solution": True,
        }
    ]
    assert result["effective_solver_relative_tolerance"] == 1.0e-2
    assert result["success_criteria"][-1] == "engineering_preview_audit_passed"
    assert mph_model.java.solutions["sol1"].stationary.properties["stol"] == 1.0e-2


def test_engineering_preview_collector_does_not_enter_legacy_strict_resolve(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from comsol_agent.v2.domains.bearing import runtime_audit

    collector = runtime_audit.ReviewedStrictAuditCollector(
        BearingSpec(),
        tmp_path,
        case_id="preview-no-resolve",
        acceptance_mode="engineering_preview",
    )
    legacy_marker = object()
    monkeypatch.setattr(runtime_audit, "_reviewed_runtime_module", lambda: legacy_marker)
    monkeypatch.setattr(
        collector,
        "_engineering_preview",
        lambda handle, legacy: {
            "passed": True,
            "same_handle": handle == "already-solved",
            "same_legacy": legacy is legacy_marker,
        },
    )
    assert collector("already-solved") == {
        "passed": True,
        "same_handle": True,
        "same_legacy": True,
    }


def test_builder_rejects_ambiguous_critical_replacements(monkeypatch: pytest.MonkeyPatch) -> None:
    from comsol_agent.v2.domains.bearing import builder as builder_module

    original = reviewed_asset_code()
    load_line = "set('FperArea', ['radial_load/(pi*inner_diameter*bearing_width)', '0', '0'])"
    assert load_line in original
    monkeypatch.setattr(
        builder_module,
        "reviewed_asset_code",
        lambda: original + "\nmodel.component('comp1').physics('solid').feature('duplicate')."
        + load_line,
    )
    spec = BearingSpec(
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
        target_radial_load_n=1.0,
    )
    with pytest.raises(RuntimeError, match="radial load vector.*found 2"):
        deterministic_model_code(spec)


@pytest.mark.asyncio
async def test_separate_geometry_selection_contact_and_physics_auditors() -> None:
    spec = BearingSpec()
    assert (await BearingGeometryAuditor().audit(spec))["passed"]
    selections = {
        tag: {"entity_count": 1}
        for tag in [
            "sel_inner_raceway_contact",
            "sel_outer_raceway_contact",
            "sel_all_roller_inner_contacts",
            "sel_all_roller_outer_contacts",
            "sel_inner_bore_load_surface",
            "sel_outer_support_surface",
            *[f"sel_roller_{index}_body" for index in range(1, 13)],
        ]
    }
    assert (await BearingSelectionAuditor().audit({"spec": spec, "selections": selections}))[
        "passed"
    ]
    pairs = {
        "cp_all_rollers_inner": {
            "source_named": "sel_all_roller_inner_contacts",
            "destination_named": "sel_inner_raceway_contact",
            "source_entity_count": 12,
            "destination_entity_count": 2,
        },
        "cp_all_rollers_outer": {
            "source_named": "sel_all_roller_outer_contacts",
            "destination_named": "sel_outer_raceway_contact",
            "source_entity_count": 12,
            "destination_entity_count": 2,
        },
    }
    assert (await BearingContactAuditor().audit({"pairs": pairs}))["passed"]
    results = result_evidence(spec)
    physical = await BearingPhysicalAuditor().audit(
        {
            "spec": spec,
            "metrics": {
                "returned_target_load_n": spec.target_radial_load_n,
                "applied_load_n": spec.target_radial_load_n,
                "support_reaction_n": -spec.target_radial_load_n,
                "outer_contact_resultant_n": spec.target_radial_load_n * 0.999,
                "stabilization_force_n": spec.target_radial_load_n * 1e-5,
                "loaded_zone_direction": "+X",
            },
            "native_plot": "artifact://plot.png",
            "native_plot_evidence": {
                "success": True,
                "expression": "solid.mises",
                "unit": "Pa",
                "dataset": results["dataset"],
                "solution_number": results["solution_number"],
                "numerical_max_pa": results["stress"]["value"],
            },
            "result_evidence": results,
            "solver_evidence": {
                "requested": spec.solver_relative_tolerance,
                "bindings": [
                    {
                        "property": "stol",
                        "actual": spec.solver_relative_tolerance,
                    }
                ],
            },
            "solved_mph": "artifact://solved.mph",
        }
    )
    assert physical["passed"]
    assert len(physical["checks"]) == 14


@pytest.mark.asyncio
async def test_physics_auditor_does_not_accept_solve_without_force_evidence() -> None:
    result = await BearingPhysicalAuditor().audit(
        {
            "spec": BearingSpec(),
            "metrics": {"max_von_mises_pa": 1e6, "max_displacement_m": 1e-7},
            "native_plot": "artifact://plot.png",
            "solved_mph": "artifact://solved.mph",
        }
    )
    assert not result["passed"]
    assert "target_step_returned" in result["errors"]
    assert "support_reaction_balance" in result["errors"]


@pytest.mark.asyncio
async def test_engineering_preview_accepts_approximate_stress_without_force_balance() -> None:
    spec = BearingSpec()
    results = result_evidence(spec)
    subject = {
        "spec": spec,
        "metrics": {
            "returned_target_load_n": spec.target_radial_load_n,
            "applied_load_n": spec.target_radial_load_n,
            "support_reaction_n": spec.target_radial_load_n * 0.5,
            "outer_contact_resultant_n": spec.target_radial_load_n * 0.4,
            "stabilization_force_n": spec.target_radial_load_n * 0.2,
            "loaded_zone_direction": "-Y",
        },
        "result_evidence": results,
        "solver_evidence": {
            "requested": spec.solver_relative_tolerance,
            "bindings": [
                {
                    "property": "stol",
                    "actual": spec.solver_relative_tolerance,
                }
            ],
        },
        "native_plot": "artifact://plot.png",
        "native_plot_evidence": {
            "success": True,
            "expression": "solid.mises",
            "unit": "Pa",
            "dataset": results["dataset"],
            "solution_number": results["solution_number"],
            "numerical_max_pa": results["stress"]["value"],
        },
        "preview_policy": {
            "expected_pa": results["stress"]["value"] * 1.1,
            "relative_tolerance": 0.2,
        },
        "strict_balance_errors": [
            "support_reaction_balance",
            "outer_contact_balance",
            "stabilization_ratio",
            "loaded_zone_direction",
        ],
        "solved_mph": "artifact://solved.mph",
    }

    strict = await BearingPhysicalAuditor().audit(subject)
    preview = await BearingEngineeringPreviewAuditor().audit(subject)

    assert strict["passed"] is False
    assert preview["passed"] is True
    assert preview["evidence"]["promotion_eligible"] is False
    assert set(preview["evidence"]["strict_balance_warnings"]) == {
        "support_reaction_balance",
        "outer_contact_balance",
        "stabilization_ratio",
        "loaded_zone_direction",
    }


@pytest.mark.asyncio
async def test_engineering_preview_rejects_stress_outside_configured_range() -> None:
    spec = BearingSpec()
    results = result_evidence(spec)
    results["stress"]["value"] = 5.0e10
    preview = await BearingEngineeringPreviewAuditor().audit(
        {
            "spec": spec,
            "result_evidence": results,
            "native_plot": "artifact://plot.png",
            "native_plot_evidence": {
                "success": True,
                "expression": "solid.mises",
                "unit": "Pa",
                "dataset": results["dataset"],
                "solution_number": results["solution_number"],
                "numerical_max_pa": results["stress"]["value"],
            },
        }
    )

    assert preview["passed"] is False
    assert "approximate_stress" in preview["errors"]


@pytest.mark.asyncio
async def test_physics_auditor_rejects_cross_dataset_stress_and_plot() -> None:
    spec = BearingSpec()
    results = result_evidence(spec)
    plot = {
        "success": True,
        "expression": "solid.mises",
        "unit": "Pa",
        "dataset": "dset_wrong",
        "solution_number": results["solution_number"],
        "numerical_max_pa": results["stress"]["value"],
    }
    result = await BearingPhysicalAuditor().audit(
        {
            "spec": spec,
            "metrics": {
                "returned_target_load_n": spec.target_radial_load_n,
                "applied_load_n": spec.target_radial_load_n,
                "support_reaction_n": spec.target_radial_load_n,
                "outer_contact_resultant_n": spec.target_radial_load_n,
                "stabilization_force_n": 0.0,
                "loaded_zone_direction": "+X",
            },
            "result_evidence": results,
            "solver_evidence": {
                "requested": spec.solver_relative_tolerance,
                "bindings": [
                    {
                        "property": "stol",
                        "actual": spec.solver_relative_tolerance,
                    }
                ],
            },
            "native_plot": "artifact://plot.png",
            "native_plot_evidence": plot,
            "solved_mph": "artifact://solved.mph",
        }
    )
    assert not result["passed"]
    assert "native_plot" in result["errors"]


def registry() -> ExtensionRegistry:
    root = Path(__file__).resolve().parents[1]
    permissions = PermissionSet(
        filesystem="write", shell="execute", comsol="solve", network="server"
    )
    loader = ExtensionLoader(
        trusted_manifest_roots=[root],
        trusted_code_roots=[root],
        compatibility=CompatibilityPolicy(agent_version="2.0", comsol_version="6.2"),
        permissions=PermissionPolicy(permissions),
    )
    return ExtensionRegistry(loader)


@pytest.mark.asyncio
async def test_all_bearing_extension_kinds_register_resolve_disable_and_remove() -> None:
    selected = registry()
    extensions = bearing_extensions()
    for extension in extensions:
        await selected.register(extension)
    async with selected.snapshot() as snapshot:
        builder = snapshot.resolve(
            ExtensionKind.BUILDER,
            "bearing.cylindrical-roller.build",
            ResolutionContext(domain="bearing", signature={"family": "cylindrical_roller"}),
        )
        assert len(builder) == 1
        paths = snapshot.candidates(
            ExtensionKind.DETERMINISTIC_PATH,
            "bearing.parameter-override",
            ResolutionContext(domain="bearing"),
        )
        assert len(paths) == 1
    await selected.disable("bearing.cylindrical-roller.skill")
    selected.unregister("bearing.cylindrical-roller.skill")
    assert len(extensions) == 9


@pytest.mark.asyncio
async def test_manifest_discovery_loads_complete_plugin_without_kernel_edits() -> None:
    selected = registry()
    manifest_root = (
        Path(__file__).resolve().parents[1]
        / "comsol_agent"
        / "v2"
        / "domains"
        / "bearing"
        / "manifests"
    )
    candidates = selected.discover([manifest_root])
    assert len(candidates) == 9
    assert all(selected.validate(candidate).valid for candidate in candidates)
    registrations = await selected.load_and_register(candidates)
    assert all(registration.error is None for registration in registrations)
    async with selected.snapshot() as snapshot:
        assert snapshot.versions["bearing.cylindrical-roller.builder"] == "1.0.0"
        assert snapshot.versions["bearing.cylindrical-roller.skill"] == "1.0.0"


def test_kernel_stays_domain_neutral() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in (root / "comsol_agent" / "v2" / "kernel").glob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert "bearing" not in source
        assert "roller" not in source
