"""Public M6 diagnosis and bounded repair API."""

from .code import WorkspaceRepairExecutor
from .diagnosis import DiagnosticService
from .llm import RestrictedLLMPatchProvider
from .memory import GovernedRepairCaseSource
from .models import (
    AffectedScope,
    CauseSummary,
    Diagnosis,
    DiagnosticErrorClass,
    ErrorCode,
    EvidenceReference,
    RepairAttempt,
    RepairCandidate,
    RepairExecutionContext,
    RepairExecutionLimits,
    RepairKind,
    RepairResult,
    RepairRuleContract,
    RepairStatus,
    RepairTraceEvent,
    Severity,
    SolverStrategyContract,
    VersionCompatibility,
)
from .orchestrator import CandidateProvider, RepairExecutor, RepairOrchestrator
from .router import ObservationRepairRouter

__all__ = [
    "CandidateProvider",
    "AffectedScope",
    "CauseSummary",
    "Diagnosis",
    "DiagnosticErrorClass",
    "DiagnosticService",
    "ErrorCode",
    "EvidenceReference",
    "GovernedRepairCaseSource",
    "RepairAttempt",
    "RepairCandidate",
    "RepairExecutor",
    "RepairExecutionContext",
    "RepairExecutionLimits",
    "RepairKind",
    "RepairOrchestrator",
    "ObservationRepairRouter",
    "RepairResult",
    "RestrictedLLMPatchProvider",
    "RepairRuleContract",
    "RepairStatus",
    "RepairTraceEvent",
    "Severity",
    "SolverStrategyContract",
    "VersionCompatibility",
    "WorkspaceRepairExecutor",
]
