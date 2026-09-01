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

from .auditors import BearingAcceptanceMode, engineering_preview_report
from .models import BearingSpec
from .results import evaluate_target_results


class ReviewedStrictAuditCollector:
    def __init__(
        self,
        spec: BearingSpec,
        artifact_root: Path,
        *,
        case_id: str,
        acceptance_mode: BearingAcceptanceMode | str = BearingAcceptanceMode.STRICT_VERIFIED,
    ) -> None:
        self.spec = spec
        self.artifact_root = artifact_root
        self.case_id = case_id
        self.acceptance_mode = BearingAcceptanceMode(acceptance_mode)

    def __call__(self, handle: Any) -> dict[str, Any]:
        # Import lazily: this is a trusted, explicitly configured compatibility
        # adapter, not executable content discovered from memory or RAG.
        legacy = _reviewed_runtime_module()
        if self.acceptance_mode == BearingAcceptanceMode.ENGINEERING_PREVIEW:
            return self._engineering_preview(handle, legacy)
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
        payload = {
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
        preview = engineering_preview_report(
            {"spec": spec, **payload}
        ).model_dump(mode="json")
        payload.update(
            {
                "passed": bool(preview["passed"]),
                "strict_passed": bool(report.get("success")),
                "engineering_preview": preview,
                "acceptance_mode": "engineering_preview",
            }
        )
        return payload

    def _engineering_preview(self, handle: Any, legacy: Any) -> dict[str, Any]:
        """Collect preview evidence from the already solved V2 model.

        This deliberately does not call the legacy strict routine, because that
        routine performs another displacement initialization and force solve.
        """
        spec = self.spec
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        java = handle.mph_model.java
        selection_tags = [
            "sel_inner_raceway_contact",
            "sel_outer_raceway_contact",
            "sel_all_roller_inner_contacts",
            "sel_all_roller_outer_contacts",
            "sel_inner_bore_load_surface",
            "sel_outer_support_surface",
            *[f"sel_roller_{index}_body" for index in range(1, spec.roller_count + 1)],
        ]
        selections: dict[str, Any] = {}
        for tag in selection_tags:
            try:
                entities = [
                    int(value)
                    for value in java.component("comp1").selection(tag).entities()
                ]
            except Exception as error:
                entities = []
                selections[tag] = {"entity_count": 0, "error": str(error)}
            else:
                selections[tag] = {
                    "entity_count": len(entities),
                    "entities": entities,
                }
        pairs: dict[str, Any] = {}
        for tag in ("cp_all_rollers_inner", "cp_all_rollers_outer"):
            try:
                pair = java.component("comp1").pair(tag)
                source = [int(value) for value in pair.source().entities()]
                destination = [int(value) for value in pair.destination().entities()]
                pairs[tag] = {
                    "source_named": str(pair.source().named()),
                    "destination_named": str(pair.destination().named()),
                    "source_entity_count": len(source),
                    "destination_entity_count": len(destination),
                }
            except Exception as error:
                pairs[tag] = {"error": str(error)}

        dataset_tags = [str(value) for value in java.result().dataset().tags()]
        dataset = dataset_tags[-1] if dataset_tags else "dset2"
        target_results = evaluate_target_results(
            java,
            dataset=dataset,
            target_load_n=spec.target_radial_load_n,
        )
        solved_mph = self.artifact_root / "engineering_preview_solved.mph"
        handle.mph_model.save(str(solved_mph))
        solution_number = target_results.get("solution_number")
        plot = legacy._export_native_3d_stage_volume_plot(
            handle.name,
            stage_name=(
                "engineering_preview_target_"
                + str(spec.target_radial_load_n).replace(".", "p")
                + "N"
            ),
            output_dir=self.artifact_root,
            solution_level=(
                int(solution_number) if isinstance(solution_number, int) else None
            ),
        )
        plot.update(
            {
                "unit": "Pa",
                "solution_number": solution_number,
                "target_parameter_name": "radial_load",
                "target_parameter_value_n": target_results.get(
                    "selected_parameter_value_n"
                ),
                "numerical_max_pa": (target_results.get("stress") or {}).get(
                    "value"
                ),
                "result_source": "same dataset/solution as java:MaxVolume.getReal",
            }
        )
        axis = spec.comsol_parameters()["load_axis"]
        sign = int(spec.comsol_parameters()["load_sign"])
        payload = {
            "passed": False,
            "strict_passed": False,
            "acceptance_mode": BearingAcceptanceMode.ENGINEERING_PREVIEW.value,
            "selections": selections,
            "pairs": pairs,
            "metrics": {
                "returned_target_load_n": target_results.get(
                    "selected_parameter_value_n"
                ),
                "applied_load_n": None,
                "support_reaction_n": None,
                "outer_contact_resultant_n": None,
                "stabilization_force_n": None,
                "loaded_zone_direction": ("+" if sign > 0 else "-") + axis.upper(),
            },
            "result_evidence": target_results,
            "native_plot": str(plot.get("filepath") or "")
            if plot.get("success")
            else "",
            "native_plot_evidence": plot,
            "solver_evidence": {
                "profile": "engineering_preview",
                "strict_balance_postprocessing_skipped": True,
            },
            "solved_mph": str(solved_mph) if solved_mph.is_file() else "",
            "reviewed_v1_adapter": {
                "kind": "engineering_preview_existing_solution",
                "case_id": self.case_id,
                "strict_resolve_performed": False,
                "reuse_scope": "native target result binding and plot export only",
            },
        }
        preview = engineering_preview_report(
            {"spec": spec, **payload}
        ).model_dump(mode="json")
        payload["engineering_preview"] = preview
        payload["passed"] = bool(preview["passed"])
        return payload


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
