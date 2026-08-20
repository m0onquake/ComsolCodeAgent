"""Cooperative cancellation primitives for the V2 kernel."""

from __future__ import annotations

from threading import Event, Lock


class RunCancelledError(RuntimeError):
    """Raised at a safe cancellation checkpoint."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._reason = "cancelled by request"

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def cancel(self, reason: str = "cancelled by request") -> None:
        with self._lock:
            self._reason = reason
            self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RunCancelledError(self.reason)
