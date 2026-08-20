"""Structured failures raised at extension-system boundaries."""

from __future__ import annotations

from .models import ConflictReport, ValidationIssue


class ExtensionError(RuntimeError):
    """Base error for extension discovery, validation, and lifecycle operations."""


class ExtensionValidationError(ExtensionError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{issue.code}: {issue.message}" for issue in issues))


class DuplicateExtensionError(ExtensionError):
    pass


class MissingDependencyError(ExtensionError):
    pass


class DependentExtensionError(ExtensionError):
    pass


class ExtensionNotFoundError(ExtensionError):
    pass


class ExtensionStateError(ExtensionError):
    pass


class ExtensionInvocationError(ExtensionError):
    def __init__(self, extension_id: str, operation: str, cause: Exception) -> None:
        self.extension_id = extension_id
        self.operation = operation
        self.cause = cause
        super().__init__(
            f"{extension_id}.{operation} failed with {type(cause).__name__}: {cause}"
        )


class ExtensionConflictError(ExtensionError):
    def __init__(self, report: ConflictReport) -> None:
        self.report = report
        super().__init__(report.reason)
