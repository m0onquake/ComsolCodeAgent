"""Dataset- and target-step-bound bearing result evidence."""

from __future__ import annotations

import math
from typing import Any


def evaluate_target_results(
    java_model: Any,
    *,
    dataset: str,
    target_load_n: float,
) -> dict[str, Any]:
    """Evaluate stress/displacement on the exact radial-load solution step.

    Expressions are explicitly normalized to SI units.  The returned evidence
    records the dataset, parameter series, one-based solution number, node kind,
    property bindings, and selected value so the Auditor need not infer result
    provenance from a generic MPh ``evaluate`` call.
    """
    target = float(target_load_n)
    if not dataset:
        raise ValueError("a concrete COMSOL result dataset is required")
    parameter_values = _evaluate_series(
        java_model,
        tag="v2_target_radial_load",
        kind="EvalGlobal",
        expression="radial_load/1[N]",
        dataset=dataset,
    )
    matches = [
        index
        for index, value in enumerate(parameter_values)
        if math.isclose(value, target, rel_tol=1e-9, abs_tol=1e-12)
    ]
    if not matches:
        raise RuntimeError(
            f"target radial_load={target:g} N is absent from dataset {dataset!r}: "
            f"{parameter_values!r}"
        )
    index = matches[-1]
    solution_number = index + 1
    stress = _evaluate_bound_field(
        java_model,
        tag="v2_target_max_mises",
        expression="solid.mises/1[Pa]",
        base_expression="solid.mises",
        unit="Pa",
        dataset=dataset,
        solution_number=solution_number,
        expected_series_length=len(parameter_values),
        expected_series_index=index,
    )
    displacement = _evaluate_bound_field(
        java_model,
        tag="v2_target_max_displacement",
        expression="solid.disp/1[m]",
        base_expression="solid.disp",
        unit="m",
        dataset=dataset,
        solution_number=solution_number,
        expected_series_length=len(parameter_values),
        expected_series_index=index,
    )
    return {
        "success": True,
        "dataset": dataset,
        "parameter_name": "radial_load",
        "parameter_expression": "radial_load/1[N]",
        "parameter_unit": "N",
        "parameter_values_n": parameter_values,
        "target_parameter_value_n": target,
        "selected_parameter_value_n": parameter_values[index],
        "solution_number": solution_number,
        "selection_policy": "last solution whose normalized radial_load equals target",
        "stress": stress,
        "displacement": displacement,
    }


def _evaluate_bound_field(
    java_model: Any,
    *,
    tag: str,
    expression: str,
    base_expression: str,
    unit: str,
    dataset: str,
    solution_number: int,
    expected_series_length: int,
    expected_series_index: int,
) -> dict[str, Any]:
    series = _evaluate_series(
        java_model,
        tag=tag,
        kind="MaxVolume",
        expression=expression,
        dataset=dataset,
    )
    if len(series) != expected_series_length:
        raise RuntimeError(
            f"{tag} result count {len(series)} does not match parameter-step count "
            f"{expected_series_length}"
        )
    selected_from_series = series[expected_series_index]
    node = java_model.result().numerical(tag)
    bindings = _bind_solution_number(node, solution_number)
    selected_values = _flatten_numeric(node.getReal())
    if not selected_values:
        raise RuntimeError(f"{tag} returned no value after target-step binding")
    selected = selected_values[-1]
    if not math.isclose(selected, selected_from_series, rel_tol=1e-9, abs_tol=1e-15):
        raise RuntimeError(
            f"{tag} target-step value {selected} disagrees with series value "
            f"{selected_from_series}"
        )
    return {
        "success": True,
        "value": selected,
        "expression": expression,
        "base_expression": base_expression,
        "unit": unit,
        "dataset": dataset,
        "solution_number": solution_number,
        "node_tag": tag,
        "node_kind": "MaxVolume",
        "source": "java:MaxVolume.getReal",
        "solution_bindings": bindings,
        "series_values": series,
    }


def _evaluate_series(
    java_model: Any,
    *,
    tag: str,
    kind: str,
    expression: str,
    dataset: str,
) -> list[float]:
    numerical = java_model.result().numerical()
    if tag in _tags(numerical):
        numerical.remove(tag)
    numerical.create(tag, kind)
    node = java_model.result().numerical(tag)
    if kind == "MaxVolume":
        node.selection().all()
    node.set("expr", [expression])
    node.set("data", dataset)
    values = _flatten_numeric(node.getReal())
    if not values or not all(math.isfinite(value) for value in values):
        raise RuntimeError(f"{tag} returned missing or non-finite values")
    return values


def _bind_solution_number(node: Any, solution_number: int) -> tuple[dict[str, Any], ...]:
    bindings: list[dict[str, Any]] = []
    for property_name, value in (
        ("looplevel", [int(solution_number)]),
        ("solnum", str(int(solution_number))),
        ("outersolnum", str(int(solution_number))),
    ):
        try:
            node.set(property_name, value)
            bindings.append({"property": property_name, "value": value})
        except Exception:
            continue
    if not bindings:
        raise RuntimeError("COMSOL result node accepted no explicit solution-number binding")
    return tuple(bindings)


def _tags(container: Any) -> list[str]:
    try:
        return [str(tag) for tag in list(container.tags())]
    except Exception:
        return []


def _flatten_numeric(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        try:
            return [float(value)]
        except ValueError:
            return []
    if isinstance(value, (int, float)):
        return [float(value)]
    try:
        items = list(value)
    except Exception:
        try:
            return [float(value)]
        except (TypeError, ValueError):
            return []
    flattened: list[float] = []
    for item in items:
        flattened.extend(_flatten_numeric(item))
    return flattened
