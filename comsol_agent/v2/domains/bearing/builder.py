"""Deterministic A-D cylindrical-roller bearing builder.

The executable handler wraps a reviewed V1 fixture generator as a trusted asset.
The public input is a strict ``BearingSpec``; callers cannot submit code.
"""

from __future__ import annotations

import io
import re
from typing import Any

from pydantic import Field

from comsol_agent.v2.contracts.models import ContractModel

from .continuation import ContinuationPlan, build_continuation
from .models import BUILDER_VERSION, BearingSpec, LoadDirection
from .solver import apply_solver_relative_tolerance
from .verified_asset import reviewed_asset_code


class BuildStage(ContractModel):
    stage: str
    capability: str
    creates: tuple[str, ...]
    acceptance: tuple[str, ...]


class BearingBuildPlan(ContractModel):
    builder_id: str = "bearing.cylindrical-roller.builder"
    builder_version: str = BUILDER_VERSION
    specification: BearingSpec
    stages: tuple[BuildStage, ...] = Field(min_length=4, max_length=4)
    continuation: ContinuationPlan
    parameter_patch: dict[str, str]
    llm_calls: int = 0
    provenance: tuple[str, ...] = (
        "scripts/run_agent_3d_bearing_full_demo.py:_build_verified_3d_full_bearing_code",
        "reports/bearing_stage_evidence/freegen_parametric_family_validation_20260803.md",
    )


def build_plan(spec: BearingSpec) -> BearingBuildPlan:
    return BearingBuildPlan(
        specification=spec,
        stages=(
            BuildStage(
                stage="A_input_geometry",
                capability="bearing.geometry.build",
                creates=("inner_ring", "outer_ring", "cage", "rollers"),
                acceptance=("spec_valid", "geometry_relations_valid", "no_overlap"),
            ),
            BuildStage(
                stage="B_selections_contact_physics_mesh",
                capability="bearing.configured.build",
                creates=("named_selections", "global_contact_pairs", "solid", "mesh1"),
                acceptance=("selection_audit", "contact_audit", "mesh_built"),
            ),
            BuildStage(
                stage="C_dynamic_load_continuation",
                capability="bearing.continuation.solve",
                creates=("stationary_study", "continuation_solution"),
                acceptance=("target_load_reached", "solve_converged"),
            ),
            BuildStage(
                stage="D_results_physical_audit",
                capability="bearing.physical.audit",
                creates=("native_plot", "solved_mph", "audit_json"),
                acceptance=("strict_physics_audit", "artifacts_hashed"),
            ),
        ),
        continuation=build_continuation(spec),
        parameter_patch=spec.comsol_parameters(),
    )


def deterministic_model_code(spec: BearingSpec) -> str:
    """Return reviewed V1 setup code specialized without an LLM call."""
    if _matches_verified_param10_topology(spec):
        # The verified param10 source is bundled as a content-addressed asset,
        # so a clean installation does not depend on ignored runtime evidence.
        code = reviewed_asset_code()
    else:
        # Lazy import keeps V1 dependencies outside the V2 Kernel and outside
        # normal contract-only import paths. This deterministic fallback builds
        # supported candidate variants; only signatures passing a fresh strict
        # gate are marked verified.
        from scripts.run_agent_3d_bearing_full_demo import (
            _build_verified_3d_full_bearing_code,
        )

        code = _build_verified_3d_full_bearing_code(
            roller_count=spec.roller_count,
            roller_angular_offset_deg=spec.roller_phase_deg,
        )
    replacements = {
        "inner_diameter": f"{spec.inner_diameter_mm:.12g}[mm]",
        "outer_diameter": f"{spec.outer_diameter_mm:.12g}[mm]",
        "bearing_width": f"{spec.bearing_width_mm:.12g}[mm]",
        "roller_diameter": f"{spec.roller_diameter_mm:.12g}[mm]",
        "roller_length": f"{spec.roller_length_mm:.12g}[mm]",
        "pitch_radius": f"{spec.pitch_radius_mm:.12g}[mm]",
        "inner_race_outer_radius": f"{spec.inner_race_outer_radius_mm:.12g}[mm]",
        "outer_race_inner_radius": f"{spec.outer_race_inner_radius_mm:.12g}[mm]",
        "cage_inner_radius": f"{spec.cage_inner_radius_mm:.12g}[mm]",
        "cage_outer_radius": f"{spec.cage_outer_radius_mm:.12g}[mm]",
        "cage_pocket_clearance": f"{spec.cage_pocket_clearance_mm:.12g}[mm]",
        "radial_load": f"{spec.target_radial_load_n:.15g}[N]",
        "mesh_bulk_size": f"{spec.mesh_bulk_size_mm:.12g}[mm]",
        "mesh_contact_size": f"{spec.mesh_contact_size_mm:.12g}[mm]",
    }
    for name, value in replacements.items():
        pattern = rf"model\.param\(\)\.set\('{re.escape(name)}',\s*'[^']*'\);?"
        code = _replace_exact(
            code,
            pattern,
            f"model.param().set('{name}', '{value}')",
            label=f"model parameter {name}",
        )
    phase_pattern = r"model\.param\(\)\.set\('roller_angular_offset_deg',\s*'[^']*'\);?"
    code = _replace_or_prepend_parameter(
        code,
        phase_pattern,
        "roller_angular_offset_deg",
        f"{spec.roller_phase_deg:.12g}[deg]",
    )
    clearance_pattern = r"model\.param\(\)\.set\('radial_clearance',\s*'[^']*'\);?"
    clearance_count = len(re.findall(clearance_pattern, code))
    if clearance_count == 0:
        code = (
            f"model.param().set('radial_clearance', '{spec.radial_clearance_mm:.12g}[mm]');\n"
            + code
        )
    elif clearance_count == 1:
        code = re.sub(
            clearance_pattern,
            f"model.param().set('radial_clearance', '{spec.radial_clearance_mm:.12g}[mm]')",
            code,
        )
    else:
        raise RuntimeError(
            "deterministic builder replacement conflict for radial_clearance: "
            f"expected 0 or 1 matches, found {clearance_count}"
        )
    axis = 0 if spec.load_direction in {LoadDirection.POSITIVE_X, LoadDirection.NEGATIVE_X} else 1
    sign = (
        "-" if spec.load_direction in {LoadDirection.NEGATIVE_X, LoadDirection.NEGATIVE_Y} else ""
    )
    load_vector = ["0", "0", "0"]
    preload_vector = ["0", "0", "0"]
    load_vector[axis] = sign + "radial_load/(pi*inner_diameter*bearing_width)"
    preload_vector[axis] = sign + "inner_radial_displacement"
    code = _replace_exact(
        code,
        r"set\('FperArea',\s*\[[^\]]+\]\)",
        f"set('FperArea', {load_vector!r})",
        label="radial load vector",
    )
    code = _replace_exact(
        code,
        r"set\('U0',\s*\[[^\]]+\]\)",
        f"set('U0', {preload_vector!r})",
        label="preload displacement vector",
    )
    continuation = build_continuation(spec)
    load_values = " ".join(
        f"{value:.15g}" for chunk in continuation.chunks for value in chunk.values_n
    )
    continuation_pattern = r"set\('plistarr',\s*\[[^\]]+\]\)"
    continuation_count = len(re.findall(continuation_pattern, code))
    continuation_replacement = f"set('plistarr', [{load_values!r}])"
    if continuation_count == 1:
        code = re.sub(continuation_pattern, continuation_replacement, code)
    elif continuation_count == 0:
        code += (
            "\nmodel.study().create('std1')\n"
            "model.study('std1').feature().create('stat', 'Stationary')\n"
            "model.study('std1').feature('stat').set('activate', ['solid', 'on'])\n"
            "model.study('std1').feature('stat').set('useparam', 'on')\n"
            "model.study('std1').feature('stat').set('pname', ['radial_load'])\n"
            f"model.study('std1').feature('stat').{continuation_replacement}\n"
            "model.study('std1').feature('stat').set('punit', ['N'])\n"
            "model.study('std1').feature('stat').set('pcontinuationmode', 'manual')\n"
            "model.study('std1').feature('stat').set('pcontinuation', 'radial_load')\n"
            "model.study('std1').feature('stat').set('preusesol', 'yes')\n"
        )
    else:
        raise RuntimeError(
            "deterministic builder replacement conflict for radial load continuation: "
            f"expected 0 or 1 matches, found {continuation_count}"
        )
    return code


def _replace_exact(code: str, pattern: str, replacement: str, *, label: str) -> str:
    updated, count = re.subn(pattern, replacement, code)
    if count != 1:
        raise RuntimeError(
            f"deterministic builder replacement conflict for {label}: "
            f"expected 1 match, found {count}"
        )
    return updated


def _replace_or_prepend_parameter(
    code: str, pattern: str, name: str, value: str
) -> str:
    count = len(re.findall(pattern, code))
    replacement = f"model.param().set('{name}', '{value}')"
    if count == 0:
        return replacement + ";\n" + code
    if count == 1:
        return re.sub(pattern, replacement, code)
    raise RuntimeError(
        f"deterministic builder replacement conflict for model parameter {name}: "
        f"expected 0 or 1 matches, found {count}"
    )


def _matches_verified_param10_topology(spec: BearingSpec) -> bool:
    expected = {
        "roller_count": 10,
        "inner_diameter_mm": 45.0,
        "outer_diameter_mm": 90.0,
        "bearing_width_mm": 20.0,
        "roller_diameter_mm": 7.5,
        "roller_length_mm": 17.0,
        "pitch_radius_mm": 34.0,
        "inner_race_outer_radius_mm": 29.5,
        "outer_race_inner_radius_mm": 38.5,
        "cage_inner_radius_mm": 29.8,
        "cage_outer_radius_mm": 38.2,
        "cage_pocket_clearance_mm": 0.3,
        "radial_clearance_mm": 1.5,
        "roller_phase_deg": 7.5,
    }
    for field, value in expected.items():
        actual = getattr(spec, field)
        if isinstance(value, float):
            if not abs(float(actual) - value) <= 1e-12:
                return False
        elif actual != value:
            return False
    return True


class CylindricalRollerBearingBuilder:
    """Pure planning API plus a fixed COMSOL handler for PinnedExecutionCatalog."""

    async def build(self, specification: dict[str, Any]) -> dict[str, Any]:
        plan = build_plan(BearingSpec.model_validate(specification))
        return plan.model_dump(mode="json")

    def execute_model(self, handle: Any, specification: dict[str, Any]) -> dict[str, Any]:
        spec = BearingSpec.model_validate(specification)
        code = deterministic_model_code(spec)
        output = io.StringIO()
        # Code is generated exclusively by the reviewed local builder above;
        # no user-supplied source reaches this trusted execution boundary.
        exec(
            compile(code, "<bearing-cylindrical-builder-v1-asset>", "exec"),
            {  # noqa: S102
                "model": handle.mph_model.java,
                "output": output,
            },
        )
        solver_bindings = apply_solver_relative_tolerance(
            handle.mph_model.java, spec.solver_relative_tolerance
        )
        handle.is_modified = True
        return {
            "builder_id": "bearing.cylindrical-roller.builder",
            "builder_version": BUILDER_VERSION,
            "build_signature": spec.build_signature,
            "topology_signature": spec.topology_signature,
            "roller_count": spec.roller_count,
            "llm_calls": 0,
            "solver_relative_tolerance_bindings": list(solver_bindings),
            "stages": [stage.model_dump(mode="json") for stage in build_plan(spec).stages],
            "builder_output": output.getvalue(),
        }
