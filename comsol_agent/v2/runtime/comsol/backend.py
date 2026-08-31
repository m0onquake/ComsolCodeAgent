"""Typed backend and worker boundaries for COMSOL execution."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import multiprocessing
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Protocol
from uuid import uuid4

from comsol_agent.v2.extensions import ExtensionKind, ExtensionSnapshot, ResolutionContext
from comsol_agent.v2.kernel import CancellationToken

from .contracts import RuntimeOperation
from .errors import WorkerCancellationError, WorkerTimeoutError


@dataclass(frozen=True)
class BackendCapabilities:
    backend: str
    backend_version: str
    comsol_version: str
    hard_cancel: bool


class SnapshotBindingError(RuntimeError):
    """Requested executable extension does not match the pinned Registry snapshot."""


@dataclass(frozen=True)
class RegisteredHandlerBinding:
    extension: Any
    extension_id: str
    extension_version: str
    extension_kind: ExtensionKind
    capability: str
    handler: Callable[[Any, dict[str, Any]], Any]


class PinnedExecutionCatalog:
    """Bind trusted model handlers to an immutable ExtensionSnapshot."""

    _ALLOWED_KINDS = frozenset({ExtensionKind.BUILDER, ExtensionKind.DETERMINISTIC_PATH})

    def __init__(
        self,
        snapshot: ExtensionSnapshot,
        bindings: list[RegisteredHandlerBinding],
    ) -> None:
        self.snapshot = snapshot
        self._bindings: dict[tuple[str, str], RegisteredHandlerBinding] = {}
        for binding in bindings:
            if binding.extension_kind not in self._ALLOWED_KINDS:
                raise SnapshotBindingError(
                    f"unsupported executable extension kind: {binding.extension_kind}"
                )
            key = (binding.extension_id, binding.capability)
            if key in self._bindings:
                raise SnapshotBindingError(f"duplicate registered handler binding: {key}")
            self._validate_binding(binding)
            self._bindings[key] = binding

    @property
    def versions(self) -> dict[str, str]:
        return dict(self.snapshot.versions)

    async def execute(
        self,
        model_handle: Any,
        *,
        extension_id: str,
        extension_version: str,
        extension_kind: str,
        capability: str,
        specification: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            kind = ExtensionKind(extension_kind)
        except ValueError as exc:
            raise SnapshotBindingError(
                f"unsupported executable extension kind: {extension_kind}"
            ) from exc
        if kind not in self._ALLOWED_KINDS:
            raise SnapshotBindingError(f"extension kind is not executable here: {kind}")
        try:
            binding = self._bindings[(extension_id, capability)]
        except KeyError as exc:
            raise SnapshotBindingError(
                f"no pinned handler for {extension_id}:{capability}"
            ) from exc
        resolved = self.snapshot.resolve(
            kind,
            capability,
            ResolutionContext(selected_extension_id=extension_id),
        )
        if len(resolved) != 1:
            raise SnapshotBindingError(
                f"pinned snapshot cannot resolve {extension_id}:{capability}"
            )
        manifest = resolved[0].manifest
        if manifest.version != extension_version:
            raise SnapshotBindingError(
                f"requested extension version {extension_version} does not match "
                f"snapshot version {manifest.version}"
            )
        if (
            binding.extension is not resolved[0]
            or binding.extension_id != manifest.id
            or binding.extension_version != manifest.version
            or binding.extension_kind != manifest.kind
            or binding.capability not in manifest.capabilities
        ):
            raise SnapshotBindingError(
                f"handler binding does not match snapshot manifest for {extension_id}"
            )
        if inspect.iscoroutinefunction(binding.handler):
            result = await binding.handler(model_handle, specification)
        else:
            # Trusted handlers may still enter blocking COMSOL Java calls. Keep
            # those calls outside the event-loop thread so runtime cancellation
            # and deadlines remain observable at the worker boundary.
            result = await asyncio.to_thread(binding.handler, model_handle, specification)
            if inspect.isawaitable(result):
                result = await result
        return dict(result or {})

    def _validate_binding(self, binding: RegisteredHandlerBinding) -> None:
        resolved = self.snapshot.resolve(
            binding.extension_kind,
            binding.capability,
            ResolutionContext(selected_extension_id=binding.extension_id),
        )
        if len(resolved) != 1 or resolved[0] is not binding.extension:
            raise SnapshotBindingError(
                f"handler owner is not the pinned extension {binding.extension_id}"
            )
        if getattr(binding.handler, "__self__", None) is not binding.extension:
            raise SnapshotBindingError(
                f"handler is not bound to pinned extension {binding.extension_id}"
            )
        manifest = resolved[0].manifest
        if (
            manifest.id != binding.extension_id
            or manifest.version != binding.extension_version
            or manifest.kind != binding.extension_kind
            or binding.capability not in manifest.capabilities
        ):
            raise SnapshotBindingError(
                f"handler binding does not match snapshot manifest for {binding.extension_id}"
            )


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
        self,
        model_name: str,
        extension_id: str,
        extension_version: str,
        extension_kind: str,
        capability: str,
        specification: dict[str, Any],
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


class ProcessBackendError(RuntimeError):
    """Structured remote-backend failure with the child cause preserved."""

    def __init__(self, message: str, *, exception_type: str, remote_traceback: str) -> None:
        super().__init__(message)
        self.exception_type = exception_type
        self.remote_traceback = remote_traceback


def _load_factory(reference: str) -> Callable[..., ComsolBackend]:
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("backend factory must use 'module:attribute' syntax")
    factory = getattr(importlib.import_module(module_name), attribute)
    if not callable(factory):
        raise TypeError(f"backend factory is not callable: {reference}")
    return factory


def _process_backend_main(
    connection: Any, factory_ref: str, factory_kwargs: dict[str, Any]
) -> None:
    """Own one backend and event loop for the complete lifetime of a worker process."""

    backend: ComsolBackend | None = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        backend = _load_factory(factory_ref)(**factory_kwargs)
        connection.send({"kind": "ready"})
        while True:
            request = connection.recv()
            if request.get("method") == "__shutdown__":
                connection.send({"id": request["id"], "ok": True, "result": None})
                break
            try:
                method = getattr(backend, request["method"])
                result = method(*request.get("args", ()), **request.get("kwargs", {}))
                if inspect.isawaitable(result):
                    result = loop.run_until_complete(result)
                connection.send({"id": request["id"], "ok": True, "result": result})
            except BaseException as exc:
                connection.send(
                    {
                        "id": request["id"],
                        "ok": False,
                        "error": {
                            "exception_type": type(exc).__name__,
                            "message": str(exc),
                            "traceback": traceback.format_exc(),
                        },
                    }
                )
    except BaseException as exc:
        try:
            connection.send(
                {
                    "kind": "startup_error",
                    "error": {
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                }
            )
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        if backend is not None:
            try:
                result = backend.stop()
                if inspect.isawaitable(result):
                    loop.run_until_complete(result)
            except BaseException:
                pass
        loop.close()
        connection.close()


class ProcessComsolBackendProxy:
    """Typed RPC proxy whose complete COMSOL backend lives in a spawn child process."""

    def __init__(
        self,
        factory: str,
        *,
        factory_kwargs: dict[str, Any] | None = None,
        capabilities: BackendCapabilities,
        startup_timeout_seconds: float = 60.0,
    ) -> None:
        _load_factory(factory)
        self.factory = factory
        self.factory_kwargs = dict(factory_kwargs or {})
        self.capabilities = capabilities
        self.startup_timeout_seconds = startup_timeout_seconds
        self._context = multiprocessing.get_context("spawn")
        self._process: multiprocessing.Process | None = None
        self._connection: Any | None = None
        self._rpc_lock = asyncio.Lock()
        self._execution_catalog: PinnedExecutionCatalog | None = None

    @property
    def execution_catalog(self) -> PinnedExecutionCatalog | None:
        return self._execution_catalog

    @execution_catalog.setter
    def execution_catalog(self, catalog: PinnedExecutionCatalog) -> None:
        if self.alive:
            raise RuntimeError("cannot replace execution catalog in a running worker")
        self._execution_catalog = catalog
        self.factory_kwargs["expected_versions"] = catalog.versions

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def alive(self) -> bool:
        return bool(self._process is not None and self._process.is_alive())

    async def ensure_started(self) -> None:
        if self.alive:
            return
        parent, child = self._context.Pipe()
        process = self._context.Process(
            target=_process_backend_main,
            args=(child, self.factory, self.factory_kwargs),
            name="comsol-v2-worker",
            daemon=False,
        )
        process.start()
        child.close()
        self._process = process
        self._connection = parent
        try:
            ready = await asyncio.wait_for(
                asyncio.to_thread(parent.recv), timeout=self.startup_timeout_seconds
            )
        except BaseException:
            await self.terminate()
            raise
        if ready.get("kind") != "ready":
            await self.terminate()
            error = ready.get("error", {})
            raise ProcessBackendError(
                str(error.get("message", "worker startup failed")),
                exception_type=str(error.get("exception_type", "WorkerStartupError")),
                remote_traceback=str(error.get("traceback", "")),
            )

    async def terminate(self) -> bool:
        process, connection = self._process, self._connection
        self._process = None
        self._connection = None
        if connection is not None:
            connection.close()
        if process is None:
            return True
        if process.is_alive():
            process.terminate()
            await asyncio.to_thread(process.join, 10.0)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, 10.0)
        confirmed = not process.is_alive()
        process.close()
        return confirmed

    async def _rpc(self, method: str, *args: Any, **kwargs: Any) -> Any:
        async with self._rpc_lock:
            await self.ensure_started()
            assert self._connection is not None
            request_id = uuid4().hex
            try:
                self._connection.send(
                    {"id": request_id, "method": method, "args": args, "kwargs": kwargs}
                )
                response = await asyncio.to_thread(self._connection.recv)
            except (BrokenPipeError, EOFError, OSError) as exc:
                raise ProcessBackendError(
                    "COMSOL worker process disconnected",
                    exception_type=type(exc).__name__,
                    remote_traceback="",
                ) from exc
            if response.get("id") != request_id:
                raise ProcessBackendError(
                    "COMSOL worker returned an out-of-order response",
                    exception_type="ProtocolError",
                    remote_traceback="",
                )
            if not response.get("ok"):
                error = response.get("error", {})
                raise ProcessBackendError(
                    str(error.get("message", "remote backend failed")),
                    exception_type=str(error.get("exception_type", "RemoteError")),
                    remote_traceback=str(error.get("traceback", "")),
                )
            return response.get("result")

    async def start(self) -> None:
        await self._rpc("start")

    async def stop(self) -> None:
        if not self.alive:
            return
        try:
            assert self._connection is not None
            request_id = uuid4().hex
            self._connection.send({"id": request_id, "method": "__shutdown__"})
            await asyncio.to_thread(self._connection.recv)
        finally:
            await self.terminate()

    async def status(self) -> dict[str, Any]:
        return dict(await self._rpc("status"))

    async def create_model(self, model_name: str) -> None:
        await self._rpc("create_model", model_name)

    async def load_model(self, model_name: str, path: Path) -> None:
        await self._rpc("load_model", model_name, path)

    async def save_model(self, model_name: str, path: Path) -> None:
        await self._rpc("save_model", model_name, path)

    async def close_model(self, model_name: str) -> None:
        await self._rpc("close_model", model_name)

    async def apply_parameters(self, model_name: str, parameters: dict[str, str]) -> None:
        await self._rpc("apply_parameters", model_name, parameters)

    async def execute_registered(
        self,
        model_name: str,
        extension_id: str,
        extension_version: str,
        extension_kind: str,
        capability: str,
        specification: dict[str, Any],
    ) -> dict[str, Any]:
        return dict(
            await self._rpc(
                "execute_registered",
                model_name,
                extension_id,
                extension_version,
                extension_kind,
                capability,
                specification,
            )
        )

    async def build(self, model_name: str) -> dict[str, Any]:
        return dict(await self._rpc("build", model_name))

    async def mesh(self, model_name: str) -> dict[str, Any]:
        return dict(await self._rpc("mesh", model_name))

    async def solve(self, model_name: str) -> dict[str, Any]:
        return dict(await self._rpc("solve", model_name))

    async def evaluate(self, model_name: str, expressions: tuple[str, ...]) -> dict[str, Any]:
        return dict(await self._rpc("evaluate", model_name, expressions))

    async def export(self, model_name: str, target: Path) -> None:
        await self._rpc("export", model_name, target)

    async def audit(self, model_name: str) -> dict[str, Any]:
        return dict(await self._rpc("audit", model_name))


class RecyclableProcessWorkerExecutor:
    """Hard-cancel a dedicated backend process and permit a clean replacement."""

    def __init__(self, backend: ProcessComsolBackendProxy) -> None:
        self.backend = backend
        self.capabilities = BackendCapabilities(
            backend=backend.capabilities.backend,
            backend_version=backend.capabilities.backend_version,
            comsol_version=backend.capabilities.comsol_version,
            hard_cancel=True,
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
        cancellation.raise_if_cancelled()
        task = asyncio.create_task(call())
        deadline = monotonic() + timeout_seconds
        try:
            while not task.done():
                if cancellation.cancelled:
                    await self._terminate_task(task)
                    raise WorkerCancellationError(
                        cancellation.reason, termination_confirmed=True
                    )
                remaining = deadline - monotonic()
                if remaining <= 0:
                    await self._terminate_task(task)
                    raise WorkerTimeoutError(
                        f"{operation} exceeded {timeout_seconds:.3f}s",
                        termination_confirmed=True,
                    )
                await asyncio.wait({task}, timeout=min(0.01, remaining))
            return await task
        except asyncio.CancelledError:
            await self._terminate_task(task)
            raise WorkerCancellationError(
                "asyncio task cancelled and worker process terminated",
                termination_confirmed=True,
            ) from None

    async def _terminate_task(self, task: asyncio.Task[Any]) -> None:
        confirmed = await self.backend.terminate()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, ProcessBackendError):
            pass
        if not confirmed:
            self.quarantined = True
            raise RuntimeError("failed to terminate COMSOL worker process")


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
        execution_catalog: PinnedExecutionCatalog | None = None,
        auditor: Callable[[Any], Any] | None = None,
        version: str | None = None,
        cores: int | None = None,
        port: int | None = 0,
    ) -> None:
        if client is None:
            from comsol_agent.tools.comsol.client import COMSOLClient

            client = COMSOLClient.get_instance()
        self.client = client
        self.execution_catalog = execution_catalog
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
        self,
        model_name: str,
        extension_id: str,
        extension_version: str,
        extension_kind: str,
        capability: str,
        specification: dict[str, Any],
    ) -> dict[str, Any]:
        if self.execution_catalog is None:
            raise SnapshotBindingError("no pinned execution catalog is configured")
        async with self._call_lock:
            return await self.execution_catalog.execute(
                self._handle(model_name),
                extension_id=extension_id,
                extension_version=extension_version,
                extension_kind=extension_kind,
                capability=capability,
                specification=specification,
            )

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
        def export() -> None:
            java = self._handle(model_name).mph_model.java
            exports = java.result().export()
            tag = "v2_runtime_data"
            try:
                if tag in [str(value) for value in exports.tags()]:
                    exports.remove(tag)
            except Exception:
                pass
            exports.create(tag, "Data")
            node = java.result().export(tag)
            node.set("filename", str(target))
            node.set("expr", ["solid.mises", "solid.disp"])
            node.run()

        await self._sync(export)

    async def audit(self, model_name: str) -> dict[str, Any]:
        if self.auditor is None:
            return {"passed": False, "reason": "no registered physical auditor"}
        async with self._call_lock:
            result = self.auditor(self._handle(model_name))
            if inspect.isawaitable(result):
                result = await result
        return dict(result)
