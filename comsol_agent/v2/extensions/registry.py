"""Lifecycle registry, deterministic resolver, and immutable run snapshots."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .errors import (
    DependentExtensionError,
    DuplicateExtensionError,
    ExtensionConflictError,
    ExtensionInvocationError,
    ExtensionNotFoundError,
    ExtensionStateError,
    ExtensionValidationError,
    MissingDependencyError,
)
from .interfaces import INTERFACE_BY_KIND, Extension
from .loader import ExtensionLoader
from .models import (
    ConflictReport,
    ExtensionCandidate,
    ExtensionKind,
    HealthReport,
    HealthStatus,
    LifecycleEvent,
    LifecycleState,
    Registration,
    ResolutionContext,
    ValidationIssue,
    ValidationResult,
)
from .policy import permissions_allow

_REQUIRED_MEMBERS: dict[ExtensionKind, tuple[str, ...]] = {
    ExtensionKind.FUNCTION: (
        "input_schema",
        "output_schema",
        "read_only",
        "idempotent",
        "timeout_seconds",
        "retryable_errors",
        "side_effects",
        "execute",
    ),
    ExtensionKind.MCP_SERVER: ("list_tools", "call_tool"),
    ExtensionKind.MCP_TOOL: ("input_schema", "output_schema", "execute"),
    ExtensionKind.SKILL: ("instructions",),
    ExtensionKind.HOOK: ("handle",),
    ExtensionKind.REPAIR_RULE: ("repair_contract", "matches", "propose", "verify"),
    ExtensionKind.SOLVER_STRATEGY: (
        "solver_contract",
        "matches",
        "propose",
        "verify",
    ),
    ExtensionKind.DETERMINISTIC_PATH: (
        "preconditions",
        "steps",
        "rollback",
        "acceptance",
    ),
    ExtensionKind.BUILDER: ("build",),
    ExtensionKind.VALIDATOR: ("validate",),
    ExtensionKind.AUDITOR: ("audit",),
    ExtensionKind.MEMORY_ADAPTER: ("read", "write", "delete"),
    ExtensionKind.RETRIEVER: ("retrieve",),
}


@dataclass
class _Record:
    extension: Extension
    state: LifecycleState
    health: HealthReport
    leases: int = 0
    pending_deactivation: bool = False
    transitioning: bool = False
    lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(frozen=True)
class _SnapshotRecord:
    extension: Extension
    health: HealthReport


class ExtensionSnapshot:
    """Immutable set of active extension objects pinned to one run."""

    def __init__(
        self,
        records: tuple[_SnapshotRecord, ...],
        release: Callable[[tuple[str, ...]], Awaitable[None]],
    ) -> None:
        self._records = records
        self._release = release
        self._closed = False
        self.versions = MappingProxyType(
            {
                record.extension.manifest.id: record.extension.manifest.version
                for record in records
            }
        )

    def resolve(
        self,
        kind: ExtensionKind,
        capability: str,
        context: ResolutionContext | None = None,
    ) -> list[Extension]:
        if self._closed:
            raise ExtensionStateError("extension snapshot is closed")
        return _resolve(
            [(record.extension, record.health) for record in self._records],
            kind,
            capability,
            context or ResolutionContext(),
        )

    def candidates(
        self,
        kind: ExtensionKind,
        capability: str,
        context: ResolutionContext | None = None,
    ) -> list[Extension]:
        """Return every healthy matching candidate in deterministic order.

        Selection services such as repair orchestration need an ordered fallback
        set so one faulty handler can be isolated without mutating the Registry.
        ``resolve`` remains the single-winner/conflict API used by normal tools.
        """
        if self._closed:
            raise ExtensionStateError("extension snapshot is closed")
        selected = context or ResolutionContext()
        candidates = []
        for record in self._records:
            extension = record.extension
            if extension.manifest.kind != kind:
                continue
            if capability not in extension.manifest.capabilities:
                continue
            if record.health.status != HealthStatus.HEALTHY:
                continue
            if selected.selected_extension_id not in {None, extension.manifest.id}:
                continue
            if not permissions_allow(
                extension.manifest.permissions, selected.required_permissions
            ):
                continue
            if not extension.supports(selected):
                continue
            candidates.append(extension)
        return sorted(
            candidates,
            key=lambda item: (
                -item.manifest.priority,
                -item.manifest.quality,
                item.manifest.id,
            ),
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._release(tuple(self.versions))

    async def __aenter__(self) -> ExtensionSnapshot:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()


class ExtensionRegistry:
    """Own extension lifecycle without any domain-specific dispatch branches."""

    def __init__(self, loader: ExtensionLoader) -> None:
        self.loader = loader
        self._records: dict[str, _Record] = {}
        self._events: list[LifecycleEvent] = []

    @property
    def events(self) -> tuple[LifecycleEvent, ...]:
        return tuple(self._events)

    def discover(self, paths: list[Path]) -> list[ExtensionCandidate]:
        return self.loader.discover(paths)

    def validate(self, candidate: ExtensionCandidate) -> ValidationResult:
        return self.loader.validate(candidate)

    async def load_and_register(
        self, candidates: list[ExtensionCandidate]
    ) -> list[Registration]:
        """Load candidates independently so one bad extension cannot abort the batch."""
        registrations: list[Registration] = []
        for candidate in candidates:
            extension_id = str(candidate.raw_manifest.get("id", candidate.path))
            try:
                extension = self.loader.load(candidate)
                registrations.append(await self.register(extension))
            except Exception as exc:
                self._record("load", extension_id, success=False, detail=str(exc))
                registrations.append(
                    Registration(
                        extension_id=extension_id,
                        version=str(candidate.raw_manifest.get("version", "0.0.0")),
                        state=LifecycleState.UNHEALTHY,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return registrations

    async def register(self, extension: Extension) -> Registration:
        manifest = extension.manifest
        if manifest.id in self._records:
            raise DuplicateExtensionError(f"duplicate extension id: {manifest.id}")
        issues = self.loader.compatibility.issues(manifest)
        issues.extend(self.loader.permissions.issues(manifest.permissions))
        issues.extend(_interface_issues(extension))
        if issues:
            raise ExtensionValidationError(issues)
        self._check_dependencies(extension)
        state = LifecycleState.REGISTERED if manifest.enabled else LifecycleState.DISABLED
        health = HealthReport(
            extension_id=manifest.id,
            status=HealthStatus.UNKNOWN if manifest.enabled else HealthStatus.DISABLED,
            detail="registered",
        )
        self._records[manifest.id] = _Record(extension=extension, state=state, health=health)
        self._record("register", manifest.id, state=state)
        if manifest.enabled:
            return await self.enable(manifest.id)
        return Registration(extension_id=manifest.id, version=manifest.version, state=state)

    async def enable(self, extension_id: str) -> Registration:
        record = self._get(extension_id)
        async with record.lifecycle_lock:
            self._check_dependencies(record.extension, require_active=True)
            record.pending_deactivation = False
            record.transitioning = True
            try:
                await record.extension.activate()
                health = await record.extension.health()
                if health.extension_id != extension_id:
                    raise ValueError("health report extension_id mismatch")
                record.health = health
                record.state = (
                    LifecycleState.ACTIVE
                    if health.status == HealthStatus.HEALTHY
                    else LifecycleState.UNHEALTHY
                )
                success = record.state == LifecycleState.ACTIVE
                detail = health.detail
            except Exception as exc:
                record.state = LifecycleState.UNHEALTHY
                record.health = HealthReport(
                    extension_id=extension_id,
                    status=HealthStatus.UNHEALTHY,
                    detail=f"{type(exc).__name__}: {exc}",
                )
                success = False
                detail = record.health.detail
            finally:
                record.transitioning = False
            self._record(
                "enable", extension_id, state=record.state, success=success, detail=detail
            )
            return Registration(
                extension_id=extension_id,
                version=record.extension.manifest.version,
                state=record.state,
                error=None if success else detail,
            )

    async def disable(self, extension_id: str) -> None:
        record = self._get(extension_id)
        async with record.lifecycle_lock:
            record.state = LifecycleState.DISABLED
            record.health = HealthReport(
                extension_id=extension_id,
                status=HealthStatus.DISABLED,
                detail="deactivation in progress",
            )
            if record.leases:
                record.pending_deactivation = True
                detail = f"deactivation deferred for {record.leases} active snapshot(s)"
            else:
                record.transitioning = True
                try:
                    detail = await self._deactivate(record)
                finally:
                    record.transitioning = False
            record.health = HealthReport(
                extension_id=extension_id, status=HealthStatus.DISABLED, detail=detail
            )
            self._record("disable", extension_id, state=record.state, detail=detail)

    def unregister(self, extension_id: str) -> None:
        record = self._get(extension_id)
        if record.state != LifecycleState.DISABLED:
            raise ExtensionStateError("disable an extension before unregistering it")
        if record.transitioning or record.lifecycle_lock.locked():
            raise ExtensionStateError(
                f"cannot unregister {extension_id}; lifecycle transition is in progress"
            )
        if record.leases:
            raise ExtensionStateError(
                f"cannot unregister {extension_id}; {record.leases} active snapshot(s) remain"
            )
        dependents = sorted(
            other.extension.manifest.id
            for other in self._records.values()
            if any(
                dependency.extension_id == extension_id
                for dependency in other.extension.manifest.dependencies
            )
        )
        capability_dependents = sorted(
            other.extension.manifest.id
            for other in self._records.values()
            if other.extension.manifest.id != extension_id
            if any(
                requirement.kind == record.extension.manifest.kind
                and requirement.capability in record.extension.manifest.capabilities
                and not self._has_capability_provider(
                    requirement.kind,
                    requirement.capability,
                    excluding=extension_id,
                )
                for requirement in other.extension.manifest.requires_capabilities
            )
        )
        dependents = sorted(set(dependents + capability_dependents))
        if dependents:
            raise DependentExtensionError(
                f"{extension_id} is required by registered extensions: {dependents}"
            )
        del self._records[extension_id]
        self._record("unregister", extension_id)

    def resolve(
        self,
        kind: ExtensionKind,
        capability: str,
        context: ResolutionContext | None = None,
    ) -> list[Extension]:
        active = [
            (record.extension, record.health)
            for record in self._records.values()
            if record.state == LifecycleState.ACTIVE
        ]
        try:
            resolved = _resolve(active, kind, capability, context or ResolutionContext())
        except ExtensionConflictError as exc:
            self._record(
                "resolve",
                ",".join(exc.report.extension_ids),
                success=False,
                detail=str(exc),
            )
            raise
        self._record("resolve", resolved[0].manifest.id if resolved else capability)
        return resolved

    async def health(self, extension_id: str) -> HealthReport:
        record = self._get(extension_id)
        async with record.lifecycle_lock:
            if record.state == LifecycleState.DISABLED:
                return record.health
            try:
                report = await record.extension.health()
            except Exception as exc:
                report = HealthReport(
                    extension_id=extension_id,
                    status=HealthStatus.UNHEALTHY,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            record.health = report
            if report.status != HealthStatus.HEALTHY:
                record.state = LifecycleState.UNHEALTHY
            self._record(
                "health",
                extension_id,
                state=record.state,
                success=report.status == "healthy",
            )
            return report

    async def invoke(self, extension_id: str, operation: str, *args: Any) -> Any:
        record = self._get(extension_id)
        if record.state != LifecycleState.ACTIVE:
            raise ExtensionStateError(f"{extension_id} is not active")
        try:
            result = getattr(record.extension, operation)(*args)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            record.state = LifecycleState.UNHEALTHY
            record.health = HealthReport(
                extension_id=extension_id,
                status=HealthStatus.UNHEALTHY,
                detail=f"{type(exc).__name__}: {exc}",
            )
            self._record("invoke", extension_id, state=record.state, success=False, detail=str(exc))
            raise ExtensionInvocationError(extension_id, operation, exc) from exc
        self._record("invoke", extension_id, state=record.state)
        return result

    def snapshot(self) -> ExtensionSnapshot:
        active_records = [
            record for record in self._records.values() if record.state == LifecycleState.ACTIVE
        ]
        for record in active_records:
            record.leases += 1
        records = tuple(
            _SnapshotRecord(extension=record.extension, health=record.health.model_copy(deep=True))
            for record in active_records
        )
        return ExtensionSnapshot(records, self._release_snapshot)

    def state(self, extension_id: str) -> LifecycleState:
        return self._get(extension_id).state

    def _get(self, extension_id: str) -> _Record:
        try:
            return self._records[extension_id]
        except KeyError as exc:
            raise ExtensionNotFoundError(extension_id) from exc

    def _check_dependencies(self, extension: Extension, *, require_active: bool = False) -> None:
        for dependency in extension.manifest.dependencies:
            record = self._records.get(dependency.extension_id)
            if record is None:
                raise MissingDependencyError(
                    f"missing dependency {dependency.extension_id} for {extension.manifest.id}"
                )
            if require_active and record.state != LifecycleState.ACTIVE:
                raise MissingDependencyError(
                    f"dependency {dependency.extension_id} is not active"
                )
            if dependency.version:
                try:
                    compatible = Version(record.extension.manifest.version) in SpecifierSet(
                        dependency.version
                    )
                except (InvalidSpecifier, InvalidVersion) as exc:
                    raise MissingDependencyError(str(exc)) from exc
                if not compatible:
                    raise MissingDependencyError(
                        f"dependency {dependency.extension_id} version "
                        f"{record.extension.manifest.version} does not satisfy {dependency.version}"
                    )
        for requirement in extension.manifest.requires_capabilities:
            if not self._has_capability_provider(
                requirement.kind,
                requirement.capability,
                require_active=require_active,
            ):
                state = "active " if require_active else ""
                raise MissingDependencyError(
                    f"missing {state}capability {requirement.kind}:{requirement.capability} "
                    f"for {extension.manifest.id}"
                )

    def _has_capability_provider(
        self,
        kind: ExtensionKind,
        capability: str,
        *,
        require_active: bool = False,
        excluding: str | None = None,
    ) -> bool:
        return any(
            extension_id != excluding
            and record.extension.manifest.kind == kind
            and capability in record.extension.manifest.capabilities
            and (not require_active or record.state == LifecycleState.ACTIVE)
            for extension_id, record in self._records.items()
        )

    async def _release_snapshot(self, extension_ids: tuple[str, ...]) -> None:
        for extension_id in extension_ids:
            record = self._records.get(extension_id)
            if record is None:
                continue
            async with record.lifecycle_lock:
                record.leases = max(0, record.leases - 1)
                if record.leases == 0 and record.pending_deactivation:
                    record.transitioning = True
                    try:
                        detail = await self._deactivate(record)
                    finally:
                        record.transitioning = False
                    record.pending_deactivation = False
                    record.health = HealthReport(
                        extension_id=extension_id,
                        status=HealthStatus.DISABLED,
                        detail=detail,
                    )
        self._record("snapshot_release", ",".join(extension_ids))

    @staticmethod
    async def _deactivate(record: _Record) -> str:
        try:
            await record.extension.deactivate()
        except Exception as exc:
            return f"deactivation isolated: {type(exc).__name__}: {exc}"
        return ""

    def _record(
        self,
        action: str,
        extension_id: str,
        *,
        state: LifecycleState | None = None,
        success: bool = True,
        detail: str = "",
    ) -> None:
        self._events.append(
            LifecycleEvent(
                sequence=len(self._events) + 1,
                action=action,
                extension_id=extension_id,
                state=state,
                success=success,
                detail=detail,
            )
        )


def _interface_issues(extension: Extension) -> list[ValidationIssue]:
    common = ("manifest", "activate", "deactivate", "health", "supports")
    missing = [
        member
        for member in (*common, *_REQUIRED_MEMBERS[extension.manifest.kind])
        if not hasattr(extension, member)
    ]
    if not missing:
        return []
    expected = INTERFACE_BY_KIND[extension.manifest.kind]
    return [
        ValidationIssue(
            code="interface_mismatch",
            location="entrypoint",
            message=f"does not implement {expected.__name__}; missing {missing}",
        )
    ]


def _resolve(
    records: list[tuple[Extension, HealthReport]],
    kind: ExtensionKind,
    capability: str,
    context: ResolutionContext,
) -> list[Extension]:
    candidates: list[tuple[Extension, HealthReport]] = []
    for extension, health in records:
        manifest = extension.manifest
        if manifest.kind != kind or capability not in manifest.capabilities:
            continue
        if context.selected_extension_id and manifest.id != context.selected_extension_id:
            continue
        if health.status != HealthStatus.HEALTHY:
            continue
        if not permissions_allow(manifest.permissions, context.required_permissions):
            continue
        try:
            supported = extension.supports(context)
        except Exception:
            continue
        if supported:
            candidates.append((extension, health))
    if context.selected_extension_id and not candidates:
        raise ExtensionNotFoundError(
            f"selected extension {context.selected_extension_id} cannot provide {capability}"
        )
    candidates.sort(
        key=lambda pair: (
            pair[0].manifest.priority,
            pair[0].manifest.quality,
            pair[0].manifest.version,
        ),
        reverse=True,
    )
    if len(candidates) > 1:
        first = candidates[0][0].manifest
        second = candidates[1][0].manifest
        if (first.priority, first.quality) == (second.priority, second.quality):
            tied = [
                extension.manifest.id
                for extension, _ in candidates
                if (extension.manifest.priority, extension.manifest.quality)
                == (first.priority, first.quality)
            ]
            raise ExtensionConflictError(
                ConflictReport(
                    kind=kind,
                    capability=capability,
                    extension_ids=tied,
                    reason=(
                        f"ambiguous active extensions for {kind}:{capability}; "
                        "set an explicit selection or distinct priority/quality"
                    ),
                )
            )
    return [extension for extension, _ in candidates]
