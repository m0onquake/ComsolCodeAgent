"""Deterministic repair action planning for failed tool calls."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from comsol_agent.repair.analyzer import Diagnosis
from comsol_agent.repair.detector import ErrorReport, ErrorType


@dataclass(frozen=True)
class RepairPlan:
    """Structured next-step guidance for the repair loop."""

    action: str
    risk_level: str
    can_auto_retry: bool
    requires_user_confirmation: bool
    suggested_tools: tuple[str, ...]
    rationale: str
    constraints: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["suggested_tools"] = list(self.suggested_tools)
        data["constraints"] = list(self.constraints)
        return data


def plan_repair_action(report: ErrorReport, diagnosis: Diagnosis) -> RepairPlan:
    """Create a conservative repair action plan from a detected failure."""
    tool_name = report.tool_name or ""

    if report.error_type == ErrorType.SYNTAX_ERROR:
        return RepairPlan(
            action="fix_code_and_retry",
            risk_level="medium",
            can_auto_retry=bool(report.code_snippet),
            requires_user_confirmation=False,
            suggested_tools=_syntax_tools(tool_name),
            rationale=(
                "The failure appears syntactic. A minimal code correction can be retried "
                "when the generated candidate passes static validation."
            ),
            constraints=_base_constraints(),
        )

    if report.error_type == ErrorType.API_ERROR:
        return RepairPlan(
            action="inspect_api_usage_then_retry",
            risk_level="medium",
            can_auto_retry=bool(report.code_snippet),
            requires_user_confirmation=False,
            suggested_tools=_api_tools(tool_name),
            rationale=(
                "The failure likely came from an invalid COMSOL/MPh API call. Inspect the "
                "model and prefer high-level tools before retrying corrected code."
            ),
            constraints=_base_constraints(),
        )

    if report.error_type == ErrorType.PHYSICS_ERROR:
        return RepairPlan(
            action="inspect_model_setup",
            risk_level="high",
            can_auto_retry=False,
            requires_user_confirmation=False,
            suggested_tools=("comsol_get_model_summary", "comsol_list_parameters"),
            rationale=(
                "The model setup may reference missing variables, selections, or domains. "
                "Gather model structure before changing physics."
            ),
            constraints=(
                *_base_constraints(),
                "Do not create or delete physics features until the missing selection/variable is identified.",
            ),
        )

    if report.error_type == ErrorType.SOLVER_ERROR:
        return RepairPlan(
            action="diagnose_solver_before_retry",
            risk_level="high",
            can_auto_retry=False,
            requires_user_confirmation=False,
            suggested_tools=("comsol_get_model_summary", "comsol_list_parameters"),
            rationale=(
                "A failed solve can indicate numerical instability or invalid physics. "
                "Inspect convergence context and model parameters before retrying."
            ),
            constraints=(
                *_base_constraints(),
                "Do not blindly rerun the same solve without changing a solver, mesh, load-step, or model condition.",
            ),
        )

    if report.error_type == ErrorType.TIMEOUT_ERROR:
        return RepairPlan(
            action="reduce_scope_or_timeout",
            risk_level="medium",
            can_auto_retry=False,
            requires_user_confirmation=True,
            suggested_tools=_timeout_tools(tool_name),
            rationale=(
                "The operation exceeded its runtime budget. Reducing problem size is safer "
                "than simply increasing timeouts."
            ),
            constraints=(
                *_base_constraints(),
                "Ask before increasing timeout or compute cost materially.",
            ),
        )

    return RepairPlan(
        action="collect_more_context",
        risk_level="unknown",
        can_auto_retry=False,
        requires_user_confirmation=False,
        suggested_tools=("comsol_get_model_summary", "comsol_list_parameters"),
        rationale=diagnosis.fix_strategy,
        constraints=_base_constraints(),
    )


def format_repair_plan_message(plan: RepairPlan) -> str:
    """Format a repair plan for the next LLM turn."""
    tools = ", ".join(plan.suggested_tools) or "(none)"
    constraints = "\n".join(f"- {item}" for item in plan.constraints)
    return (
        "Structured repair plan:\n"
        f"- action: {plan.action}\n"
        f"- risk_level: {plan.risk_level}\n"
        f"- can_auto_retry: {str(plan.can_auto_retry).lower()}\n"
        f"- requires_user_confirmation: {str(plan.requires_user_confirmation).lower()}\n"
        f"- suggested_tools: {tools}\n"
        f"- rationale: {plan.rationale}\n"
        "Constraints:\n"
        f"{constraints}"
    )


def _syntax_tools(tool_name: str) -> tuple[str, ...]:
    if tool_name == "comsol_execute_java":
        return ("comsol_execute_java",)
    return (tool_name,) if tool_name else ()


def _api_tools(tool_name: str) -> tuple[str, ...]:
    if tool_name == "comsol_execute_java":
        return ("comsol_get_model_summary", "comsol_execute_java")
    if tool_name.startswith("comsol_"):
        return ("comsol_get_model_summary", tool_name)
    return (tool_name,) if tool_name else ()


def _timeout_tools(tool_name: str) -> tuple[str, ...]:
    if tool_name in {"simulation_run_parameter_sweep", "simulation_rerun_artifact"}:
        return ("simulation_plan_parameter_sweep", tool_name)
    if tool_name:
        return (tool_name,)
    return ()


def _base_constraints() -> tuple[str, ...]:
    return (
        "Make the smallest change needed to recover.",
        "Preserve the user's physical modeling intent.",
        "Prefer high-level COMSOL tools over arbitrary Java when they cover the operation.",
        "Do not save, overwrite, delete, or close user models unless requested.",
    )
