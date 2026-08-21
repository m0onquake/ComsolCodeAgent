"""Typed backend and worker boundaries for COMSOL execution."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Protocol

from comsol_agent.v2.kernel import CancellationToken

from .contracts import RuntimeOperation
from .errors import WorkerCancellationError, WorkerTimeoutError


@dataclass(frozen=True)
class BackendCapabilities:
    backend: str
    backend_version: str
    comsol_version: str
    hard_cancel: bool


class ComsolBackend(Protocol):
    capabilities: BackendCapabilities

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def status(self) -> dict[str, Any]: ...
    async def create_model(self, model_name: str) -> None: ...
    async def load_model(self, model_name: str, path: Path) -> None: ...
    async def save_model(self, model_name: str, path: Path) -> None: ...
    async def close_model(self, model_name: str) -> None: ...
    async def apply_parameters(self, model_name: str, parameters: dict[str, str]) -> None: ...
    async def execute_registered(
        self, model_name: str, extension_id: str, specification: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def build(self, model_name: str) -> dict[str, Any]: ...
    async def mesh(self, model_name: str) -> dict[str, Any]: ...
    async def solve(self, model_name: str) -> dict[str, Any]: ...
    async def evaluate(self, model_name: str, expressions: tuple[str, ...]) -> dict[str, Any]: ...
    async def export(self, model_name: str, target: Path) -> None: ...
    async def audit(self, model_name: str) -> dict[str, Any]: ...


class BackendWorker(Protocol):
    capabilities: BackendCapabilities
    quarantined: bool

    async def execute(
        self,
        operation: RuntimeOperation,
        call: Callable[[], Awaitable[Any]],
        *,
        timeout_seconds: float,
        cancellation: CancellationToken,
    ) -> Any: ...


class InProcessWorkerExecutor:
    """Testable executor boundary with explicit, truthful cancellation semantics.

    It is also suitable for async fake backends. Production MPh calls use the
    same boundary, but a process worker is required before hard cancellation can
    be claimed for a blocking COMSOL solve.
    """

    def __init__(self, backend: ComsolBackend, *, hard_cancel: bool | None = None) -> None:
        self.backend = backend
        supported = backend.capabilities.hard_cancel if hard_cancel is None else hard_cancel
        self.capabilities = BackendCapabilities(
            backend=backend.capabilities.backend,
            backend_version=backend.capabilities.backend_version,
            comsol_version=backend.capabilities.comsol_version,
            hard_cancel=supported,
        )
        self.quarantined = False

    async def execute(
        self,
        operation: RuntimeOperation,
        call: Callable[[], Awaitable[Any]],
        *,
        timeout_seconds: float,
        cancellation: CancellationToken,
    ) -> Any:
        if self.quarantined:
            raise RuntimeError("COMSOL worker is quarantined after unconfirmed termination")
        cancellation.raise_if_cancelled()
        task = asyncio.create_task(call())
        deadline = monotonic() + timeout_seconds
        try:
            while not task.done():
                if cancellation.cancelled:
                    return await self._cancel_task(task, cancellation.reason, cancelled=True)
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return await self._cancel_task(
                        task, f"{operation} exceeded {timeout_seconds:.3f}s", cancelled=False
                    )
                done, _ = await asyncio.wait({task}, timeout=min(0.01, remaining))
                if done:
                    break
            return await task
        except asyncio.CancelledError:
            return await self._cancel_task(
                task, "asyncio task cancelled; COMSOL termination is not implied", cancelled=True
            )

    async def _cancel_task(self, task: asyncio.Task[Any], message: str, *, cancelled: bool) -> Any:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        confirmed = self.capabilities.hard_cancel
        if not confirmed:
            self.quarantined = True
        if cancelled:
            raise WorkerCancellationError(message, termination_confirmed=confirmed)
        raise WorkerTimeoutError(message, termination_confirmed=confirmed)


# Compatibility alias used by deterministic fake-backend tests.
FakeWorkerExecutor = InProcessWorkerExecutor


class MphBackendAdapter:
    """Typed adapter over the repository's long-lived ``COMSOLClient``.

    The V2 runtime never calls the legacy dict-returning tools. Trusted builders
    and auditors are injected by stable extension ID; arbitrary Java/Python is
    intentionally absent from this public adapter.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        registered_handlers: dict[str, Callable[[Any, dict[str, Any]], Any]] | None = None,
        auditor: Callable[[Any], Any] | None = None,
        version: str | None = None,
        cores: int | None = None,
        port: int | None = 0,
    ) -> None:
        if client is None:
            from comsol_agent.tools.comsol.client import COMSOLClient

            client = COMSOLClient.get_instance()
        self.client = client
        self.registered_handlers = registered_handlers or {}
        self.auditor = auditor
        self.requested_version = version
        self.cores = cores
        self.port = port
        self._names: dict[str, str] = {}
        self._call_lock = asyncio.Lock()
        self.capabilities = BackendCapabilities(
            backend="MPh",
            backend_version=self._mph_version(),
            comsol_version=version or "unknown",
            hard_cancel=False,
        )

    @staticmethod
    def _mph_version() -> str:
        try:
            import mph

            return str(getattr(mph, "__version__", "unknown"))
        except ImportError:
            return "unavailable"

    async def _sync(self, call: Callable[[], Any]) -> Any:
        async with self._call_lock:
            return await asyncio.to_thread(call)

    async def start(self) -> None:
        await self._sync(
            lambda: self.client.start(
                cores=self.cores,
                version=self.requested_version,
                port=self.port,
            )
        )
        mph_client = getattr(self.client, "_mph_client", None)
        discovered = getattr(mph_client, "version", None)
        if discovered:
            self.capabilities = BackendCapabilities(
                backend="MPh",
                backend_version=self.capabilities.backend_version,
                comsol_version=str(discovered),
                hard_cancel=False,
            )

    async def stop(self) -> None:
        await self._sync(self.client.stop)
        self._names.clear()

    async def status(self) -> dict[str, Any]:
        return {
            "started": bool(self.client.is_running),
            "models": sorted(self._names),
            "single_client_per_process": True,
        }

    def _handle(self, model_name: str) -> Any:
        return self.client.get_model(self._names.get(model_name, model_name))

    async def create_model(self, model_name: str) -> None:
        handle = await self._sync(lambda: self.client.create(model_name))
        self._names[model_name] = handle.name

    async def load_model(self, model_name: str, path: Path) -> None:
        handle = await self._sync(lambda: self.client.load(path))
        self._names[model_name] = handle.name

    async def save_model(self, model_name: str, path: Path) -> None:
        await self._sync(lambda: self.client.save(self._names.get(model_name, model_name), path))

    async def close_model(self, model_name: str) -> None:
        actual = self._names.pop(model_name, model_name)
        await self._sync(lambda: self.client.close(actual))

    async def apply_parameters(self, model_name: str, parameters: dict[str, str]) -> None:
        def apply() -> None:
            handle = self._handle(model_name)
            for name, value in parameters.items():
                handle.mph_model.parameter(name, value)
            handle.is_modified = True

        await self._sync(apply)

    async def execute_registered(
        self, model_name: str, extension_id: str, specification: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            handler = self.registered_handlers[extension_id]
        except KeyError as exc:
            raise LookupError(f"registered builder/path not available: {extension_id}") from exc

        async with self._call_lock:
            result = handler(self._handle(model_name), specification)
            if inspect.isawaitable(result):
                result = await result
        return dict(result or {})

    async def build(self, model_name: str) -> dict[str, Any]:
        def build() -> dict[str, Any]:
            handle = self._handle(model_name)
            handle.mph_model.build()
            handle.is_modified = True
            return {"summary": self.client.get_model_summary(handle.name)}

        return await self._sync(build)

    async def mesh(self, model_name: str) -> dict[str, Any]:
        def mesh() -> dict[str, Any]:
            handle = self._handle(model_name)
            handle.mph_model.mesh()
            handle.is_modified = True
            return {"meshed": True}

        return await self._sync(mesh)

    async def solve(self, model_name: str) -> dict[str, Any]:
        def solve() -> dict[str, Any]:
            handle = self._handle(model_name)
            handle.mph_model.solve()
            handle.is_modified = True
            return {"converged": True}

        return await self._sync(solve)

    async def evaluate(self, model_name: str, expressions: tuple[str, ...]) -> dict[str, Any]:
        def evaluate() -> dict[str, Any]:
            handle = self._handle(model_name)
            values = {}
            for expression in expressions:
                value = handle.mph_model.evaluate(expression)
                values[expression] = value.tolist() if hasattr(value, "tolist") else value
            return values

        return await self._sync(evaluate)

    async def export(self, model_name: str, target: Path) -> None:
        await self._sync(lambda: self._handle(model_name).mph_model.export("data", str(target)))

    async def audit(self, model_name: str) -> dict[str, Any]:
        if self.auditor is None:
            return {"passed": False, "reason": "no registered physical auditor"}
        async with self._call_lock:
            result = self.auditor(self._handle(model_name))
            if inspect.isawaitable(result):
                result = await result
        return dict(result)
