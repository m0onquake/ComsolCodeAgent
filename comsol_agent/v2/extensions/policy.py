"""Compatibility and least-authority checks for extension manifests."""

from __future__ import annotations

from fnmatch import fnmatchcase

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .models import (
    ComsolPermission,
    ExtensionManifest,
    FilesystemPermission,
    NetworkPermission,
    PermissionSet,
    ShellPermission,
    ValidationIssue,
)

_PERMISSION_LEVELS = {
    "filesystem": {
        FilesystemPermission.NONE: 0,
        FilesystemPermission.READ: 1,
        FilesystemPermission.WRITE: 2,
    },
    "shell": {ShellPermission.NONE: 0, ShellPermission.EXECUTE: 1},
    "comsol": {
        ComsolPermission.NONE: 0,
        ComsolPermission.MODEL_READ: 1,
        ComsolPermission.MODEL_WRITE: 2,
        ComsolPermission.SOLVE: 3,
    },
    "network": {
        NetworkPermission.NONE: 0,
        NetworkPermission.CLIENT: 1,
        NetworkPermission.SERVER: 2,
    },
}


class PermissionPolicy:
    """Maximum authority an installation is willing to grant."""

    def __init__(self, allowed: PermissionSet) -> None:
        self.allowed = allowed

    @classmethod
    def deny_all(cls) -> PermissionPolicy:
        return cls(
            PermissionSet(filesystem="none", shell="none", comsol="none", network="none")
        )

    def issues(self, requested: PermissionSet) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for field, levels in _PERMISSION_LEVELS.items():
            actual = getattr(requested, field)
            limit = getattr(self.allowed, field)
            if levels[actual] > levels[limit]:
                issues.append(
                    ValidationIssue(
                        code="permission_denied",
                        location=f"permissions.{field}",
                        message=f"requested {actual!s}, policy allows at most {limit!s}",
                    )
                )
        return issues


class CompatibilityPolicy:
    """Runtime versions against which manifests are checked before import."""

    def __init__(self, *, agent_version: str, comsol_version: str | None = None) -> None:
        self.agent_version = agent_version
        self.comsol_version = comsol_version

    def issues(self, manifest: ExtensionManifest) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        try:
            agent_matches = Version(self.agent_version) in SpecifierSet(
                manifest.compatibility.agent_api
            )
        except (InvalidSpecifier, InvalidVersion) as exc:
            issues.append(
                ValidationIssue(
                    code="invalid_compatibility",
                    location="compatibility.agent_api",
                    message=str(exc),
                )
            )
        else:
            if not agent_matches:
                issues.append(
                    ValidationIssue(
                        code="incompatible_agent_api",
                        location="compatibility.agent_api",
                        message=(
                            f"agent {self.agent_version} does not satisfy "
                            f"{manifest.compatibility.agent_api}"
                        ),
                    )
                )

        patterns = manifest.compatibility.comsol
        if patterns:
            if self.comsol_version is None:
                issues.append(
                    ValidationIssue(
                        code="comsol_version_unknown",
                        location="compatibility.comsol",
                        message="extension requires a known compatible COMSOL runtime",
                    )
                )
            elif not any(
                fnmatchcase(self.comsol_version, pattern.replace("x", "*"))
                for pattern in patterns
            ):
                issues.append(
                    ValidationIssue(
                        code="incompatible_comsol",
                        location="compatibility.comsol",
                        message=f"COMSOL {self.comsol_version} does not match {patterns}",
                    )
                )
        return issues


def permissions_allow(granted: PermissionSet, required: frozenset[str]) -> bool:
    """Return whether a manifest's maximum permissions cover action-level requirements."""
    for token in required:
        try:
            field, requested = token.split(":", 1)
            levels = _PERMISSION_LEVELS[field]
            requested_level = next(
                level for permission, level in levels.items() if permission == requested
            )
        except (KeyError, StopIteration, ValueError):
            return False
        if requested_level > levels[getattr(granted, field)]:
            return False
    return True
