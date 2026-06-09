"""Repair validation contracts.

Runtime validation requires executing COMSOL/tool calls.  The functions here
provide the offline preflight layer: they reject obviously unsafe candidates and
normalize post-execution results when real execution is available.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from comsol_agent.repair.detector import ErrorReport, ErrorType, detect_tool_error
from comsol_agent.repair.fixer import FixedCode, inspect_candidate_code


@dataclass
class ValidationResult:
    """Result of validating a repair candidate."""

    success: bool
    warnings: list[str]
    new_error: ErrorReport | None = None
    requires_runtime: bool = False
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.new_error is not None:
            data["new_error"] = self.new_error.to_dict()
        return data


def preflight_fixed_code(candidate: FixedCode) -> ValidationResult:
    """Validate a FixedCode candidate before runtime execution."""
    warnings = list(candidate.warnings)
    warnings.extend(inspect_candidate_code(candidate.code))
    warnings = sorted(set(warnings))

    if not candidate.code.strip():
        return ValidationResult(
            success=False,
            warnings=warnings or ["Candidate code is empty."],
            requires_runtime=False,
            details="No code is available to validate.",
        )

    if warnings:
        return ValidationResult(
            success=False,
            warnings=warnings,
            requires_runtime=False,
            details="Candidate failed static preflight validation.",
        )

    return ValidationResult(
        success=True,
        warnings=[],
        requires_runtime=True,
        details="Candidate passed static preflight; runtime COMSOL validation is still required.",
    )


def validate_tool_result_after_fix(
    *,
    tool_name: str,
    tool_output: str | dict[str, Any],
    original_error_type: ErrorType | None = None,
) -> ValidationResult:
    """Normalize a real post-fix tool result after runtime execution."""
    parsed = _parse_output(tool_output)
    if isinstance(parsed, dict) and parsed.get("success") is True:
        warnings = []
        if original_error_type == ErrorType.SOLVER_ERROR:
            warnings.append("Solver repair succeeded; physical plausibility checks are still recommended.")
        return ValidationResult(
            success=True,
            warnings=warnings,
            requires_runtime=False,
            details="Runtime tool result reported success.",
        )

    report = detect_tool_error(tool_name=tool_name, tool_output=tool_output)
    same_error = original_error_type is not None and report.error_type == original_error_type
    details = (
        "Runtime validation failed with the same error category."
        if same_error
        else "Runtime validation failed with a new or unknown error category."
    )
    return ValidationResult(
        success=False,
        warnings=[],
        new_error=report,
        requires_runtime=False,
        details=details,
    )


def _parse_output(tool_output: str | dict[str, Any]) -> str | dict[str, Any]:
    if isinstance(tool_output, dict):
        return tool_output
    try:
        parsed = json.loads(tool_output)
        return parsed if isinstance(parsed, dict) else str(parsed)
    except json.JSONDecodeError:
        return tool_output
