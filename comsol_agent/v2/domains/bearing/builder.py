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
    # Every candidate is derived from the same reviewed, content-addressed
    # strict asset.  The older V1 variant generator predates the global-contact
    # and per-roller audit contract, so it is not a valid fallback for a new
    # topology.  Candidate variants remain unverified until a fresh strict gate
    # passes; specializing the reviewed loop bounds does not promote them.
    code = _specialize_reviewed_topology(reviewed_asset_code(), spec)
    code = _specialize_reviewed_selection_boxes(code, spec)
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
    preload_direction = ["0", "0", "0"]
    guidance_vector = ["1[N/m^3]", "1[N/m^3]", "1[N/m^3]"]
    load_vector[axis] = sign + "radial_load/(pi*inner_diameter*bearing_width)"
    preload_vector[axis] = sign + "inner_radial_displacement"
    preload_direction[axis] = "1"
    guidance_vector[axis] = "1e4[N/m^3]"
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
    code = _replace_exact(
        code,
        r"preload_inner_radial\.set\('Direction',\s*\[[^\]]+\]\)",
        f"preload_inner_radial.set('Direction', {preload_direction!r})",
        label="preload direction vector",
    )
    code = _replace_exact(
        code,
        r"spring_inner_ring_guidance\.set\('kPerArea',\s*\[[^\n]+\]\)",
        f"spring_inner_ring_guidance.set('kPerArea', {guidance_vector!r})",
        label="inner-ring guidance vector",
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
    # A COMSOL Contact feature bound through its ``pairs`` property owns a
    # non-editable derived selection.  The reviewed V1 fragment also contained
    # two redundant ``contact.selection().named(...)`` calls which COMSOL 6.2
    # rejects before geometry build.  Remove only those pair-bound edits; pair
    # endpoint selections remain explicit on the ContactPair nodes.
    code, removed_contact_selections = re.subn(
        r"(?m)^contact_all_rollers_(?:inner|outer)\.selection\(\)\.named\([^\n]+\)\s*$\n?",
        "",
        code,
    )
    if removed_contact_selections not in {0, 2}:
        raise RuntimeError(
            "deterministic builder expected zero or two redundant pair-bound "
            f"contact selection edits, found {removed_contact_selections}"
        )
    # Result datasets are created by the solver, not during model setup.  A
    # premature fixed ``dset1`` binding makes a fresh blank-model build fail.
    code, removed_early_datasets = re.subn(
        r"(?m)^model\.result\([^\n]+\)\.set\('data',\s*'dset\d+'\)\s*$\n?",
        "",
        code,
    )
    if removed_early_datasets not in {0, 1}:
        raise RuntimeError(
            "deterministic builder found ambiguous early dataset bindings: "
            f"{removed_early_datasets}"
        )
    # Disambiguate JPype's PropFeature.set(String, String[]) overload for the
    # four loop-generated selection lists in the reviewed asset.
    list_replacements = {
        "[f'geom1_roller_partition_{n}_dom']": (
            "[str(f'geom1_roller_partition_{n}_dom')]"
        ),
        "[f'geom1_roller_partition_{n}_bnd']": (
            "[str(f'geom1_roller_partition_{n}_bnd')]"
        ),
        "[box_inner_tag, f'geom1_roller_partition_{n}_bnd']": (
            "[str(box_inner_tag), str(f'geom1_roller_partition_{n}_bnd')]"
        ),
        "[box_outer_tag, f'geom1_roller_partition_{n}_bnd']": (
            "[str(box_outer_tag), str(f'geom1_roller_partition_{n}_bnd')]"
        ),
    }
    for before, after in list_replacements.items():
        count = code.count(before)
        if count not in {0, 1}:
            raise RuntimeError(f"ambiguous deterministic list overload: {before}")
        code = code.replace(before, after)
    code, invalid_method_count = re.subn(
        r"(?m)^model\.result\(\)\.numerical\([^\n]+\)\.set\('method',\s*'max'\)\s*$\n?",
        "",
        code,
    )
    if invalid_method_count not in {0, 1}:
        raise RuntimeError("ambiguous invalid EvalGlobal method property")
    return code


def _specialize_reviewed_topology(code: str, spec: BearingSpec) -> str:
    assignments = {
        "pitch_radius_mm": spec.pitch_radius_mm,
        "roller_diameter_mm": spec.roller_diameter_mm,
        "roller_length_mm": spec.roller_length_mm,
        "offset_deg": spec.roller_phase_deg,
    }
    for name, value in assignments.items():
        pattern = rf"(?m)^{name} = [-+0-9.eE]+$"
        replacement = f"{name} = {float(value):.15g}"
        code, count = re.subn(pattern, replacement, code)
        if count != 2:
            raise RuntimeError(
                f"reviewed bearing asset expected two {name} assignments, found {count}"
            )
    scalar_replacements = {
        r"model\.param\(\)\.set\('roller_count',\s*'10'\)": (
            f"model.param().set('roller_count', '{spec.roller_count}')"
        ),
        r"(?m)^num_rollers = 10$": f"num_rollers = {spec.roller_count}",
        r"(?m)^roller_count = 10$": f"roller_count = {spec.roller_count}",
        r"for i in range\(10\):": f"for i in range({spec.roller_count}):",
    }
    for pattern, replacement in scalar_replacements.items():
        code, count = re.subn(pattern, replacement, code)
        if count != 1:
            raise RuntimeError(
                "reviewed bearing asset topology specialization conflict for "
                f"{pattern}: expected 1 match, found {count}"
            )
    return code


def _specialize_reviewed_selection_boxes(code: str, spec: BearingSpec) -> str:
    """Move every reviewed spatial selection with the requested 3D geometry."""
    radial_margin_mm = 0.1
    raceway_axial_half_mm = min(
        spec.roller_length_mm / 2 + 0.4,
        spec.bearing_width_mm / 2 - radial_margin_mm,
    )
    roller_contact_axial_half_mm = min(
        spec.roller_length_mm / 2 - 0.6,
        spec.bearing_width_mm / 2 - radial_margin_mm,
    )
    if roller_contact_axial_half_mm <= 0:
        raise RuntimeError("roller contact selection has no positive axial span")

    bounds = {
        "box_inner_raceway": {
            "xmin": spec.inner_race_outer_radius_mm - radial_margin_mm,
            "xmax": spec.inner_race_outer_radius_mm + radial_margin_mm,
            "ymin": -radial_margin_mm,
            "ymax": radial_margin_mm,
            "zmin": -raceway_axial_half_mm,
            "zmax": raceway_axial_half_mm,
        },
        "box_outer_raceway": {
            "xmin": spec.outer_race_inner_radius_mm - radial_margin_mm,
            "xmax": spec.outer_race_inner_radius_mm + radial_margin_mm,
            "ymin": -radial_margin_mm,
            "ymax": radial_margin_mm,
            "zmin": -raceway_axial_half_mm,
            "zmax": raceway_axial_half_mm,
        },
        "box_outer_support": {
            "xmin": spec.outer_diameter_mm / 2 - radial_margin_mm,
            "xmax": spec.outer_diameter_mm / 2 + radial_margin_mm,
            "ymin": -radial_margin_mm,
            "ymax": radial_margin_mm,
            "zmin": -raceway_axial_half_mm,
            "zmax": raceway_axial_half_mm,
        },
        "box_inner_bore": {
            "xmin": -(spec.inner_diameter_mm / 2 + radial_margin_mm),
            "xmax": spec.inner_diameter_mm / 2 + radial_margin_mm,
            "ymin": -(spec.inner_diameter_mm / 2 + radial_margin_mm),
            "ymax": spec.inner_diameter_mm / 2 + radial_margin_mm,
            "zmin": -(spec.bearing_width_mm / 2 + radial_margin_mm),
            "zmax": spec.bearing_width_mm / 2 + radial_margin_mm,
        },
    }
    for tag, properties in bounds.items():
        for name, value in properties.items():
            code = _replace_exact(
                code,
                (
                    rf"comp\.selection\('{re.escape(tag)}'\)\.set\("  # noqa: ISC003
                    rf"'{name}',\s*'[^']+'\)"
                ),
                f"comp.selection('{tag}').set('{name}', '{value:.12g}[mm]')",
                label=f"{tag}.{name}",
            )

    for variable in ("box_inner_tag", "box_outer_tag"):
        for name, value in (
            ("zmin", -roller_contact_axial_half_mm),
            ("zmax", roller_contact_axial_half_mm),
        ):
            code = _replace_exact(
                code,
                rf"comp\.selection\({variable}\)\.set\('{name}',\s*'[^']+'\)",
                f"comp.selection({variable}).set('{name}', '{value:.12g}[mm]')",
                label=f"{variable}.{name}",
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
