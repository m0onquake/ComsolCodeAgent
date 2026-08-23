"""Typed COMSOL solver bindings for the bearing deterministic paths."""

from __future__ import annotations

import math
from typing import Any


def apply_solver_relative_tolerance(
    java_model: Any,
    value: float,
    *,
    solution_tag: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Set and read back COMSOL's ``stol`` relative-tolerance property.

    The value is a solver-node property, not a COMSOL model parameter.  A
    successful return therefore proves both the target node and its read-back
    value; callers must treat an empty or unverifiable binding as failure.
    """
    tolerance = float(value)
    if not math.isfinite(tolerance) or not 0.0 < tolerance <= 0.1:
        raise ValueError("solver relative tolerance must be finite and in (0, 0.1]")

    if solution_tag is None:
        tags = _tags(java_model.sol())
        if not tags:
            java_model.study("std1").createAutoSequences("sol")
            tags = _tags(java_model.sol())
    else:
        tags = [solution_tag]
    if not tags:
        raise RuntimeError("no COMSOL solution sequence is available for relative tolerance")

    bindings: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for tag in tags:
        try:
            stationary = java_model.sol(tag).feature("s1")
            stationary.set("stol", tolerance)
            actual = _read_numeric_property(stationary, "stol")
            if actual is None or not math.isclose(actual, tolerance, rel_tol=1e-12, abs_tol=0.0):
                raise RuntimeError(f"stol read-back mismatch: expected {tolerance}, got {actual}")
            bindings.append(
                {
                    "solution_tag": str(tag),
                    "feature_tag": "s1",
                    "property": "stol",
                    "requested": tolerance,
                    "actual": actual,
                    "source": "java:Solution/Stationary.set+readback",
                }
            )
        except Exception as error:
            failures.append({"solution_tag": str(tag), "error": str(error)})
    if not bindings or failures:
        raise RuntimeError(
            "solver relative tolerance binding failed: "
            + repr({"bindings": bindings, "failures": failures})
        )
    return tuple(bindings)


def _tags(container: Any) -> list[str]:
    return [str(tag) for tag in list(container.tags())]


def _read_numeric_property(node: Any, name: str) -> float | None:
    for getter in ("getDouble", "getString", "get"):
        try:
            raw = getattr(node, getter)(name)
            return float(raw)
        except Exception:
            continue
    return None
