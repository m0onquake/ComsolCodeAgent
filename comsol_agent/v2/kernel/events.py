"""In-process lifecycle events with an append-only trace subscriber."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from comsol_agent.v2.contracts.models import ContractModel, utc_now


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    STAGE_CHANGED = "stage_changed"
    ACTION_STARTED = "action_started"
    OBSERVATION_RECORDED = "observation_recorded"
    REPAIR_SCHEDULED = "repair_scheduled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    RUN_CANCELLED = "run_cancelled"
    RUN_FAILED = "run_failed"
    RUN_COMPLETED = "run_completed"


class KernelEvent(ContractModel):
    sequence: int = Field(ge=1)
    trace_id: str
    event_type: EventType
    stage: str
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utc_now)


EventSubscriber = Callable[[KernelEvent], None | Awaitable[None]]


class EventBus:
    """Ordered event delivery; subscriber failures are isolated and reported."""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._sequence = 0
        self._subscribers: list[EventSubscriber] = []
        self.subscriber_errors: list[str] = []

    def subscribe(self, subscriber: EventSubscriber) -> Callable[[], None]:
        self._subscribers.append(subscriber)

        def unsubscribe() -> None:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

        return unsubscribe

    async def emit(
        self,
        event_type: EventType,
        stage: str,
        payload: dict[str, Any] | None = None,
    ) -> KernelEvent:
        self._sequence += 1
        event = KernelEvent(
            sequence=self._sequence,
            trace_id=self.trace_id,
            event_type=event_type,
            stage=stage,
            payload=payload or {},
        )
        for subscriber in tuple(self._subscribers):
            try:
                result = subscriber(event)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # event consumers cannot break the run
                self.subscriber_errors.append(f"{type(exc).__name__}: {exc}")
        return event


class TraceRecorder:
    """Append-only event trace for diagnostics and manifest persistence."""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._events: list[KernelEvent] = []

    def record(self, event: KernelEvent) -> None:
        if event.trace_id != self.trace_id:
            raise ValueError("TraceRecorder received an event for a different trace")
        self._events.append(event)

    @property
    def events(self) -> tuple[KernelEvent, ...]:
        return tuple(self._events)

    def as_dicts(self) -> list[dict[str, Any]]:
        return [event.model_dump(mode="json") for event in self._events]
