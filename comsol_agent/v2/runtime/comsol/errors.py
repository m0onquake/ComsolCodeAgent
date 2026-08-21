"""Runtime exceptions and cause-preserving COMSOL error classification."""

from __future__ import annotations

from .contracts import CauseFrame, ErrorClass, RuntimeFailure, RuntimeOperation, RuntimeStage


class ComsolRuntimeError(RuntimeError):
    pass


class ResourceLeaseError(ComsolRuntimeError):
    pass


class CheckpointCompatibilityError(ComsolRuntimeError):
    pass


class PhysicalAuditError(ComsolRuntimeError):
    pass


class WorkerTimeoutError(ComsolRuntimeError):
    def __init__(self, message: str, *, termination_confirmed: bool) -> None:
        super().__init__(message)
        self.termination_confirmed = termination_confirmed


class WorkerCancellationError(ComsolRuntimeError):
    def __init__(self, message: str, *, termination_confirmed: bool) -> None:
        super().__init__(message)
        self.termination_confirmed = termination_confirmed


def _safe_message(error: BaseException) -> str:
    try:
        return str(error)
    except Exception as stringify_error:
        return f"message unavailable ({type(stringify_error).__name__})"


def _cause_chain(error: BaseException) -> list[CauseFrame]:
    causes: list[CauseFrame] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        causes.append(
            CauseFrame(exception_type=type(current).__name__, message=_safe_message(current))
        )
        current = current.__cause__ or current.__context__
    return causes


def classify_backend_error(
    error: BaseException,
    stage: RuntimeStage,
    operation: RuntimeOperation | None = None,
) -> RuntimeFailure:
    """Classify without discarding the nested Java/Python exception chain."""
    causes = _cause_chain(error)
    text = " | ".join(cause.message for cause in causes).lower()
    exception_names = " ".join(cause.exception_type.lower() for cause in causes)
    termination_confirmed: bool | None = None
    if isinstance(error, WorkerCancellationError):
        error_class, code, retryable = ErrorClass.CANCELLED, "CANCELLED", False
        termination_confirmed = error.termination_confirmed
    elif type(error).__name__ in {"RunCancelledError", "CancelledError"}:
        error_class, code, retryable = ErrorClass.CANCELLED, "CANCELLED", False
        termination_confirmed = True
    elif isinstance(error, WorkerTimeoutError):
        error_class, code, retryable = ErrorClass.TIMEOUT, "TIMEOUT", True
        termination_confirmed = error.termination_confirmed
    elif isinstance(error, ResourceLeaseError):
        error_class, code, retryable = ErrorClass.RESOURCE, "RESOURCE_UNAVAILABLE", True
    elif isinstance(error, PhysicalAuditError) or "audit" in text:
        error_class, code, retryable = ErrorClass.PHYSICS_AUDIT, "PHYSICS_AUDIT_FAILURE", False
    elif "unknown feature" in text:
        error_class, code, retryable = ErrorClass.API_CODE, "UNKNOWN_FEATURE", True
    elif "invalid property" in text or "unknown property" in text:
        error_class, code, retryable = ErrorClass.API_CODE, "INVALID_PROPERTY", True
    elif "overload" in text or "typeerror" in exception_names:
        error_class, code, retryable = ErrorClass.API_CODE, "INVALID_OVERLOAD", True
    elif "empty selection" in text:
        error_class, code, retryable = ErrorClass.API_CODE, "EMPTY_SELECTION", True
    elif "entity dimension" in text or "dimension mismatch" in text:
        error_class, code, retryable = ErrorClass.API_CODE, "ENTITY_DIMENSION", True
    elif "pair" in text and any(marker in text for marker in ("source", "destination", "binding")):
        error_class, code, retryable = ErrorClass.API_CODE, "PAIR_BINDING", True
    elif any(marker in text for marker in ("license", "runtime unavailable", "server unavailable")):
        error_class, code, retryable = ErrorClass.RESOURCE, "RUNTIME_UNAVAILABLE", True
    elif operation == RuntimeOperation.MESH or "mesh" in text:
        error_class, code, retryable = ErrorClass.MESH, "MESH_FAILURE", True
    elif stage == RuntimeStage.SOLVE or any(
        marker in text for marker in ("non convergence", "nonlinear", "find a solution", "converg")
    ):
        error_class, code, retryable = (
            ErrorClass.SOLVE_CONVERGENCE,
            "NON_CONVERGENCE",
            True,
        )
    elif any(marker in text for marker in ("geometry", "boolean", "partition")):
        error_class, code, retryable = ErrorClass.GEOMETRY, "GEOMETRY_FAILURE", True
    else:
        error_class, code, retryable = ErrorClass.API_CODE, "COMSOL_API_ERROR", False
    return RuntimeFailure(
        error_class=error_class,
        code=code,
        message=causes[0].message,
        stage=stage,
        operation=operation,
        retryable=retryable,
        causes=causes,
        termination_confirmed=termination_confirmed,
    )
