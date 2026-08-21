"""Strict contracts for the V2 dynamic extension system."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from comsol_agent.v2.contracts.models import ContractModel, utc_now

API_VERSION = "comsol-agent/v2alpha1"


class ExtensionKind(StrEnum):
    FUNCTION = "function"
    MCP_SERVER = "mcp_server"
    MCP_TOOL = "mcp_tool"
    SKILL = "skill"
    HOOK = "hook"
    REPAIR_RULE = "repair_rule"
    SOLVER_STRATEGY = "solver_strategy"
    DETERMINISTIC_PATH = "deterministic_path"
    BUILDER = "builder"
    VALIDATOR = "validator"
    AUDITOR = "auditor"
    MEMORY_ADAPTER = "memory_adapter"
    RETRIEVER = "retriever"


class FilesystemPermission(StrEnum):
    NONE = "none"
    READ = "read"
    WRITE = "write"


class ShellPermission(StrEnum):
    NONE = "none"
    EXECUTE = "execute"


class ComsolPermission(StrEnum):
    NONE = "none"
    MODEL_READ = "model_read"
    MODEL_WRITE = "model_write"
    SOLVE = "solve"


class NetworkPermission(StrEnum):
    NONE = "none"
    CLIENT = "client"
    SERVER = "server"


class PermissionSet(ContractModel):
    """Explicit authority requested by an extension."""

    filesystem: FilesystemPermission
    shell: ShellPermission
    comsol: ComsolPermission
    network: NetworkPermission

    def tokens(self) -> frozenset[str]:
        return frozenset(
            {
                f"filesystem:{self.filesystem}",
                f"shell:{self.shell}",
                f"comsol:{self.comsol}",
                f"network:{self.network}",
            }
        )


class CompatibilitySpec(ContractModel):
    agent_api: str = Field(min_length=1)
    comsol: list[str] = Field(default_factory=list)


class DependencySpec(ContractModel):
    extension_id: str = Field(min_length=1)
    version: str = Field(default="", description="PEP 440 version specifier")


class CapabilityRequirement(ContractModel):
    kind: ExtensionKind
    capability: str = Field(min_length=1)


class ExtensionManifest(ContractModel):
    """Versioned manifest shared by every extension kind."""

    api_version: str
    kind: ExtensionKind
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    enabled: bool
    entrypoint: str = Field(pattern=r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$")
    description: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    compatibility: CompatibilitySpec
    permissions: PermissionSet
    priority: int = 0
    quality: float = Field(default=0.0, ge=0.0, le=1.0)
    config_schema: str | dict[str, Any] | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[DependencySpec] = Field(default_factory=list)
    requires_capabilities: list[CapabilityRequirement] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    repair_contract: dict[str, Any] | None = None
    solver_strategy_contract: dict[str, Any] | None = None
    tests: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identity_and_dependencies(self) -> ExtensionManifest:
        if self.api_version != API_VERSION:
            raise ValueError(f"api_version must be {API_VERSION}")
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("capabilities must be unique")
        dependency_ids = [dependency.extension_id for dependency in self.dependencies]
        if self.id in dependency_ids:
            raise ValueError("an extension cannot depend on itself")
        if len(dependency_ids) != len(set(dependency_ids)):
            raise ValueError("dependencies must be unique")
        capability_keys = [
            (requirement.kind, requirement.capability)
            for requirement in self.requires_capabilities
        ]
        if len(capability_keys) != len(set(capability_keys)):
            raise ValueError("requires_capabilities must be unique")
        if self.kind == ExtensionKind.REPAIR_RULE and self.repair_contract is None:
            raise ValueError("repair_rule manifests require repair_contract")
        if (
            self.kind == ExtensionKind.SOLVER_STRATEGY
            and self.solver_strategy_contract is None
        ):
            raise ValueError("solver_strategy manifests require solver_strategy_contract")
        return self


class CandidateState(StrEnum):
    DISCOVERED = "discovered"
    VALIDATED = "validated"
    REJECTED = "rejected"


class ExtensionCandidate(ContractModel):
    path: Path
    raw_manifest: dict[str, Any] = Field(default_factory=dict)
    manifest: ExtensionManifest | None = None
    state: CandidateState = CandidateState.DISCOVERED


class ValidationIssue(ContractModel):
    code: str
    message: str
    location: str | None = None


class ValidationResult(ContractModel):
    valid: bool
    candidate: ExtensionCandidate
    issues: list[ValidationIssue] = Field(default_factory=list)


class LifecycleState(StrEnum):
    REGISTERED = "registered"
    DISABLED = "disabled"
    ACTIVE = "active"
    UNHEALTHY = "unhealthy"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class HealthReport(ContractModel):
    extension_id: str
    status: HealthStatus
    detail: str = ""
    checked_at: datetime = Field(default_factory=utc_now)


class Registration(ContractModel):
    extension_id: str
    version: str
    state: LifecycleState
    error: str | None = None


class ResolutionContext(ContractModel):
    selected_extension_id: str | None = None
    domain: str | None = None
    signature: dict[str, Any] = Field(default_factory=dict)
    required_permissions: frozenset[str] = Field(default_factory=frozenset)


class ConflictReport(ContractModel):
    kind: ExtensionKind
    capability: str
    extension_ids: list[str]
    reason: str


class LifecycleEvent(ContractModel):
    sequence: int = Field(ge=1)
    action: str
    extension_id: str
    state: LifecycleState | None = None
    success: bool = True
    detail: str = ""
    occurred_at: datetime = Field(default_factory=utc_now)
