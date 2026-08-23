"""Controlled fake/replay/real gateway with strict JSON output validation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Protocol

from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema import validate as validate_json_schema

from comsol_agent.llm.base import LLMProvider, LLMResponse

from .contracts import (
    ModelError,
    ModelErrorCode,
    ModelGatewayError,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    StructuredOutput,
    Usage,
)


class ModelBackend(Protocol):
    provider_name: str
    model_name: str
    endpoint: str | None

    async def generate(self, request: ModelRequest) -> LLMResponse: ...


class ProviderBackend:
    """Adapter around the repository's existing LLMProvider clients."""

    def __init__(self, provider: LLMProvider, *, provider_name: str):
        self.provider = provider
        self.provider_name = provider_name
        self.model_name = provider.model
        self.endpoint = getattr(provider, "base_url", None)

    async def generate(self, request: ModelRequest) -> LLMResponse:
        messages = [
            *request.messages,
            {
                "role": "system",
                "content": (
                    "The response must be one JSON object matching this JSON Schema exactly: "
                    + json.dumps(
                        request.output_json_schema,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
            },
        ]
        return await self.provider.generate(
            messages=messages,
            tools=None,
            temperature=request.temperature,
            max_tokens=request.max_output_tokens,
            response_format={"type": "json_object"},
        )


class FakeBackend:
    def __init__(self, outputs: list[dict[str, Any] | str], *, model: str = "fake-v1"):
        self.provider_name = "fake"
        self.model_name = model
        self.endpoint = None
        self.outputs = list(outputs)
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> LLMResponse:
        self.requests.append(request)
        if not self.outputs:
            raise RuntimeError("fake backend output queue is empty")
        raw = self.outputs.pop(0)
        text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        return LLMResponse(
            text=text,
            usage={"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
        )


class ReplayBackend:
    def __init__(self, records: dict[str, dict[str, Any]], *, model: str = "replay-v1"):
        self.provider_name = "replay"
        self.model_name = model
        self.endpoint = None
        self.records = records

    async def generate(self, request: ModelRequest) -> LLMResponse:
        digest = prompt_digest(request)
        if digest not in self.records:
            raise LookupError(f"replay miss for prompt digest {digest}")
        record = self.records[digest]
        return LLMResponse(
            text=json.dumps(record["output"], ensure_ascii=False),
            finish_reason=record.get("finish_reason", "stop"),
            usage=record.get("usage", {}),
        )


class RecordingBackend:
    """Record sanitized structured outputs for later digest-keyed replay."""

    def __init__(self, backend: ModelBackend, records: dict[str, dict[str, Any]]):
        self.backend = backend
        self.records = records
        self.provider_name = backend.provider_name
        self.model_name = backend.model_name
        self.endpoint = getattr(backend, "endpoint", None)

    async def generate(self, request: ModelRequest) -> LLMResponse:
        response = await self.backend.generate(request)
        output = _strict_json_object(response.text)
        self.records[prompt_digest(request)] = {
            "output": output,
            "finish_reason": response.finish_reason,
            "usage": dict(response.usage),
            "provider": self.provider_name,
            "model": self.model_name,
            "provider_request_id": response.provider_request_id,
        }
        return response


class ModelGateway:
    def __init__(
        self,
        backend: ModelBackend,
        *,
        trace_sink: Callable[[dict[str, Any]], None] | None = None,
        input_cost_per_million_usd: float | None = None,
        output_cost_per_million_usd: float | None = None,
    ) -> None:
        self.backend = backend
        self.trace_sink = trace_sink
        self.input_cost_per_million_usd = input_cost_per_million_usd
        self.output_cost_per_million_usd = output_cost_per_million_usd

    async def complete(
        self,
        request: ModelRequest,
        *,
        cancellation: asyncio.Event | None = None,
    ) -> ModelResponse:
        digest = prompt_digest(request)
        started = datetime.now(UTC)
        last_error: Exception | None = None
        for attempt in range(1, request.max_retries + 2):
            if cancellation is not None and cancellation.is_set():
                self._raise(
                    request,
                    ModelErrorCode.CANCELLED,
                    "model call cancelled",
                    attempt - 1,
                    digest,
                )
            try:
                response = await _await_model(
                    self.backend.generate(request),
                    timeout=request.timeout_seconds,
                    cancellation=cancellation,
                )
                usage = _usage(
                    response.usage,
                    input_rate=self.input_cost_per_million_usd,
                    output_rate=self.output_cost_per_million_usd,
                )
                if usage.total_tokens > request.max_total_tokens:
                    self._raise(
                        request,
                        ModelErrorCode.BUDGET_EXCEEDED,
                        f"token budget exceeded: {usage.total_tokens} > {request.max_total_tokens}",
                        attempt,
                        digest,
                    )
                if request.max_cost_usd is not None:
                    if usage.estimated_cost_usd is None:
                        self._raise(
                            request,
                            ModelErrorCode.BUDGET_EXCEEDED,
                            "cost budget supplied but provider pricing is not configured",
                            attempt,
                            digest,
                        )
                    if usage.estimated_cost_usd > request.max_cost_usd:
                        self._raise(
                            request,
                            ModelErrorCode.BUDGET_EXCEEDED,
                            "estimated model cost exceeds request budget",
                            attempt,
                            digest,
                        )
                raw = _strict_json_object(response.text)
                validate_json_schema(raw, request.output_json_schema)
                structured = StructuredOutput(
                    schema_id=request.output_schema_id,
                    schema_version=request.output_schema_version,
                    value=raw,
                )
                result = ModelResponse(
                    request_id=request.request_id,
                    provider=self.backend.provider_name,
                    model=self.backend.model_name,
                    endpoint=getattr(self.backend, "endpoint", None),
                    output_source=(
                        "live_provider"
                        if self.backend.provider_name not in {"fake", "replay"}
                        else self.backend.provider_name
                    ),
                    structured=structured,
                    usage=usage,
                    finish_reason=response.finish_reason,
                    attempts=attempt,
                    provider_request_id=response.provider_request_id,
                    prompt_digest=digest,
                    started_at=started,
                    tool_calls=[
                        ModelToolCall(call_id=item.id, name=item.name, arguments=item.arguments)
                        for item in response.tool_calls
                    ],
                )
                self._trace(request, result)
                return result
            except ModelGatewayError:
                raise
            except asyncio.CancelledError:
                self._raise(
                    request,
                    ModelErrorCode.CANCELLED,
                    "model call cancelled",
                    attempt,
                    digest,
                )
            except TimeoutError as error:
                last_error = error
                code = ModelErrorCode.TIMEOUT
            except (
                json.JSONDecodeError,
                JSONSchemaValidationError,
                ValueError,
                TypeError,
            ) as error:
                self._raise(
                    request,
                    ModelErrorCode.INVALID_STRUCTURED_OUTPUT,
                    f"invalid structured model output: {error}",
                    attempt,
                    digest,
                )
            except LookupError as error:
                self._raise(request, ModelErrorCode.REPLAY_MISS, str(error), attempt, digest)
            except Exception as error:
                last_error = error
                code = _classify_provider_error(error)
            if attempt > request.max_retries:
                self._raise(request, code, _safe_error(last_error), attempt, digest)
            await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)), 1.0))
        raise AssertionError("unreachable")

    def _raise(
        self,
        request: ModelRequest,
        code: ModelErrorCode,
        message: str,
        attempts: int,
        digest: str,
    ) -> None:
        error = ModelError(
            request_id=request.request_id,
            code=code,
            message=message,
            provider=self.backend.provider_name,
            model=self.backend.model_name,
            attempts=attempts,
            retryable=code
            in {
                ModelErrorCode.RATE_LIMIT,
                ModelErrorCode.TIMEOUT,
                ModelErrorCode.PROVIDER,
            },
            prompt_digest=digest,
        )
        if self.trace_sink:
            self.trace_sink({"kind": "model_error", **error.model_dump(mode="json")})
        raise ModelGatewayError(error)

    def _trace(self, request: ModelRequest, response: ModelResponse) -> None:
        if self.trace_sink:
            self.trace_sink(
                {
                    "kind": "model_call",
                    "request_id": response.request_id,
                    "provider_request_id": response.provider_request_id,
                    "task": request.task,
                    "prompt_id": request.prompt_id,
                    "prompt_version": request.prompt_version,
                    "schema_id": request.output_schema_id,
                    "schema_version": request.output_schema_version,
                    "prompt_digest": response.prompt_digest,
                    "provider": response.provider,
                    "model": response.model,
                    "endpoint": response.endpoint,
                    "usage": response.usage.model_dump(mode="json"),
                    "started_at": response.started_at.isoformat(),
                    "finished_at": response.finished_at.isoformat(),
                    "output_source": response.output_source,
                }
            )


def prompt_digest(request: ModelRequest) -> str:
    payload = {
        "prompt_id": request.prompt_id,
        "prompt_version": request.prompt_version,
        "messages": request.messages,
        "schema": request.output_json_schema,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _strict_json_object(text: str | None) -> dict[str, Any]:
    if not text or not text.strip():
        raise ValueError("empty response")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise TypeError("top-level output must be a JSON object")
    return value


def _usage(
    raw: dict[str, int],
    *,
    input_rate: float | None,
    output_rate: float | None,
) -> Usage:
    input_tokens = int(raw.get("input_tokens", 0))
    output_tokens = int(raw.get("output_tokens", 0))
    total_tokens = int(raw.get("total_tokens", input_tokens + output_tokens))
    cost = None
    if input_rate is not None and output_rate is not None:
        cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=max(total_tokens, input_tokens + output_tokens),
        estimated_cost_usd=cost,
    )


async def _await_model(
    awaitable: Any,
    *,
    timeout: float,
    cancellation: asyncio.Event | None,
) -> LLMResponse:
    if cancellation is None:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    model_task = asyncio.create_task(awaitable)
    cancel_task = asyncio.create_task(cancellation.wait())
    done, _ = await asyncio.wait(
        {model_task, cancel_task},
        timeout=timeout,
        return_when=asyncio.FIRST_COMPLETED,
    )
    if model_task in done:
        cancel_task.cancel()
        with suppress(asyncio.CancelledError):
            await cancel_task
        return await model_task
    model_task.cancel()
    cancel_task.cancel()
    with suppress(asyncio.CancelledError):
        await model_task
    with suppress(asyncio.CancelledError):
        await cancel_task
    if cancellation.is_set():
        raise asyncio.CancelledError
    raise TimeoutError


def _classify_provider_error(error: Exception) -> ModelErrorCode:
    text = f"{type(error).__name__}: {error}".lower()
    if "auth" in text or "401" in text or "api key" in text:
        return ModelErrorCode.AUTHENTICATION
    if "rate" in text or "429" in text:
        return ModelErrorCode.RATE_LIMIT
    return ModelErrorCode.PROVIDER


def _safe_error(error: Exception | None) -> str:
    if error is None:
        return "provider call failed"
    message = f"{type(error).__name__}: {error}"
    return re.sub(
        r"(?i)(api[_ -]?key|authorization|bearer)(\s*[:=]?\s*)\S+",
        r"\1\2[REDACTED]",
        message,
    )
