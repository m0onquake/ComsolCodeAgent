"""Manifest-backed extension objects for the V2 bearing domain."""

from __future__ import annotations

from typing import Any

from comsol_agent.v2.extensions import (
    API_VERSION,
    ExtensionKind,
    ExtensionManifest,
    HealthReport,
    HealthStatus,
    ResolutionContext,
)

from .auditors import (
    BearingContactAuditor,
    BearingEngineeringPreviewAuditor,
    BearingGeometryAuditor,
    BearingPhysicalAuditor,
    BearingSelectionAuditor,
)
from .builder import CylindricalRollerBearingBuilder
from .models import BearingSpec
from .paths import DynamicLoadContinuation, ParameterOverridePath
from .skill import BearingSkill

ENTRYPOINT = "comsol_agent.v2.domains.bearing.extensions:BearingExtension"


def _manifest(
    extension_id: str,
    kind: ExtensionKind,
    capabilities: list[str],
    description: str,
    *,
    comsol: str = "none",
    requires: list[dict[str, str]] | None = None,
) -> ExtensionManifest:
    return ExtensionManifest(
        api_version=API_VERSION,
        kind=kind,
        id=extension_id,
        version="1.0.0",
        enabled=True,
        entrypoint=ENTRYPOINT,
        description=description,
        capabilities=capabilities,
        compatibility={"agent_api": ">=2.0,<3", "comsol": ["6.x"]},
        permissions={
            "filesystem": "none",
            "shell": "none",
            "comsol": comsol,
            "network": "none",
        },
        priority=100,
        quality=1.0,
        requires_capabilities=requires or [],
        metadata={
            "domain": "bearing",
            "topology": "cylindrical_roller",
            "provenance": "M7 deterministic migration of reviewed V1 assets",
        },
        tests=["tests/test_v2_bearing_domain.py"],
    )


class BearingExtension:
    def __init__(self, manifest: ExtensionManifest, service: Any) -> None:
        self.manifest = manifest
        self.service = service
        self.active = False

    async def activate(self) -> None:
        self.active = True

    async def deactivate(self) -> None:
        self.active = False

    async def health(self) -> HealthReport:
        return HealthReport(
            extension_id=self.manifest.id,
            status=HealthStatus.HEALTHY if self.active else HealthStatus.DISABLED,
        )

    def supports(self, context: ResolutionContext) -> bool:
        return (
            context.domain in {None, "bearing"}
            and context.signature.get("family", "cylindrical_roller") == "cylindrical_roller"
        )

    async def build(self, specification: dict[str, Any]) -> dict[str, Any]:
        return await self.service.build(specification)

    async def audit(self, subject: Any) -> dict[str, Any]:
        return await self.service.audit(subject)

    async def instructions(self, context: ResolutionContext) -> str:
        return await self.service.instructions(context)

    def preconditions(self, context: ResolutionContext) -> tuple[str, ...]:
        return ("bearing_spec_valid", "pinned_extension_snapshot")

    def steps(self) -> tuple[str, ...]:
        if isinstance(self.service, ParameterOverridePath):
            return (
                "classify_change_set",
                "restore_B",
                "apply_parameter_patch",
                "solve_continuation",
                "run_strict_and_preview_audits",
            )
        return (
            "restore_B",
            "configure_directional_continuation",
            "solve",
            "run_strict_and_preview_audits",
        )

    def rollback(self) -> dict[str, Any]:
        return {"checkpoint": "B_configured_model", "required": True}

    def acceptance(self) -> tuple[str, ...]:
        return ("target_load_reached", "solve_converged", "selected_acceptance_gate_passed")

    def execute_model(self, handle: Any, specification: dict[str, Any]) -> dict[str, Any]:
        return self.service.execute_model(handle, specification)


def bearing_extensions() -> list[BearingExtension]:
    builder = BearingExtension(
        _manifest(
            "bearing.cylindrical-roller.builder",
            ExtensionKind.BUILDER,
            ["bearing.cylindrical-roller.build"],
            "Deterministic A-D builder for supported 3D cylindrical roller bearings.",
            comsol="model_write",
        ),
        CylindricalRollerBearingBuilder(),
    )
    geometry = BearingExtension(
        _manifest(
            "bearing.geometry.auditor",
            ExtensionKind.AUDITOR,
            ["bearing.geometry.audit"],
            "Cylindrical bearing geometry contract auditor.",
        ),
        BearingGeometryAuditor(),
    )
    selection = BearingExtension(
        _manifest(
            "bearing.selection.auditor",
            ExtensionKind.AUDITOR,
            ["bearing.selection.audit"],
            "Named selection entity-count auditor.",
            comsol="model_read",
        ),
        BearingSelectionAuditor(),
    )
    contact = BearingExtension(
        _manifest(
            "bearing.contact.auditor",
            ExtensionKind.AUDITOR,
            ["bearing.contact.audit"],
            "Global contact-pair binding auditor.",
            comsol="model_read",
        ),
        BearingContactAuditor(),
    )
    physical = BearingExtension(
        _manifest(
            "bearing.physics.auditor",
            ExtensionKind.AUDITOR,
            ["bearing.physics.audit"],
            "Strict bearing force and artifact auditor.",
            comsol="model_read",
        ),
        BearingPhysicalAuditor(),
    )
    preview = BearingExtension(
        _manifest(
            "bearing.engineering-preview.auditor",
            ExtensionKind.AUDITOR,
            ["bearing.engineering-preview.audit"],
            "Approximate-stress acceptance auditor for non-promotable engineering previews.",
            comsol="model_read",
        ),
        BearingEngineeringPreviewAuditor(),
    )
    override = BearingExtension(
        _manifest(
            "bearing.parameter-override.path",
            ExtensionKind.DETERMINISTIC_PATH,
            ["bearing.parameter-override"],
            "Smallest-safe-path parameter override with deterministic count rebuild routing.",
            comsol="model_write",
            requires=[{"kind": "builder", "capability": "bearing.cylindrical-roller.build"}],
        ),
        ParameterOverridePath(),
    )
    continuation = BearingExtension(
        _manifest(
            "bearing.dynamic-load-continuation.path",
            ExtensionKind.DETERMINISTIC_PATH,
            ["bearing.dynamic-load-continuation"],
            "Direction-aware bounded radial-load continuation path.",
            comsol="solve",
            requires=[
                {"kind": "auditor", "capability": "bearing.physics.audit"},
                {"kind": "auditor", "capability": "bearing.engineering-preview.audit"},
            ],
        ),
        DynamicLoadContinuation(),
    )
    skill = BearingExtension(
        _manifest(
            "bearing.cylindrical-roller.skill",
            ExtensionKind.SKILL,
            ["bearing.cylindrical-roller.workflow"],
            "Permission-neutral bearing build and audit workflow.",
            requires=[
                {"kind": "builder", "capability": "bearing.cylindrical-roller.build"},
                {"kind": "deterministic_path", "capability": "bearing.parameter-override"},
                {"kind": "deterministic_path", "capability": "bearing.dynamic-load-continuation"},
            ],
        ),
        BearingSkill(),
    )
    return [
        builder,
        geometry,
        selection,
        contact,
        physical,
        preview,
        override,
        continuation,
        skill,
    ]


def baseline_spec() -> BearingSpec:
    return BearingSpec()


# Loader factories keep discovery declarative while the runtime objects remain
# ordinary in-process trusted extensions. ``config`` is reserved for compatible
# future versions and is deliberately not interpreted as executable input.
def cylindrical_builder_extension(
    *, manifest: ExtensionManifest, config: dict[str, Any]
) -> BearingExtension:
    return BearingExtension(manifest, CylindricalRollerBearingBuilder())


def geometry_auditor_extension(
    *, manifest: ExtensionManifest, config: dict[str, Any]
) -> BearingExtension:
    return BearingExtension(manifest, BearingGeometryAuditor())


def selection_auditor_extension(
    *, manifest: ExtensionManifest, config: dict[str, Any]
) -> BearingExtension:
    return BearingExtension(manifest, BearingSelectionAuditor())


def contact_auditor_extension(
    *, manifest: ExtensionManifest, config: dict[str, Any]
) -> BearingExtension:
    return BearingExtension(manifest, BearingContactAuditor())


def physical_auditor_extension(
    *, manifest: ExtensionManifest, config: dict[str, Any]
) -> BearingExtension:
    return BearingExtension(manifest, BearingPhysicalAuditor())


def engineering_preview_auditor_extension(
    *, manifest: ExtensionManifest, config: dict[str, Any]
) -> BearingExtension:
    return BearingExtension(manifest, BearingEngineeringPreviewAuditor())


def parameter_override_extension(
    *, manifest: ExtensionManifest, config: dict[str, Any]
) -> BearingExtension:
    return BearingExtension(manifest, ParameterOverridePath())


def continuation_extension(
    *, manifest: ExtensionManifest, config: dict[str, Any]
) -> BearingExtension:
    return BearingExtension(manifest, DynamicLoadContinuation())


def skill_extension(*, manifest: ExtensionManifest, config: dict[str, Any]) -> BearingExtension:
    return BearingExtension(manifest, BearingSkill())
