"""Self-repair primitives."""

from comsol_agent.repair.analyzer import Diagnosis, build_diagnosis_prompt, suggest_diagnosis
from comsol_agent.repair.detector import ErrorReport, ErrorType, detect_tool_error, format_repair_notice
from comsol_agent.repair.fixer import FixedCode, build_fix_prompt, candidate_from_text, inspect_candidate_code
from comsol_agent.repair.planner import RepairPlan, format_repair_plan_message, plan_repair_action
from comsol_agent.repair.validator import (
    ValidationResult,
    preflight_fixed_code,
    validate_tool_result_after_fix,
)

__all__ = [
    "Diagnosis",
    "ErrorReport",
    "ErrorType",
    "FixedCode",
    "RepairPlan",
    "ValidationResult",
    "build_diagnosis_prompt",
    "build_fix_prompt",
    "candidate_from_text",
    "detect_tool_error",
    "format_repair_notice",
    "format_repair_plan_message",
    "inspect_candidate_code",
    "preflight_fixed_code",
    "plan_repair_action",
    "suggest_diagnosis",
    "validate_tool_result_after_fix",
]
