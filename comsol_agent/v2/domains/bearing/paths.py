"""Registered deterministic bearing paths and parameter-override execution."""

from __future__ import annotations

from typing import Any

from .continuation import ContinuationPlan, build_continuation
from .models import BearingChangeSet, BearingSpec, ChangeRoute, classify_changes
from .solver import apply_solver_relative_tolerance


class ParameterOverridePath:
    """Route a same-topology change to COMSOL parameters or a deterministic rebuild."""

    def plan(self, previous: BearingSpec, requested: BearingSpec) -> dict[str, Any]:
        changes = classify_changes(previous, requested)
        if changes.route == ChangeRoute.UNSUPPORTED_TOPOLOGY:
            raise ValueError(changes.reason)
        changed_names = {change.field for change in changes.changes}
        parameters = requested.comsol_parameters()
        patch = {
            name: value
            for name, value in parameters.items()
            if _parameter_source_field(name) in changed_names
        }
        solver_patch = (
            {"stationary.stol": requested.solver_relative_tolerance}
            if "solver_relative_tolerance" in changed_names
            else {}
        )
        return {
            "change_set": changes.model_dump(mode="json"),
            "route": changes.route.value,
            "parameter_patch": patch,
            "solver_patch": solver_patch,
            "llm_calls": 0,
            "restore_checkpoint": "B_configured_model"
            if changes.route == ChangeRoute.PARAMETER_OVERRIDE
            else None,
            "requires_builder": changes.route == ChangeRoute.DETERMINISTIC_REBUILD,
            "acceptance": ["spec_valid", "solve", "strict_physics_audit"],
        }

    def execute_model(self, handle: Any, specification: dict[str, Any]) -> dict[str, Any]:
        previous = BearingSpec.model_validate(specification["previous"])
        requested = BearingSpec.model_validate(specification["requested"])
        plan = self.plan(previous, requested)
        if plan["route"] != ChangeRoute.PARAMETER_OVERRIDE:
            raise ValueError("parameter override handler only accepts parameter_override route")
        for name, value in plan["parameter_patch"].items():
            if name in {"load_axis", "load_sign"}:
                continue
            handle.mph_model.parameter(name, value)
        if plan["solver_patch"]:
            plan["solver_bindings"] = list(
                apply_solver_relative_tolerance(
                    handle.mph_model.java,
                    requested.solver_relative_tolerance,
                )
            )
        if any(change["field"] == "load_direction" for change in plan["change_set"]["changes"]):
            direction = requested.load_direction
            axis = 0 if direction.value.endswith("X") else 1
            sign = "-" if direction.value.startswith("-") else ""
            load_vector = ["0", "0", "0"]
            preload_vector = ["0", "0", "0"]
            load_vector[axis] = sign + "radial_load/(pi*inner_diameter*bearing_width)"
            preload_vector[axis] = sign + "inner_radial_displacement"
            solid = handle.mph_model.java.component("comp1").physics("solid")
            solid.feature("load_inner_bore").set("FperArea", load_vector)
            solid.feature("preload_inner_radial").set("U0", preload_vector)
        handle.is_modified = True
        return plan


class DynamicLoadContinuation:
    def plan(self, spec: BearingSpec, *, last_converged_n: float | None = None) -> ContinuationPlan:
        return build_continuation(spec, last_converged_n=last_converged_n)

    def execute_model(self, handle: Any, specification: dict[str, Any]) -> dict[str, Any]:
        spec = BearingSpec.model_validate(specification["spec"])
        continuation = self.plan(spec, last_converged_n=specification.get("last_converged_n"))
        stat = handle.mph_model.java.study("std1").feature("stat")
        values = " ".join(
            f"{value:.15g}" for chunk in continuation.chunks for value in chunk.values_n
        )
        stat.set("useparam", "on")
        stat.set("pname", ["radial_load"])
        stat.set("plistarr", [values])
        stat.set("punit", ["N"])
        stat.set("pcontinuationmode", "manual")
        stat.set("pcontinuation", "radial_load")
        stat.set("preusesol", "yes")
        handle.is_modified = True
        return continuation.model_dump(mode="json")


def _parameter_source_field(parameter: str) -> str:
    return {
        "inner_diameter": "inner_diameter_mm",
        "outer_diameter": "outer_diameter_mm",
        "bearing_width": "bearing_width_mm",
        "roller_diameter": "roller_diameter_mm",
        "roller_length": "roller_length_mm",
        "pitch_radius": "pitch_radius_mm",
        "inner_race_outer_radius": "inner_race_outer_radius_mm",
        "outer_race_inner_radius": "outer_race_inner_radius_mm",
        "cage_inner_radius": "cage_inner_radius_mm",
        "cage_outer_radius": "cage_outer_radius_mm",
        "cage_pocket_clearance": "cage_pocket_clearance_mm",
        "radial_clearance": "radial_clearance_mm",
        "roller_angular_offset_deg": "roller_phase_deg",
        "radial_load": "target_radial_load_n",
        "mesh_bulk_size": "mesh_bulk_size_mm",
        "mesh_contact_size": "mesh_contact_size_mm",
        "load_axis": "load_direction",
        "load_sign": "load_direction",
    }[parameter]


def route_change(previous: BearingSpec, requested: BearingSpec) -> BearingChangeSet:
    return classify_changes(previous, requested)
