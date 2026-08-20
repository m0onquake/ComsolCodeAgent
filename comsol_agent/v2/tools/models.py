"""Strict, domain-neutral contracts for workspace and sandbox tools."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from comsol_agent.v2.contracts.models import ContractModel


class WorkspaceErrorClass(StrEnum):
    PATH_OUTSIDE_WORKSPACE = "path_outside_workspace"
    PATH_NOT_FOUND = "path_not_found"
    PATH_NOT_FILE = "path_not_file"
    SYMLINK_REJECTED = "symlink_rejected"
    BINARY_FILE = "binary_file"
    FILE_TOO_LARGE = "file_too_large"
    PATCH_CONFLICT = "patch_conflict"
    CHECKPOINT_NOT_FOUND = "checkpoint_not_found"
    INVALID_REQUEST = "invalid_request"


class WorkspaceToolError(RuntimeError):
    """A stable error classification at the workspace authority boundary."""

    def __init__(self, error_class: WorkspaceErrorClass, message: str) -> None:
        self.error_class = error_class
        super().__init__(message)


class SearchMatch(ContractModel):
    path: str
    line: int = Field(ge=1)
    column: int = Field(ge=1)
    text: str


class FileRead(ContractModel):
    path: str
    content: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TextReplacement(ContractModel):
    """One exact replacement; ambiguity is rejected instead of guessed."""

    path: str = Field(min_length=1)
    old: str
    new: str
    expected_count: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def changes_content(self) -> TextReplacement:
        if self.old == self.new:
            raise ValueError("a text replacement must change content")
        if not self.old:
            raise ValueError("old text cannot be empty")
        return self


class PatchSet(ContractModel):
    description: str = Field(min_length=1)
    replacements: list[TextReplacement] = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)


class AppliedPatch(ContractModel):
    description: str
    paths: list[str]
    diff: str
    evidence: list[str] = Field(default_factory=list)


class CheckpointRef(ContractModel):
    checkpoint_id: str
    paths: list[str]


class SandboxStatus(StrEnum):
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    OUTPUT_LIMIT = "output_limit"


class CommandSpec(ContractModel):
    argv: list[str] = Field(min_length=1)
    cwd: str = "."
    timeout_seconds: float = Field(default=60.0, gt=0)
    env: dict[str, str] = Field(default_factory=dict)


class SandboxResult(ContractModel):
    argv: list[str]
    cwd: str
    status: SandboxStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = Field(ge=0)
    output_truncated: bool = False


class TestFailure(ContractModel):
    node_id: str
    message: str
    detail: str = ""
    location: str | None = None
    kind: str = "failure"


class IterationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class CodeIterationResult(ContractModel):
    status: IterationStatus
    observations: list[dict]
    patches: list[AppliedPatch]
    repair_attempts: int = Field(ge=0)
    rolled_back: bool = False
    failure_reason: str | None = None
