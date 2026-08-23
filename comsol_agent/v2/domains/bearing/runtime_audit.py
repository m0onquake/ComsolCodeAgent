"""Transitional in-process adapter for the reviewed V1 strict COMSOL audit asset.

The adapter is domain-owned and never imported by the Kernel.  It exists to
reuse the already verified force-integration and native-plot routines while the
corresponding Java collectors are migrated behind native V2 auditor handlers.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Any

from .models import BearingSpec


class ReviewedStrictAuditCollector:
    def __init__(self, spec: BearingSpec, artifact_root: Path, *, case_id: str) -> None:
        self.spec = spec
        self.artifact_root = artifact_root
        self.case_id = case_id

    def __call__(self, handle: Any) -> dict[str, Any]:
        # Import lazily: this is a trusted, explicitly configured compatibility
        # adapter, not executable content discovered from memory or RAG.
        legacy = _reviewed_runtime_module()
        strict_bearing_variant = legacy.StrictBearingVariant
        run_strict = legacy._run_strict_generated_global_contact_solve

        spec = self.spec
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        axis = spec.comsol_parameters()["load_axis"]
        sign = int(spec.comsol_parameters()["load_sign"])
        report = run_strict(
            handle.name,
            artifact_root=self.artifact_root,
            target_load_n=spec.target_radial_load_n,
            load_axis=axis,
            load_sign=sign,
            roller_angular_offset_deg=spec.roller_phase_deg,
            variant=strict_bearing_variant(
                roller_count=spec.roller_count,
                inner_diameter_mm=spec.inner_diameter_mm,
                outer_diameter_mm=spec.outer_diameter_mm,
                bearing_width_mm=spec.bearing_width_mm,
                roller_diameter_mm=spec.roller_diameter_mm,
                roller_length_mm=spec.roller_length_mm,
                pitch_radius_mm=spec.pitch_radius_mm,
                inner_race_outer_radius_mm=spec.inner_race_outer_radius_mm,
                outer_race_inner_radius_mm=spec.outer_race_inner_radius_mm,
                cage_inner_radius_mm=spec.cage_inner_radius_mm,
                cage_outer_radius_mm=spec.cage_outer_radius_mm,
            ),
            case_id=self.case_id,
            solver_relative_tolerance=spec.solver_relative_tolerance,
        )
        selection = report.get("pre_solve_selection_audit") or {}
        final = report.get("final_audit") or {}
        target_results = final.get("target_results") or {}
        bindings = list(report.get("initialization_solver_tolerance_bindings") or [])
        for stage in report.get("force_stage_results") or []:
            bindings.extend(stage.get("solver_relative_tolerance_bindings") or [])
        solved_path = Path((report.get("solved_model_save") or {}).get("saved_to") or "")
        plot = report.get("native_stress_plot") or {}
        plot_path = Path(plot.get("filepath") or "")
        return {
            "passed": bool(report.get("success")),
            "selections": selection.get("selections") or {},
            "pairs": selection.get("pairs") or {},
            "metrics": {
                "returned_target_load_n": final.get("target_load_n"),
                "applied_load_n": final.get("applied_load_n"),
                "support_reaction_n": _magnitude(
                    final.get("support_reaction_vector_n") or {}
                ),
                "outer_contact_resultant_n": _magnitude(
                    final.get("outer_contact_vector_n") or {}
                ),
                "stabilization_force_n": final.get("spring_resultant_n"),
                "loaded_zone_direction": (
                    ("+" if sign > 0 else "-") + axis.upper()
                ),
            },
            "result_evidence": target_results,
            "native_plot": str(plot_path) if plot_path.is_file() else "",
            "native_plot_evidence": plot,
            "solver_evidence": {
                "requested": spec.solver_relative_tolerance,
                "bindings": bindings,
            },
            "solved_mph": str(solved_path) if solved_path.is_file() else "",
            "reviewed_v1_adapter": {
                "kind": report.get("kind"),
                "case_id": report.get("case_id"),
                "success": report.get("success"),
                "final_gates": final.get("gates") or {},
                "reuse_scope": "force integration, target result binding, native plot",
            },
        }


def _magnitude(vector: dict[str, Any]) -> float:
    return math.sqrt(sum(float(vector.get(axis, 0.0)) ** 2 for axis in ("x", "y", "z")))


def _reviewed_runtime_module() -> Any:
    source = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "run_agent_3d_bearing_full_demo.py"
    )
    spec = importlib.util.spec_from_file_location(
        "comsol_agent_reviewed_v1_bearing_runtime", source
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load reviewed V1 runtime asset: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
