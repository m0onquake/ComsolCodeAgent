"""Repair-code generation contracts and offline candidate checks."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from comsol_agent.repair.analyzer import Diagnosis


@dataclass
class FixedCode:
    """Candidate code produced by a repair step."""

    code: str
    explanation: str
    confidence: float
    warnings: list[str]

    @property
    def is_usable(self) -> bool:
        return bool(self.code.strip()) and self.confidence > 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_fix_prompt(
    *,
    original_code: str,
    diagnosis: Diagnosis,
    constraints: list[str] | None = None,
) -> str:
    """Build the LLM prompt for Phase 3 fixer."""
    constraint_text = "\n".join(f"- {item}" for item in (constraints or _default_constraints()))
    hints = "\n".join(f"- {hint}" for hint in diagnosis.api_hints) or "- No API hints available."
    return (
        "Given this COMSOL code:\n"
        f"{original_code or '(No code captured.)'}\n\n"
        f"Root cause: {diagnosis.root_cause}\n"
        f"Fix strategy: {diagnosis.fix_strategy}\n"
        f"API hints:\n{hints}\n\n"
        "Generate corrected code.\n"
        "Rules:\n"
        f"{constraint_text}\n\n"
        "Return only the corrected code unless explicitly asked for explanation."
    )


def candidate_from_text(
    text: str,
    *,
    explanation: str = "",
    confidence: float = 0.5,
) -> FixedCode:
    """Normalize an LLM/raw candidate into a FixedCode object."""
    code = _strip_code_fences(text).strip()
    warnings = inspect_candidate_code(code)
    adjusted_confidence = confidence
    if not code:
        warnings.append("Candidate code is empty.")
        adjusted_confidence = 0.0
    if warnings:
        adjusted_confidence = min(adjusted_confidence, 0.4)

    return FixedCode(
        code=code,
        explanation=explanation,
        confidence=max(0.0, min(1.0, adjusted_confidence)),
        warnings=warnings,
    )


def inspect_candidate_code(code: str) -> list[str]:
    """Return static warnings for risky or unusable repair code."""
    warnings: list[str] = []
    lowered = code.lower()
    risky_patterns = {
        r"\bsudo\b": "Privileged shell invocation detected.",
        r"rm\s+-rf\s+/": "Dangerous recursive deletion detected.",
        r"delete\(\)": "Potential destructive API call detected.",
        r"\bformat\s*\(": "Potential disk formatting call detected.",
        r"system\.exit": "Process termination call detected.",
        r"runtime\.getruntime\(\)\.exec": "Nested process execution detected.",
    }
    for pattern, warning in risky_patterns.items():
        if re.search(pattern, lowered):
            warnings.append(warning)

    if len(code) > 20000:
        warnings.append("Candidate code is unusually long; review before execution.")

    return warnings


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text

    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return text


def _default_constraints() -> list[str]:
    return [
        "Make the minimal change needed to address the detected error.",
        "Preserve the original physics intent and model scope.",
        "Use correct COMSOL Java API or MPh calls for the target operation.",
        "Do not save, delete, overwrite, or close user models unless requested.",
    ]
