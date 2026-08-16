"""Tests for the local presentation web UI."""

from __future__ import annotations

import json

import pytest

from comsol_agent.cli.config import Config
from comsol_agent.web.demo_case import build_demo_case
from comsol_agent.web.runtime import WebSession, WebSessionManager


@pytest.mark.asyncio
async def test_agent_loop_emits_tool_result_callback():
    from collections.abc import AsyncIterator
    from typing import Any

    from comsol_agent.agent.loop import AgentLoop
    from comsol_agent.agent.tool_registry import register_sync
    from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolCall, ToolDefinition

    register_sync(
        name="web_callback_probe",
        description="Web callback test tool",
        parameters={"type": "object", "properties": {}},
        handler=lambda: {"success": True, "value": 7},
    )

    class CallbackProvider(LLMProvider):
        def __init__(self):
            super().__init__(model="fake")
            self.calls = 0

        async def generate(
            self,
            messages: list[dict[str, Any]],
            tools: list[ToolDefinition] | None = None,
            **kwargs: Any,
        ) -> LLMResponse:
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    tool_calls=[ToolCall(id="probe", name="web_callback_probe", arguments={})]
                )
            return LLMResponse(text="done")

        async def generate_stream(
            self,
            messages: list[dict[str, Any]],
            tools: list[ToolDefinition] | None = None,
            **kwargs: Any,
        ) -> AsyncIterator[str]:
            if False:
                yield ""

        def count_tokens(self, messages: list[dict[str, Any]]) -> int:
            return 1

    results: list[tuple[str, str, bool]] = []
    agent = AgentLoop(
        CallbackProvider(),
        Config(),
        on_tool_result=lambda name, output, failed: results.append((name, output, failed)),
    )

    assert await agent.run("run probe") == "done"
    assert results[0][0] == "web_callback_probe"
    assert '"value": 7' in results[0][1]
    assert results[0][2] is False


def test_demo_case_uses_real_repository_artifacts():
    case = build_demo_case()

    assert case["available"] is True
    assert len(case["artifacts"]) >= 5
    assert any(item["id"] == "stress" for item in case["artifacts"])
    assert len(case["roller_loads"]) == 12
    assert "model.component" in case["code"]


@pytest.mark.asyncio
async def test_demo_stream_completes_without_llm_or_comsol(monkeypatch):
    monkeypatch.setenv("COMSOL_AGENT_WEB_DEMO_DELAY", "0")
    manager = WebSessionManager(Config())
    events = [
        event
        async for event in manager.stream(
            "demo requirement",
            mode="demo",
        )
    ]

    assert events[0]["type"] == "session"
    assert any(event["type"] == "code" for event in events)
    assert any(event["type"] == "artifacts" for event in events)
    assert events[-1]["type"] == "complete"
    snapshot = events[-1]["session"]
    assert snapshot["status"] == "completed"
    assert len(snapshot["artifacts"]) >= 5
    json.dumps(events, ensure_ascii=False)


def test_web_health_and_demo_routes(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from comsol_agent.web.app import app

    client = TestClient(app)
    health = client.get("/api/health")
    demo = client.get("/api/demo")

    assert health.status_code == 200
    assert health.json()["demo_available"] is True
    assert demo.status_code == 200
    assert "12 个滚子" in demo.json()["requirement"]


def test_web_rejects_unknown_mode():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from comsol_agent.web.app import app

    response = TestClient(app).post(
        "/api/chat",
        json={"requirement": "test", "mode": "unknown"},
    )

    assert response.status_code == 422


def test_live_callbacks_capture_code_metrics_and_artifacts(tmp_path, monkeypatch):
    from types import SimpleNamespace

    manager = WebSessionManager(Config())
    session = WebSession(id="capture", mode="live")
    session.agent = SimpleNamespace(on_tool_call=None, on_tool_result=None)
    emitted = []
    monkeypatch.setattr(manager, "_is_allowed_path", lambda path: tmp_path in path.parents)
    image = tmp_path / "stress.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    def emit(event_type, **payload):
        emitted.append((event_type, payload))

    manager._attach_callbacks(session, emit)
    session.agent.on_tool_result(
        "simulation_read_template",
        json.dumps({"success": True, "template": {"java_code": "model.study().create('std1');"}}),
        False,
    )
    session.agent.on_tool_call("comsol_execute_java", {"java_code": "model.sol();"})
    session.agent.on_tool_result(
        "comsol_evaluate",
        json.dumps(
            {
                "success": True,
                "expression": "solid.mises/1[MPa]",
                "statistics": {"max": 250.21},
                "filepath": str(image),
            }
        ),
        False,
    )

    assert session.code == "model.study().create('std1');"
    assert session.metrics == [
        {
            "label": "solid.mises/1[MPa]",
            "value": "250.21 MPa",
            "expression": "solid.mises/1[MPa]",
            "unit": "MPa",
            "tone": "blue",
        }
    ]
    assert any(item.path == image for item in session.artifacts.values())
    assert any(event_type == "code" for event_type, _payload in emitted)
    assert any(event_type == "artifacts" for event_type, _payload in emitted)


def test_unnormalized_comsol_metric_is_not_displayed():
    manager = WebSessionManager(Config())
    session = WebSession(id="metric", mode="live")

    manager._capture_metric(
        session,
        "comsol_evaluate",
        {"success": True, "expression": "solid.disp", "statistics": {"max": 0.001}},
    )

    assert session.metrics == []
