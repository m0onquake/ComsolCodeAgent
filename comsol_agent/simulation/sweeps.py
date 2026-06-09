"""Offline parameter sweep planning utilities."""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SweepAxis:
    """One parameter axis in a sweep."""

    parameter: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class SweepCase:
    """One expanded sweep case."""

    index: int
    parameters: dict[str, str]
    label: str


@dataclass(frozen=True)
class SweepPlan:
    """Offline plan for a COMSOL parameter sweep."""

    model_name: str
    axes: tuple[SweepAxis, ...]
    cases: tuple[SweepCase, ...]
    output_expressions: tuple[str, ...]
    estimated_runs: int
    execution_strategy: str
    next_tool_sequence: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["axes"] = [asdict(axis) for axis in self.axes]
        data["cases"] = [asdict(case) for case in self.cases]
        return data


def plan_parameter_sweep(
    *,
    model_name: str,
    parameters: dict[str, list[str] | tuple[str, ...]],
    output_expressions: list[str] | tuple[str, ...] | None = None,
    max_cases: int = 100,
) -> SweepPlan:
    """Expand parameter axes into an offline sweep plan.

    This does not call COMSOL. Runtime execution should iterate over cases with
    comsol_set_parameter, comsol_solve, and comsol_evaluate.
    """
    axes = _normalize_axes(parameters)
    estimated_runs = _product_size(axes)
    warnings = []
    if estimated_runs == 0:
        warnings.append("Sweep has no runnable cases.")
    if estimated_runs > max_cases:
        warnings.append(
            f"Sweep expands to {estimated_runs} cases; showing first {max_cases} cases only."
        )

    cases = _expand_cases(axes, max_cases=max_cases)
    expressions = tuple(output_expressions or ())
    next_tools = ("comsol_set_parameter", "comsol_solve")
    if expressions:
        next_tools = (*next_tools, "comsol_evaluate")

    return SweepPlan(
        model_name=model_name,
        axes=tuple(axes),
        cases=tuple(cases),
        output_expressions=expressions,
        estimated_runs=estimated_runs,
        execution_strategy=(
            "For each case, set every parameter, run the selected study, "
            "then evaluate requested output expressions. Persist each result row."
        ),
        next_tool_sequence=next_tools,
        warnings=tuple(warnings),
    )


def _normalize_axes(parameters: dict[str, list[str] | tuple[str, ...]]) -> list[SweepAxis]:
    axes = []
    for name, raw_values in parameters.items():
        values = tuple(str(value) for value in raw_values if str(value))
        if not name.strip():
            raise ValueError("Parameter names must be non-empty.")
        if not values:
            raise ValueError(f"Parameter '{name}' must have at least one value.")
        axes.append(SweepAxis(parameter=name, values=values))
    if not axes:
        raise ValueError("At least one sweep parameter is required.")
    return axes


def _product_size(axes: list[SweepAxis]) -> int:
    total = 1
    for axis in axes:
        total *= len(axis.values)
    return total


def _expand_cases(axes: list[SweepAxis], *, max_cases: int) -> list[SweepCase]:
    cases = []
    names = [axis.parameter for axis in axes]
    value_products = itertools.product(*(axis.values for axis in axes))
    for index, values in enumerate(value_products, start=1):
        if len(cases) >= max_cases:
            break
        params = dict(zip(names, values, strict=True))
        label = ", ".join(f"{name}={value}" for name, value in params.items())
        cases.append(SweepCase(index=index, parameters=params, label=label))
    return cases
