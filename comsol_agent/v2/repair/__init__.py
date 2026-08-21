"""Public M6 diagnosis and bounded repair API."""

from .code import WorkspaceRepairExecutor
from .diagnosis import DiagnosticService
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
    "RepairResult",
    "RepairRuleContract",
    "RepairStatus",
    "RepairTraceEvent",
    "Severity",
    "SolverStrategyContract",
    "VersionCompatibility",
    "WorkspaceRepairExecutor",
]
