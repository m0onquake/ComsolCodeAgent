"""Direction-aware, bounded radial-load continuation planning."""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import Field

from comsol_agent.v2.contracts.models import ContractModel

from .models import BearingSpec, LoadDirection


class ContinuationChunk(ContractModel):
    values_n: tuple[float, ...] = Field(min_length=1)
    reuse_previous_solution: bool = True


class ContinuationProfile(StrEnum):
    ENGINEERING_PREVIEW = "engineering_preview"
    STRICT_VERIFIED = "strict_verified"


class ContinuationPlan(ContractModel):
    parameter: str = "radial_load"
    target_n: float
    direction: LoadDirection
    chunks: tuple[ContinuationChunk, ...]
    max_solves: int = Field(ge=1)
    profile: ContinuationProfile = ContinuationProfile.STRICT_VERIFIED
    effective_solver_relative_tolerance: float = Field(gt=0, le=0.1)
    rollback_checkpoint: str = "B_configured_model"
    success_criteria: tuple[str, ...] = (
        "target_load_reached",
        "solve_converged",
        "strict_physics_audit_passed",
    )


def build_continuation(
    spec: BearingSpec,
    *,
    last_converged_n: float | None = None,
    profile: ContinuationProfile | str = ContinuationProfile.STRICT_VERIFIED,
) -> ContinuationPlan:
    profile = ContinuationProfile(profile)
    target = spec.target_radial_load_n
    directional = spec.load_direction != LoadDirection.POSITIVE_X
    if profile == ContinuationProfile.ENGINEERING_PREVIEW:
        fractions = (0.01, 0.1, 1.0)
    else:
        fractions = (
            (0.001, 0.005, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0)
            if directional
            else (0.001, 0.01, 0.05, 0.1, 0.5, 1.0)
        )
    values = [min(1.0e-4, target * 0.001)]
    values.extend(target * fraction for fraction in fractions)
    values = [
        value for value in values if value <= target * (1 + 1e-12) and value > 0
    ]
    values.append(target)
    if last_converged_n and math.isfinite(last_converged_n) and last_converged_n > 0:
        values = [last_converged_n, *[value for value in values if value > last_converged_n]]
    values = list(dict.fromkeys(float(value) for value in values))
    # Retain native continuation state within at most two solver runs. The old
    # absolute thresholds created four to seven fresh solvers for scaled or
    # phased variants and exhausted the run budget before reaching design load.
    cutoffs = (
        ()
        if profile == ContinuationProfile.ENGINEERING_PREVIEW
        else (target * 0.1,)
    )
    chunks: list[ContinuationChunk] = []
    lower = -math.inf
    for cutoff in (*cutoffs, math.inf):
        bucket = tuple(value for value in values if lower < value <= cutoff)
        if bucket:
            chunks.append(ContinuationChunk(values_n=bucket))
        lower = cutoff
    return ContinuationPlan(
        target_n=target,
        direction=spec.load_direction,
        chunks=tuple(chunks),
        max_solves=len(chunks),
        profile=profile,
        effective_solver_relative_tolerance=(
            max(spec.solver_relative_tolerance, 1.0e-2)
            if profile == ContinuationProfile.ENGINEERING_PREVIEW
            else spec.solver_relative_tolerance
        ),
        success_criteria=(
            (
                "target_load_reached",
                "solve_converged",
                "engineering_preview_audit_passed",
            )
            if profile == ContinuationProfile.ENGINEERING_PREVIEW
            else (
                "target_load_reached",
                "solve_converged",
                "strict_physics_audit_passed",
            )
        ),
    )
