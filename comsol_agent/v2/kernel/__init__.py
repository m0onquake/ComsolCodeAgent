"""Public domain-neutral V2 kernel API."""

from comsol_agent.v2.kernel.budget import (
    BudgetExceededError,
    BudgetLimits,
    BudgetSnapshot,
    RunBudget,
)
from comsol_agent.v2.kernel.cancellation import CancellationToken, RunCancelledError
from comsol_agent.v2.kernel.context import (
    ContextEntry,
    ContextKind,
    ContextManager,
    ContextSnapshot,
    InMemoryContextManager,
)
from comsol_agent.v2.kernel.events import EventBus, EventType, KernelEvent, TraceRecorder
from comsol_agent.v2.kernel.loop import AgentKernel, ToolExecutor
from comsol_agent.v2.kernel.state import InvalidTransitionError, RunStage, RunStateMachine

__all__ = [
    "AgentKernel",
    "BudgetExceededError",
    "BudgetLimits",
    "BudgetSnapshot",
    "CancellationToken",
    "ContextEntry",
    "ContextKind",
    "ContextManager",
    "ContextSnapshot",
    "EventBus",
    "EventType",
    "InMemoryContextManager",
    "InvalidTransitionError",
    "KernelEvent",
    "RunBudget",
    "RunCancelledError",
    "RunStage",
    "RunStateMachine",
    "ToolExecutor",
    "TraceRecorder",
]
