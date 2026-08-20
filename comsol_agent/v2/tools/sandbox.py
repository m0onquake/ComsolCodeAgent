"""Allowlisted subprocess execution with workspace cwd, timeout, and cancellation."""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from time import monotonic

from comsol_agent.v2.kernel import CancellationToken, RunCancelledError

from .models import CommandSpec, SandboxResult, SandboxStatus
from .workspace import Workspace


class SandboxPolicyError(RuntimeError):
    """Raised before starting a command that exceeds sandbox policy."""


class ShellSandbox:
    """Run argv-only commands under an explicit executable allowlist.

    This boundary deliberately does not invoke a shell. It confines cwd and
    inherited environment, controls process lifetime, and kills the process
    group on timeout/cancellation. It is not an OS container for untrusted code.
    """

    def __init__(
        self,
        workspace: Workspace,
        *,
        allowed_executables: tuple[str | Path, ...],
        allowed_argument_prefixes: dict[
            str | Path, tuple[tuple[str, ...], ...]
        ] | None = None,
        max_timeout_seconds: float = 300.0,
        max_output_bytes: int = 1_000_000,
        base_env: dict[str, str] | None = None,
    ) -> None:
        self.workspace = workspace
        self.allowed_executables = frozenset(
            str(Path(executable).resolve(strict=True)) for executable in allowed_executables
        )
        self.allowed_argument_prefixes = {
            str(Path(executable).resolve(strict=True)): prefixes
            for executable, prefixes in (allowed_argument_prefixes or {}).items()
        }
        self.max_timeout_seconds = max_timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.base_env = dict(base_env or {})

    async def run(
        self, spec: CommandSpec, cancellation: CancellationToken
    ) -> SandboxResult:
        cancellation.raise_if_cancelled()
        executable = str(Path(spec.argv[0]).resolve(strict=True))
        if executable not in self.allowed_executables:
            raise SandboxPolicyError(f"executable is not allowlisted: {spec.argv[0]}")
        prefixes = self.allowed_argument_prefixes.get(executable)
        arguments = tuple(spec.argv[1:])
        if prefixes is not None and not any(
            arguments[: len(prefix)] == prefix for prefix in prefixes
        ):
            raise SandboxPolicyError(
                f"arguments do not match an allowlisted command profile: {spec.argv[0]}"
            )
        if spec.timeout_seconds > self.max_timeout_seconds:
            raise SandboxPolicyError("requested timeout exceeds sandbox limit")
        cwd = self.workspace.resolve(spec.cwd)
        if not cwd.is_dir():
            raise SandboxPolicyError("command cwd must be a workspace directory")
        env = self._environment(spec.env)
        started_at = monotonic()
        process = await asyncio.create_subprocess_exec(
            executable,
            *spec.argv[1:],
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        communication = asyncio.create_task(process.communicate())
        status = SandboxStatus.COMPLETED
        try:
            while not communication.done():
                if cancellation.cancelled:
                    await self._terminate(process, communication)
                    raise RunCancelledError(cancellation.reason)
                if monotonic() - started_at >= spec.timeout_seconds:
                    status = SandboxStatus.TIMED_OUT
                    await self._terminate(process, communication)
                    break
                await asyncio.sleep(0.02)
            stdout_bytes, stderr_bytes = await communication
        except BaseException:
            if process.returncode is None:
                await self._terminate(process, communication)
            raise
        combined_size = len(stdout_bytes) + len(stderr_bytes)
        truncated = combined_size > self.max_output_bytes
        if truncated:
            status = (
                SandboxStatus.OUTPUT_LIMIT
                if status == SandboxStatus.COMPLETED
                else status
            )
            stdout_bytes = stdout_bytes[: self.max_output_bytes // 2]
            stderr_bytes = stderr_bytes[: self.max_output_bytes // 2]
        return SandboxResult(
            argv=[executable, *spec.argv[1:]],
            cwd=cwd.relative_to(self.workspace.root).as_posix() or ".",
            status=status,
            exit_code=process.returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            duration_ms=(monotonic() - started_at) * 1000,
            output_truncated=truncated,
        )

    def _environment(self, requested: dict[str, str]) -> dict[str, str]:
        allowed_keys = {"CI", "LANG", "LC_ALL", "PYTHONPATH", "PYTHONWARNINGS"}
        rejected = set(requested) - allowed_keys
        if rejected:
            raise SandboxPolicyError(
                f"environment key(s) not allowed: {', '.join(sorted(rejected))}"
            )
        env = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            **self.base_env,
            **requested,
        }
        return env

    @staticmethod
    async def _terminate(
        process: asyncio.subprocess.Process,
        communication: asyncio.Task[tuple[bytes, bytes]],
    ) -> None:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(asyncio.shield(communication), timeout=0.5)
        except TimeoutError:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await communication
