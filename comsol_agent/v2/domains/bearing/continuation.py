"""Direction-aware, bounded radial-load continuation planning."""

from __future__ import annotations

import math

from pydantic import Field

from comsol_agent.v2.contracts.models import ContractModel

from .models import BearingSpec, LoadDirection


class ContinuationChunk(ContractModel):
    values_n: tuple[float, ...] = Field(min_length=1)
    reuse_previous_solution: bool = True


class ContinuationPlan(ContractModel):
    parameter: str = "radial_load"
    target_n: float
    direction: LoadDirection
    chunks: tuple[ContinuationChunk, ...]
    max_solves: int = Field(ge=1)
    rollback_checkpoint: str = "B_configured_model"
    success_criteria: tuple[str, ...] = (
        "target_load_reached",
        "solve_converged",
        "strict_physics_audit_passed",
    )


def build_continuation(
    spec: BearingSpec, *, last_converged_n: float | None = None
) -> ContinuationPlan:
    target = spec.target_radial_load_n
    directional = (
        spec.load_direction != LoadDirection.POSITIVE_X or abs(spec.roller_phase_deg) > 1e-12
    )
    seeds = [1e-6, 1e-4, 0.005, 0.01, 0.02, 0.05, 0.08, 0.101, 0.2, 0.5, 1.0]
    if not directional:
        seeds = [1e-6, 1e-4, 0.01, 0.02, 0.05, 0.08, 0.101, 0.5, 1.0]
    values = [value for value in seeds if value < target * (1 - 1e-12)]
    cursor = values[-1] if values else min(1e-6, target)
    while cursor * 2 < target * (1 - 1e-12):
        cursor *= 2
        values.append(cursor)
    values.append(target)
    if last_converged_n and math.isfinite(last_converged_n) and last_converged_n > 0:
        values = [last_converged_n, *[value for value in values if value > last_converged_n]]
    values = list(dict.fromkeys(float(value) for value in values))
    cutoffs = (0.02, 0.101) if directional else (0.101,)
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
    )
