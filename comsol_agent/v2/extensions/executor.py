"""Adapter from a pinned extension snapshot to the Kernel ToolExecutor contract."""

from __future__ import annotations

from time import monotonic

from jsonschema import Draft202012Validator

from comsol_agent.v2.contracts import Action, Observation, SourceRef
from comsol_agent.v2.kernel import CancellationToken

from .errors import ExtensionConflictError
from .models import ExtensionKind, ResolutionContext
from .registry import ExtensionSnapshot


class RegistryToolExecutor:
    """Execute typed Function/MCP tools without teaching the Kernel extension identities."""

    def __init__(self, snapshot: ExtensionSnapshot) -> None:
        self.snapshot = snapshot

    async def execute(
        self, action: Action, cancellation: CancellationToken
    ) -> Observation:
        cancellation.raise_if_cancelled()
        started_at = monotonic()
        context = ResolutionContext(required_permissions=action.permissions)
        extension = None
        try:
            for kind in (ExtensionKind.FUNCTION, ExtensionKind.MCP_TOOL):
                resolved = self.snapshot.resolve(kind, action.tool, context)
                if resolved:
                    extension = resolved[0]
                    break
        except ExtensionConflictError:
            return self._failure(
                action,
                "extension_conflict",
                "AmbiguousExtensionResolution",
                started_at,
                "registry",
                "snapshot",
            )
        if extension is None:
            try:
                permission_denied = any(
                    self.snapshot.resolve(kind, action.tool, ResolutionContext())
                    for kind in (ExtensionKind.FUNCTION, ExtensionKind.MCP_TOOL)
                )
            except ExtensionConflictError:
                return self._failure(
                    action,
                    "extension_conflict",
                    "AmbiguousExtensionResolution",
                    started_at,
                    "registry",
                    "snapshot",
                )
            return self._failure(
                action,
                "permission_denied" if permission_denied else "extension_not_found",
                "ActionPermissionDenied" if permission_denied else "NoActiveExtension",
                started_at,
                "registry",
                "snapshot",
            )
        try:
            Draft202012Validator.check_schema(extension.input_schema)
            input_errors = list(
                Draft202012Validator(extension.input_schema).iter_errors(action.arguments)
            )
        except Exception:
            input_errors = ["invalid input schema"]
        if input_errors:
            return self._failure(
                action,
                "contract_violation",
                "InvalidExtensionInput",
                started_at,
                extension.manifest.id,
                extension.manifest.version,
            )
        try:
            observation = await extension.execute(action, cancellation)
        except Exception as exc:
            return self._failure(
                action,
                "extension_failure",
                type(exc).__name__,
                started_at,
                extension.manifest.id,
                extension.manifest.version,
            )
        if not isinstance(observation, Observation):
            return self._failure(
                action,
                "contract_violation",
                "InvalidObservationType",
                started_at,
                extension.manifest.id,
                extension.manifest.version,
            )
        try:
            Draft202012Validator.check_schema(extension.output_schema)
            output_errors = list(
                Draft202012Validator(extension.output_schema).iter_errors(observation.data)
            )
        except Exception:
            output_errors = ["invalid output schema"]
        if output_errors:
            return self._failure(
                action,
                "contract_violation",
                "InvalidExtensionOutput",
                started_at,
                extension.manifest.id,
                extension.manifest.version,
            )
        return observation

    @staticmethod
    def _failure(
        action: Action,
        error_class: str,
        exception_type: str,
        started_at: float,
        source_id: str,
        source_version: str,
    ) -> Observation:
        return Observation(
            action_id=action.action_id,
            success=False,
            status="extension_error",
            stage="execute",
            error_class=error_class,
            exception_type=exception_type,
            retryable=False,
            duration_ms=(monotonic() - started_at) * 1000,
            source=SourceRef(
                kind="extension", identifier=source_id, version=source_version
            ),
        )
