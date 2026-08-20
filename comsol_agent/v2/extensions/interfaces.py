"""Domain-neutral interfaces for all V2 extension kinds."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from comsol_agent.v2.contracts import Action, Observation
from comsol_agent.v2.kernel import CancellationToken, KernelEvent

from .models import ExtensionManifest, HealthReport, ResolutionContext


@runtime_checkable
class Extension(Protocol):
    manifest: ExtensionManifest

    async def activate(self) -> None: ...
    async def deactivate(self) -> None: ...
    async def health(self) -> HealthReport: ...
    def supports(self, context: ResolutionContext) -> bool: ...


@runtime_checkable
class FunctionExtension(Extension, Protocol):
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    read_only: bool
    idempotent: bool
    timeout_seconds: float
    retryable_errors: frozenset[str]
    side_effects: tuple[str, ...]

    async def execute(
        self, action: Action, cancellation: CancellationToken
    ) -> Observation: ...


@runtime_checkable
class McpServerExtension(Extension, Protocol):
    async def list_tools(self) -> list[dict[str, Any]]: ...
    async def call_tool(
        self, name: str, arguments: dict[str, Any], cancellation: CancellationToken
    ) -> Observation: ...


@runtime_checkable
class McpToolExtension(Extension, Protocol):
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    async def execute(
        self, action: Action, cancellation: CancellationToken
    ) -> Observation: ...


@runtime_checkable
class SkillExtension(Extension, Protocol):
    async def instructions(self, context: ResolutionContext) -> str: ...


@runtime_checkable
class HookExtension(Extension, Protocol):
    async def handle(self, event: KernelEvent) -> dict[str, Any]: ...


@runtime_checkable
class RepairRuleExtension(Extension, Protocol):
    def matches(self, observation: Observation, context: ResolutionContext) -> bool: ...
    async def propose(self, observation: Observation) -> dict[str, Any]: ...
    async def verify(self, observation: Observation) -> bool: ...


@runtime_checkable
class DeterministicPathExtension(Extension, Protocol):
    def preconditions(self, context: ResolutionContext) -> tuple[str, ...]: ...
    def steps(self) -> tuple[str, ...]: ...
    def rollback(self) -> dict[str, Any]: ...
    def acceptance(self) -> tuple[str, ...]: ...


@runtime_checkable
class BuilderExtension(Extension, Protocol):
    async def build(self, specification: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class ValidatorExtension(Extension, Protocol):
    async def validate(self, subject: Any) -> dict[str, Any]: ...


@runtime_checkable
class AuditorExtension(Extension, Protocol):
    async def audit(self, subject: Any) -> dict[str, Any]: ...


@runtime_checkable
class MemoryAdapterExtension(Extension, Protocol):
    async def read(self, record_id: str) -> dict[str, Any] | None: ...
    async def write(self, record: dict[str, Any]) -> str: ...
    async def delete(self, record_id: str) -> None: ...


@runtime_checkable
class RetrieverExtension(Extension, Protocol):
    async def retrieve(self, query: str, filters: dict[str, Any]) -> list[dict[str, Any]]: ...


INTERFACE_BY_KIND: dict[str, type[Extension]] = {
    "function": FunctionExtension,
    "mcp_server": McpServerExtension,
    "mcp_tool": McpToolExtension,
    "skill": SkillExtension,
    "hook": HookExtension,
    "repair_rule": RepairRuleExtension,
    "deterministic_path": DeterministicPathExtension,
    "builder": BuilderExtension,
    "validator": ValidatorExtension,
    "auditor": AuditorExtension,
    "memory_adapter": MemoryAdapterExtension,
    "retriever": RetrieverExtension,
}
