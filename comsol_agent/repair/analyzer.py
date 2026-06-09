"""Repair analysis contracts and deterministic fallback strategies.

The full architecture calls an LLM plus retrieved COMSOL API docs to diagnose
failures.  This module defines that contract and provides a deterministic
fallback that is useful before real API/RAG integration is configured.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from comsol_agent.repair.detector import ErrorReport, ErrorType


@dataclass
class Diagnosis:
    """Root-cause analysis and repair strategy."""

    error_type: ErrorType
    root_cause: str
    fix_strategy: str
    api_hints: list[str]
    confidence: float
    needs_llm_analysis: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_type"] = self.error_type.value
        return data


def build_diagnosis_prompt(
    report: ErrorReport,
    *,
    retrieved_docs: list[str] | None = None,
    conversation_context: str | None = None,
) -> str:
    """Build the LLM prompt for Phase 2 analyzer."""
    docs = "\n\n".join(retrieved_docs or ["(No retrieved docs available.)"])
    context = conversation_context or "(No additional conversation context.)"
    code = report.code_snippet or "(No related code snippet captured.)"
    return (
        "You are debugging a COMSOL simulation error.\n\n"
        f"Error type: {report.error_type.value}\n"
        f"Tool: {report.tool_name or 'unknown'}\n"
        f"Error message: {report.message}\n\n"
        f"Related code:\n{code}\n\n"
        f"Conversation context:\n{context}\n\n"
        f"Relevant API docs:\n{docs}\n\n"
        "Identify the likely root cause and propose a minimal fix approach. "
        "Preserve the user's original physics intent. Return root_cause, "
        "fix_strategy, and api_hints."
    )


def suggest_diagnosis(report: ErrorReport) -> Diagnosis:
    """Return a deterministic fallback diagnosis for a detected error."""
    if report.error_type == ErrorType.SYNTAX_ERROR:
        return Diagnosis(
            error_type=report.error_type,
            root_cause="Generated code appears syntactically invalid or incomplete.",
            fix_strategy=(
                "Repair the smallest syntax issue first, then retry the same operation "
                "without changing model intent."
            ),
            api_hints=["Check delimiters, method-call syntax, quotes, and statement boundaries."],
            confidence=0.7,
        )

    if report.error_type == ErrorType.API_ERROR:
        return Diagnosis(
            error_type=report.error_type,
            root_cause="Generated code likely called a missing or incompatible COMSOL API method.",
            fix_strategy=(
                "Verify the target COMSOL Java/MPh API call, argument order, and object type. "
                "Prefer a high-level tool if one covers the operation."
            ),
            api_hints=[
                "Confirm model.geom(), model.physics(), model.mesh(), study, and result object chains.",
                "Check Java exception names and method signatures.",
            ],
            confidence=0.65,
        )

    if report.error_type == ErrorType.PHYSICS_ERROR:
        return Diagnosis(
            error_type=report.error_type,
            root_cause="The model setup likely references missing variables, selections, domains, or boundary conditions.",
            fix_strategy=(
                "Inspect the model summary, parameters, geometry selections, and physics features before retrying."
            ),
            api_hints=[
                "List parameters and model structure before modifying physics.",
                "Verify geometry/domain/boundary selections exist.",
            ],
            confidence=0.6,
        )

    if report.error_type == ErrorType.SOLVER_ERROR:
        return Diagnosis(
            error_type=report.error_type,
            root_cause="The configured numerical problem likely failed during solve or produced invalid values.",
            fix_strategy=(
                "Do not blindly rerun. Inspect convergence status, initial values, mesh quality, "
                "material parameters, and solver tolerances."
            ),
            api_hints=[
                "Check for NaN, singular matrix, nonlinear convergence, and mesh warnings.",
                "Consider smaller load steps, refined mesh, or adjusted solver settings.",
            ],
            confidence=0.6,
        )

    if report.error_type == ErrorType.TIMEOUT_ERROR:
        return Diagnosis(
            error_type=report.error_type,
            root_cause="The operation exceeded its configured runtime limit.",
            fix_strategy=(
                "Reduce problem size or split the operation into smaller steps before increasing timeouts."
            ),
            api_hints=["Check command timeout, model size, mesh density, and study complexity."],
            confidence=0.75,
        )

    return Diagnosis(
        error_type=ErrorType.UNKNOWN,
        root_cause="The detector could not match the error to a known repair category.",
        fix_strategy=(
            "Ask for or collect more context: recent tool calls, model summary, full error output, "
            "and intended simulation step."
        ),
        api_hints=[],
        confidence=0.25,
    )
