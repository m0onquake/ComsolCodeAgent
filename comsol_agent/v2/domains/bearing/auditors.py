"""Separate geometry, selection, contact and physical bearing auditors."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from comsol_agent.v2.contracts.models import ContractModel

from .models import BearingSpec, LoadDirection


class AuditCheck(ContractModel):
    name: str
    passed: bool
    actual: Any = None
    expected: Any = None
    tolerance: float | None = None


class BearingAudit(ContractModel):
    kind: str
    passed: bool
    checks: tuple[AuditCheck, ...] = Field(min_length=1)
    errors: tuple[str, ...] = ()
    evidence: dict[str, Any] = Field(default_factory=dict)
    contract_version: str = "1.0.0"


class BearingAcceptanceMode(StrEnum):
    ENGINEERING_PREVIEW = "engineering_preview"
    STRICT_VERIFIED = "strict_verified"


class EngineeringStressPolicy(ContractModel):
    """Versioned, intentionally broad stress plausibility policy for previews."""

    minimum_pa: float = Field(default=1.0e3, gt=0)
    maximum_pa: float = Field(default=1.0e9, gt=0)
    expected_pa: float | None = Field(default=None, gt=0)
    relative_tolerance: float = Field(default=1.0, ge=0, le=10)
    contract_version: str = "1.0.0"

    @model_validator(mode="after")
    def validate_range(self) -> EngineeringStressPolicy:
        if self.maximum_pa <= self.minimum_pa:
            raise ValueError("maximum_pa must be greater than minimum_pa")
        return self


def _report(
    kind: str, checks: list[AuditCheck], evidence: dict[str, Any] | None = None
) -> BearingAudit:
    errors = tuple(check.name for check in checks if not check.passed)
    return BearingAudit(
        kind=kind, passed=not errors, checks=tuple(checks), errors=errors, evidence=evidence or {}
    )


class BearingGeometryAuditor:
    async def audit(self, subject: Any) -> dict[str, Any]:
        spec = subject if isinstance(subject, BearingSpec) else BearingSpec.model_validate(subject)
        spacing = 2 * spec.pitch_radius_mm * math.sin(math.pi / spec.roller_count)
        pocket = spec.roller_diameter_mm + 2 * spec.cage_pocket_clearance_mm
        contact_offset = spec.roller_diameter_mm / 2 + spec.radial_clearance_mm / 2
        result = _report(
            "bearing_geometry",
            [
                AuditCheck(
                    name="inner_contact_closure",
                    passed=math.isclose(
                        spec.inner_race_outer_radius_mm,
                        spec.pitch_radius_mm - contact_offset,
                        abs_tol=1e-6,
                    ),
                ),
                AuditCheck(
                    name="outer_contact_closure",
                    passed=math.isclose(
                        spec.outer_race_inner_radius_mm,
                        spec.pitch_radius_mm + contact_offset,
                        abs_tol=1e-6,
                    ),
                ),
                AuditCheck(
                    name="roller_pocket_nonoverlap",
                    passed=spacing > pocket,
                    actual=spacing,
                    expected=f"> {pocket}",
                ),
                AuditCheck(
                    name="positive_ring_thickness",
                    passed=spec.inner_diameter_mm / 2
                    < spec.inner_race_outer_radius_mm
                    < spec.outer_race_inner_radius_mm
                    < spec.outer_diameter_mm / 2,
                ),
            ],
        )
        return result.model_dump(mode="json")


class BearingSelectionAuditor:
    async def audit(self, subject: Any) -> dict[str, Any]:
        spec = BearingSpec.model_validate(subject["spec"])
        selections = subject.get("selections", {})
        required = [
            "sel_inner_raceway_contact",
            "sel_outer_raceway_contact",
            "sel_all_roller_inner_contacts",
            "sel_all_roller_outer_contacts",
            "sel_inner_bore_load_surface",
            "sel_outer_support_surface",
            *[f"sel_roller_{index}_body" for index in range(1, spec.roller_count + 1)],
        ]
        checks = [
            AuditCheck(
                name=tag,
                passed=int((selections.get(tag) or {}).get("entity_count", 0)) > 0,
                actual=(selections.get(tag) or {}).get("entity_count"),
                expected="> 0",
            )
            for tag in required
        ]
        return _report("bearing_selection", checks, {"required": required}).model_dump(mode="json")


class BearingContactAuditor:
    async def audit(self, subject: Any) -> dict[str, Any]:
        pairs = subject.get("pairs", {})
        expected = {
            "cp_all_rollers_inner": ("sel_all_roller_inner_contacts", "sel_inner_raceway_contact"),
            "cp_all_rollers_outer": ("sel_all_roller_outer_contacts", "sel_outer_raceway_contact"),
        }
        checks: list[AuditCheck] = []
        for tag, endpoints in expected.items():
            pair = pairs.get(tag) or {}
            actual = (pair.get("source_named"), pair.get("destination_named"))
            nonempty = (
                int(pair.get("source_entity_count", 0)) > 0
                and int(pair.get("destination_entity_count", 0)) > 0
            )
            checks.append(
                AuditCheck(
                    name=f"{tag}_binding",
                    passed=actual == endpoints and nonempty,
                    actual=actual,
                    expected=endpoints,
                )
            )
        return _report("bearing_contact", checks).model_dump(mode="json")


class BearingPhysicalAuditor:
    """Strict force, stability, direction, finite-result and artifact gates."""

    async def audit(self, subject: Any) -> dict[str, Any]:
        spec = BearingSpec.model_validate(subject["spec"])
        metrics = subject.get("metrics", {})
        result_evidence = subject.get("result_evidence", {})
        stress_evidence = result_evidence.get("stress", {})
        displacement_evidence = result_evidence.get("displacement", {})
        plot_evidence = subject.get("native_plot_evidence", {})
        solver_evidence = subject.get("solver_evidence", {})
        target = spec.target_radial_load_n
        applied = _finite(metrics.get("applied_load_n"))
        reaction = _finite(metrics.get("support_reaction_n"))
        contact = _finite(metrics.get("outer_contact_resultant_n"))
        parsed_spring = _finite(metrics.get("stabilization_force_n"))
        spring = math.inf if parsed_spring is None else abs(parsed_spring)
        stress = _finite(stress_evidence.get("value"))
        displacement = _finite(displacement_evidence.get("value"))
        returned = _finite(metrics.get("returned_target_load_n"))
        direction = str(metrics.get("loaded_zone_direction", ""))

        def relative_error(value: float | None) -> float:
            return math.inf if value is None else abs(abs(value) - target) / target

        checks = [
            AuditCheck(
                name="target_step_returned",
                passed=returned is not None and math.isclose(returned, target, rel_tol=1e-9),
                actual=returned,
                expected=target,
            ),
            AuditCheck(
                name="applied_load",
                passed=relative_error(applied) <= 2e-3,
                actual=applied,
                expected=target,
                tolerance=2e-3,
            ),
            AuditCheck(
                name="support_reaction_balance",
                passed=relative_error(reaction) <= 2e-2,
                actual=reaction,
                expected=target,
                tolerance=2e-2,
            ),
            AuditCheck(
                name="outer_contact_balance",
                passed=relative_error(contact) <= 2e-2,
                actual=contact,
                expected=target,
                tolerance=2e-2,
            ),
            AuditCheck(
                name="stabilization_ratio",
                passed=spring / target <= 1e-3,
                actual=spring / target,
                expected="<= 0.001",
                tolerance=1e-3,
            ),
            AuditCheck(
                name="loaded_zone_direction",
                passed=direction == spec.load_direction.value,
                actual=direction,
                expected=spec.load_direction.value,
            ),
            AuditCheck(
                name="result_target_step",
                passed=_target_result_evidence_matches(result_evidence, target),
                actual={
                    "dataset": result_evidence.get("dataset"),
                    "solution_number": result_evidence.get("solution_number"),
                    "selected_parameter_value_n": result_evidence.get(
                        "selected_parameter_value_n"
                    ),
                },
                expected={"parameter": "radial_load", "value_n": target},
            ),
            AuditCheck(
                name="solver_relative_tolerance",
                passed=_solver_evidence_matches(
                    solver_evidence, spec.solver_relative_tolerance
                ),
                actual=solver_evidence,
                expected=spec.solver_relative_tolerance,
            ),
            AuditCheck(
                name="stress_result_source",
                passed=_field_evidence_matches(
                    stress_evidence,
                    result_evidence,
                    expression="solid.mises/1[Pa]",
                    base_expression="solid.mises",
                    unit="Pa",
                ),
                actual=stress_evidence,
                expected="target-bound java MaxVolume solid.mises/1[Pa]",
            ),
            AuditCheck(
                name="displacement_result_source",
                passed=_field_evidence_matches(
                    displacement_evidence,
                    result_evidence,
                    expression="solid.disp/1[m]",
                    base_expression="solid.disp",
                    unit="m",
                ),
                actual=displacement_evidence,
                expected="target-bound java MaxVolume solid.disp/1[m]",
            ),
            AuditCheck(
                name="finite_stress",
                passed=stress is not None and stress >= 0.0,
                actual=stress,
                expected="finite",
            ),
            AuditCheck(
                name="finite_displacement",
                passed=displacement is not None and displacement >= 0.0,
                actual=displacement,
                expected="finite",
            ),
            AuditCheck(
                name="native_plot",
                passed=bool(subject.get("native_plot"))
                and _plot_evidence_matches(plot_evidence, result_evidence, stress_evidence),
                actual=plot_evidence,
                expected="same dataset/solution/base expression as stress result",
            ),
            AuditCheck(name="solved_mph", passed=bool(subject.get("solved_mph"))),
        ]
        return _report(
            "bearing_strict_physics",
            checks,
            {
                "metrics": metrics,
                "result_evidence": result_evidence,
                "native_plot_evidence": plot_evidence,
                "solver_evidence": solver_evidence,
            },
        ).model_dump(mode="json")


class BearingEngineeringPreviewAuditor:
    """Accept solved models on structural validity and approximate stress only."""

    async def audit(self, subject: Any) -> dict[str, Any]:
        return engineering_preview_report(subject).model_dump(mode="json")


def engineering_preview_report(subject: Any) -> BearingAudit:
    spec = BearingSpec.model_validate(subject["spec"])
    policy = EngineeringStressPolicy.model_validate(subject.get("preview_policy") or {})
    result_evidence = subject.get("result_evidence", {})
    stress_evidence = result_evidence.get("stress", {})
    plot_evidence = subject.get("native_plot_evidence", {})
    stress = _finite(stress_evidence.get("value"))
    if stress is None:
        approximate = False
        expected: Any = policy.model_dump(mode="json")
    elif policy.expected_pa is not None:
        approximate = (
            abs(stress - policy.expected_pa) / policy.expected_pa
            <= policy.relative_tolerance
        )
        expected = {
            "expected_pa": policy.expected_pa,
            "relative_tolerance": policy.relative_tolerance,
        }
    else:
        approximate = policy.minimum_pa <= stress <= policy.maximum_pa
        expected = {"minimum_pa": policy.minimum_pa, "maximum_pa": policy.maximum_pa}
    checks = [
        AuditCheck(
            name="result_target_step",
            passed=_target_result_evidence_matches(
                result_evidence, spec.target_radial_load_n
            ),
            actual={
                "dataset": result_evidence.get("dataset"),
                "solution_number": result_evidence.get("solution_number"),
                "selected_parameter_value_n": result_evidence.get(
                    "selected_parameter_value_n"
                ),
            },
            expected={"parameter": "radial_load", "value_n": spec.target_radial_load_n},
        ),
        AuditCheck(
            name="stress_result_source",
            passed=_field_evidence_matches(
                stress_evidence,
                result_evidence,
                expression="solid.mises/1[Pa]",
                base_expression="solid.mises",
                unit="Pa",
            ),
            actual=stress_evidence,
            expected="target-bound java MaxVolume solid.mises/1[Pa]",
        ),
        AuditCheck(
            name="finite_positive_stress",
            passed=stress is not None and stress > 0.0,
            actual=stress,
            expected="> 0 Pa and finite",
        ),
        AuditCheck(
            name="approximate_stress",
            passed=approximate,
            actual=stress,
            expected=expected,
            tolerance=(
                policy.relative_tolerance if policy.expected_pa is not None else None
            ),
        ),
        AuditCheck(
            name="native_stress_plot",
            passed=bool(subject.get("native_plot"))
            and _plot_evidence_matches(plot_evidence, result_evidence, stress_evidence),
            actual=plot_evidence,
            expected="same dataset/solution/base expression as stress result",
        ),
    ]
    strict_warnings = tuple(
        name
        for name in (
            "applied_load",
            "support_reaction_balance",
            "outer_contact_balance",
            "stabilization_ratio",
            "loaded_zone_direction",
        )
        if name in set(subject.get("strict_balance_errors") or ())
    )
    return _report(
        "bearing_engineering_stress_preview",
        checks,
        {
            "stress_pa": stress,
            "policy": policy.model_dump(mode="json"),
            "strict_balance_warnings": strict_warnings,
            "promotion_eligible": False,
        },
    )


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _target_result_evidence_matches(evidence: dict[str, Any], target: float) -> bool:
    selected = _finite(evidence.get("selected_parameter_value_n"))
    solution_number = evidence.get("solution_number")
    return bool(
        evidence.get("success") is True
        and evidence.get("dataset")
        and evidence.get("parameter_name") == "radial_load"
        and evidence.get("parameter_expression") == "radial_load/1[N]"
        and evidence.get("parameter_unit") == "N"
        and selected is not None
        and math.isclose(selected, target, rel_tol=1e-9, abs_tol=1e-12)
        and isinstance(solution_number, int)
        and solution_number >= 1
    )


def _field_evidence_matches(
    field: dict[str, Any],
    result: dict[str, Any],
    *,
    expression: str,
    base_expression: str,
    unit: str,
) -> bool:
    return bool(
        field.get("success") is True
        and field.get("expression") == expression
        and field.get("base_expression") == base_expression
        and field.get("unit") == unit
        and field.get("dataset") == result.get("dataset")
        and field.get("solution_number") == result.get("solution_number")
        and field.get("node_kind") == "MaxVolume"
        and field.get("source") == "java:MaxVolume.getReal"
        and field.get("solution_bindings")
    )


def _plot_evidence_matches(
    plot: dict[str, Any], result: dict[str, Any], stress: dict[str, Any]
) -> bool:
    numerical_max = _finite(plot.get("numerical_max_pa"))
    stress_value = _finite(stress.get("value"))
    return bool(
        plot.get("success") is True
        and plot.get("expression") == stress.get("base_expression")
        and plot.get("unit") == "Pa"
        and plot.get("dataset") == result.get("dataset")
        and plot.get("solution_number") == result.get("solution_number")
        and numerical_max is not None
        and stress_value is not None
        and math.isclose(numerical_max, stress_value, rel_tol=1e-9, abs_tol=1e-15)
    )


def _solver_evidence_matches(evidence: dict[str, Any], expected: float) -> bool:
    bindings = evidence.get("bindings")
    if evidence.get("requested") != expected or not isinstance(bindings, list) or not bindings:
        return False
    return all(
        binding.get("property") == "stol"
        and _finite(binding.get("actual")) is not None
        and math.isclose(float(binding["actual"]), expected, rel_tol=1e-12)
        for binding in bindings
    )


def expected_load_vector(spec: BearingSpec) -> tuple[int, int]:
    axis = 0 if spec.load_direction in {LoadDirection.POSITIVE_X, LoadDirection.NEGATIVE_X} else 1
    sign = -1 if spec.load_direction in {LoadDirection.NEGATIVE_X, LoadDirection.NEGATIVE_Y} else 1
    return axis, sign
