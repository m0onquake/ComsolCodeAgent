"""Spawn-safe factory for the production bearing COMSOL backend."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from comsol_agent.v2.extensions import (
    CompatibilityPolicy,
    ExtensionKind,
    ExtensionLoader,
    ExtensionRegistry,
    PermissionPolicy,
    PermissionSet,
    ResolutionContext,
)
from comsol_agent.v2.runtime.comsol import (
    MphBackendAdapter,
    PinnedExecutionCatalog,
    RegisteredHandlerBinding,
)

from .auditors import BearingAcceptanceMode
from .extensions import bearing_extensions
from .models import BearingSpec
from .runtime_audit import ReviewedStrictAuditCollector
from .workflow import BearingWorkflowTool


class BearingProcessBackend(MphBackendAdapter):
    """MPh backend retaining the child-local Registry snapshot lease."""

    def __init__(self, *args: Any, snapshot_lease: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._snapshot_lease = snapshot_lease

    async def stop(self) -> None:
        try:
            await super().stop()
        finally:
            if self._snapshot_lease is not None:
                lease, self._snapshot_lease = self._snapshot_lease, None
                await lease.__aexit__(None, None, None)


def create_bearing_process_backend(
    *,
    specification: dict[str, Any],
    audit_root: str,
    case_id: str,
    version: str = "6.2",
    cores: int = 1,
    port: int = 0,
    expected_versions: dict[str, str] | None = None,
    acceptance_mode: BearingAcceptanceMode | str = BearingAcceptanceMode.ENGINEERING_PREVIEW,
) -> BearingProcessBackend:
    """Construct all trusted executable state inside the dedicated child process."""

    repository_root = Path(__file__).resolve().parents[4]
    loader = ExtensionLoader(
        compatibility=CompatibilityPolicy(agent_version="2.0", comsol_version=version),
        permissions=PermissionPolicy(
            PermissionSet(
                filesystem="write", shell="none", comsol="solve", network="none"
            )
        ),
        trusted_manifest_roots=(repository_root,),
        trusted_code_roots=(repository_root,),
    )
    registry = ExtensionRegistry(loader)
    loop = asyncio.get_event_loop()
    for extension in bearing_extensions():
        loop.run_until_complete(registry.register(extension))
    loop.run_until_complete(registry.register(BearingWorkflowTool(SimpleNamespace())))
    lease = registry.snapshot()
    snapshot = loop.run_until_complete(lease.__aenter__())
    if expected_versions is not None and snapshot.versions != expected_versions:
        loop.run_until_complete(lease.__aexit__(None, None, None))
        raise RuntimeError("child Registry snapshot does not match parent pinned versions")
    bindings: list[RegisteredHandlerBinding] = []
    for kind, capability in (
        (ExtensionKind.BUILDER, "bearing.cylindrical-roller.build"),
        (ExtensionKind.DETERMINISTIC_PATH, "bearing.parameter-override"),
        (ExtensionKind.DETERMINISTIC_PATH, "bearing.dynamic-load-continuation"),
    ):
        extension = snapshot.resolve(
            kind, capability, ResolutionContext(domain="bearing")
        )[0]
        bindings.append(
            RegisteredHandlerBinding(
                extension=extension,
                extension_id=extension.manifest.id,
                extension_version=extension.manifest.version,
                extension_kind=kind,
                capability=capability,
                handler=extension.execute_model,
            )
        )
    collector = ReviewedStrictAuditCollector(
        BearingSpec.model_validate(specification),
        Path(audit_root),
        case_id=case_id,
        acceptance_mode=acceptance_mode,
    )
    return BearingProcessBackend(
        version=version,
        cores=cores,
        port=port,
        auditor=collector,
        execution_catalog=PinnedExecutionCatalog(snapshot, bindings),
        snapshot_lease=lease,
    )
