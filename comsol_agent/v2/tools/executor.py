"""Typed dispatch from Kernel Actions to the built-in M3 tool set."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from pydantic import ValidationError

from comsol_agent.v2.contracts import Action, Observation, SourceRef
from comsol_agent.v2.kernel import CancellationToken

from .models import CommandSpec, PatchSet, WorkspaceToolError
from .sandbox import SandboxPolicyError, ShellSandbox
from .testing import TestRunner
from .workspace import Workspace

Handler = Callable[[Action, CancellationToken], Awaitable[Observation]]


class CodeToolExecutor:
    """A mapping-based executor; adding tools does not change Kernel control flow."""

    def __init__(
        self,
        workspace: Workspace,
        sandbox: ShellSandbox,
        test_runner: TestRunner,
    ) -> None:
        self.workspace = workspace
        self.sandbox = sandbox
        self.test_runner = test_runner
        self._handlers: dict[str, Handler] = {
            "workspace.search": self._search,
            "workspace.read": self._read,
            "workspace.apply_patch": self._apply_patch,
            "workspace.checkpoint": self._checkpoint,
            "workspace.rollback": self._rollback,
            "sandbox.exec": self._sandbox_exec,
            "test.pytest": self._pytest,
            "test.ruff": self._ruff,
        }

    async def execute(
        self, action: Action, cancellation: CancellationToken
    ) -> Observation:
        cancellation.raise_if_cancelled()
        handler = self._handlers.get(action.tool)
        if handler is None:
            return self._failure(action, "tool_not_found", "UnknownCodeTool")
        try:
            return await handler(action, cancellation)
        except WorkspaceToolError as exc:
            return self._failure(action, str(exc.error_class), type(exc).__name__, detail=str(exc))
        except SandboxPolicyError as exc:
            return self._failure(
                action, "sandbox_permission_denied", type(exc).__name__, detail=str(exc)
            )
        except (ValidationError, TypeError, ValueError) as exc:
            return self._failure(
                action, "invalid_tool_arguments", type(exc).__name__, detail=str(exc)
            )

    async def _search(self, action: Action, cancellation: CancellationToken) -> Observation:
        cancellation.raise_if_cancelled()
        arguments = action.arguments
        matches = self.workspace.search(
            str(arguments["query"]),
            include=tuple(arguments.get("include", ["*"])),
            regex=bool(arguments.get("regex", False)),
            max_results=int(arguments.get("max_results", 200)),
        )
        return self._success(action, {"matches": [item.model_dump() for item in matches]})

    async def _read(self, action: Action, cancellation: CancellationToken) -> Observation:
        cancellation.raise_if_cancelled()
        result = self.workspace.read(
            str(action.arguments["path"]),
            start_line=int(action.arguments.get("start_line", 1)),
            end_line=action.arguments.get("end_line"),
        )
        return self._success(action, result.model_dump())

    async def _apply_patch(self, action: Action, cancellation: CancellationToken) -> Observation:
        cancellation.raise_if_cancelled()
        patch = PatchSet.model_validate(action.arguments)
        applied = self.workspace.apply_patch(patch)
        return self._success(action, applied.model_dump(), checkpoint=None)

    async def _checkpoint(self, action: Action, cancellation: CancellationToken) -> Observation:
        cancellation.raise_if_cancelled()
        checkpoint = self.workspace.create_checkpoint(tuple(action.arguments["paths"]))
        return self._success(
            action, checkpoint.model_dump(), checkpoint=checkpoint.checkpoint_id
        )

    async def _rollback(self, action: Action, cancellation: CancellationToken) -> Observation:
        cancellation.raise_if_cancelled()
        checkpoint = self.workspace.rollback(str(action.arguments["checkpoint_id"]))
        return self._success(action, checkpoint.model_dump())

    async def _sandbox_exec(
        self, action: Action, cancellation: CancellationToken
    ) -> Observation:
        started_at = monotonic()
        result = await self.sandbox.run(CommandSpec.model_validate(action.arguments), cancellation)
        success = result.status == "completed" and result.exit_code == 0
        return Observation(
            action_id=action.action_id,
            success=success,
            status=result.status,
            stage="execute",
            data=result.model_dump(mode="json"),
            error_class=None if success else f"sandbox_{result.status}",
            exception_type=None if success else "SandboxCommandFailure",
            retryable=False,
            duration_ms=(monotonic() - started_at) * 1000,
            source=self._source(action.tool),
        )

    async def _pytest(self, action: Action, cancellation: CancellationToken) -> Observation:
        return await self.test_runner.pytest(
            action_id=action.action_id,
            targets=tuple(action.arguments.get("targets", ())),
            extra_args=tuple(action.arguments.get("extra_args", ())),
            timeout_seconds=float(action.arguments.get("timeout_seconds", 120.0)),
            cancellation=cancellation,
        )

    async def _ruff(self, action: Action, cancellation: CancellationToken) -> Observation:
        return await self.test_runner.ruff(
            action_id=action.action_id,
            targets=tuple(action.arguments.get("targets", (".",))),
            extra_args=tuple(action.arguments.get("extra_args", ())),
            timeout_seconds=float(action.arguments.get("timeout_seconds", 120.0)),
            cancellation=cancellation,
        )

    def _success(
        self, action: Action, data: dict[str, Any], *, checkpoint: str | None = None
    ) -> Observation:
        return Observation(
            action_id=action.action_id,
            success=True,
            status="ok",
            stage="execute",
            data=data,
            checkpoint=checkpoint,
            source=self._source(action.tool),
        )

    def _failure(
        self,
        action: Action,
        error_class: str,
        exception_type: str,
        *,
        detail: str = "",
    ) -> Observation:
        return Observation(
            action_id=action.action_id,
            success=False,
            status="rejected",
            stage="execute",
            data={"detail": detail},
            error_class=error_class,
            exception_type=exception_type,
            retryable=False,
            source=self._source(action.tool),
        )

    @staticmethod
    def _source(tool: str) -> SourceRef:
        return SourceRef(kind="builtin_function", identifier=tool, version="1.0")
