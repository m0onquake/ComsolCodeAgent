"""Versioned, provider-neutral contracts for controlled model calls."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field, model_validator

from comsol_agent.v2.contracts.models import ContractModel, utc_now


class ModelTask(StrEnum):
    INTAKE = "intake"
    PLANNING = "planning"
    LOCAL_REPAIR = "local_repair"


class ModelErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PROVIDER = "provider_error"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    BUDGET_EXCEEDED = "budget_exceeded"
    REPLAY_MISS = "replay_miss"


class Usage(ContractModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def total_is_consistent(self) -> Usage:
        if self.total_tokens < self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens cannot be smaller than input + output")
        return self


class StructuredOutput(ContractModel):
    schema_id: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    value: dict[str, Any]


class ModelToolCall(ContractModel):
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelRequest(ContractModel):
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    task: ModelTask
    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    messages: list[dict[str, Any]] = Field(min_length=1)
    output_schema_id: str = Field(min_length=1)
    output_schema_version: str = Field(min_length=1)
    output_json_schema: dict[str, Any]
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    max_retries: int = Field(default=1, ge=0, le=3)
    max_output_tokens: int = Field(default=2048, ge=1, le=32768)
    max_total_tokens: int = Field(default=16000, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)
    temperature: float = Field(default=0.0, ge=0, le=2)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(ContractModel):
    request_id: str
    provider: str
    model: str
    endpoint: str | None = None
    output_source: str
    structured: StructuredOutput
    usage: Usage
    finish_reason: str
    attempts: int = Field(ge=1)
    provider_request_id: str | None = None
    prompt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: datetime
    finished_at: datetime = Field(default_factory=utc_now)
    tool_calls: list[ModelToolCall] = Field(default_factory=list)


class ModelError(ContractModel):
    request_id: str
    code: ModelErrorCode
    message: str
    provider: str | None = None
    model: str | None = None
    attempts: int = Field(default=0, ge=0)
    retryable: bool = False
    prompt_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    occurred_at: datetime = Field(default_factory=utc_now)


class ModelGatewayError(RuntimeError):
    """Exception carrying a safe, serializable model error."""

    def __init__(self, error: ModelError):
        self.error = error
        super().__init__(error.message)
