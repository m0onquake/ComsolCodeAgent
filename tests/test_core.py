"""Basic tests for COMSOL Agent core modules.

These tests verify imports, configuration loading, and basic agent logic.
COMSOL-specific tests require a local COMSOL installation and are marked accordingly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestConfig:
    """Tests for configuration management."""

    def test_default_config(self):
        from comsol_agent.cli.config import Config

        config = Config()
        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4o"
        assert config.agent.llm_max_retries == 3
        assert config.agent.auto_repair is True
        assert config.agent.max_repair_attempts == 3

    def test_env_overrides(self, monkeypatch):
        from comsol_agent.cli.config import Config, _apply_env_overrides

        config = Config()
        monkeypatch.setenv("COMSOL_AGENT_MODEL", "gpt-5")
        monkeypatch.setenv("COMSOL_AGENT_PROVIDER", "anthropic")

        config = _apply_env_overrides(config)
        assert config.llm.model == "gpt-5"
        assert config.llm.provider == "anthropic"

    def test_deepseek_env_overrides(self, monkeypatch):
        from comsol_agent.cli.config import Config, _apply_env_overrides

        config = Config()
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

        config = _apply_env_overrides(config)
        assert config.llm.provider == "deepseek"
        assert config.llm.model == "deepseek-v4-flash"
        assert config.llm.api_key == "sk-test"
        assert config.llm.base_url == "https://api.deepseek.com"


class TestLLMDefinitions:
    """Tests for LLM abstractions."""

    def test_tool_definition(self):
        from comsol_agent.llm.base import ToolDefinition

        td = ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
        )
        assert td.name == "test_tool"
        assert td.description == "A test tool"

    def test_llm_response_text(self):
        from comsol_agent.llm.base import LLMResponse

        resp = LLMResponse(text="Hello")
        assert resp.is_text is True
        assert resp.is_tool_calls is False

    def test_llm_response_tool_calls(self):
        from comsol_agent.llm.base import LLMResponse, ToolCall

        resp = LLMResponse(
            tool_calls=[ToolCall(id="1", name="test", arguments={})]
        )
        assert resp.is_tool_calls is True
        assert resp.is_text is False


class TestLLMRouter:
    """Tests for offline LLM routing plans."""

    def test_plan_route_uses_task_tiers_and_fallback_chain(self):
        from comsol_agent.llm.router import plan_route

        repair_plan = plan_route("code_repair", preferred_provider="openai")
        compact_plan = plan_route("memory_compaction", preferred_provider="anthropic")

        assert repair_plan.model_tier == "strong_model"
        assert repair_plan.provider_chain == ["openai", "anthropic"]
        assert repair_plan.primary_model == "gpt-4o"
        assert compact_plan.model_tier == "fast_model"
        assert compact_plan.provider_chain == ["anthropic", "openai"]
        assert compact_plan.primary_model == "claude-3-5-haiku-20241022"

    def test_plan_route_respects_preferred_model_for_primary_provider(self):
        from comsol_agent.llm.router import plan_route

        plan = plan_route(
            "summarization",
            preferred_provider="openai",
            preferred_model="custom-fast-model",
        )

        assert plan.primary_provider == "openai"
        assert plan.primary_model == "custom-fast-model"
        assert plan.models_by_provider["anthropic"] == "claude-3-5-haiku-20241022"

    def test_plan_route_supports_deepseek_provider(self):
        from comsol_agent.llm.router import plan_route

        plan = plan_route("code_generation", preferred_provider="deepseek")

        assert plan.primary_provider == "deepseek"
        assert plan.primary_model == "deepseek-v4-pro"
        assert plan.provider_chain == ["deepseek", "openai", "anthropic"]

    def test_plan_route_rejects_unsupported_provider_set(self):
        from comsol_agent.llm.router import plan_route

        with pytest.raises(ValueError, match="No supported providers"):
            plan_route("text_response", preferred_provider="local", enabled_providers=["local"])

    def test_create_provider_from_plan_uses_selected_provider(self, monkeypatch):
        from comsol_agent.llm.router import create_provider_from_plan, plan_route

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        plan = plan_route("text_response", preferred_provider="openai")

        with pytest.raises(ValueError, match="OpenAI API key not found"):
            create_provider_from_plan(plan)

    def test_deepseek_provider_requires_key(self, monkeypatch):
        from comsol_agent.llm.router import create_provider_from_plan, plan_route

        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        plan = plan_route("text_response", preferred_provider="deepseek")

        with pytest.raises(ValueError, match="DeepSeek API key not found"):
            create_provider_from_plan(plan)

    def test_mock_llm_server_response_shape(self):
        from comsol_agent.dev.mock_llm_server import build_chat_completion_response

        payload = {
            "model": "mock-model",
            "messages": [
                {"role": "system", "content": "You are a test assistant."},
                {"role": "user", "content": "hello mock server"},
            ],
            "tools": [{"type": "function", "function": {"name": "file_list"}}],
        }

        response = build_chat_completion_response(payload)

        assert response["object"] == "chat.completion"
        assert response["model"] == "mock-model"
        assert "hello mock server" in response["choices"][0]["message"]["content"]
        assert response["usage"]["total_tokens"] > 0

    @pytest.mark.asyncio
    async def test_deepseek_v4_tool_request_disables_thinking_and_tool_choice(self, monkeypatch):
        from types import SimpleNamespace

        from comsol_agent.llm.base import ToolDefinition
        from comsol_agent.llm.openai import OpenAIProvider

        captured = {}

        class FakeCompletions:
            async def create(self, **params):
                captured.update(params)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="ok", tool_calls=None),
                            finish_reason="stop",
                        )
                    ],
                    usage=SimpleNamespace(
                        prompt_tokens=1,
                        completion_tokens=1,
                        total_tokens=2,
                    ),
                )

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(
                    completions=FakeCompletions()
                )

        import comsol_agent.llm.openai as openai_module

        monkeypatch.setattr(
            openai_module,
            "AsyncOpenAI",
            FakeAsyncOpenAI,
            raising=False,
        )
        monkeypatch.setitem(
            __import__("sys").modules,
            "openai",
            SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
        )

        provider = OpenAIProvider(
            model="deepseek-v4-flash",
            api_key="test",
            base_url="https://api.deepseek.com",
        )
        await provider.generate(
            messages=[{"role": "user", "content": "call tool"}],
            tools=[
                ToolDefinition(
                    name="record_probe",
                    description="test",
                    parameters={"type": "object", "properties": {}},
                )
            ],
        )

        assert "tool_choice" not in captured
        assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


class TestToolRegistry:
    """Tests for tool registration."""

    def test_register_and_get(self):
        from comsol_agent.agent.tool_registry import (
            register_sync,
            get_tool_handler,
            get_tool_definitions,
        )

        def my_tool(value: int) -> dict:
            return {"success": True, "value": value}

        register_sync(
            name="my_test_tool",
            description="Test tool",
            parameters={"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]},
            handler=my_tool,
        )

        definitions = get_tool_definitions()
        assert any(d.name == "my_test_tool" for d in definitions)

        handler = get_tool_handler("my_test_tool")
        assert handler is not None

    @pytest.mark.asyncio
    async def test_register_sync_handles_async_tool(self):
        from comsol_agent.agent.tool_registry import get_tool_handler, register_sync

        async def my_async_tool(value: int) -> dict:
            return {"success": True, "value": value}

        register_sync(
            name="my_async_test_tool",
            description="Async test tool",
            parameters={"type": "object", "properties": {"value": {"type": "integer"}}},
            handler=my_async_tool,
        )

        handler = get_tool_handler("my_async_test_tool")
        assert handler is not None

        result = await handler(value=7)
        assert result == {"success": True, "value": 7}

    def test_validate_tool_arguments(self):
        from comsol_agent.agent.tool_registry import register_sync, validate_tool_arguments

        def my_tool(mode: str, count: int) -> dict:
            return {"success": True, "mode": mode, "count": count}

        register_sync(
            name="my_validated_tool",
            description="Validated test tool",
            parameters={
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["fast", "safe"]},
                    "count": {"type": "integer"},
                },
                "required": ["mode", "count"],
            },
            handler=my_tool,
        )

        assert validate_tool_arguments(
            "my_validated_tool", {"mode": "fast", "count": 2}
        ) == []

        errors = validate_tool_arguments("my_validated_tool", {"mode": "slow"})
        assert "Missing required argument: count" in errors
        assert any("must be one of" in error for error in errors)

    def test_register_bootstrap(self):
        from comsol_agent.agent.tools_bootstrap import register_all_tools
        from comsol_agent.agent.tool_registry import get_tool_definitions

        register_all_tools()
        definitions = get_tool_definitions()
        names = {d.name for d in definitions}

        # Core COMSOL tools should be registered
        assert "comsol_load_model" in names
        assert "comsol_solve" in names
        assert "comsol_evaluate" in names
        assert "comsol_set_parameter" in names
        assert "simulation_plan_bearing_contact" in names
        assert "simulation_plan_multiroller_bearing" in names
        assert "simulation_probe_3d_selection_binding" in names
        assert "simulation_plan_generated_code" in names
        assert "simulation_plan_parameter_sweep" in names
        assert "simulation_search_local_docs" in names
        assert "simulation_retrieve_api_docs" in names
        assert "simulation_list_example_models" in names
        assert "simulation_list_templates" in names
        assert "simulation_search_templates" in names
        assert "simulation_read_template" in names
        assert "simulation_save_template" in names
        assert "simulation_validate_template" in names
        assert "simulation_export_template" in names
        assert "simulation_run_template" in names
        assert "simulation_list_artifacts" in names
        assert "simulation_search_artifacts" in names
        assert "simulation_read_artifact" in names
        assert "simulation_answer_artifact_question" in names
        assert "simulation_compare_artifacts" in names
        assert "simulation_export_artifact_report" in names
        assert "simulation_export_bearing_contact_package" in names
        assert "simulation_rerun_artifact" in names
        assert "simulation_run_example_model" in names
        assert "simulation_run_parameter_sweep" in names


class TestTokenCounter:
    """Tests for token counting utilities."""

    def test_estimate_tokens(self):
        from comsol_agent.utils.token_counter import estimate_tokens

        tokens = estimate_tokens("Hello world")
        assert tokens > 0

    def test_estimate_tokens_falls_back_when_tiktoken_encoding_fails(self, monkeypatch):
        import sys
        from types import SimpleNamespace

        from comsol_agent.utils.token_counter import estimate_tokens

        def fail(*args, **kwargs):
            raise RuntimeError("offline")

        monkeypatch.setitem(
            sys.modules,
            "tiktoken",
            SimpleNamespace(encoding_for_model=fail, get_encoding=fail),
        )

        assert estimate_tokens("offline fallback works") > 0

    def test_estimate_messages(self):
        from comsol_agent.utils.token_counter import estimate_messages_tokens

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ]
        tokens = estimate_messages_tokens(messages)
        assert tokens > 10  # Should be more than just the text


class TestSystemPrompt:
    """Tests for system prompt building."""

    def test_basic_prompt(self):
        from comsol_agent.agent.prompt import build_system_prompt

        prompt = build_system_prompt()
        assert "COMSOL" in prompt
        assert "tool" in prompt.lower()
        assert "Missing Parameters and Defaults" in prompt
        assert "bearing_contact_hertz_seed" in prompt
        assert "simulation_plan_generated_code" in prompt
        assert "template-first but not template-only" in prompt
        assert "simulation_probe_3d_selection_binding" in prompt

    def test_domain_prompt(self):
        from comsol_agent.agent.prompt import build_system_prompt

        prompt = build_system_prompt(simulation_domain="thermal")
        assert "thermal conductivity" in prompt.lower()
        assert "heat" in prompt.lower()

    def test_extra_context(self):
        from comsol_agent.agent.prompt import build_system_prompt

        prompt = build_system_prompt(extra_context="Working on brake disc simulation.")
        assert "brake disc" in prompt


class TestAgentLoop:
    """Tests for the agent state machine without calling real APIs."""

    @pytest.mark.asyncio
    async def test_uses_configured_tool_iteration_limit(self):
        from collections.abc import AsyncIterator
        from typing import Any

        from comsol_agent.agent.loop import AgentLoop
        from comsol_agent.cli.config import Config
        from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolCall, ToolDefinition

        class LoopingProvider(LLMProvider):
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
                if tools is None:
                    return LLMResponse(text="Forced final summary.")
                return LLMResponse(
                    tool_calls=[
                        ToolCall(id=f"call_{self.calls}", name="missing_tool", arguments={})
                    ]
                )

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

        config = Config()
        config.agent.max_tool_iterations = 2
        provider = LoopingProvider()
        agent = AgentLoop(provider, config)

        response = await agent.run("Keep calling tools")

        assert response == "Forced final summary."
        assert provider.calls == 3
        assert agent.state.tool_iterations_this_turn == 2

    @pytest.mark.asyncio
    async def test_invalid_tool_arguments_return_structured_error(self):
        from collections.abc import AsyncIterator
        from typing import Any

        from comsol_agent.agent.loop import AgentLoop
        from comsol_agent.agent.tool_registry import register_sync
        from comsol_agent.cli.config import Config
        from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolCall, ToolDefinition

        executed = False

        def required_tool(value: str) -> dict:
            nonlocal executed
            executed = True
            return {"success": True, "value": value}

        register_sync(
            name="requires_value_tool",
            description="Requires one value",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            handler=required_tool,
        )

        class OneBadCallProvider(LLMProvider):
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
                        tool_calls=[
                            ToolCall(id="call_1", name="requires_value_tool", arguments={})
                        ]
                    )
                return LLMResponse(text="Saw the validation error.")

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

        agent = AgentLoop(OneBadCallProvider(), Config())
        response = await agent.run("Call it badly")

        assert response == "Saw the validation error."
        assert executed is False
        tool_messages = [msg for msg in agent.state.messages if msg["role"] == "tool"]
        assert "Missing required argument: value" in tool_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_llm_generate_retries_transient_errors(self, monkeypatch):
        from collections.abc import AsyncIterator
        from typing import Any

        import comsol_agent.agent.loop as loop_module
        from comsol_agent.agent.loop import AgentLoop
        from comsol_agent.cli.config import Config
        from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolDefinition

        async def no_sleep(seconds: int) -> None:
            return None

        monkeypatch.setattr(loop_module.asyncio, "sleep", no_sleep)

        class FlakyProvider(LLMProvider):
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
                if self.calls < 3:
                    raise TimeoutError("temporary timeout")
                return LLMResponse(text="Recovered.")

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

        config = Config()
        config.agent.llm_max_retries = 3
        provider = FlakyProvider()
        agent = AgentLoop(provider, config)

        response = await agent.run("Hello")

        assert response == "Recovered."
        assert provider.calls == 3

    @pytest.mark.asyncio
    async def test_session_store_snapshot_after_turn(self, tmp_path):
        from collections.abc import AsyncIterator
        from typing import Any
        import json

        from comsol_agent.agent.loop import AgentLoop
        from comsol_agent.cli.config import Config
        from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolDefinition
        from comsol_agent.memory.session_store import SessionStore

        class TextProvider(LLMProvider):
            async def generate(
                self,
                messages: list[dict[str, Any]],
                tools: list[ToolDefinition] | None = None,
                **kwargs: Any,
            ) -> LLMResponse:
                return LLMResponse(text="Stored response.", usage={"total_tokens": 3})

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

        config = Config()
        store = SessionStore(tmp_path / "sessions", session_id="test_session")
        agent = AgentLoop(TextProvider(model="fake"), config, session_store=store)

        response = await agent.run("Save this session")

        payload = json.loads(store.path.read_text(encoding="utf-8"))
        assert response == "Stored response."
        assert payload["schema_version"] == 1
        assert payload["session_id"] == "test_session"
        assert payload["llm"] == {"provider": "openai", "model": "gpt-4o"}
        assert payload["stats"]["total_tokens_used"] == 3
        assert payload["stats"]["turn_count"] == 1
        assert payload["messages"][-1]["content"] == "Stored response."
        assert [turn["role"] for turn in payload["turns"]] == ["user", "assistant"]

    def test_cli_app_imports(self):
        from comsol_agent.cli.app import CLIApp

        assert CLIApp is not None


class TestCompaction:
    """Tests for deterministic context compaction."""

    def test_compact_messages_preserves_user_text_and_summarizes_tools(self):
        from comsol_agent.memory.compaction import compact_messages

        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old exact user request"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "comsol_evaluate", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "comsol_evaluate",
                "content": '{"success": true, "data": "' + ("x" * 6000) + '"}',
            },
            {"role": "user", "content": "recent exact user request"},
            {"role": "assistant", "content": "recent response"},
        ]

        result = compact_messages(messages, recency_zone_tokens=20)

        assert result.changed is True
        contents = [message.get("content", "") for message in result.messages]
        assert "old exact user request" in contents
        assert "recent exact user request" in contents
        assert any("[Compacted context]" in content for content in contents)
        assert result.compacted_tokens < result.original_tokens

    def test_agent_loop_manual_compaction(self):
        from comsol_agent.agent.loop import AgentLoop
        from comsol_agent.cli.config import Config
        from comsol_agent.llm.base import LLMProvider, LLMResponse

        class TextProvider(LLMProvider):
            async def generate(self, messages, tools=None, **kwargs):
                return LLMResponse(text="done")

            async def generate_stream(self, messages, tools=None, **kwargs):
                if False:
                    yield ""

            def count_tokens(self, messages):
                return 1

        config = Config()
        config.memory.recency_zone_tokens = 20
        agent = AgentLoop(TextProvider(model="fake"), config)
        agent.state.messages.extend(
            [
                {"role": "user", "content": "old request"},
                {"role": "assistant", "content": "a" * 4000},
                {"role": "tool", "name": "file_read", "content": "b" * 4000},
                {"role": "user", "content": "recent request"},
            ]
        )

        result = agent.compact_context(manual=True)

        assert result["changed"] is True
        assert any(
            message.get("content") == "old request" for message in agent.state.messages
        )
        assert any(
            "[Compacted context]" in str(message.get("content"))
            for message in agent.state.messages
        )


class TestRepairDetector:
    """Tests for deterministic repair error detection."""

    @pytest.mark.parametrize(
        ("message", "expected_type"),
        [
            ("Syntax error near unexpected token", "SYNTAX_ERROR"),
            ("No method named geommm on model object", "API_ERROR"),
            ("Boundary condition is not defined on this domain", "PHYSICS_ERROR"),
            ("Solver failed to converge; NaN detected", "SOLVER_ERROR"),
            ("Command timed out after 120s", "TIMEOUT_ERROR"),
            ("Something unusual happened", "UNKNOWN"),
        ],
    )
    def test_detect_tool_error_classifies_messages(self, message, expected_type):
        from comsol_agent.repair.detector import detect_tool_error

        report = detect_tool_error(
            tool_name="comsol_execute_java",
            tool_output={"success": False, "error": message},
            arguments={"java_code": "model.geom('geom1');"},
        )

        assert report.error_type.value == expected_type
        assert report.tool_name == "comsol_execute_java"
        assert report.code_snippet == "model.geom('geom1');"

    @pytest.mark.asyncio
    async def test_agent_loop_records_repair_report_for_tool_error(self):
        from collections.abc import AsyncIterator
        from typing import Any

        from comsol_agent.agent.loop import AgentLoop
        from comsol_agent.agent.tool_registry import register_sync
        from comsol_agent.cli.config import Config
        from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolCall, ToolDefinition

        def failing_tool() -> dict:
            return {
                "success": False,
                "error": "Failed to converge because the matrix is singular",
            }

        register_sync(
            name="repair_detector_test_tool",
            description="Always fails for repair detector testing",
            parameters={"type": "object", "properties": {}},
            handler=failing_tool,
        )

        class FailingToolProvider(LLMProvider):
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
                        tool_calls=[
                            ToolCall(
                                id="call_repair",
                                name="repair_detector_test_tool",
                                arguments={},
                            )
                        ]
                    )
                assert any(
                    "Auto-repair detector classified" in str(message.get("content", ""))
                    for message in messages
                )
                assert any(
                    "Structured repair plan" in str(message.get("content", ""))
                    for message in messages
                )
                return LLMResponse(text="Reported the failure.")

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

        agent = AgentLoop(FailingToolProvider(), Config())
        response = await agent.run("Trigger failing tool")

        assert response == "Reported the failure."
        assert agent.state.repair_reports
        assert agent.state.repair_reports[0]["error_type"] == "SOLVER_ERROR"
        assert agent.state.repair_reports[0]["diagnosis"]["error_type"] == "SOLVER_ERROR"
        assert agent.state.repair_reports[0]["repair_plan"]["action"] == "diagnose_solver_before_retry"
        assert agent.state.repair_reports[0]["repair_plan"]["can_auto_retry"] is False
        assert agent.state.repair_reports[0]["fix_prompt"] is None
        assert agent.state.repair_reports[0]["validation"]["requires_runtime"] is True
        assert any(
            "SOLVER_ERROR" in str(message.get("content", ""))
            for message in agent.state.messages
        )
        assert any(
            "Fallback diagnosis" in str(message.get("content", ""))
            for message in agent.state.messages
        )

    @pytest.mark.asyncio
    async def test_agent_loop_stops_repeated_identical_failed_tool_calls(self):
        from collections.abc import AsyncIterator
        from typing import Any

        from comsol_agent.agent.loop import AgentLoop
        from comsol_agent.agent.tool_registry import register_sync
        from comsol_agent.cli.config import Config
        from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolCall, ToolDefinition

        def bad_input_tool() -> dict:
            return {
                "success": False,
                "error": "Either name or java_code is required.",
                "error_type": "TOOL_INPUT_ERROR",
                "retryable": False,
            }

        register_sync(
            name="repeated_bad_input_tool",
            description="Always fails with a deterministic input error",
            parameters={"type": "object", "properties": {}},
            handler=bad_input_tool,
        )

        class RepeatingBadToolProvider(LLMProvider):
            def __init__(self):
                super().__init__(model="fake")

            async def generate(
                self,
                messages: list[dict[str, Any]],
                tools: list[ToolDefinition] | None = None,
                **kwargs: Any,
            ) -> LLMResponse:
                return LLMResponse(
                    tool_calls=[
                        ToolCall(
                            id=f"call_bad_{len(messages)}",
                            name="repeated_bad_input_tool",
                            arguments={},
                        )
                    ]
                )

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

        config = Config()
        config.agent.max_tool_iterations = 10
        agent = AgentLoop(RepeatingBadToolProvider(), config)
        response = await agent.run("Trigger repeated bad tool calls")

        assert "Stopped after the same tool call failed repeatedly" in response
        assert agent.state.tool_iterations_this_turn == 3

    @pytest.mark.asyncio
    async def test_repeated_failure_batch_records_all_tool_responses_before_stop(self):
        from collections.abc import AsyncIterator
        from typing import Any

        from comsol_agent.agent.loop import AgentLoop
        from comsol_agent.agent.tool_registry import register_sync
        from comsol_agent.cli.config import Config
        from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolCall, ToolDefinition

        def repeated_batch_bad_tool() -> dict:
            return {"success": False, "error": "deterministic failure"}

        def repeated_batch_side_tool() -> dict:
            return {"success": True, "ok": True}

        register_sync(
            name="repeated_batch_bad_tool",
            description="Always fails for batch history testing",
            parameters={"type": "object", "properties": {}},
            handler=repeated_batch_bad_tool,
        )
        register_sync(
            name="repeated_batch_side_tool",
            description="Always succeeds for batch history testing",
            parameters={"type": "object", "properties": {}},
            handler=repeated_batch_side_tool,
        )

        class BatchFailingProvider(LLMProvider):
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
                return LLMResponse(
                    tool_calls=[
                        ToolCall(id=f"bad_{self.calls}", name="repeated_batch_bad_tool", arguments={}),
                        ToolCall(id=f"side_{self.calls}", name="repeated_batch_side_tool", arguments={}),
                    ]
                )

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

        config = Config()
        config.agent.max_tool_iterations = 10
        agent = AgentLoop(BatchFailingProvider(), config)

        response = await agent.run("Trigger repeated failure in a multi-tool batch")

        assert "Stopped after the same tool call failed repeatedly" in response
        last_batch_index = max(
            index
            for index, msg in enumerate(agent.state.messages)
            if msg["role"] == "assistant" and msg.get("tool_calls")
        )
        last_tool_call_ids = [
            tool_call["id"] for tool_call in agent.state.messages[last_batch_index]["tool_calls"]
        ]
        final_assistant_index = len(agent.state.messages) - 1
        assert agent.state.messages[final_assistant_index]["role"] == "assistant"
        tool_messages_after_last_batch = [
            msg
            for msg in agent.state.messages[last_batch_index + 1 : final_assistant_index]
            if msg["role"] == "tool"
        ]
        assert [msg["tool_call_id"] for msg in tool_messages_after_last_batch] == last_tool_call_ids

    @pytest.mark.asyncio
    async def test_agent_loop_stores_fix_prompt_when_code_snippet_exists(self):
        from collections.abc import AsyncIterator
        from typing import Any

        from comsol_agent.agent.loop import AgentLoop
        from comsol_agent.agent.tool_registry import register_sync
        from comsol_agent.cli.config import Config
        from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolCall, ToolDefinition

        def failing_code_tool(java_code: str) -> dict:
            return {"success": False, "error": "No method named LLMRouter fallback"}

        register_sync(
            name="repair_code_prompt_test_tool",
            description="Fails with code snippet",
            parameters={
                "type": "object",
                "properties": {"java_code": {"type": "string"}},
                "required": ["java_code"],
            },
            handler=failing_code_tool,
        )

        class CodeFailureProvider(LLMProvider):
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
                        tool_calls=[
                            ToolCall(
                                id="call_code_repair",
                                name="repair_code_prompt_test_tool",
                                arguments={"java_code": "model.geommm('geom1');"},
                            )
                        ]
                    )
                return LLMResponse(text="Prompt captured.")

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

        agent = AgentLoop(CodeFailureProvider(), Config())
        response = await agent.run("Trigger code repair")
        report = agent.state.repair_reports[0]

        assert response == "Prompt captured."
        assert report["error_type"] == "API_ERROR"
        assert report["code_snippet"] == "model.geommm('geom1');"
        assert report["retrieved_docs"]
        assert report["repair_plan"]["can_auto_retry"] is True
        assert "repair_code_prompt_test_tool" in report["repair_plan"]["suggested_tools"]
        assert "LLMRouter" in report["diagnosis_prompt"]
        assert "Relevant API docs" in report["diagnosis_prompt"]
        assert report["fix_prompt"] is not None
        assert "model.geommm('geom1');" in report["fix_prompt"]

    def test_analyzer_prompt_and_fallback_diagnosis(self):
        from comsol_agent.repair.analyzer import build_diagnosis_prompt, suggest_diagnosis
        from comsol_agent.repair.detector import ErrorReport, ErrorType

        report = ErrorReport(
            error_type=ErrorType.API_ERROR,
            message="No method named foo",
            tool_name="comsol_execute_java",
            code_snippet="model.foo();",
        )

        prompt = build_diagnosis_prompt(
            report,
            retrieved_docs=["model.geom() creates geometry features."],
            conversation_context="User is editing a heat transfer model.",
        )
        diagnosis = suggest_diagnosis(report)

        assert "Error type: API_ERROR" in prompt
        assert "model.foo();" in prompt
        assert "Relevant API docs" in prompt
        assert diagnosis.error_type == ErrorType.API_ERROR
        assert diagnosis.needs_llm_analysis is True
        assert diagnosis.api_hints

    def test_repair_planner_builds_structured_actions(self):
        from comsol_agent.repair.analyzer import suggest_diagnosis
        from comsol_agent.repair.detector import ErrorReport, ErrorType
        from comsol_agent.repair.planner import (
            format_repair_plan_message,
            plan_repair_action,
        )

        api_report = ErrorReport(
            error_type=ErrorType.API_ERROR,
            message="No method named geommm",
            tool_name="comsol_execute_java",
            code_snippet="model.geommm('geom1');",
        )
        solver_report = ErrorReport(
            error_type=ErrorType.SOLVER_ERROR,
            message="Failed to converge",
            tool_name="comsol_solve",
        )

        api_plan = plan_repair_action(api_report, suggest_diagnosis(api_report))
        solver_plan = plan_repair_action(solver_report, suggest_diagnosis(solver_report))

        assert api_plan.action == "inspect_api_usage_then_retry"
        assert api_plan.can_auto_retry is True
        assert "comsol_execute_java" in api_plan.suggested_tools
        assert solver_plan.action == "diagnose_solver_before_retry"
        assert solver_plan.can_auto_retry is False
        assert "comsol_get_model_summary" in solver_plan.suggested_tools
        assert "Structured repair plan" in format_repair_plan_message(api_plan)

    def test_fixer_prompt_and_candidate_preflight(self):
        from comsol_agent.repair.analyzer import Diagnosis
        from comsol_agent.repair.detector import ErrorType
        from comsol_agent.repair.fixer import build_fix_prompt, candidate_from_text
        from comsol_agent.repair.validator import preflight_fixed_code

        diagnosis = Diagnosis(
            error_type=ErrorType.API_ERROR,
            root_cause="Wrong API call.",
            fix_strategy="Use the correct geometry API.",
            api_hints=["Use model.geom('geom1')."],
            confidence=0.8,
        )

        prompt = build_fix_prompt(
            original_code="model.geommm('geom1');",
            diagnosis=diagnosis,
        )
        candidate = candidate_from_text("```java\nmodel.geom('geom1');\n```", confidence=0.8)
        validation = preflight_fixed_code(candidate)

        assert "Root cause: Wrong API call." in prompt
        assert "model.geommm" in prompt
        assert candidate.code == "model.geom('geom1');"
        assert candidate.is_usable is True
        assert validation.success is True
        assert validation.requires_runtime is True

    def test_fixer_rejects_risky_candidate_and_validator_normalizes_runtime_failure(self):
        from comsol_agent.repair.detector import ErrorType
        from comsol_agent.repair.fixer import candidate_from_text
        from comsol_agent.repair.validator import (
            preflight_fixed_code,
            validate_tool_result_after_fix,
        )

        risky = candidate_from_text("Runtime.getRuntime().exec('rm -rf /')", confidence=0.9)
        preflight = preflight_fixed_code(risky)
        runtime_result = validate_tool_result_after_fix(
            tool_name="comsol_solve",
            tool_output={"success": False, "error": "Solver failed to converge"},
            original_error_type=ErrorType.SOLVER_ERROR,
        )

        assert risky.is_usable is True
        assert preflight.success is False
        assert any("process execution" in warning for warning in preflight.warnings)
        assert runtime_result.success is False
        assert runtime_result.new_error is not None
        assert runtime_result.new_error.error_type == ErrorType.SOLVER_ERROR
        assert "same error category" in runtime_result.details


class TestArchiveStore:
    """Tests for SQLite archive storage."""

    def test_archive_store_sessions_memories_and_templates(self, tmp_path):
        from comsol_agent.memory.archive_store import ArchiveStore

        store = ArchiveStore(tmp_path / "archive.sqlite3")

        session = store.upsert_session(
            "session_a",
            name="demo",
            summary="Initial summary",
        )
        memory = store.add_memory(
            "session_a",
            memory_type="compaction_summary",
            content="Loaded heat_sink and changed power to 50W.",
            token_count=42,
            embedding=[0.1, 0.2],
            metadata={"turn_range": "1-3"},
        )
        template = store.add_template(
            name="thermal_block",
            domain="thermal",
            java_code="model.geom('geom1');",
            params={"power": "50[W]"},
        )

        assert session.id == "session_a"
        assert store.get_session("session_a").summary == "Initial summary"
        assert memory.embedding == [0.1, 0.2]
        assert memory.metadata == {"turn_range": "1-3"}
        assert store.search_sessions("Initial")[0].id == "session_a"
        overview = store.get_session_overview("session_a")
        assert overview["memory_count"] == 1
        assert overview["memory_types"] == {"compaction_summary": 1}
        assert store.search_memories("heat_sink")[0].id == memory.id
        assert store.list_memories(session_id="session_a")[0].content.startswith("Loaded")
        assert template.params == {"power": "50[W]"}
        assert store.get_template("thermal_block").java_code == "model.geom('geom1');"
        assert store.list_templates(domain="thermal")[0].name == "thermal_block"
        assert store.search_templates("power", domain="thermal")[0].name == "thermal_block"

    def test_archive_store_indexes_simulation_artifacts(self, tmp_path):
        from comsol_agent.memory.archive_store import ArchiveStore

        store = ArchiveStore(tmp_path / "archive.sqlite3")
        manifest = {
            "run_id": "sweep_case_001",
            "kind": "parameter_sweep",
            "model_name": "heat_conduction_in_slab",
            "source": {"type": "example", "example_name": "thermal_slab"},
            "executed_cases": 2,
            "truncated": False,
            "json_path": str(tmp_path / "sweep.json"),
            "csv_path": str(tmp_path / "sweep.csv"),
            "manifest_path": str(tmp_path / "sweep.manifest.json"),
        }

        artifact = store.index_simulation_artifact(
            manifest,
            metadata={"csv_rows": 2},
        )

        assert artifact.run_id == "sweep_case_001"
        assert artifact.kind == "parameter_sweep"
        assert artifact.source["example_name"] == "thermal_slab"
        assert artifact.metadata == {"csv_rows": 2}
        assert store.get_simulation_artifact("sweep_case_001").model_name == "heat_conduction_in_slab"
        assert store.list_simulation_artifacts(model_name="heat_conduction_in_slab")[0].run_id == "sweep_case_001"
        assert store.search_simulation_artifacts("thermal_slab")[0].run_id == "sweep_case_001"

    def test_cleanup_missing_artifact_indexes_dry_run_and_apply(self, tmp_path):
        from comsol_agent.memory.archive_cleanup import cleanup_missing_artifact_indexes
        from comsol_agent.memory.archive_store import ArchiveStore

        archive = ArchiveStore(tmp_path / "archive.sqlite3")
        existing_json = tmp_path / "existing.json"
        existing_csv = tmp_path / "existing.csv"
        existing_manifest = tmp_path / "existing.manifest.json"
        for path in (existing_json, existing_csv, existing_manifest):
            path.write_text("{}", encoding="utf-8")

        archive.index_simulation_artifact(
            {
                "run_id": "existing_artifact",
                "kind": "parameter_sweep",
                "model_name": "loaded",
                "source": {},
                "executed_cases": 1,
                "truncated": False,
                "json_path": str(existing_json),
                "csv_path": str(existing_csv),
                "manifest_path": str(existing_manifest),
            }
        )
        archive.index_simulation_artifact(
            {
                "run_id": "missing_artifact",
                "kind": "parameter_sweep",
                "model_name": "loaded",
                "source": {},
                "executed_cases": 1,
                "truncated": False,
                "json_path": str(tmp_path / "missing.json"),
                "csv_path": str(tmp_path / "missing.csv"),
                "manifest_path": str(tmp_path / "missing.manifest.json"),
            }
        )

        dry_run = cleanup_missing_artifact_indexes(archive, limit=10)
        assert dry_run["dry_run"] is True
        assert dry_run["stale_count"] == 1
        assert dry_run["deleted_count"] == 0
        assert archive.get_simulation_artifact("missing_artifact").run_id == "missing_artifact"

        applied = cleanup_missing_artifact_indexes(archive, limit=10, apply=True)
        assert applied["deleted_run_ids"] == ["missing_artifact"]
        with pytest.raises(KeyError):
            archive.get_simulation_artifact("missing_artifact")
        assert archive.get_simulation_artifact("existing_artifact").run_id == "existing_artifact"

    def test_session_store_syncs_compaction_summary_to_archive(self, tmp_path):
        from types import SimpleNamespace

        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.memory.session_store import SessionStore

        archive = ArchiveStore(tmp_path / "archive.sqlite3")
        store = SessionStore(
            tmp_path / "sessions",
            session_id="session_archive",
            archive_store=archive,
        )
        state = SimpleNamespace(
            messages=[{"role": "user", "content": "old request"}],
            turns=[],
            repair_reports=[],
            total_tokens_used=5,
            tool_iterations_this_turn=0,
        )

        store.save(
            state=state,
            provider="openai",
            model="gpt-4o",
            metadata={
                "event": "manual_compact",
                "compaction_summary": "Older assistant/tool messages summarized.",
                "original_tokens": 1000,
                "compacted_tokens": 400,
                "compressed_message_count": 2,
            },
        )

        memories = archive.list_memories(session_id="session_archive")
        assert archive.get_session("session_archive").id == "session_archive"
        assert len(memories) == 1
        assert memories[0].type == "compaction_summary"
        assert memories[0].token_count == 400
        assert memories[0].metadata["compressed_message_count"] == 2

    def test_archive_export_bundle_writes_json(self, tmp_path):
        import json
        from types import SimpleNamespace

        from comsol_agent.memory.archive_export import export_archive_bundle
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.memory.session_store import SessionStore
        from comsol_agent.simulation.artifacts import persist_sweep_result

        archive_path = tmp_path / "archive.sqlite3"
        session_dir = tmp_path / "sessions"
        archive = ArchiveStore(archive_path)
        session_store = SessionStore(
            session_dir,
            session_id="session_export",
            archive_store=archive,
        )
        session_store.save(
            state=SimpleNamespace(
                messages=[
                    {"role": "user", "content": "export me"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_export",
                                "type": "function",
                                "function": {
                                    "name": "simulation_run_parameter_sweep",
                                    "arguments": '{"parameters": {"L": ["1[mm]"]}}',
                                },
                            }
                        ],
                    },
                ],
                turns=[],
                repair_reports=[],
                total_tokens_used=7,
                tool_iterations_this_turn=1,
            ),
            provider="deepseek",
            model="deepseek-v4-flash",
            metadata={"summary": "Export bundle session"},
        )
        archive.add_memory(
            "session_export",
            memory_type="compaction_summary",
            content="Exported session memory.",
        )
        archive.add_template(
            name="export_template",
            domain="thermal",
            java_code="model.geom('geom1');",
        )
        persist_sweep_result(
            {
                "success": True,
                "model_name": "loaded",
                "source": {"type": "loaded_model", "model_name": "loaded"},
                "plan": {"estimated_runs": 1},
                "executed_cases": 1,
                "truncated": False,
                "cases": [],
                "close": None,
                "tool_sequence": [],
            },
            output_dir=tmp_path / "artifacts",
            run_name="export_artifact",
            archive_path=archive_path,
        )

        result = export_archive_bundle(
            archive,
            output_path=tmp_path / "exports" / "archive.json",
            session_dir=session_dir,
            include_timelines=True,
        )
        payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

        assert result["success"] is True
        assert result["counts"] == {
            "sessions": 1,
            "memories": 1,
            "templates": 1,
            "simulation_artifacts": 1,
        }
        assert payload["sessions"][0]["timeline_summary"]["event_count"] >= 2
        assert payload["memories"][0]["content"] == "Exported session memory."
        assert payload["templates"][0]["name"] == "export_template"
        assert payload["simulation_artifacts"][0]["run_id"].startswith("export_artifact")

    def test_retrieval_builds_memory_context_message(self, tmp_path):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.memory.retrieval import (
            build_memory_context_message,
            retrieve_memories,
        )

        archive = ArchiveStore(tmp_path / "archive.sqlite3")
        archive.add_memory(
            "session_retrieve",
            memory_type="compaction_summary",
            content="Aluminum plate heat model used power=50W.",
        )

        memories = retrieve_memories(archive, "Aluminum plate", limit=5)
        message = build_memory_context_message(memories)

        assert len(memories) == 1
        assert message is not None
        assert message["role"] == "user"
        assert "[Retrieved from memory]" in message["content"]
        assert "power=50W" in message["content"]

    @pytest.mark.asyncio
    async def test_agent_loop_injects_retrieved_memory(self, tmp_path):
        from collections.abc import AsyncIterator
        from typing import Any

        from comsol_agent.agent.loop import AgentLoop
        from comsol_agent.cli.config import Config
        from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolDefinition
        from comsol_agent.memory.archive_store import ArchiveStore

        archive = ArchiveStore(tmp_path / "archive.sqlite3")
        archive.add_memory(
            "session_memory",
            memory_type="compaction_summary",
            content="heat_sink model previously used power=50W.",
        )

        class MemoryAwareProvider(LLMProvider):
            async def generate(
                self,
                messages: list[dict[str, Any]],
                tools: list[ToolDefinition] | None = None,
                **kwargs: Any,
            ) -> LLMResponse:
                assert any(
                    "[Retrieved from memory]" in str(message.get("content", ""))
                    for message in messages
                )
                return LLMResponse(text="Used retrieved memory.")

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

        agent = AgentLoop(MemoryAwareProvider(model="fake"), Config(), archive_store=archive)
        response = await agent.run("What about heat_sink?")

        assert response == "Used retrieved memory."
        assert any(
            "[Retrieved from memory]" in str(message.get("content", ""))
            for message in agent.state.messages
        )

    @pytest.mark.asyncio
    async def test_memory_command_runs_with_archive_store(self, tmp_path):
        from types import SimpleNamespace

        from comsol_agent.cli.commands import CommandResult, handle_command
        from comsol_agent.cli.config import Config
        from comsol_agent.memory.archive_store import ArchiveStore

        archive = ArchiveStore(tmp_path / "archive.sqlite3")
        archive.add_memory(
            "session_cli_memory",
            memory_type="compaction_summary",
            content="CLI memory command content.",
        )
        agent = SimpleNamespace(archive_store=archive)

        result = await handle_command("/memory CLI", agent, Config())

        assert result == CommandResult.CONTINUE

    @pytest.mark.asyncio
    async def test_sessions_command_runs_with_archive_store(self, tmp_path):
        from types import SimpleNamespace

        from comsol_agent.cli.commands import CommandResult, handle_command
        from comsol_agent.cli.config import Config
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.memory.session_store import SessionStore

        archive = ArchiveStore(tmp_path / "archive.sqlite3")
        session_store = SessionStore(
            tmp_path / "sessions",
            session_id="session_cli_history",
            archive_store=archive,
        )
        state = SimpleNamespace(
            messages=[
                {"role": "system", "content": "system"},
                {"role": "user", "content": "Run a thermal sweep"},
                {
                    "role": "assistant",
                    "content": "I will run the sweep.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "simulation_run_parameter_sweep",
                                "arguments": '{"example_name": "thermal_slab", "parameters": {"L": ["1[mm]"]}}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "name": "simulation_run_parameter_sweep",
                    "content": '{"success": true, "run_id": "timeline_sweep"}',
                },
                {"role": "assistant", "content": "Sweep completed"},
            ],
            turns=[],
            repair_reports=[
                {
                    "error_type": "SOLVER_ERROR",
                    "tool_name": "comsol_solve",
                    "message": "Recovered by reducing cases.",
                    "repair_plan": {"risk_level": "medium", "action": "retry_smaller_sweep"},
                }
            ],
            total_tokens_used=12,
            tool_iterations_this_turn=0,
        )
        session_store.save(
            state=state,
            provider="deepseek",
            model="deepseek-v4-flash",
            metadata={
                "summary": "Thermal sweep session",
                "session_name": "thermal-history",
            },
        )
        archive.add_memory(
            "session_cli_history",
            memory_type="compaction_summary",
            content="Thermal sweep completed with archived result.",
        )
        agent = SimpleNamespace(archive_store=archive, session_store=session_store)

        assert await handle_command("/sessions", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command("/sessions search Thermal", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command("/sessions show session_cli_history 10", agent, Config()) == CommandResult.CONTINUE

    @pytest.mark.asyncio
    async def test_archive_command_exports_bundle(self, tmp_path):
        from types import SimpleNamespace

        from comsol_agent.cli.commands import CommandResult, handle_command
        from comsol_agent.cli.config import Config
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.memory.session_store import SessionStore

        archive = ArchiveStore(tmp_path / "archive.sqlite3")
        session_store = SessionStore(
            tmp_path / "sessions",
            session_id="session_archive_command",
            archive_store=archive,
        )
        session_store.save(
            state=SimpleNamespace(
                messages=[{"role": "user", "content": "archive command"}],
                turns=[],
                repair_reports=[],
                total_tokens_used=1,
                tool_iterations_this_turn=0,
            ),
            provider="deepseek",
            model="deepseek-v4-flash",
            metadata={"summary": "Archive command session"},
        )
        archive.index_simulation_artifact(
            {
                "run_id": "stale_cli_artifact",
                "kind": "parameter_sweep",
                "model_name": "loaded",
                "source": {},
                "executed_cases": 1,
                "truncated": False,
                "json_path": str(tmp_path / "missing.json"),
                "csv_path": str(tmp_path / "missing.csv"),
                "manifest_path": str(tmp_path / "missing.manifest.json"),
            }
        )
        agent = SimpleNamespace(archive_store=archive, session_store=session_store)
        output_path = tmp_path / "archive_export.json"

        assert await handle_command("/archive", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command(
            f"/archive export {output_path} 10 timelines",
            agent,
            Config(),
        ) == CommandResult.CONTINUE
        assert output_path.exists()
        assert await handle_command("/archive cleanup 10", agent, Config()) == CommandResult.CONTINUE
        assert archive.get_simulation_artifact("stale_cli_artifact").run_id == "stale_cli_artifact"
        assert await handle_command("/archive cleanup 10 apply", agent, Config()) == CommandResult.CONTINUE
        with pytest.raises(KeyError):
            archive.get_simulation_artifact("stale_cli_artifact")

    def test_list_sessions_script_outputs_json(self, tmp_path):
        import json
        import subprocess
        import sys
        from types import SimpleNamespace

        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.memory.session_store import SessionStore

        archive_path = tmp_path / "archive.sqlite3"
        session_dir = tmp_path / "sessions"
        archive = ArchiveStore(archive_path)
        session_store = SessionStore(
            session_dir,
            session_id="session_script_history",
            archive_store=archive,
        )
        session_store.save(
            state=SimpleNamespace(
                messages=[
                    {"role": "user", "content": "script session"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_script",
                                "type": "function",
                                "function": {
                                    "name": "simulation_export_artifact_report",
                                    "arguments": '{"query": "script"}',
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call_script",
                        "name": "simulation_export_artifact_report",
                        "content": '{"success": true, "report_id": "script_report"}',
                    },
                ],
                turns=[],
                repair_reports=[
                    {
                        "error_type": "API_ERROR",
                        "tool_name": "simulation_export_artifact_report",
                        "message": "Recovered with archived data.",
                        "repair_plan": {"risk_level": "low", "action": "use_archive"},
                    }
                ],
                total_tokens_used=3,
                tool_iterations_this_turn=0,
            ),
            provider="deepseek",
            model="deepseek-v4-flash",
            metadata={"summary": "Script-visible session"},
        )

        listed = subprocess.run(
            [
                sys.executable,
                "scripts/list_sessions.py",
                "--archive-path",
                str(archive_path),
                "--session-dir",
                str(session_dir),
                "--query",
                "Script-visible",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        shown = subprocess.run(
            [
                sys.executable,
                "scripts/list_sessions.py",
                "--archive-path",
                str(archive_path),
                "--session-dir",
                str(session_dir),
                "--show",
                "session_script_history",
                "--max-events",
                "10",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        list_payload = json.loads(listed.stdout)
        show_payload = json.loads(shown.stdout)
        assert list_payload["sessions"][0]["id"] == "session_script_history"
        assert show_payload["snapshot"]["stats"]["total_tokens_used"] == 3
        assert show_payload["timeline_summary"]["event_count"] >= 4
        assert {event["type"] for event in show_payload["timeline"]} >= {
            "user",
            "tool_call",
            "tool_result",
            "repair_report",
        }

    def test_export_archive_script_outputs_json(self, tmp_path):
        import json
        import subprocess
        import sys
        from types import SimpleNamespace

        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.memory.session_store import SessionStore

        archive_path = tmp_path / "archive.sqlite3"
        session_dir = tmp_path / "sessions"
        archive = ArchiveStore(archive_path)
        session_store = SessionStore(
            session_dir,
            session_id="session_export_script",
            archive_store=archive,
        )
        session_store.save(
            state=SimpleNamespace(
                messages=[{"role": "user", "content": "export script"}],
                turns=[],
                repair_reports=[],
                total_tokens_used=2,
                tool_iterations_this_turn=0,
            ),
            provider="deepseek",
            model="deepseek-v4-flash",
            metadata={"summary": "Export script session"},
        )
        output_path = tmp_path / "export.json"

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/export_archive.py",
                "--archive-path",
                str(archive_path),
                "--session-dir",
                str(session_dir),
                "--output",
                str(output_path),
                "--include-timelines",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        result = json.loads(completed.stdout)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert result["success"] is True
        assert result["counts"]["sessions"] == 1
        assert payload["sessions"][0]["id"] == "session_export_script"

    def test_cleanup_archive_script_dry_run_and_apply(self, tmp_path):
        import json
        import subprocess
        import sys

        from comsol_agent.memory.archive_store import ArchiveStore

        archive_path = tmp_path / "archive.sqlite3"
        archive = ArchiveStore(archive_path)
        archive.index_simulation_artifact(
            {
                "run_id": "stale_script_artifact",
                "kind": "parameter_sweep",
                "model_name": "loaded",
                "source": {},
                "executed_cases": 1,
                "truncated": False,
                "json_path": str(tmp_path / "missing.json"),
                "csv_path": str(tmp_path / "missing.csv"),
                "manifest_path": str(tmp_path / "missing.manifest.json"),
            }
        )

        dry_run = subprocess.run(
            [
                sys.executable,
                "scripts/cleanup_archive.py",
                "--archive-path",
                str(archive_path),
                "--limit",
                "10",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        applied = subprocess.run(
            [
                sys.executable,
                "scripts/cleanup_archive.py",
                "--archive-path",
                str(archive_path),
                "--limit",
                "10",
                "--apply",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        dry_payload = json.loads(dry_run.stdout)
        applied_payload = json.loads(applied.stdout)
        assert dry_payload["dry_run"] is True
        assert dry_payload["stale_count"] == 1
        assert applied_payload["deleted_run_ids"] == ["stale_script_artifact"]
        with pytest.raises(KeyError):
            archive.get_simulation_artifact("stale_script_artifact")

    @pytest.mark.asyncio
    async def test_artifacts_command_runs_with_archive_store(self, tmp_path):
        from types import SimpleNamespace

        from comsol_agent.cli.commands import CommandResult, handle_command
        from comsol_agent.cli.config import Config
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.simulation.artifacts import persist_sweep_result

        archive = ArchiveStore(tmp_path / "archive.sqlite3")
        artifact = persist_sweep_result(
            {
                "success": True,
                "model_name": "loaded",
                "source": {"type": "loaded_model", "model_name": "loaded"},
                "plan": {
                    "axes": [{"parameter": "L", "values": ["1[mm]"]}],
                    "output_expressions": ["T"],
                },
                "executed_cases": 1,
                "truncated": False,
                "cases": [
                    {
                        "success": True,
                        "case_index": 1,
                        "label": "L=1[mm]",
                        "parameters": {"L": "1[mm]"},
                        "solve": {"elapsed_seconds": 0.1, "status": "ok"},
                        "evaluations": [
                            {
                                "success": True,
                                "expression": "T",
                                "statistics": {"min": 0.0, "max": 1.0, "mean": 0.5},
                            }
                        ],
                    }
                ],
                "close": None,
                "tool_sequence": [],
            },
            output_dir=tmp_path / "artifacts",
            run_name="cli_artifact",
            archive_path=tmp_path / "archive.sqlite3",
        )
        agent = SimpleNamespace(archive_store=archive)

        assert await handle_command("/artifacts", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command("/artifacts search cli_artifact", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command(f"/artifacts show {artifact['run_id']} 5", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command("/artifacts compare cli_artifact mean T max", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command("/artifacts report cli_artifact mean T max", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command("/artifacts report cli_artifact mean T max html", agent, Config()) == CommandResult.CONTINUE

    @pytest.mark.asyncio
    async def test_repairs_command_renders_reports(self):
        from types import SimpleNamespace

        from comsol_agent.cli.commands import CommandResult, handle_command
        from comsol_agent.cli.config import Config

        agent = SimpleNamespace(
            state=SimpleNamespace(
                repair_reports=[
                    {
                        "error_type": "SOLVER_ERROR",
                        "tool_name": "comsol_solve",
                        "message": "Failed to converge",
                        "diagnosis": {
                            "root_cause": "Numerical problem failed.",
                            "fix_strategy": "Inspect model setup before retrying.",
                        },
                        "repair_plan": {
                            "action": "diagnose_solver_before_retry",
                            "risk_level": "high",
                            "can_auto_retry": False,
                            "requires_user_confirmation": False,
                            "suggested_tools": ["comsol_get_model_summary"],
                        },
                    }
                ]
            )
        )

        assert await handle_command("/repairs", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command("/repairs show 1", agent, Config()) == CommandResult.CONTINUE

    @pytest.mark.asyncio
    async def test_doctor_command_runs(self):
        from types import SimpleNamespace

        from comsol_agent.cli.commands import CommandResult, handle_command
        from comsol_agent.cli.config import Config

        result = await handle_command(
            "/doctor",
            SimpleNamespace(state=SimpleNamespace(repair_reports=[]), archive_store=None),
            Config(),
        )

        assert result == CommandResult.CONTINUE

    @pytest.mark.asyncio
    async def test_doctor_command_runs_deep_llm_branch(self, monkeypatch):
        from types import SimpleNamespace

        import comsol_agent.diagnostics as diagnostics
        from comsol_agent.cli.commands import CommandResult, handle_command
        from comsol_agent.cli.config import Config

        captured = {}

        async def fake_deep_doctor(config, **kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "status": "ok",
                "python": "python",
                "deep": True,
                "checks": [
                    {
                        "name": "llm_api",
                        "status": "ok",
                        "message": "fake ok",
                        "details": {},
                    }
                ],
            }

        monkeypatch.setattr(diagnostics, "run_deep_doctor", fake_deep_doctor)

        result = await handle_command(
            "/doctor --llm-only --timeout 5",
            SimpleNamespace(state=SimpleNamespace(repair_reports=[]), archive_store=None),
            Config(),
        )

        assert result == CommandResult.CONTINUE
        assert captured["check_llm"] is True
        assert captured["check_comsol"] is False
        assert captured["timeout_seconds"] == 5.0


class TestSimulationSkills:
    """Tests for built-in simulation skills and templates."""

    def test_skill_matching_and_context_message(self):
        from comsol_agent.simulation.skills import build_skill_context_message, match_skills

        skills = match_skills("Set up a heat transfer model with temperature output")
        message = build_skill_context_message(skills)

        assert skills
        assert skills[0].name == "thermal"
        assert message is not None
        assert "[Simulation skill: thermal]" in message["content"]
        assert "Heat Transfer" in message["content"]

    def test_skill_matching_uses_keyword_boundaries(self):
        from comsol_agent.simulation.skills import match_skills

        assert [skill.name for skill in match_skills("runtime_smoke/fullflow_demo")] == []
        assert [skill.name for skill in match_skills("laminar flow in a channel")] == ["fluid"]

    def test_bearing_contact_skill_matching_ranks_specific_skill_first(self):
        from comsol_agent.simulation.skills import build_skill_context_message, match_skills

        skills = match_skills("Build a ball bearing Hertz contact stress model")
        message = build_skill_context_message(skills)

        assert skills
        assert skills[0].name == "bearing_contact"
        assert message is not None
        assert "bearing_contact_hertz_seed" in message["content"]
        assert "2D plane-strain single-ball/raceway contact cell" in message["content"]

    def test_seed_builtin_templates(self, tmp_path):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.simulation.skills import seed_builtin_templates

        archive = ArchiveStore(tmp_path / "archive.sqlite3")
        templates = seed_builtin_templates(archive)

        assert len(templates) >= 5
        assert archive.get_template("thermal_heat_transfer_seed").domain == "thermal"
        assert archive.list_templates(domain="fluid")[0].name == "fluid_flow_seed"
        bearing_template = archive.get_template("bearing_contact_hertz_seed")
        assert bearing_template.domain == "structural"
        assert bearing_template.params["radial_load"] == "1000[N]"
        assert "SolidMechanics" in bearing_template.java_code
        pair_template = archive.get_template("bearing_contact_pair_seed")
        assert pair_template.domain == "structural"
        assert pair_template.params["contact_interference"] == "2[um]"
        assert "pair().create('cp_ball_race', 'Contact')" in pair_template.java_code

    def test_bearing_contact_template_validates_offline(self, tmp_path):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.simulation.skills import seed_builtin_templates
        from comsol_agent.tools.simulation import simulation_run_template, simulation_validate_template

        archive_path = tmp_path / "archive.sqlite3"
        seed_builtin_templates(ArchiveStore(archive_path))

        empty_result = simulation_validate_template()
        assert empty_result["success"] is False
        assert empty_result["error_type"] == "TOOL_INPUT_ERROR"
        assert empty_result["retryable"] is False
        assert "java_code" in empty_result["repair_hint"]
        run_empty_result = simulation_run_template(create_model_name="bad_empty_code")
        assert run_empty_result["success"] is False
        assert run_empty_result["error_type"] == "TOOL_INPUT_ERROR"
        assert run_empty_result["retryable"] is False

        result = simulation_validate_template(
            name="bearing_contact_hertz_seed",
            archive_path=str(archive_path),
        )

        assert result["success"] is True
        assert result["validation"]["errors"] == []
        assert "radial_load" in result["validation"]["params_checked"]

        pair_result = simulation_validate_template(
            name="bearing_contact_pair_seed",
            archive_path=str(archive_path),
        )

        assert pair_result["success"] is True
        assert pair_result["validation"]["errors"] == []
        assert "contact_interference" in pair_result["validation"]["params_checked"]

    def test_bearing_contact_planner_asks_for_required_missing_params(self):
        from comsol_agent.tools.simulation import simulation_plan_bearing_contact

        result = simulation_plan_bearing_contact(
            user_request="建立一个轴承接触仿真，要求尽量真实",
            provided_params={"radial_load": "1500[N]"},
        )
        plan = result["plan"]

        assert result["success"] is True
        assert plan["ready_to_run"] is False
        assert plan["mode"] == "clarify_before_run"
        assert "inner_diameter" in plan["missing_required"]
        assert "radial_load" not in plan["missing_required"]
        assert any("内径" in question for question in plan["follow_up_questions"])

    def test_bearing_contact_planner_allows_quick_default_demo(self):
        from comsol_agent.tools.simulation import simulation_plan_bearing_contact

        result = simulation_plan_bearing_contact(
            user_request="先用默认案例跑通一个轴承接触 stress demo",
            provided_params={"load": "1200[N]", "width": "16[mm]"},
            allow_defaults=True,
        )
        plan = result["plan"]

        assert result["success"] is True
        assert plan["ready_to_run"] is True
        assert plan["mode"] == "quick_default_demo"
        assert plan["template_name"] == "bearing_contact_hertz_seed"
        assert plan["resolved_params"]["radial_load"] == "1200[N]"
        assert plan["resolved_params"]["bearing_width"] == "16[mm]"
        assert "solid.mises" in plan["recommended_outputs"]

    def test_bearing_contact_planner_selects_pair_template_for_realistic_contact(self):
        from comsol_agent.tools.simulation import simulation_plan_bearing_contact

        result = simulation_plan_bearing_contact(
            user_request="用默认参数先跑通一个更真实的轴承接触对仿真",
            provided_params={},
            allow_defaults=True,
        )
        plan = result["plan"]

        assert result["success"] is True
        assert plan["ready_to_run"] is True
        assert plan["template_name"] == "bearing_contact_pair_seed"
        assert any("contact-pair" in note for note in plan["notes"])

    def test_multiroller_bearing_planner_requires_real_contact_scope(self):
        from comsol_agent.tools.simulation import simulation_plan_multiroller_bearing

        result = simulation_plan_multiroller_bearing(
            user_request="建立一个多子滚轴轴承真实接触仿真",
            provided_params={"radial_load": "3500[N]"},
        )
        plan = result["plan"]

        assert result["success"] is True
        assert plan["ready_to_run"] is False
        assert "inner_diameter" in plan["missing_required"]
        assert any("滚子" in question for question in plan["follow_up_questions"])
        assert any("Contact Pair" in item or "Contact" in item for item in plan["contact_requirements"])
        assert "generated_code_multiroller_contact" == plan["workflow"]

    def test_multiroller_bearing_planner_defaults_still_require_bearing_contact(self):
        from comsol_agent.tools.simulation import simulation_plan_multiroller_bearing

        result = simulation_plan_multiroller_bearing(
            user_request="先用默认参数跑通圆柱滚子轴承真实接触 demo",
            provided_params={"rollers": "4", "cage": "false"},
            allow_defaults=True,
        )
        plan = result["plan"]

        assert result["success"] is True
        assert plan["ready_to_run"] is True
        assert plan["resolved_params"]["roller_count"] == "4"
        assert plan["resolved_params"]["cage_included"] == "false"
        assert any("inner ring" in item for item in plan["contact_requirements"])
        assert any("generated-code fallback" in note for note in plan["notes"])

    def test_bearing_contact_package_exports_report_and_archive(self, tmp_path, monkeypatch):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.tools import simulation as simulation_tools

        archive_path = tmp_path / "archive.sqlite3"
        plot_path = tmp_path / "stress.png"
        plot_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        monkeypatch.setattr(
            simulation_tools,
            "comsol_save_model",
            lambda model_name, filepath: {
                "success": True,
                "model_name": model_name,
                "saved_to": filepath,
            },
        )

        def fake_evaluate(model_name, expression):
            if expression == "solid.mises":
                return {
                    "success": True,
                    "model_name": model_name,
                    "expression": expression,
                    "statistics": {"min": 1.0, "max": 250.0, "mean": 25.0},
                }
            return {
                "success": True,
                "model_name": model_name,
                "expression": expression,
                "statistics": {"min": 1.8, "max": 1.8, "mean": 1.8},
            }

        monkeypatch.setattr(simulation_tools, "comsol_evaluate", fake_evaluate)

        result = simulation_tools.simulation_export_bearing_contact_package(
            model_name="bearing_model",
            template_run_id="template_run_1",
            plot_path=str(plot_path),
            output_dir=str(tmp_path / "packages"),
            package_name="bearing_contact_package",
            archive_path=str(archive_path),
        )

        assert result["success"] is True
        assert result["metrics"]["von_mises_max"] == 250.0
        assert Path(result["json_path"]).exists()
        assert Path(result["markdown_path"]).read_text(encoding="utf-8").startswith("# Bearing Contact")
        assert result["model_path"].endswith("bearing_model.mph")
        archived = ArchiveStore(archive_path).get_simulation_artifact(result["run_id"])
        assert archived.kind == "bearing_contact_package"
        assert archived.metadata["plot_path"] == str(plot_path.resolve())
        read_back = simulation_tools.simulation_read_artifact(
            result["run_id"],
            archive_path=str(archive_path),
        )
        assert read_back["success"] is True
        assert read_back["preview"]["summary"]["metrics"]["von_mises_max"] == 250.0
        assert read_back["preview"]["summary"]["result_interpretation"]["highest_risk_region"]

        answer = simulation_tools.simulation_answer_artifact_question(
            "最大应力是多少，位置在哪里？",
            run_id=result["run_id"],
            archive_path=str(archive_path),
        )
        assert answer["success"] is True
        assert "250.0" in answer["answer"]
        assert "位置" in answer["answer"]

    def test_bearing_contact_package_accepts_contact_pressure_est_fallback(self, tmp_path, monkeypatch):
        from comsol_agent.tools import simulation as simulation_tools

        archive_path = tmp_path / "archive.sqlite3"
        plot_path = tmp_path / "stress.png"
        plot_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        monkeypatch.setattr(
            simulation_tools,
            "comsol_save_model",
            lambda model_name, filepath: {
                "success": True,
                "model_name": model_name,
                "saved_to": filepath,
            },
        )

        def fake_evaluate(model_name, expression):
            if expression == "solid.mises":
                return {
                    "success": True,
                    "model_name": model_name,
                    "expression": expression,
                    "statistics": {"min": 1.0, "max": 325.0, "mean": 25.0},
                }
            if expression == "contact_pressure_guess":
                return {"success": False, "expression": expression, "error": "undefined"}
            return {
                "success": True,
                "model_name": model_name,
                "expression": expression,
                "statistics": {"min": 10.0, "max": 10.0, "mean": 10.0},
            }

        monkeypatch.setattr(simulation_tools, "comsol_evaluate", fake_evaluate)

        result = simulation_tools.simulation_export_bearing_contact_package(
            model_name="multiroller_model",
            plot_path=str(plot_path),
            output_dir=str(tmp_path / "packages"),
            package_name="multiroller_package",
            archive_path=str(archive_path),
        )

        assert result["success"] is True
        assert result["metrics"]["contact_pressure_guess"] == 10.0
        assert result["metrics"]["contact_pressure_expression"] == "contact_pressure_est"

    def test_bearing_contact_demo_prompt_fixture(self):
        from scripts.run_agent_bearing_contact_demo import build_bearing_contact_prompts

        prompts = build_bearing_contact_prompts(
            archive_path="runtime_smoke/bearing_contact_demo.sqlite3",
            artifact_root="runtime_smoke/bearing_contact_demo",
            report_dir="runtime_smoke/bearing_contact_demo/reports",
            template_name="bearing_contact_hertz_seed",
            model_name="agent_bearing_contact_model",
        )

        assert prompts[0].name == "bearing_contact_default_run"
        assert "quick default demo" in prompts[0].prompt
        assert "simulation_plan_bearing_contact" in prompts[0].required_tools
        assert "allow_defaults=true" in prompts[0].prompt
        assert "simulation_export_bearing_contact_package" in prompts[0].required_tools
        assert "simulation_read_template" in prompts[0].required_tools
        assert "comsol_solve" in prompts[0].required_tools
        assert "comsol_plot" in prompts[0].successful_tools
        assert "close_model=false" in prompts[0].prompt
        assert "solid.mises" in prompts[0].prompt
        assert "Do not call file tools" in prompts[0].prompt
        assert "comsol_execute_java" in prompts[0].prompt
        assert "bearing_contact_hertz_seed" in prompts[0].prompt
        assert prompts[1].name == "bearing_contact_artifact_report"

    def test_multiroller_bearing_demo_prompt_fixture_and_quality_gate(self):
        from scripts.run_agent_multiroller_bearing_demo import (
            build_multiroller_code_generation_prompt,
            build_multiroller_execution_prompt,
            validate_multiroller_code_draft,
        )

        draft = build_multiroller_code_generation_prompt(
            archive_path="runtime_smoke/multiroller_bearing_demo.sqlite3",
        )
        execute = build_multiroller_execution_prompt(
            java_code="<generated_code>",
            archive_path="runtime_smoke/multiroller_bearing_demo.sqlite3",
            artifact_dir="runtime_smoke/multiroller_bearing_demo/template_runs",
            plot_path="runtime_smoke/multiroller_bearing_demo/multiroller_von_mises.png",
            model_name="agent_multiroller_bearing_model",
            template_name="agent_multiroller_bearing_generated_seed",
            package_dir="runtime_smoke/multiroller_bearing_demo/result_packages",
        )

        assert draft.name == "multiroller_code_draft"
        assert "simulation_plan_multiroller_bearing" in draft.required_tools
        assert "plate, beam, or block" in draft.prompt
        assert "Contact Pair/Contact" in draft.prompt
        assert "unfolded bearing contact cell" in draft.prompt
        assert "Do not create annular rings with Difference/Union" in draft.prompt
        assert execute.name == "multiroller_execute_package_answer"
        assert "simulation_answer_artifact_question" in execute.required_tools
        assert "Do not replace it with a plate/block" in execute.prompt
        assert "do not call COMSOL introspection/probing APIs" in execute.prompt
        assert "VERIFIED_FALLBACK_CODE" in execute.prompt
        assert "cp_r1_outer" in execute.prompt
        assert "cp_r2_outer" in execute.prompt

        good_code = """
        model.param().set('inner_diameter', '40[mm]');
        model.param().set('outer_diameter', '80[mm]');
        model.component().create('comp1', true);
        model.component('comp1').geom().create('geom1', 2);
        model.component('comp1').geom('geom1').create('inner_raceway', 'Circle');
        model.component('comp1').geom('geom1').create('outer_raceway', 'Circle');
        model.component('comp1').geom('geom1').create('roller_1', 'Circle');
        model.component('comp1').geom('geom1').create('roller_2', 'Circle');
        model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
        model.component('comp1').pair().create('cp_roller_outer', 'Contact');
        model.component('comp1').pair().create('cp_roller_inner', 'Contact');
        model.component('comp1').mesh().create('mesh1');
        model.study().create('std1');
        model.study('std1').create('stat', 'Stationary');
        model.result().create('pg_stress', 'PlotGroup2D');
        model.result('pg_stress').feature().create('surf_stress', 'Surface');
        model.result('pg_stress').feature('surf_stress').set('expr', 'solid.mises');
        output.write('cage omitted for first demo');
        """
        bad_code = "model.component().create('comp1', true); // rectangular structural plate"
        bad_introspection = good_code + "\nmodel.component('comp1').geom('geom1').getBoundaries();"
        bad_difference = """
        model.param().set('roller_diameter', '8[mm]');
        model.component().create('comp1', true);
        model.component('comp1').geom().create('geom1', 2);
        model.component('comp1').geom('geom1').create('inner_ring', 'Difference');
        model.component('comp1').geom('geom1').create('roller1', 'Circle');
        model.component('comp1').geom('geom1').create('roller2', 'Circle');
        model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
        model.component('comp1').pair().create('cp_roller_outer', 'Contact');
        model.component('comp1').mesh().create('mesh1');
        model.study().create('std1');
        model.study('std1').create('stat', 'Stationary');
        model.result().create('pg_stress', 'PlotGroup2D');
        model.result('pg_stress').feature().create('surf_stress', 'Surface');
        model.result('pg_stress').feature('surf_stress').set('expr', 'solid.mises');
        output.write('cage omitted');
        """

        assert validate_multiroller_code_draft(good_code)["success"] is True
        assert validate_multiroller_code_draft(bad_code)["success"] is False
        assert validate_multiroller_code_draft(bad_introspection)["success"] is False
        assert validate_multiroller_code_draft(bad_difference)["success"] is False

    def test_3d_full_bearing_demo_prompt_fixture_and_quality_gate(self):
        from comsol_agent.simulation.bearing_3d import (
            SEGMENTED_3D_CODE_SPECS,
            SEGMENT_MARKER_MANIFEST_END,
            SEGMENT_MARKER_MANIFEST_START,
            VERIFIED_ROLLER_COUNT,
            assemble_segmented_3d_code,
            audit_3d_physical_results,
            audit_3d_selection_binding,
            build_3d_execution_context,
            build_contact_convergence_report,
            build_selection_binding_probe_code,
            build_segmented_3d_generation_prompt,
            extract_generated_code,
            extract_segment_manifest,
            normalize_generated_mph_code,
            parse_selection_binding_probe_output,
            selection_binding_contract,
            validate_3d_bearing_code_draft,
            validate_segmented_3d_segment,
        )
        from scripts.run_agent_3d_bearing_full_demo import (
            VERIFIED_3D_FULL_BEARING_CODE,
            __file__ as demo_script_file,
            SEGMENTED_3D_CODE_SPECS as SCRIPT_SEGMENTED_3D_CODE_SPECS,
            build_3d_bearing_code_generation_prompt,
            build_3d_bearing_execution_prompt,
            apply_bounded_3d_generated_code_repairs,
            apply_runtime_preflight_3d_repairs,
        )

        assert SCRIPT_SEGMENTED_3D_CODE_SPECS is SEGMENTED_3D_CODE_SPECS
        demo_source = Path(demo_script_file).read_text(encoding="utf-8")
        assert "def build_segmented_3d_generation_prompt(" not in demo_source
        assert "class Segmented3DCodeSpec" not in demo_source
        assert "def validate_3d_bearing_code_draft(" not in demo_source
        assert "def _build_3d_execution_context(" not in demo_source

        execution_context = build_3d_execution_context(
            workflow="bearing_3d_generated_code_agent_execution",
            draft_quality={"success": True, "quality_level": "production_candidate"},
            repair_history=[{"stage": "offline_quality_gate", "success": True}],
            require_free_generated_code=True,
            allow_verified_fallback=False,
            draft_summary={"name": "draft", "success": True, "response": "x" * 500},
            selection_binding_audit={"success": True, "runtime_checked": True},
            physical_result_audit={"success": True, "production_ready": True},
            contact_convergence_report={"success": True, "runtime_verified": True},
        )
        assert execution_context["workflow"] == "bearing_3d_generated_code_agent_execution"
        assert execution_context["draft_summary"]["response_excerpt"] == "x" * 400
        assert execution_context["selection_binding_audit"]["runtime_checked"] is True
        assert execution_context["physical_result_audit"]["production_ready"] is True
        assert execution_context["contact_convergence_report"]["runtime_verified"] is True

        draft = build_3d_bearing_code_generation_prompt(
            archive_path="runtime_smoke/bearing_3d_full_demo.sqlite3",
        )
        execute = build_3d_bearing_execution_prompt(
            java_code="<generated_code>",
            archive_path="runtime_smoke/bearing_3d_full_demo.sqlite3",
            artifact_dir="runtime_smoke/bearing_3d_full_demo/template_runs",
            plot_path="runtime_smoke/bearing_3d_full_demo/bearing_3d_von_mises.png",
            model_name="agent_3d_bearing_model",
            template_name="agent_3d_bearing_generated_seed",
            package_dir="runtime_smoke/bearing_3d_full_demo/result_packages",
        )

        assert draft.name == "bearing_3d_code_draft"
        assert "simulation_plan_multiroller_bearing" in draft.required_tools
        assert "complete 3D cylindrical-roller bearing" in draft.prompt
        assert "explicit cage ring with Boolean roller pockets" in draft.prompt
        assert "Do not replace it with a plate, block, beam, 2D" in draft.prompt
        assert "Do not call simulation_validate_template" in draft.prompt
        assert "file_read, file_write, or any file tools" in draft.prompt
        assert "PlotGroup3D" in draft.prompt
        assert "Do not use CylinderSelection" in draft.prompt
        assert "physics-level ContactPair" in draft.prompt
        assert "Difference object/objects setters" in draft.prompt
        assert "do not call output.write or model.output().write" in draft.prompt
        assert "model.component('comp1').pair().create" in draft.prompt
        assert "pair.set('source')" in draft.prompt
        assert "source().named" in draft.prompt
        assert "top-level model.study()/model.result()" in draft.prompt
        assert execute.name == "bearing_3d_execute_package_answer"
        assert "Every repair attempt must keep the model 3D" in execute.prompt
        assert "simulation_probe_3d_selection_binding" in execute.prompt
        assert "simulation_probe_3d_selection_binding" in execute.required_tools
        assert "VERIFIED_3D_FALLBACK_CODE" in execute.prompt
        assert "cage_pocket_12" in execute.prompt
        assert ".manualSelection(True)" in VERIFIED_3D_FULL_BEARING_CODE
        assert ".set('pfm', 'penalty')" in VERIFIED_3D_FULL_BEARING_CODE
        assert "selection().create('sel_inner_raceway_12_contact', 'Intersection')" in VERIFIED_3D_FULL_BEARING_CODE
        assert "selection('sel_inner_raceway_12_contact').set('input', ['box_roller_12_inner_contact_patch', 'geom1_inner_ring_bnd'])" in VERIFIED_3D_FULL_BEARING_CODE
        assert ".destination().named('sel_outer_raceway_12_contact')" in VERIFIED_3D_FULL_BEARING_CODE

        segment_b = SEGMENTED_3D_CODE_SPECS[1]
        segment_prompt = build_segmented_3d_generation_prompt(
            segment_b,
            completed_manifests=[{
                "segment_id": "A_base_geometry",
                "creates": ["comp1", "geom1", "inner_ring", "outer_ring", "cage_annulus"],
            }],
            previous_code_tail="model.component('comp1').geom('geom1').create('cage_annulus', 'Difference');",
        )
        assert "SEGMENT_ID: B_cage_pockets_and_rollers" in segment_prompt
        assert "COMPLETED_MANIFESTS_JSON" in segment_prompt
        assert "Do not recreate comp1/geom1" in segment_prompt
        assert "SEGMENT_MANIFEST_START" in segment_prompt
        segmented_response = (
            f"{SEGMENT_MARKER_MANIFEST_START}\n"
            '{"segment_id":"B_cage_pockets_and_rollers","depends_on":["A_base_geometry"],'
            '"creates":["cage_pocket_1","cage_pocket_12","cage","roller_1","roller_12"],"uses":["cage_annulus"]}\n'
            f"{SEGMENT_MARKER_MANIFEST_END}\n"
            "GENERATED_CODE_START\n"
            "model.component('comp1').geom('geom1').create('cage_pocket_1', 'Cylinder');\n"
            "model.component('comp1').geom('geom1').create('cage_pocket_12', 'Cylinder');\n"
            "model.component('comp1').geom('geom1').create('cage', 'Difference');\n"
            "model.component('comp1').geom('geom1').create('roller_1', 'Cylinder');\n"
            "model.component('comp1').geom('geom1').create('roller_12', 'Cylinder');\n"
            "GENERATED_CODE_END"
        )
        manifest = extract_segment_manifest(segmented_response)
        assert manifest is not None
        assert manifest["segment_id"] == "B_cage_pockets_and_rollers"
        segment_code = extract_generated_code(segmented_response) or ""
        segment_quality = validate_segmented_3d_segment(
            segment_b,
            manifest,
            segment_code,
            completed_manifests=[{"segment_id": "A_base_geometry"}],
            existing_tags={"comp1", "geom1", "inner_ring", "outer_ring", "cage_annulus"},
        )
        assert segment_quality["success"] is True
        duplicate_quality = validate_segmented_3d_segment(
            segment_b,
            manifest,
            "model.component().create('comp1', True);\n" + segment_code,
            completed_manifests=[{"segment_id": "A_base_geometry"}],
            existing_tags={"comp1", "geom1"},
        )
        assert duplicate_quality["success"] is False
        assert any("forbidden snippet" in error or "duplicate" in error for error in duplicate_quality["errors"])
        assembled_code, assembly_manifest = assemble_segmented_3d_code([
            {
                "code": VERIFIED_3D_FULL_BEARING_CODE,
                "manifest": {"segment_id": "verified_single_segment"},
                "created_tags": [],
                "warnings": [],
            }
        ])
        assert "cage_pocket_12" in assembled_code
        assert assembly_manifest["final_quality"]["success"] is True

        quality = validate_3d_bearing_code_draft(VERIFIED_3D_FULL_BEARING_CODE)
        assert quality["success"] is True
        assert quality["quality_level"] == "smoke"
        assert quality["warnings"] == []
        production_quality = validate_3d_bearing_code_draft(
            VERIFIED_3D_FULL_BEARING_CODE,
            require_named_selections=True,
        )
        assert production_quality["success"] is True
        assert production_quality["quality_level"] == "production_candidate"
        assert not any("sel_roller_1_body" in error for error in production_quality["errors"])
        assert not any("probe_roller_1_max_mises" in error for error in production_quality["errors"])
        assert not any("sel_roller_1_inner_contact" in error for error in production_quality["errors"])
        assert not any("sel_roller_1_outer_contact" in error for error in production_quality["errors"])
        assert production_quality["errors"] == []

        binding_contract = selection_binding_contract()
        assert binding_contract["kind"] == "bearing_3d_selection_binding_contract"
        assert binding_contract["roller_count"] == VERIFIED_ROLLER_COUNT
        assert len(binding_contract["entries"]) == 5 + 5 * VERIFIED_ROLLER_COUNT
        code_binding_audit = audit_3d_selection_binding(
            java_code=VERIFIED_3D_FULL_BEARING_CODE,
        )
        assert code_binding_audit["success"] is True
        assert code_binding_audit["runtime_checked"] is False
        assert code_binding_audit["code_declared_count"] == code_binding_audit["required_selection_count"]
        runtime_selection_report = {
            entry["tag"]: {
                "entitydim": entry["entitydim"],
                "entity_count": entry["expected_min_entities"],
                "binding_source": entry["binding_method"],
            }
            for entry in binding_contract["entries"]
        }
        runtime_binding_audit = audit_3d_selection_binding(
            java_code=VERIFIED_3D_FULL_BEARING_CODE,
            selection_report=runtime_selection_report,
        )
        assert runtime_binding_audit["success"] is True
        assert runtime_binding_audit["runtime_bound_count"] == runtime_binding_audit["required_selection_count"]
        runtime_selection_report["sel_roller_1_inner_contact"]["entity_count"] = 0
        failed_binding_audit = audit_3d_selection_binding(
            java_code=VERIFIED_3D_FULL_BEARING_CODE,
            selection_report=runtime_selection_report,
        )
        assert failed_binding_audit["success"] is False
        assert any("sel_roller_1_inner_contact selected 0 entities" in error for error in failed_binding_audit["errors"])
        probe_code = build_selection_binding_probe_code()
        assert "SELECTION_BINDING_PROBE_START" in probe_code
        assert "selection_probe_selection.entities()" in probe_code
        parsed_probe = parse_selection_binding_probe_output(
            "noise\n"
            "SELECTION_BINDING_PROBE_START\n"
            "SEL|sel_inner_raceway_contact|2|2|3,4|\n"
            "SEL|sel_roller_1_inner_contact|2|-1||Missing selection\n"
            "SELECTION_BINDING_PROBE_END\n"
        )
        assert parsed_probe["count"] == 2
        assert parsed_probe["success"] is False
        assert parsed_probe["selections"][0]["entity_count"] == 2
        assert parsed_probe["selections"][1]["error"] == "Missing selection"
        physical_audit = audit_3d_physical_results(
            evaluations=[
                {
                    "success": True,
                    "expression": "solid.mises",
                    "statistics": {"max": 3.17e6, "mean": 1.2e5},
                },
                {"success": True, "expression": "contact_pressure_est", "value": 1.95e6},
            ],
            metrics={"von_mises_max": 3.17e6},
        )
        assert physical_audit["success"] is True
        assert physical_audit["production_ready"] is False
        assert physical_audit["quality_level"] == "nonzero_stress_smoke_gate"
        assert any("displacement_nonzero" in warning for warning in physical_audit["warnings"])
        production_physical_audit = audit_3d_physical_results(
            evaluations=[
                {
                    "success": True,
                    "expression": "solid.mises",
                    "statistics": {"max": 3.17e6, "mean": 1.2e5},
                },
                {"success": True, "expression": "contact_pressure_est", "value": 1.95e6},
                {"success": True, "expression": "solid.disp", "statistics": {"max": 2.5e-6, "mean": 7.5e-7}},
            ],
            metrics={"von_mises_max": 3.17e6},
            require_displacement=True,
            require_contact_pressure=True,
        )
        assert production_physical_audit["success"] is True
        assert production_physical_audit["production_ready"] is True
        assert production_physical_audit["quality_level"] == "production_physics_gate"
        zero_stress_audit = audit_3d_physical_results(
            evaluations=[
                {
                    "success": True,
                    "expression": "solid.mises",
                    "statistics": {"max": 0.0, "mean": 0.0},
                }
            ],
        )
        assert zero_stress_audit["success"] is False
        assert any("von_mises_nonzero is near zero" in error for error in zero_stress_audit["errors"])
        contact_report = build_contact_convergence_report(
            solve_result={"success": True, "status": "Solve completed.", "elapsed_seconds": 12.3},
            metrics={"contact_pressure_guess": 1.95e6},
            selection_binding_audit=runtime_binding_audit,
            physical_result_audit=production_physical_audit,
            contact_pair_count=VERIFIED_ROLLER_COUNT * 2,
        )
        assert contact_report["success"] is True
        assert contact_report["runtime_verified"] is True
        assert contact_report["quality_level"] == "contact_runtime_convergence_checked"
        unverified_contact_report = build_contact_convergence_report(
            metrics={"contact_pressure_guess": 1.95e6},
            selection_binding_audit=code_binding_audit,
            physical_result_audit=production_physical_audit,
            contact_pair_count=VERIFIED_ROLLER_COUNT * 2,
        )
        assert unverified_contact_report["success"] is True
        assert unverified_contact_report["runtime_verified"] is False
        assert any("Solve result was not provided" in warning for warning in unverified_contact_report["warnings"])
        code_only_contact_report = build_contact_convergence_report(
            solve_result={"success": True, "status": "Solve completed."},
            metrics={"contact_pressure_guess": 1.95e6},
            selection_binding_audit=code_binding_audit,
            physical_result_audit=production_physical_audit,
            contact_pair_count=VERIFIED_ROLLER_COUNT * 2,
        )
        assert code_only_contact_report["success"] is True
        assert code_only_contact_report["runtime_verified"] is False
        assert any("code-declared only" in warning for warning in code_only_contact_report["warnings"])

        bad_2d = """
        model.component().create('comp1', true);
        model.component('comp1').geom().create('geom1', 2);
        model.component('comp1').geom('geom1').create('inner_raceway', 'Rectangle');
        model.component('comp1').geom('geom1').create('outer_raceway', 'Rectangle');
        model.component('comp1').geom('geom1').create('roller_1', 'Circle');
        model.component('comp1').geom('geom1').create('roller_2', 'Circle');
        model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
        model.component('comp1').pair().create('cp_roller_outer', 'Contact');
        model.result().create('pg_stress', 'PlotGroup2D');
        output.write('cage geometry is omitted');
        """
        bad_no_cage = VERIFIED_3D_FULL_BEARING_CODE.replace("cage_pocket_12", "pocket_missing")

        assert validate_3d_bearing_code_draft(bad_2d)["success"] is False
        assert validate_3d_bearing_code_draft(bad_no_cage)["success"] is False

        marked_with_prose = (
            "I will produce code, not a plate model.\n"
            "GENERATED_CODE_START\n"
            "```java\n"
            'model.component().create("comp1", true);\n'
            'model.component("comp1").geom().create("geom1", 3);\n'
            'model.component("comp1").geom("geom1").create("roller_1", "Cylinder");\n'
            "```\n"
            "GENERATED_CODE_END\n"
            "This explanation mentions a plate only outside the code."
        )
        extracted = extract_generated_code(marked_with_prose)
        assert extracted is not None
        assert extracted.startswith('model.component().create("comp1", true);')
        assert "This explanation" not in extracted
        marked_without_fence = (
            "GENERATED_CODE_START\n"
            "The following table summarizes the design before code.\n"
            "// setup-only 3D code\n"
            "model.param().set('inner_diameter', '40[mm]');\n"
            "model.geom().create('geom1', 3);\n"
            "\n"
            "### Summary\n"
            "- not executable code\n"
            "GENERATED_CODE_END"
        )
        assert extract_generated_code(marked_without_fence) == (
            "// setup-only 3D code\n"
            "model.param().set('inner_diameter', '40[mm]');\n"
            "model.geom().create('geom1', 3);"
        )
        normalized = normalize_generated_mph_code(
            'model.component().create("comp1", true);\n'
            'model.component("comp1").geom("geom1").feature("roller_1").set("pos", {"0", "0", "-1[mm]"});'
        )
        assert 'create("comp1", True)' in normalized
        assert '["0", "0", "-1[mm]"]' in normalized
        normalized_arrays = normalize_generated_mph_code(
            'model.geom("geom1").feature("cyl_r6").set("pos", new double[]{pitch_diameter/2*0.5, 0, -roller_length/2});\n'
            'model.geom("geom1").feature("diff").selection("input2").set(new String[]{"pocket1", "pocket6"});\n'
            'model.material("mat1").selection().set(new int[]{1, 2, 3});\n'
            'model.physics("solid").feature("fix1").selection().set(new int[]{/* outer boundary */ 4});'
        )
        assert '["pitch_diameter/2*0.5", 0, "-roller_length/2"]' in normalized_arrays
        assert '["pocket1", "pocket6"]' in normalized_arrays
        assert "[1, 2, 3]" in normalized_arrays
        assert "/*" not in normalized_arrays
        assert "[4]" in normalized_arrays

        double_quote_code = VERIFIED_3D_FULL_BEARING_CODE.replace(
            "geom().create('geom1', 3)",
            'geom().create("geom1", 3)',
        )
        assert validate_3d_bearing_code_draft(double_quote_code)["success"] is True
        python_comment_code = (
            "# no new int[], no new String[] should be ignored in comments\n"
            + VERIFIED_3D_FULL_BEARING_CODE
        )
        assert validate_3d_bearing_code_draft(python_comment_code)["success"] is True
        alternate_names = VERIFIED_3D_FULL_BEARING_CODE.replace("roller_12", "cyl_r12").replace("cage_pocket_12", "pocket12")
        assert validate_3d_bearing_code_draft(alternate_names)["success"] is True
        short_generated_names = VERIFIED_3D_FULL_BEARING_CODE.replace("roller_12", "rol12").replace("cage_pocket_12", "pkt12")
        assert validate_3d_bearing_code_draft(short_generated_names)["success"] is True

        missing_pairs = "\n".join(
            line for line in VERIFIED_3D_FULL_BEARING_CODE.splitlines()
            if ".pair().create" not in line
        )
        missing_pairs_quality = validate_3d_bearing_code_draft(missing_pairs)
        assert missing_pairs_quality["success"] is False
        repaired, repair_reports, repaired_quality = apply_bounded_3d_generated_code_repairs(
            missing_pairs,
            missing_pairs_quality,
            max_attempts=2,
        )
        assert repair_reports
        assert repair_reports[0]["stage"] == "offline_bounded_repair"
        assert repair_reports[0]["strategy"] == "append_verified_contact_pair_anchor_snippet"
        assert repair_reports[0]["api_doc_query"]
        assert "repair_cp_inner_raceway" in repaired
        assert repaired_quality["success"] is True

        runtime_risky_generated = (
            VERIFIED_3D_FULL_BEARING_CODE
            .replace("model.study().create('std1');", "model.component(\"comp1\").study().create(\"std1\")")
            .replace("model.study('std1').create('stat', 'Stationary');", "model.component(\"comp1\").study(\"std1\").feature().create(\"stat\", \"Stationary\")")
            .replace("model.result().create('pg_stress3d', 'PlotGroup3D');", "model.component(\"comp1\").result().create(\"pg1\", \"PlotGroup3D\")")
            .replace("model.result('pg_stress3d').feature().create('surf_mises', 'Surface');", "model.component(\"comp1\").result(\"pg1\").feature().create(\"surf1\", \"Surface\")")
            .replace("model.result('pg_stress3d').feature('surf_mises').set('expr', 'solid.mises');", "model.component(\"comp1\").result(\"pg1\").feature(\"surf1\").set(\"expr\", \"solid.mises\")")
            .replace("'Fixed'", "\"FixedConstraint\"", 1)
            + """
model.component("comp1").geom("geom1").feature("roller_1").set("ax", ["0", "0", "1"])
model.component("comp1").pair().create("pair1", "contact")
model.component("comp1").pair("pair1").source().set(["geom1"])
model.component("comp1").pair("pair1").destination().set(["geom1"])
model.component("comp1").physics("solid").feature().create("cp_extra", "Contact", 1)
model.component("comp1").physics("solid").feature("cp_extra").set("contact_pair", "pair1")
model.component("comp1").geom("geom1").run()
model.component("comp1").geom("geom1").finalize("assembly")
model.component("comp1").geom("geom1").selection().create("sel_r1_inner", "Explicit")
model.component("comp1").geom("geom1").selection("sel_r1_inner").set("entitydim", 2)
model.output().write("Cage included: Boolean cage ring with twelve pockets.")
"""
        )
        risky_quality = validate_3d_bearing_code_draft(runtime_risky_generated)
        assert risky_quality["success"] is False
        assert any("runtime-risky COMSOL API pattern" in error for error in risky_quality["errors"])
        preflight_repaired, preflight_reports, preflight_quality = apply_runtime_preflight_3d_repairs(
            runtime_risky_generated,
            risky_quality,
        )
        assert preflight_reports
        assert preflight_reports[0]["stage"] == "offline_runtime_preflight_repair"
        assert preflight_reports[0]["changes"]
        assert "model.study().create" in preflight_repaired
        assert "model.result().create" in preflight_repaired
        assert "cp_roller_inner_raceway" in preflight_repaired
        assert "FixedConstraint" not in preflight_repaired
        assert '"contact_pair"' not in preflight_repaired
        assert "model.output().write" not in preflight_repaired
        assert '.set("ax"' not in preflight_repaired
        assert ".finalize(" not in preflight_repaired
        assert ".feature('fin').set('action', 'assembly')" in preflight_repaired
        assert '.geom("geom1").selection()' not in preflight_repaired
        assert 'model.component("comp1").selection().create("sel_r1_inner", "Explicit")' in preflight_repaired
        assert "model_output_write_to_comment" in " ".join(preflight_reports[0]["changes"])
        assert "remove_unsupported_cylinder_axis_property" in " ".join(preflight_reports[0]["changes"])
        assert "geom_finalize_assembly_to_verified_fin_action" in " ".join(preflight_reports[0]["changes"])
        assert "geom_scoped_selection_create_to_component_selection" in " ".join(preflight_reports[0]["changes"])
        assert preflight_quality["success"] is True, preflight_quality

        unsupported_runtime_api = runtime_risky_generated + """
        model.component("comp1").geom("geom1").feature().create("sel_bad", "CylinderSelection")
        model.component("comp1").geom("geom1").feature().create("sel_explicit_bad", "Explicit")
        model.component("comp1").physics().create("pair_bad", "ContactPair", "geom1")
        model.component("comp1").geom("geom1").feature("diff_bad").set("objects", ["hole"])
        model.component("comp1").pair("cp_bad").set("source", ["sel_rollers"])
        """
        unsupported_quality = validate_3d_bearing_code_draft(unsupported_runtime_api)
        assert unsupported_quality["success"] is False
        assert any("CylinderSelection/BoxSelection/ExplicitSelection" in error for error in unsupported_quality["errors"])
        assert any("Explicit as a geometry operation" in error for error in unsupported_quality["errors"])
        assert any("ContactPair as a physics interface" in error for error in unsupported_quality["errors"])
        assert any("Difference object/objects setters" in error for error in unsupported_quality["errors"])
        assert any("Contact pair endpoints" in error for error in unsupported_quality["errors"])

        latest_prompt_style = runtime_risky_generated + """
        model.component("comp1").geom("geom1").feature().create("sel_rollers", "ExplicitSelection")
        model.component("comp1").pair().create("pair1", "Contact")
        model.component("comp1").pair("pair1").set("source", ["sel_rollers"])
        model.component("comp1").pair("pair1").set("destination", ["sel_inner_raceway"])
        """
        latest_prompt_quality = validate_3d_bearing_code_draft(latest_prompt_style)
        latest_prompt_repaired, latest_prompt_reports, latest_prompt_repaired_quality = apply_runtime_preflight_3d_repairs(
            latest_prompt_style,
            latest_prompt_quality,
        )
        assert latest_prompt_reports
        assert "explicitselection_to_explicit" in " ".join(latest_prompt_reports[0]["changes"])
        assert "contact_pair_set_endpoint_to_named" in " ".join(latest_prompt_reports[0]["changes"])
        assert '"ExplicitSelection"' not in latest_prompt_repaired
        assert ".source().named" in latest_prompt_repaired
        assert ".destination().named" in latest_prompt_repaired
        assert latest_prompt_repaired_quality["success"] is False
        assert any("Explicit as a geometry operation" in error for error in latest_prompt_repaired_quality["errors"])

        historical_generated = Path("runtime_smoke/bearing_3d_full_demo/generated_code_3d_bearing_cage.java")
        if historical_generated.exists():
            historical_code = normalize_generated_mph_code(historical_generated.read_text())
            historical_quality = validate_3d_bearing_code_draft(historical_code)
            historical_repaired, historical_reports, historical_repaired_quality = apply_runtime_preflight_3d_repairs(
                historical_code,
                historical_quality,
            )
            assert historical_quality["success"] is False
            assert historical_reports
            assert "component_scoped_study_create_to_top_level" in " ".join(historical_reports[0]["changes"])
            assert "rename_placeholder_contact_pair_pair1" in " ".join(historical_reports[0]["changes"])
            assert "result_create_to_numerical_create" in " ".join(historical_reports[0]["changes"])
            assert "FixedConstraint" not in historical_repaired
            assert historical_repaired_quality["success"] is False
            assert any("twelfth roller" in error for error in historical_repaired_quality["errors"])
            assert any("Boolean pocket cutouts" in error for error in historical_repaired_quality["errors"])

    def test_generated_code_agent_demo_prompt_fixture_and_extraction(self):
        from scripts.run_agent_generated_code_demo import (
            build_code_generation_prompt,
            build_generated_code_execution_prompt,
            extract_generated_code,
        )

        draft = build_code_generation_prompt(
            archive_path="runtime_smoke/agent_generated_code_demo.sqlite3",
        )
        execute = build_generated_code_execution_prompt(
            java_code="model.param().set('L', '50[mm]');",
            archive_path="runtime_smoke/agent_generated_code_demo.sqlite3",
            artifact_dir="runtime_smoke/agent_generated_code_demo/template_runs",
            plot_path="runtime_smoke/agent_generated_code_demo/generated_code_von_mises.png",
            model_name="agent_generated_code_model",
            template_name="agent_generated_structural_plate_seed",
        )

        assert draft.name == "generated_code_draft"
        assert "simulation_plan_generated_code" in draft.required_tools
        assert "GENERATED_CODE_START" in draft.prompt
        assert "Do not call simulation_validate_template" in draft.prompt
        assert execute.name == "generated_code_execute"
        assert "simulation_run_template" in execute.required_tools
        assert "RAW_GENERATED_CODE" in execute.prompt
        assert "model.param().set('L', '50[mm]');" in execute.prompt

        marked = (
            "Here is code\n"
            "GENERATED_CODE_START\n"
            "```java\nmodel.param().set('L', '50[mm]');\n```\n"
            "GENERATED_CODE_END"
        )
        assert extract_generated_code(marked) == "model.param().set('L', '50[mm]');"
        assert extract_generated_code("```java\nmodel.component().create('comp1', true);\n```") == "model.component().create('comp1', true);"

    def test_3d_package_metadata_injection_exposes_top_level_metrics(self, tmp_path):
        from scripts.run_agent_3d_bearing_full_demo import VERIFIED_ROLLER_COUNT, _inject_3d_package_metadata

        summary_path = tmp_path / "summary.json"
        report_path = tmp_path / "report.md"
        summary_path.write_text(
            json.dumps(
                {
                    "success": True,
                    "metrics": {
                        "von_mises_max": 123.0,
                        "von_mises_mean": 45.0,
                        "von_mises_min": 6.0,
                        "contact_pressure_guess": 78.0,
                        "contact_pressure_expression": "contact_pressure_est",
                        "displacement_max": 2.0e-6,
                        "displacement_mean": 8.0e-7,
                        "displacement_expression": "solid.disp",
                    },
                }
            ),
            encoding="utf-8",
        )
        report_path.write_text("# Report\n", encoding="utf-8")

        _inject_3d_package_metadata(
            {"json_path": str(summary_path), "markdown_path": str(report_path)},
            repair_history=[{"attempt": 1, "stage": "offline_quality_gate", "success": True}],
            cage_model="simplified cage ring",
            per_roller_probe_results=[
                {"roller": f"roller_{index}", "success": True, "value": float(index)}
                for index in range(1, VERIFIED_ROLLER_COUNT + 1)
            ],
        )

        injected = json.loads(summary_path.read_text(encoding="utf-8"))
        assert injected["kind"] == "bearing_3d_full_package"
        assert injected["max_von_mises_pa"] == 123.0
        assert injected["mean_von_mises_pa"] == 45.0
        assert injected["contact_pressure_estimate_pa"] == 78.0
        assert "roller/raceway contact region" in injected["max_stress_location_approx"]
        assert injected["highest_risk_roller"] == "roller_12"
        assert injected["roller_risk_ranking"][0]["roller"] == "roller_12"
        assert injected["selection_status"].startswith("verified_named_box_region_roller_body_and_contact_surface")
        assert "probe_scope_verified" in injected["probe_scope_status"]
        assert injected["per_roller_probe_results"][0]["value"] == 1.0
        assert injected["selection_plan"]["global_selections"]["outer_support_surface"] == "sel_outer_support_surface"
        assert injected["selection_plan"]["roller_contact_sets"][0]["risk_probe"] == "probe_roller_1_max_mises"
        assert injected["selection_binding_contract"]["kind"] == "bearing_3d_selection_binding_contract"
        assert len(injected["selection_binding_contract"]["entries"]) == 5 + 5 * VERIFIED_ROLLER_COUNT
        assert injected["selection_binding_audit"]["success"] is True
        assert injected["physical_result_audit"]["success"] is True
        assert injected["physical_result_audit"]["production_ready"] is True
        assert injected["physical_result_audit"]["quality_level"] == "production_physics_gate"
        assert injected["physical_result_audit"]["checks"]["von_mises_nonzero"]["value"] == 123.0
        assert injected["max_displacement_m"] == 2.0e-6
        assert injected["contact_convergence_report"]["success"] is True
        assert injected["contact_convergence_report"]["quality_level"] == "contact_smoke_convergence_unverified"
        assert "failed_code_excerpt" not in injected["repair_history"][0]
        assert injected["repair_history"][0]["stage"] == "offline_quality_gate"
        assert "Max stress location" in report_path.read_text(encoding="utf-8")
        assert "Highest-risk roller estimate" in report_path.read_text(encoding="utf-8")
        assert "Selection status" in report_path.read_text(encoding="utf-8")
        assert "Contact convergence report" in report_path.read_text(encoding="utf-8")
        assert injected["artifact_qa"]
        assert any("最大 von Mises 应力" in item["answer"] for item in injected["artifact_qa"])
        assert injected["report_paths"]["markdown_path"] == str(report_path)
        html_path = Path(injected["report_paths"]["html_path"])
        assert html_path.exists()
        html = html_path.read_text(encoding="utf-8")
        assert "<!doctype html>" in html
        assert "Artifact Q&amp;A Smoke" in html
        assert "最大应力是多少" in html

    def test_3d_artifact_answer_reports_risk_roller_and_cage(self):
        from comsol_agent.tools.simulation import _answer_from_artifact_summary

        summary = {
            "max_von_mises_pa": 123.0,
            "cage_model": "simplified cage ring with six pocket/constraint point markers",
            "roller_risk_ranking": [
                {"roller": "roller_1", "relative_risk": 1.0},
                {"roller": "roller_2", "relative_risk": 0.5},
            ],
            "highest_risk_roller": "roller_1",
            "selection_status": "verified_named_box_region_roller_body_and_contact_surface_selections_with_scoped_per_roller_probe_evaluation",
            "probe_scope_status": "probe_scope_verified via component Maximum coupling operators bound to per-roller body selections",
            "selection_plan": {
                "global_selections": {
                    "outer_support_surface": "sel_outer_support_surface",
                    "inner_load_region": "sel_inner_load_region",
                }
            },
            "result_interpretation": {
                "max_stress_location_approx": "3D roller/raceway contact region",
                "highest_risk_region": "roller_1 roller/raceway contact interfaces",
                "contact_pair_status": "explicit COMSOL Contact pair features were created",
                "cage_status": "cage included",
            },
        }

        stress_answer = _answer_from_artifact_summary("最大应力和哪个滚子风险最高？", summary)
        cage_answer = _answer_from_artifact_summary("保持架是否建模？", summary)
        selection_answer = _answer_from_artifact_summary("边界选择和 probe 情况？", summary)

        assert "123.0" in stress_answer
        assert "roller_1" in stress_answer
        assert "保持架建模状态" in cage_answer
        assert "simplified cage ring" in cage_answer
        assert "选择状态" in selection_answer
        assert "probe 作用域状态" in selection_answer
        assert "sel_outer_support_surface" in selection_answer

    def test_template_tools_list_and_read_seeded_templates(self, tmp_path):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.simulation.skills import seed_builtin_templates
        from comsol_agent.tools.simulation import (
            simulation_list_templates,
            simulation_read_template,
            simulation_search_templates,
        )

        archive_path = tmp_path / "archive.sqlite3"
        seed_builtin_templates(ArchiveStore(archive_path))

        listed = simulation_list_templates(domain="thermal", archive_path=str(archive_path))
        searched = simulation_search_templates(
            query="ambient",
            domain="thermal",
            archive_path=str(archive_path),
        )
        read = simulation_read_template("thermal_heat_transfer_seed", archive_path=str(archive_path))

        assert listed["success"] is True
        assert listed["count"] == 1
        assert listed["templates"][0]["name"] == "thermal_heat_transfer_seed"
        assert searched["success"] is True
        assert searched["templates"][0]["name"] == "thermal_heat_transfer_seed"
        assert "Offline keyword search" in searched["note"]
        assert "power" in listed["templates"][0]["params"]
        assert read["success"] is True
        assert "model.param().set('power'" in read["template"]["java_code"]

    def test_template_tool_saves_custom_template(self, tmp_path, monkeypatch):
        from comsol_agent.tools.simulation import (
            simulation_export_template,
            simulation_list_templates,
            simulation_read_template,
            simulation_save_template,
            simulation_validate_template,
        )

        monkeypatch.setenv("COMSOL_AGENT_ALLOWED_PATHS", str(tmp_path))
        archive_path = tmp_path / "archive.sqlite3"
        saved = simulation_save_template(
            name="custom_thermal_plate",
            domain="thermal",
            java_code="model.param().set('power', '25[W]');",
            params={"power": "25[W]"},
            archive_path=str(archive_path),
        )
        listed = simulation_list_templates(domain="thermal", archive_path=str(archive_path))
        read = simulation_read_template("custom_thermal_plate", archive_path=str(archive_path))
        validated = simulation_validate_template(
            name="custom_thermal_plate",
            archive_path=str(archive_path),
        )
        exported = simulation_export_template(
            "custom_thermal_plate",
            output_path=str(tmp_path / "custom_thermal_plate.java"),
            archive_path=str(archive_path),
        )

        assert saved["success"] is True
        assert saved["validation"]["status"] == "ok"
        assert listed["templates"][0]["name"] == "custom_thermal_plate"
        assert read["template"]["params"] == {"power": "25[W]"}
        assert validated["success"] is True
        assert validated["validation"]["status"] == "ok"
        assert exported["success"] is True
        exported_content = Path(exported["output_path"]).read_text(encoding="utf-8")
        assert "COMSOL Agent template: custom_thermal_plate" in exported_content
        assert "model.param().set('power', '25[W]');" in exported_content

    def test_template_validation_rejects_dangerous_java(self):
        from comsol_agent.tools.simulation import simulation_validate_template

        result = simulation_validate_template(
            name="unsafe",
            java_code="System.exit(0);",
        )

        assert result["success"] is False
        assert result["validation"]["status"] == "fail"
        assert any("System.exit" in error for error in result["validation"]["errors"])

    def test_template_run_requires_explicit_model_target(self):
        from comsol_agent.tools.simulation import simulation_run_template

        result = simulation_run_template(name="thermal_heat_transfer_seed")

        assert result["success"] is False
        assert "model_name or create_model_name" in result["error"]

    def test_template_run_executes_and_persists_with_created_model(self, tmp_path, monkeypatch):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.simulation.skills import seed_builtin_templates
        from comsol_agent.tools import simulation as simulation_tools

        archive_path = tmp_path / "archive.sqlite3"
        seed_builtin_templates(ArchiveStore(archive_path))
        calls = []

        def fake_create_model(name):
            calls.append(("create", name))
            return {"success": True, "model_name": name}

        def fake_execute_java(java_code, model_name):
            calls.append(("execute", model_name, java_code))
            return {"success": True, "output": "Code executed successfully (no output)."}

        def fake_close_model(model_name, save=False):
            calls.append(("close", model_name, save))
            return {"success": True, "model_name": model_name, "save": save}

        monkeypatch.setattr(simulation_tools, "comsol_create_model", fake_create_model)
        monkeypatch.setattr(simulation_tools, "comsol_execute_java", fake_execute_java)
        monkeypatch.setattr(simulation_tools, "comsol_close_model", fake_close_model)

        result = simulation_tools.simulation_run_template(
            name="thermal_heat_transfer_seed",
            create_model_name="template_smoke_model",
            artifact_dir=str(tmp_path / "template_runs"),
            archive_path=str(archive_path),
        )

        assert result["success"] is True
        assert result["executed"] is True
        assert result["validation"]["status"] == "ok"
        assert calls[0] == ("create", "template_smoke_model")
        assert calls[1][0] == "execute"
        assert calls[2] == ("close", "template_smoke_model", False)
        assert Path(result["artifacts"]["json_path"]).exists()
        archived = ArchiveStore(archive_path).get_simulation_artifact(result["artifacts"]["run_id"])
        assert archived.kind == "template_execution"

    def test_generated_code_run_persists_as_generated_code_execution(self, tmp_path, monkeypatch):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.tools import simulation as simulation_tools
        from comsol_agent.tools.simulation import simulation_read_artifact

        calls = []

        def fake_create_model(name):
            calls.append(("create", name))
            return {"success": True, "model_name": name}

        def fake_execute_java(java_code, model_name):
            calls.append(("execute", model_name, java_code))
            return {"success": True, "output": "Code executed successfully (no output)."}

        def fake_close_model(model_name, save=False):
            calls.append(("close", model_name, save))
            return {"success": True, "model_name": model_name, "save": save}

        monkeypatch.setattr(simulation_tools, "comsol_create_model", fake_create_model)
        monkeypatch.setattr(simulation_tools, "comsol_execute_java", fake_execute_java)
        monkeypatch.setattr(simulation_tools, "comsol_close_model", fake_close_model)

        archive_path = tmp_path / "archive.sqlite3"
        result = simulation_tools.simulation_run_template(
            name="generated_bearing_seed",
            java_code="model.component().create('comp1', true);",
            create_model_name="generated_code_model",
            params={"radial_load": "3000[N]"},
            execution_context={
                "workflow": "bearing_3d_generated_code_agent_execution",
                "draft_quality": {"success": True, "quality_level": "production_candidate"},
                "repair_history": [{"stage": "offline_runtime_preflight_repair", "success": True}],
                "selection_binding_audit": {"success": True, "runtime_checked": True},
                "physical_result_audit": {
                    "success": True,
                    "quality_level": "production_physics_gate",
                    "production_ready": True,
                },
                "contact_convergence_report": {
                    "success": True,
                    "quality_level": "contact_runtime_convergence_checked",
                    "runtime_verified": True,
                },
                "require_free_generated_code": True,
            },
            artifact_dir=str(tmp_path / "template_runs"),
            archive_path=str(archive_path),
        )

        assert result["success"] is True
        assert result["executed"] is True
        assert calls[0] == ("create", "generated_code_model")
        assert Path(result["artifacts"]["json_path"]).exists()
        archived = ArchiveStore(archive_path).get_simulation_artifact(result["artifacts"]["run_id"])
        assert archived.kind == "generated_code_execution"
        assert archived.metadata["selection_binding_runtime_checked"] is True
        assert archived.metadata["physical_result_production_ready"] is True
        assert archived.metadata["contact_runtime_verified"] is True
        read_back = simulation_read_artifact(
            run_id=result["artifacts"]["run_id"],
            archive_path=str(archive_path),
        )
        assert read_back["success"] is True
        assert read_back["preview"]["summary"]["execution_audit"]["workflow"] == "bearing_3d_generated_code_agent_execution"
        assert read_back["preview"]["summary"]["execution_audit"]["repair_history_count"] == 1
        assert read_back["preview"]["summary"]["execution_audit"]["quality_gate_level"] == "production_candidate"
        assert read_back["preview"]["summary"]["execution_audit"]["selection_binding_success"] is True
        assert read_back["preview"]["summary"]["execution_audit"]["selection_binding_runtime_checked"] is True
        assert read_back["preview"]["summary"]["execution_audit"]["physical_result_success"] is True
        assert read_back["preview"]["summary"]["execution_audit"]["physical_result_quality_level"] == "production_physics_gate"
        assert read_back["preview"]["summary"]["execution_audit"]["physical_result_production_ready"] is True
        assert read_back["preview"]["summary"]["execution_audit"]["contact_convergence_level"] == "contact_runtime_convergence_checked"
        assert read_back["preview"]["summary"]["execution_audit"]["contact_runtime_verified"] is True

    def test_simulation_probe_3d_selection_binding_parses_runtime_entities(self, monkeypatch):
        from comsol_agent.simulation.bearing_3d import (
            SELECTION_BINDING_PROBE_END,
            SELECTION_BINDING_PROBE_START,
            selection_binding_contract,
        )
        from comsol_agent.tools import simulation as simulation_tools

        entries = selection_binding_contract()["entries"]
        probe_lines = [SELECTION_BINDING_PROBE_START]
        for entry in entries:
            probe_lines.append(f"SEL|{entry['tag']}|{entry['entitydim']}|1|101|")
        probe_lines.append(SELECTION_BINDING_PROBE_END)

        calls = []

        def fake_execute_java(java_code, model_name):
            calls.append((java_code, model_name))
            return {
                "success": True,
                "stdout": "\n".join(probe_lines),
                "output": "\n".join(probe_lines),
            }

        monkeypatch.setattr(simulation_tools, "comsol_execute_java", fake_execute_java)

        result = simulation_tools.simulation_probe_3d_selection_binding(
            model_name="agent_3d_bearing_model",
            java_code=" ".join(entry["tag"] for entry in entries),
        )

        assert result["success"] is True
        assert calls and calls[0][1] == "agent_3d_bearing_model"
        assert "selection_probe_entries" in calls[0][0]
        assert result["selection_report"]["count"] == len(entries)
        assert result["selection_binding_audit"]["runtime_checked"] is True
        assert result["selection_binding_audit"]["runtime_bound_count"] == len(entries)

    @pytest.mark.asyncio
    async def test_agent_loop_injects_skill_context(self):
        from collections.abc import AsyncIterator
        from typing import Any

        from comsol_agent.agent.loop import AgentLoop
        from comsol_agent.cli.config import Config
        from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolDefinition

        class SkillAwareProvider(LLMProvider):
            async def generate(
                self,
                messages: list[dict[str, Any]],
                tools: list[ToolDefinition] | None = None,
                **kwargs: Any,
            ) -> LLMResponse:
                assert any(
                    "[Simulation skill: structural]" in str(message.get("content", ""))
                    for message in messages
                )
                return LLMResponse(text="Used structural skill.")

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

        agent = AgentLoop(SkillAwareProvider(model="fake"), Config())
        response = await agent.run("Analyze structural stress under load")

        assert response == "Used structural skill."
        assert any(
            "[Simulation skill: structural]" in str(message.get("content", ""))
            for message in agent.state.messages
        )

    @pytest.mark.asyncio
    async def test_skills_command_runs(self):
        from types import SimpleNamespace

        from comsol_agent.cli.commands import CommandResult, handle_command
        from comsol_agent.cli.config import Config

        result = await handle_command("/skills", SimpleNamespace(), Config())

        assert result == CommandResult.CONTINUE

    @pytest.mark.asyncio
    async def test_templates_command_runs_with_archive_store(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        import json

        from comsol_agent.cli.commands import CommandResult, handle_command
        from comsol_agent.cli.config import Config
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.simulation.skills import seed_builtin_templates

        monkeypatch.setenv("COMSOL_AGENT_ALLOWED_PATHS", str(tmp_path))
        archive = ArchiveStore(tmp_path / "archive.sqlite3")
        seed_builtin_templates(archive)
        java_file = tmp_path / "custom.java"
        params_file = tmp_path / "custom.params.json"
        java_file.write_text("model.param().set('power', '30[W]');", encoding="utf-8")
        params_file.write_text(json.dumps({"power": "30[W]"}), encoding="utf-8")
        agent = SimpleNamespace(archive_store=archive)

        assert await handle_command("/help templates", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command("/templates help", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command("/templates", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command("/templates domain thermal", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command("/templates search ambient thermal", agent, Config()) == CommandResult.CONTINUE
        assert await handle_command(
            "/templates show thermal_heat_transfer_seed",
            agent,
            Config(),
        ) == CommandResult.CONTINUE
        assert await handle_command(
            "/templates validate thermal_heat_transfer_seed",
            agent,
            Config(),
        ) == CommandResult.CONTINUE
        export_path = tmp_path / "thermal_seed.java"
        assert await handle_command(
            f"/templates export thermal_heat_transfer_seed {export_path}",
            agent,
            Config(),
        ) == CommandResult.CONTINUE
        assert export_path.exists()
        assert await handle_command(
            f"/templates save custom_cli thermal {java_file} {params_file}",
            agent,
            Config(),
        ) == CommandResult.CONTINUE
        assert archive.get_template("custom_cli").params == {"power": "30[W]"}

    @pytest.mark.asyncio
    async def test_templates_run_command_uses_template_runner(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        from comsol_agent.cli.commands import CommandResult, handle_command
        from comsol_agent.cli.config import Config
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.simulation.skills import seed_builtin_templates
        from comsol_agent.tools import simulation as simulation_tools

        archive = ArchiveStore(tmp_path / "archive.sqlite3")
        seed_builtin_templates(archive)
        calls = []

        def fake_run_template(**kwargs):
            calls.append(kwargs)
            return {
                "success": True,
                "model_name": kwargs.get("create_model_name") or kwargs.get("model_name"),
                "artifacts": {"run_id": "template_run_test"},
            }

        monkeypatch.setattr(simulation_tools, "simulation_run_template", fake_run_template)
        agent = SimpleNamespace(archive_store=archive)

        assert await handle_command(
            "/templates run thermal_heat_transfer_seed create cli_template_model",
            agent,
            Config(),
        ) == CommandResult.CONTINUE
        assert calls[0]["name"] == "thermal_heat_transfer_seed"
        assert calls[0]["create_model_name"] == "cli_template_model"

        assert await handle_command(
            "/templates run thermal_heat_transfer_seed model loaded_model",
            agent,
            Config(),
        ) == CommandResult.CONTINUE
        assert len(calls) == 1

        assert await handle_command(
            "/templates run thermal_heat_transfer_seed model loaded_model --allow-modify-loaded",
            agent,
            Config(),
        ) == CommandResult.CONTINUE
        assert calls[1]["model_name"] == "loaded_model"

    def test_startup_status_hides_api_secret(self, capsys):
        from comsol_agent.cli.renderer import render_startup_status

        render_startup_status(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key_present=True,
            base_url="https://api.deepseek.com",
            comsol_executable="/Applications/COMSOL62/Multiphysics/bin/comsol",
            comsol_version="6.2",
            archive_path="/tmp/archive.sqlite3",
            session_dir="/tmp/sessions",
        )

        output = capsys.readouterr().out
        assert "deepseek/deepseek-v4-flash" in output
        assert "configured" in output
        assert "archive.sqlite3" in output
        assert "sk-" not in output

    def test_list_templates_script_outputs_json(self, tmp_path, monkeypatch):
        import json
        import subprocess
        import sys

        monkeypatch.setenv("COMSOL_AGENT_ALLOWED_PATHS", str(tmp_path))
        archive_path = tmp_path / "archive.sqlite3"
        java_file = tmp_path / "script_template.java"
        java_file.write_text("model.param().set('power', '35[W]');", encoding="utf-8")
        saved = subprocess.run(
            [
                sys.executable,
                "scripts/list_templates.py",
                "--archive-path",
                str(archive_path),
                "--save",
                "script_custom_template",
                "--domain",
                "thermal",
                "--java-file",
                str(java_file),
                "--params-json",
                '{"power": "35[W]"}',
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        listed = subprocess.run(
            [
                sys.executable,
                "scripts/list_templates.py",
                "--archive-path",
                str(archive_path),
                "--seed-builtins",
                "--domain",
                "thermal",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        shown = subprocess.run(
            [
                sys.executable,
                "scripts/list_templates.py",
                "--archive-path",
                str(archive_path),
                "--show",
                "thermal_heat_transfer_seed",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        validated = subprocess.run(
            [
                sys.executable,
                "scripts/list_templates.py",
                "--archive-path",
                str(archive_path),
                "--validate",
                "thermal_heat_transfer_seed",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        export_path = tmp_path / "script_thermal_seed.java"
        exported = subprocess.run(
            [
                sys.executable,
                "scripts/list_templates.py",
                "--archive-path",
                str(archive_path),
                "--export",
                "thermal_heat_transfer_seed",
                "--output",
                str(export_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        searched = subprocess.run(
            [
                sys.executable,
                "scripts/list_templates.py",
                "--archive-path",
                str(archive_path),
                "--query",
                "ambient",
                "--domain",
                "thermal",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        saved_payload = json.loads(saved.stdout)
        list_payload = json.loads(listed.stdout)
        show_payload = json.loads(shown.stdout)
        validate_payload = json.loads(validated.stdout)
        export_payload = json.loads(exported.stdout)
        search_payload = json.loads(searched.stdout)
        assert saved_payload["template"]["name"] == "script_custom_template"
        assert list_payload["templates"][0]["domain"] == "thermal"
        assert show_payload["template"]["name"] == "thermal_heat_transfer_seed"
        assert validate_payload["validation"]["status"] == "ok"
        assert export_payload["output_path"] == str(export_path.resolve())
        assert export_path.exists()
        assert search_payload["templates"][0]["name"] == "thermal_heat_transfer_seed"


class TestParameterSweeps:
    """Tests for offline parameter sweep planning."""

    def test_plan_parameter_sweep_expands_cases(self):
        from comsol_agent.simulation.sweeps import plan_parameter_sweep

        plan = plan_parameter_sweep(
            model_name="heat_sink",
            parameters={
                "power": ["10[W]", "50[W]"],
                "h": ["5[W/(m^2*K)]", "10[W/(m^2*K)]"],
            },
            output_expressions=["maxop1(T)"],
        )

        assert plan.estimated_runs == 4
        assert len(plan.cases) == 4
        assert plan.cases[0].parameters == {
            "power": "10[W]",
            "h": "5[W/(m^2*K)]",
        }
        assert plan.next_tool_sequence == (
            "comsol_set_parameter",
            "comsol_solve",
            "comsol_evaluate",
        )

    def test_plan_parameter_sweep_truncates_large_case_listing(self):
        from comsol_agent.simulation.sweeps import plan_parameter_sweep

        plan = plan_parameter_sweep(
            model_name="model",
            parameters={"a": ["1", "2", "3"], "b": ["x", "y", "z"]},
            max_cases=4,
        )

        assert plan.estimated_runs == 9
        assert len(plan.cases) == 4
        assert plan.warnings
        assert "showing first 4" in plan.warnings[0]

    def test_simulation_plan_parameter_sweep_tool(self):
        from comsol_agent.tools.simulation import simulation_plan_parameter_sweep

        result = simulation_plan_parameter_sweep(
            model_name="heat_sink",
            parameters={"power": ["10[W]", "50[W]"]},
            output_expressions=["maxop1(T)"],
        )

        assert result["success"] is True
        assert result["plan"]["estimated_runs"] == 2
        assert result["plan"]["output_expressions"] == ("maxop1(T)",)

    def test_simulation_run_parameter_sweep_uses_loaded_model(self, monkeypatch):
        import comsol_agent.tools.simulation as simulation_tools

        calls = []
        monkeypatch.setattr(
            simulation_tools,
            "comsol_set_parameter",
            lambda model_name, name, value: calls.append(("set_parameter", model_name, name, value))
            or {"success": True, "model_name": model_name, "parameter": name, "value": value},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_solve",
            lambda model_name, study_name=None: calls.append(("solve", model_name, study_name))
            or {"success": True, "model_name": model_name, "study": study_name or "default"},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_evaluate",
            lambda model_name, expression: calls.append(("evaluate", model_name, expression))
            or {
                "success": True,
                "model_name": model_name,
                "expression": expression,
                "statistics": {"min": 1.0, "max": 2.0, "mean": 1.5},
                "data_sample": [1.0, 2.0],
            },
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_close_model",
            lambda model_name, save=False: calls.append(("close", model_name, save))
            or {"success": True},
        )

        result = simulation_tools.simulation_run_parameter_sweep(
            model_name="loaded",
            parameters={"L": ["1[mm]", "2[mm]"]},
            expressions=["T"],
            study_name="std1",
        )

        assert result["success"] is True
        assert result["executed_cases"] == 2
        assert result["close"] is None
        assert result["cases"][0]["evaluations"][0]["statistics"]["max"] == 2.0
        assert calls == [
            ("set_parameter", "loaded", "L", "1[mm]"),
            ("solve", "loaded", "std1"),
            ("evaluate", "loaded", "T"),
            ("set_parameter", "loaded", "L", "2[mm]"),
            ("solve", "loaded", "std1"),
            ("evaluate", "loaded", "T"),
        ]

    def test_simulation_run_parameter_sweep_persists_artifacts(self, monkeypatch, tmp_path):
        import json

        import comsol_agent.tools.simulation as simulation_tools

        monkeypatch.setattr(
            simulation_tools,
            "comsol_set_parameter",
            lambda model_name, name, value: {"success": True, "parameter": name, "value": value},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_solve",
            lambda model_name, study_name=None: {
                "success": True,
                "model_name": model_name,
                "elapsed_seconds": 0.1,
                "status": "ok",
            },
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_evaluate",
            lambda model_name, expression: {
                "success": True,
                "model_name": model_name,
                "expression": expression,
                "shape": [2],
                "statistics": {"min": 1.0, "max": 3.0, "mean": 2.0},
                "data_sample": [1.0, 3.0],
            },
        )

        result = simulation_tools.simulation_run_parameter_sweep(
            model_name="loaded",
            parameters={"L": ["1[mm]"]},
            expressions=["T"],
            artifact_dir=str(tmp_path),
            artifact_name="unit_sweep",
            archive_path=str(tmp_path / "archive.sqlite3"),
        )

        artifacts = result["artifacts"]
        json_path = Path(artifacts["json_path"])
        csv_path = Path(artifacts["csv_path"])
        manifest_path = Path(artifacts["manifest_path"])

        assert result["success"] is True
        assert json_path.exists()
        assert csv_path.exists()
        assert manifest_path.exists()
        assert artifacts["csv_rows"] == 1
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert payload["model_name"] == "loaded"
        assert manifest["kind"] == "parameter_sweep"
        assert "param_L" in csv_path.read_text(encoding="utf-8")

        list_result = simulation_tools.simulation_list_artifacts(
            model_name="loaded",
            archive_path=str(tmp_path / "archive.sqlite3"),
        )
        search_result = simulation_tools.simulation_search_artifacts(
            query="unit_sweep",
            archive_path=str(tmp_path / "archive.sqlite3"),
        )

        assert artifacts["archive"]["kind"] == "parameter_sweep"
        assert list_result["success"] is True
        assert list_result["count"] == 1
        assert search_result["success"] is True
        assert search_result["artifacts"][0]["run_id"].startswith("unit_sweep")

    def test_simulation_compare_artifacts_ranks_archived_sweeps(self, tmp_path):
        from comsol_agent.simulation.artifacts import persist_sweep_result
        from comsol_agent.tools.simulation import simulation_compare_artifacts

        archive_path = tmp_path / "archive.sqlite3"
        artifact_dir = tmp_path / "artifacts"
        base_result = {
            "success": True,
            "model_name": "loaded",
            "source": {"type": "loaded_model", "model_name": "loaded"},
            "plan": {"estimated_runs": 1},
            "executed_cases": 1,
            "truncated": False,
            "close": None,
            "tool_sequence": [],
        }
        persist_sweep_result(
            {
                **base_result,
                "cases": [
                    {
                        "success": True,
                        "case_index": 1,
                        "label": "L=1[mm]",
                        "parameters": {"L": "1[mm]"},
                        "solve": {"elapsed_seconds": 0.1, "status": "ok"},
                        "evaluations": [
                            {
                                "success": True,
                                "expression": "T",
                                "statistics": {"min": 0.0, "max": 1.0, "mean": 0.2},
                            }
                        ],
                    }
                ],
            },
            output_dir=artifact_dir,
            run_name="compare_low",
            archive_path=archive_path,
        )
        persist_sweep_result(
            {
                **base_result,
                "cases": [
                    {
                        "success": True,
                        "case_index": 1,
                        "label": "L=2[mm]",
                        "parameters": {"L": "2[mm]"},
                        "solve": {"elapsed_seconds": 0.1, "status": "ok"},
                        "evaluations": [
                            {
                                "success": True,
                                "expression": "T",
                                "statistics": {"min": 0.0, "max": 2.0, "mean": 0.8},
                            }
                        ],
                    }
                ],
            },
            output_dir=artifact_dir,
            run_name="compare_high",
            archive_path=archive_path,
        )

        result = simulation_compare_artifacts(
            query="compare_",
            metric="mean",
            expression="T",
            direction="max",
            archive_path=str(archive_path),
        )

        comparison = result["comparison"]
        assert result["success"] is True
        assert comparison["comparable_row_count"] == 2
        assert comparison["best"]["parameters"] == {"L": "2[mm]"}
        assert comparison["worst"]["parameters"] == {"L": "1[mm]"}
        assert comparison["parameter_differences"] == {"L": ["2[mm]", "1[mm]"]}

    def test_simulation_export_artifact_report_writes_markdown(self, tmp_path):
        from comsol_agent.simulation.artifacts import persist_sweep_result
        from comsol_agent.tools.simulation import (
            simulation_export_artifact_report,
            simulation_read_artifact,
            simulation_search_artifacts,
        )

        archive_path = tmp_path / "archive.sqlite3"
        artifact_dir = tmp_path / "artifacts"
        persist_sweep_result(
            {
                "success": True,
                "model_name": "loaded",
                "source": {"type": "loaded_model", "model_name": "loaded"},
                "plan": {"estimated_runs": 1},
                "executed_cases": 1,
                "truncated": False,
                "cases": [
                    {
                        "success": True,
                        "case_index": 1,
                        "label": "L=1[mm]",
                        "parameters": {"L": "1[mm]"},
                        "solve": {"elapsed_seconds": 0.1, "status": "ok"},
                        "evaluations": [
                            {
                                "success": True,
                                "expression": "T",
                                "statistics": {"min": 0.0, "max": 1.0, "mean": 0.5},
                            }
                        ],
                    }
                ],
                "close": None,
                "tool_sequence": [],
            },
            output_dir=artifact_dir,
            run_name="report_unit",
            archive_path=archive_path,
        )

        result = simulation_export_artifact_report(
            query="report_unit",
            metric="mean",
            expression="T",
            output_dir=str(tmp_path / "reports"),
            report_name="unit_report",
            output_format="html",
            archive_path=str(archive_path),
        )

        report_path = Path(result["report"]["path"])
        html_path = Path(result["report"]["html_path"])
        manifest_path = Path(result["report"]["manifest_path"])
        content = report_path.read_text(encoding="utf-8")
        html_content = html_path.read_text(encoding="utf-8")
        assert result["success"] is True
        assert report_path.exists()
        assert html_path.exists()
        assert manifest_path.exists()
        assert result["report"]["archive"]["kind"] == "comparison_report"
        assert result["report"]["output_format"] == "html"
        assert "# COMSOL Sweep Comparison Report" in content
        assert "Best Case" in content
        assert "report_unit" in content
        assert "<!doctype html>" in html_content
        assert "COMSOL Sweep Comparison Report" in html_content
        assert "report_unit" in html_content

        search_result = simulation_search_artifacts(
            query="unit_report",
            archive_path=str(archive_path),
        )
        assert search_result["success"] is True
        assert search_result["artifacts"][0]["kind"] == "comparison_report"
        assert search_result["artifacts"][0]["metadata"]["html_path"] == str(html_path)

        read_result = simulation_read_artifact(
            run_id=result["report"]["report_id"],
            archive_path=str(archive_path),
            max_lines=5,
        )
        assert read_result["success"] is True
        assert read_result["artifact"]["kind"] == "comparison_report"
        assert read_result["preview"]["markdown"]["lines"][0] == "# COMSOL Sweep Comparison Report"

    def test_export_sweep_report_script_writes_html(self, tmp_path):
        import json
        import subprocess
        import sys

        from comsol_agent.simulation.artifacts import persist_sweep_result

        archive_path = tmp_path / "archive.sqlite3"
        persist_sweep_result(
            {
                "success": True,
                "model_name": "loaded",
                "source": {"type": "loaded_model", "model_name": "loaded"},
                "plan": {"estimated_runs": 1},
                "executed_cases": 1,
                "truncated": False,
                "cases": [
                    {
                        "success": True,
                        "case_index": 1,
                        "label": "L=1[mm]",
                        "parameters": {"L": "1[mm]"},
                        "solve": {"elapsed_seconds": 0.1, "status": "ok"},
                        "evaluations": [
                            {
                                "success": True,
                                "expression": "T",
                                "statistics": {"min": 0.0, "max": 1.0, "mean": 0.5},
                            }
                        ],
                    }
                ],
                "close": None,
                "tool_sequence": [],
            },
            output_dir=tmp_path / "artifacts",
            run_name="script_report_unit",
            archive_path=archive_path,
        )

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/export_sweep_report.py",
                "--query",
                "script_report_unit",
                "--metric",
                "mean",
                "--expression",
                "T",
                "--output-dir",
                str(tmp_path / "reports"),
                "--report-name",
                "script_report",
                "--format",
                "html",
                "--archive-path",
                str(archive_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        html_path = Path(payload["report"]["html_path"])
        assert payload["success"] is True
        assert html_path.exists()
        assert "<!doctype html>" in html_path.read_text(encoding="utf-8")

    def test_agent_fullflow_demo_prints_reproducible_prompts(self):
        import json
        import subprocess
        import sys

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_agent_fullflow_demo.py",
                "--print-prompts",
                "--archive-path",
                "runtime_smoke/fullflow_demo.sqlite3",
                "--artifact-root",
                "runtime_smoke/fullflow_demo",
                "--report-dir",
                "runtime_smoke/fullflow_demo/reports",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        prompts = json.loads(completed.stdout)
        assert [prompt["name"] for prompt in prompts] == [
            "template_run",
            "sweep_report",
            "artifact_inspection",
        ]
        required = {tool for prompt in prompts for tool in prompt["required_tools"]}
        assert {
            "simulation_search_templates",
            "simulation_validate_template",
            "simulation_run_template",
            "simulation_run_parameter_sweep",
            "simulation_export_artifact_report",
            "simulation_read_artifact",
        }.issubset(required)
        assert "output_format='html'" in prompts[1]["prompt"]
        assert "<sweep_run_id>" in prompts[2]["prompt"]

    def test_agent_fullflow_demo_extracts_latest_artifact_run_id(self):
        from scripts.run_agent_fullflow_demo import _latest_artifact_run_id

        assert _latest_artifact_run_id(
            [
                {
                    "name": "simulation_export_artifact_report",
                    "payload": {"report": {"report_id": "report_1"}},
                },
                {
                    "name": "simulation_run_parameter_sweep",
                    "payload": {"artifacts": {"run_id": "sweep_1"}},
                },
            ],
            preferred_tool="simulation_run_parameter_sweep",
        ) == "sweep_1"

    def test_agent_fullflow_demo_compacts_artifact_lists(self):
        from scripts.run_agent_fullflow_demo import _compact_summaries

        compact = _compact_summaries([
            {
                "name": "artifact_inspection",
                "success": True,
                "observed_tools": ["simulation_search_artifacts"],
                "missing_calls": [],
                "missing_successes": [],
                "new_tool_results": [
                    {
                        "name": "simulation_search_artifacts",
                        "payload": {
                            "success": True,
                            "artifacts": [
                                {"run_id": "run_a"},
                                {"run_id": "run_b"},
                            ],
                        },
                    },
                    {
                        "name": "simulation_read_artifact",
                        "payload": {
                            "success": True,
                            "artifact": {"run_id": "run_a"},
                        },
                    },
                ],
            }
        ])

        artifacts = compact[0]["artifacts"]
        assert artifacts[0]["artifact_count"] == 2
        assert artifacts[0]["run_ids"] == ["run_a", "run_b"]
        assert artifacts[1]["run_id"] == "run_a"

    def test_simulation_rerun_artifact_replays_with_overrides(
        self,
        monkeypatch,
        tmp_path,
    ):
        import comsol_agent.tools.simulation as simulation_tools
        from comsol_agent.simulation.artifacts import persist_sweep_result

        archive_path = tmp_path / "archive.sqlite3"
        artifact_dir = tmp_path / "artifacts"
        source_artifact = persist_sweep_result(
            {
                "success": True,
                "model_name": "loaded",
                "source": {"type": "loaded_model", "model_name": "loaded"},
                "plan": {
                    "axes": [{"parameter": "L", "values": ["1[mm]"]}],
                    "output_expressions": ["T"],
                },
                "executed_cases": 1,
                "truncated": False,
                "cases": [
                    {
                        "success": True,
                        "case_index": 1,
                        "label": "L=1[mm]",
                        "parameters": {"L": "1[mm]"},
                        "solve": {"elapsed_seconds": 0.1, "status": "ok"},
                        "evaluations": [
                            {
                                "success": True,
                                "expression": "T",
                                "statistics": {"min": 0.0, "max": 1.0, "mean": 0.5},
                            }
                        ],
                    }
                ],
                "close": None,
                "tool_sequence": [],
            },
            output_dir=artifact_dir,
            run_name="source_replay",
            archive_path=archive_path,
        )
        calls = []
        monkeypatch.setattr(
            simulation_tools,
            "comsol_set_parameter",
            lambda model_name, name, value: calls.append(("set_parameter", model_name, name, value))
            or {"success": True, "model_name": model_name, "parameter": name, "value": value},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_solve",
            lambda model_name, study_name=None: calls.append(("solve", model_name, study_name))
            or {"success": True, "model_name": model_name, "elapsed_seconds": 0.1},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_evaluate",
            lambda model_name, expression: calls.append(("evaluate", model_name, expression))
            or {
                "success": True,
                "model_name": model_name,
                "expression": expression,
                "statistics": {"min": 0.0, "max": 2.0, "mean": 1.0},
            },
        )

        result = simulation_tools.simulation_rerun_artifact(
            source_artifact["run_id"],
            parameter_overrides={"L": ["2[mm]"]},
            artifact_name="rerun_unit",
            artifact_dir=str(artifact_dir),
            archive_path=str(archive_path),
        )

        assert result["success"] is True
        assert result["replay"]["source_run_id"] == source_artifact["run_id"]
        assert result["cases"][0]["parameters"] == {"L": "2[mm]"}
        assert result["artifacts"]["run_id"].startswith("rerun_unit")
        assert calls == [
            ("set_parameter", "loaded", "L", "2[mm]"),
            ("solve", "loaded", None),
            ("evaluate", "loaded", "T"),
        ]

    def test_build_template_replay_request_uses_archived_snapshot(self, tmp_path):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.simulation.artifacts import persist_template_execution_result
        from comsol_agent.simulation.replay import build_template_replay_request

        archive_path = tmp_path / "archive.sqlite3"
        source_artifact = persist_template_execution_result(
            {
                "success": True,
                "executed": True,
                "template_name": "thermal_seed",
                "model_name": "template_model",
                "source": {"type": "template", "name": "thermal_seed", "domain": "thermal"},
                "params": {"power": "10[W]"},
                "template": {
                    "name": "thermal_seed",
                    "domain": "thermal",
                    "params": {"power": "10[W]"},
                    "java_code": "model.param().set('power', power);",
                },
                "validation": {"status": "ok", "errors": [], "warnings": []},
                "create": {"success": True, "model_name": "template_model"},
                "execution": {"success": True, "stdout": "", "error": None},
                "tool_sequence": [
                    "comsol_create_model",
                    "simulation_validate_template",
                    "comsol_execute_java",
                    "comsol_close_model",
                ],
            },
            output_dir=tmp_path / "artifacts",
            run_name="template_replay_source",
            archive_path=archive_path,
        )

        replay = build_template_replay_request(
            ArchiveStore(archive_path),
            run_id=source_artifact["run_id"],
            params_overrides={"power": "20[W]"},
        )

        request = replay["request"]
        assert replay["source_run_id"] == source_artifact["run_id"]
        assert request["name"] == "thermal_seed"
        assert request["java_code"] == "model.param().set('power', power);"
        assert request["params"] == {"power": "20[W]"}
        assert request["create_model_name"] == "template_model"
        assert request["validate_first"] is True

    def test_build_generated_code_replay_request_uses_archived_snapshot(self, tmp_path):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.simulation.artifacts import persist_template_execution_result
        from comsol_agent.simulation.replay import build_template_replay_request

        archive_path = tmp_path / "archive.sqlite3"
        source_artifact = persist_template_execution_result(
            {
                "success": True,
                "executed": True,
                "template_name": "generated_bearing_seed",
                "model_name": "generated_model",
                "source": {"type": "raw_template", "name": "generated_bearing_seed", "domain": "structural"},
                "params": {"radial_load": "3000[N]"},
                "template": {
                    "name": "generated_bearing_seed",
                    "domain": "structural",
                    "params": {"radial_load": "3000[N]"},
                    "java_code": "model.component().create('comp1', true);",
                },
                "validation": {"status": "ok", "errors": [], "warnings": []},
                "create": {"success": True, "model_name": "generated_model"},
                "execution": {"success": True, "stdout": "", "error": None},
                "tool_sequence": [
                    "comsol_create_model",
                    "simulation_validate_template",
                    "comsol_execute_java",
                    "comsol_close_model",
                ],
            },
            output_dir=tmp_path / "artifacts",
            run_name="generated_code_replay_source",
            archive_path=archive_path,
            artifact_kind="generated_code_execution",
        )

        replay = build_template_replay_request(
            ArchiveStore(archive_path),
            run_id=source_artifact["run_id"],
            params_overrides={"radial_load": "3200[N]"},
        )

        request = replay["request"]
        assert replay["source_artifact"]["kind"] == "generated_code_execution"
        assert request["name"] == "generated_bearing_seed"
        assert request["java_code"] == "model.component().create('comp1', true);"
        assert request["params"] == {"radial_load": "3200[N]"}
        assert request["create_model_name"] == "generated_model"
        assert request["validate_first"] is True

    def test_simulation_rerun_artifact_dispatches_template_execution(
        self,
        monkeypatch,
        tmp_path,
    ):
        import comsol_agent.tools.simulation as simulation_tools
        from comsol_agent.simulation.artifacts import persist_template_execution_result

        archive_path = tmp_path / "archive.sqlite3"
        source_artifact = persist_template_execution_result(
            {
                "success": True,
                "executed": True,
                "template_name": "thermal_seed",
                "model_name": "template_model",
                "source": {"type": "template", "name": "thermal_seed", "domain": "thermal"},
                "params": {"power": "10[W]"},
                "template": {
                    "name": "thermal_seed",
                    "domain": "thermal",
                    "params": {"power": "10[W]"},
                    "java_code": "model.param().set('power', power);",
                },
                "validation": {"status": "ok", "errors": [], "warnings": []},
                "create": {"success": True, "model_name": "template_model"},
                "execution": {"success": True},
                "tool_sequence": ["comsol_create_model", "comsol_execute_java"],
            },
            output_dir=tmp_path / "artifacts",
            run_name="template_dispatch_source",
            archive_path=archive_path,
        )
        captured = {}

        def fake_run_template(**kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "executed": True,
                "model_name": kwargs.get("create_model_name"),
                "template_name": kwargs.get("name"),
            }

        monkeypatch.setattr(simulation_tools, "simulation_run_template", fake_run_template)

        result = simulation_tools.simulation_rerun_artifact(
            source_artifact["run_id"],
            params_overrides={"power": "25[W]"},
            create_model_name="template_model_replay",
            artifact_name="template_replay",
            artifact_dir=str(tmp_path / "reruns"),
            archive_path=str(archive_path),
        )

        assert result["success"] is True
        assert result["replay"]["source_run_id"] == source_artifact["run_id"]
        assert captured["name"] == "thermal_seed"
        assert captured["params"] == {"power": "25[W]"}
        assert captured["create_model_name"] == "template_model_replay"
        assert captured["artifact_name"] == "template_replay"

    def test_simulation_export_artifact_report_handles_template_execution(self, tmp_path):
        from comsol_agent.simulation.artifacts import persist_template_execution_result
        from comsol_agent.tools.simulation import (
            simulation_export_artifact_report,
            simulation_read_artifact,
            simulation_search_artifacts,
        )

        archive_path = tmp_path / "archive.sqlite3"
        artifact_dir = tmp_path / "artifacts"
        persist_template_execution_result(
            {
                "success": True,
                "executed": True,
                "template_name": "thermal_seed",
                "model_name": "template_model_ok",
                "source": {"type": "template", "name": "thermal_seed", "domain": "thermal"},
                "params": {"power": "10[W]"},
                "template": {
                    "name": "thermal_seed",
                    "domain": "thermal",
                    "params": {"power": "10[W]"},
                    "java_code": "model.param().set('power', power);",
                },
                "validation": {"status": "ok", "errors": [], "warnings": []},
                "execution": {"success": True},
                "tool_sequence": ["comsol_execute_java"],
            },
            output_dir=artifact_dir,
            run_name="template_report_ok",
            archive_path=archive_path,
        )
        persist_template_execution_result(
            {
                "success": False,
                "executed": True,
                "template_name": "thermal_seed",
                "model_name": "template_model_fail",
                "source": {"type": "template", "name": "thermal_seed", "domain": "thermal"},
                "params": {"power": "bad"},
                "template": {
                    "name": "thermal_seed",
                    "domain": "thermal",
                    "params": {"power": "bad"},
                    "java_code": "model.param().set('power', power);",
                },
                "validation": {"status": "ok", "errors": [], "warnings": []},
                "execution": {
                    "success": False,
                    "error": "Unknown parameter",
                    "error_type": "api_error",
                },
                "tool_sequence": ["comsol_execute_java"],
            },
            output_dir=artifact_dir,
            run_name="template_report_fail",
            archive_path=archive_path,
        )

        result = simulation_export_artifact_report(
            query="template_report_",
            kind="template_execution",
            output_dir=str(tmp_path / "reports"),
            report_name="template_report",
            output_format="html",
            archive_path=str(archive_path),
        )

        report_path = Path(result["report"]["path"])
        html_path = Path(result["report"]["html_path"])
        content = report_path.read_text(encoding="utf-8")
        assert result["success"] is True
        assert result["kind"] == "template_execution"
        assert result["summary"]["run_count"] == 2
        assert result["summary"]["success_count"] == 1
        assert result["summary"]["failure_count"] == 1
        assert result["report"]["archive"]["kind"] == "template_execution_report"
        assert "# COMSOL Template Execution Report" in content
        assert "template_model_fail" in content
        assert "<!doctype html>" in html_path.read_text(encoding="utf-8")

        search_result = simulation_search_artifacts(
            query="template_report",
            archive_path=str(archive_path),
        )
        assert search_result["success"] is True
        assert any(item["kind"] == "template_execution_report" for item in search_result["artifacts"])

        read_result = simulation_read_artifact(
            run_id=result["report"]["report_id"],
            archive_path=str(archive_path),
            max_lines=5,
        )
        assert read_result["success"] is True
        assert read_result["artifact"]["kind"] == "template_execution_report"
        assert read_result["preview"]["markdown"]["lines"][0] == "# COMSOL Template Execution Report"

    def test_simulation_export_artifact_report_handles_generated_code_execution(self, tmp_path):
        from comsol_agent.simulation.artifacts import persist_template_execution_result
        from comsol_agent.tools.simulation import (
            simulation_export_artifact_report,
            simulation_read_artifact,
            simulation_search_artifacts,
        )

        archive_path = tmp_path / "archive.sqlite3"
        artifact_dir = tmp_path / "artifacts"
        persist_template_execution_result(
            {
                "success": True,
                "executed": True,
                "template_name": "generated_bearing_seed",
                "model_name": "generated_model_ok",
                "source": {"type": "raw_template", "name": "generated_bearing_seed", "domain": "structural"},
                "params": {"radial_load": "3000[N]"},
                "template": {
                    "name": "generated_bearing_seed",
                    "domain": "structural",
                    "params": {"radial_load": "3000[N]"},
                    "java_code": "model.component().create('comp1', true);",
                },
                "execution_context": {
                    "workflow": "bearing_3d_generated_code_agent_execution",
                    "draft_quality": {"success": True, "quality_level": "production_candidate"},
                    "repair_history": [{"stage": "offline_runtime_preflight_repair", "success": True}],
                    "selection_binding_audit": {"success": True, "runtime_checked": True},
                    "physical_result_audit": {
                        "success": True,
                        "quality_level": "production_physics_gate",
                        "production_ready": True,
                    },
                    "contact_convergence_report": {
                        "success": True,
                        "quality_level": "contact_runtime_convergence_checked",
                        "runtime_verified": True,
                    },
                },
                "validation": {"status": "ok", "errors": [], "warnings": []},
                "execution": {"success": True},
                "tool_sequence": ["comsol_execute_java"],
            },
            output_dir=artifact_dir,
            run_name="generated_report_ok",
            archive_path=archive_path,
            artifact_kind="generated_code_execution",
        )
        persist_template_execution_result(
            {
                "success": False,
                "executed": True,
                "template_name": "generated_bearing_seed",
                "model_name": "generated_model_fail",
                "source": {"type": "raw_template", "name": "generated_bearing_seed", "domain": "structural"},
                "params": {"radial_load": "bad"},
                "template": {
                    "name": "generated_bearing_seed",
                    "domain": "structural",
                    "params": {"radial_load": "bad"},
                    "java_code": "model.component().create('comp1', true);",
                },
                "execution_context": {
                    "workflow": "bearing_3d_generated_code_agent_execution",
                    "draft_quality": {"success": False, "quality_level": "smoke"},
                    "selection_binding_audit": {"success": False, "runtime_checked": False},
                    "physical_result_audit": {
                        "success": False,
                        "quality_level": "failed_physics_gate",
                        "production_ready": False,
                    },
                    "contact_convergence_report": {
                        "success": False,
                        "quality_level": "contact_smoke_convergence_unverified",
                        "runtime_verified": False,
                    },
                    "repair_history": [
                        {"stage": "offline_runtime_preflight_repair", "success": True},
                        {"stage": "simulation_run_template", "success": False},
                    ],
                },
                "validation": {"status": "ok", "errors": [], "warnings": []},
                "execution": {
                    "success": False,
                    "error": "Unknown pair selection",
                    "error_type": "api_error",
                },
                "tool_sequence": ["comsol_execute_java"],
            },
            output_dir=artifact_dir,
            run_name="generated_report_fail",
            archive_path=archive_path,
            artifact_kind="generated_code_execution",
        )

        result = simulation_export_artifact_report(
            query="generated_report_",
            kind="generated_code_execution",
            output_dir=str(tmp_path / "reports"),
            report_name="generated_code_report",
            output_format="html",
            archive_path=str(archive_path),
        )

        report_path = Path(result["report"]["path"])
        html_path = Path(result["report"]["html_path"])
        content = report_path.read_text(encoding="utf-8")
        assert result["success"] is True
        assert result["kind"] == "generated_code_execution"
        assert result["summary"]["run_count"] == 2
        assert result["summary"]["success_count"] == 1
        assert result["summary"]["failure_count"] == 1
        ok_run = next(run for run in result["summary"]["runs"] if run["model_name"] == "generated_model_ok")
        assert ok_run["selection_binding_runtime_checked"] is True
        assert ok_run["physical_result_production_ready"] is True
        assert ok_run["physical_result_quality_level"] == "production_physics_gate"
        assert ok_run["contact_runtime_verified"] is True
        assert result["report"]["archive"]["kind"] == "generated_code_execution_report"
        assert "# COMSOL Generated-Code Execution Report" in content
        assert "generated_model_fail" in content
        assert "Binding Runtime" in content
        assert "Physics Gate" in content
        assert "Contact Runtime" in content
        assert "production_physics_gate" in content
        assert "bearing_3d_generated_code_agent_execution" in content
        assert "contact_runtime_convergence_checked" in content
        assert "contact_smoke_convergence_unverified" in content
        assert "<!doctype html>" in html_path.read_text(encoding="utf-8")

        search_result = simulation_search_artifacts(
            query="generated_code_report",
            archive_path=str(archive_path),
        )
        assert search_result["success"] is True
        assert any(item["kind"] == "generated_code_execution_report" for item in search_result["artifacts"])

        read_result = simulation_read_artifact(
            run_id=result["report"]["report_id"],
            archive_path=str(archive_path),
            max_lines=5,
        )
        assert read_result["success"] is True
        assert read_result["artifact"]["kind"] == "generated_code_execution_report"
        assert read_result["preview"]["markdown"]["lines"][0] == "# COMSOL Generated-Code Execution Report"

    def test_simulation_run_parameter_sweep_loads_and_closes_example(
        self,
        monkeypatch,
        tmp_path,
    ):
        import comsol_agent.tools.simulation as simulation_tools
        from comsol_agent.simulation.examples import SimulationExample

        calls = []
        fake_example = SimulationExample(
            name="fake_example",
            domain="thermal",
            description="Fake example",
            model_path=str(tmp_path / "fake.mph"),
            default_expression="T",
        )
        Path(fake_example.model_path).write_text("fake", encoding="utf-8")

        monkeypatch.setattr(simulation_tools, "get_example", lambda name: fake_example)
        monkeypatch.setattr(
            simulation_tools,
            "comsol_load_model",
            lambda path: calls.append(("load", path)) or {"success": True, "model_name": "fake"},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_set_parameter",
            lambda model_name, name, value: calls.append(("set_parameter", model_name, name, value))
            or {"success": True, "model_name": model_name, "parameter": name, "value": value},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_solve",
            lambda model_name, study_name=None: calls.append(("solve", model_name, study_name))
            or {"success": True, "model_name": model_name},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_evaluate",
            lambda model_name, expression: calls.append(("evaluate", model_name, expression))
            or {"success": True, "model_name": model_name, "expression": expression, "value": 42},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_close_model",
            lambda model_name, save=False: calls.append(("close", model_name, save))
            or {"success": True},
        )

        result = simulation_tools.simulation_run_parameter_sweep(
            example_name="fake_example",
            parameters={"L": ["1[mm]"]},
        )

        assert result["success"] is True
        assert result["example"]["name"] == "fake_example"
        assert result["cases"][0]["evaluations"][0]["value"] == 42
        assert result["tool_sequence"] == [
            "comsol_load_model",
            "comsol_set_parameter",
            "comsol_solve",
            "comsol_evaluate",
            "comsol_close_model",
        ]
        assert calls == [
            ("load", fake_example.model_path),
            ("set_parameter", "fake", "L", "1[mm]"),
            ("solve", "fake", None),
            ("evaluate", "fake", "T"),
            ("close", "fake", False),
        ]


class TestLocalDocsSearch:
    """Tests for offline local documentation search."""

    def test_build_index_from_directory_searches_workspace_docs(self):
        from comsol_agent.simulation.local_docs import build_index_from_directory

        index = build_index_from_directory("docs")
        results = index.search("LLMRouter fallback", limit=3)

        assert results
        assert results[0].score > 0
        assert "architecture.md" in results[0].chunk.source
        assert results[0].chunk.title
        assert "LLMRouter" in results[0].chunk.content
        assert "llmrouter" in results[0].matched_terms

    def test_simulation_search_local_docs_tool(self):
        from comsol_agent.tools.simulation import simulation_search_local_docs

        result = simulation_search_local_docs(
            query="ToolDefinition format",
            directory="docs",
            max_results=2,
        )

        assert result["success"] is True
        assert result["count"] >= 1
        assert len(result["results"]) <= 2
        assert any(
            item["chunk"]["source"].endswith("architecture.md")
            for item in result["results"]
        )
        assert "Offline keyword search" in result["note"]

    def test_local_docs_index_extracts_api_metadata(self, tmp_path, monkeypatch):
        from comsol_agent.simulation.local_docs import build_index_from_directory

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "comsol_api.md").write_text(
            "# COMSOL 6.2 Thermal API\n\n"
            "Use model.param().set('power', '10[W]') before Heat Transfer solve.\n"
            "The comsol_execute_java tool can run model.geom().create() snippets.\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        index = build_index_from_directory("docs")
        snippets = index.retrieve_api_docs("model.param().set thermal", limit=1)

        assert snippets
        snippet = snippets[0]
        assert snippet["citation"].endswith("comsol_api:1")
        assert snippet["domain"] == "thermal"
        assert "6.2" in snippet["comsol_versions"]
        assert "model.param().set()" in snippet["api_symbols"]
        assert "model.geom().create()" in snippet["api_symbols"]
        assert "model.param().set()" in snippet["metadata"]["api_functions"]
        assert "model.param().set" in snippet["snippet"]

    def test_simulation_retrieve_api_docs_tool_returns_cited_snippets(self):
        from comsol_agent.tools.simulation import simulation_retrieve_api_docs

        result = simulation_retrieve_api_docs(
            query="model.param().set Java API",
            directory="docs",
            max_results=3,
        )

        assert result["success"] is True
        assert result["count"] >= 1
        first = result["snippets"][0]
        assert first["citation"]
        assert first["source"].endswith(".md")
        assert first["snippet"]
        assert "metadata" in first
        assert "Offline local retrieval" in result["note"]

    def test_simulation_plan_generated_code_returns_controlled_prompt(self, tmp_path, monkeypatch):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.tools.simulation import simulation_plan_generated_code

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "thermal_api.md").write_text(
            "# COMSOL thermal setup\n\n"
            "Use model.param().set('power', '10[W]') and create Heat Transfer physics with model.component('comp1').physics().create('ht', 'HeatTransfer', 'geom1').\n"
            "Create geometry with model.component('comp1').geom('geom1').create('r1', 'Rectangle').\n",
            encoding="utf-8",
        )
        archive_path = tmp_path / "archive.sqlite3"
        ArchiveStore(archive_path).add_template(
            name="thermal_plate_seed",
            domain="thermal",
            java_code="model.param().set('power', '10[W]');",
            params={"power": "10[W]"},
        )
        monkeypatch.chdir(tmp_path)

        result = simulation_plan_generated_code(
            user_request="Build a custom thermal model for a plate with a heat source and plot temperature",
            known_params={
                "geometry": "2D plate 10[mm] by 5[mm]",
                "physics": "Heat Transfer",
                "material": "copper",
                "boundary_conditions": "left edge fixed temperature, heat source in center",
                "study_type": "stationary",
                "outputs": "max temperature and temperature plot",
                "power": "10[W]",
            },
            domain="thermal",
            allow_defaults=False,
            archive_path=str(archive_path),
            docs_directory="docs",
        )

        assert result["success"] is True
        assert result["mode"] == "generated_code_fallback"
        assert result["ready_to_generate"] is True
        assert result["validation_params"] == {"power": "10[W]"}
        assert result["template_policy"]["candidate_count"] == 1
        assert result["retrieval"]["count"] >= 1
        prompt = result["controlled_prompt_block"]
        assert "Return ONLY executable COMSOL Java/API code" in prompt
        assert "simulation_validate_template" in prompt
        assert "model.param().set" in prompt
        assert "unit parameter subset" in prompt
        assert result["safety"]["generated_code_is_untrusted_until_validated"] is True

    def test_simulation_plan_generated_code_asks_for_missing_decisions(self):
        from comsol_agent.tools.simulation import simulation_plan_generated_code

        result = simulation_plan_generated_code(
            user_request="帮我做一个新的仿真模型",
            known_params={},
            allow_defaults=False,
            max_doc_results=1,
        )

        assert result["success"] is True
        assert result["ready_to_generate"] is False
        assert "geometry" in result["missing_decisions"]
        assert result["follow_up_questions"]
        assert "Do not invent missing problem-defining values" in result["controlled_prompt_block"]

        defaulted = simulation_plan_generated_code(
            user_request="先用默认值做一个新的仿真模型",
            known_params={},
            allow_defaults=True,
            max_doc_results=1,
        )

        assert defaulted["success"] is True
        assert defaulted["ready_to_generate"] is True
        assert defaulted["missing_decisions"] == []
        assert "You may fill missing low-risk values" in defaulted["controlled_prompt_block"]

    def test_local_docs_search_rejects_outside_workspace_directory(self):
        from comsol_agent.tools.simulation import simulation_search_local_docs

        result = simulation_search_local_docs(
            query="anything",
            directory="/private/tmp",
        )

        assert result["success"] is False
        assert "inside the workspace" in result["error"]


class TestSimulationExamples:
    """Tests for built-in simulation example tools."""

    def test_list_examples_filters_by_domain(self):
        from comsol_agent.tools.simulation import simulation_list_example_models

        result = simulation_list_example_models(domain="thermal")

        assert result["success"] is True
        assert result["count"] >= 1
        assert any(example["name"] == "thermal_slab" for example in result["examples"])
        assert all(example["domain"] == "thermal" for example in result["examples"])

    def test_run_example_model_composes_comsol_tools(self, monkeypatch, tmp_path):
        import comsol_agent.tools.simulation as simulation_tools
        from comsol_agent.simulation.examples import SimulationExample

        calls = []
        fake_example = SimulationExample(
            name="fake_example",
            domain="thermal",
            description="Fake example",
            model_path=str(tmp_path / "fake.mph"),
            default_expression="T",
        )
        Path(fake_example.model_path).write_text("fake", encoding="utf-8")

        monkeypatch.setattr(simulation_tools, "get_example", lambda name: fake_example)
        monkeypatch.setattr(
            simulation_tools,
            "comsol_load_model",
            lambda path: calls.append(("load", path)) or {"success": True, "model_name": "fake"},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_get_model_summary",
            lambda model_name: calls.append(("summary", model_name))
            or {"success": True, "model_name": model_name, "summary": "ok"},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_set_parameter",
            lambda model_name, name, value: calls.append(("set_parameter", model_name, name, value))
            or {"success": True, "model_name": model_name, "parameter": name, "value": value},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_solve",
            lambda model_name, study_name=None: calls.append(("solve", model_name, study_name))
            or {"success": True, "model_name": model_name},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_evaluate",
            lambda model_name, expression: calls.append(("evaluate", model_name, expression))
            or {"success": True, "model_name": model_name, "expression": expression},
        )
        monkeypatch.setattr(
            simulation_tools,
            "comsol_close_model",
            lambda model_name, save=False: calls.append(("close", model_name, save))
            or {"success": True},
        )

        result = simulation_tools.simulation_run_example_model(
            "fake_example",
            expressions=["T", "ht.qx"],
            parameters={"L": "1[mm]"},
        )

        assert result["success"] is True
        assert result["model_name"] == "fake"
        assert len(result["parameters"]) == 1
        assert len(result["evaluations"]) == 2
        assert result["evaluation"]["expression"] == "T"
        assert result["tool_sequence"] == [
            "comsol_load_model",
            "comsol_get_model_summary",
            "comsol_set_parameter",
            "comsol_solve",
            "comsol_evaluate",
            "comsol_close_model",
        ]
        assert calls == [
            ("load", fake_example.model_path),
            ("summary", "fake"),
            ("set_parameter", "fake", "L", "1[mm]"),
            ("solve", "fake", None),
            ("evaluate", "fake", "T"),
            ("evaluate", "fake", "ht.qx"),
            ("close", "fake", False),
        ]

    def test_normalize_expressions_preserves_legacy_input_and_deduplicates(self):
        from comsol_agent.tools.simulation import _normalize_expressions

        assert _normalize_expressions(
            expression="T",
            expressions=["T", "ht.qx"],
            default_expression="solid.disp",
        ) == ["T", "ht.qx"]
        assert _normalize_expressions(
            expression=None,
            expressions=None,
            default_expression="T",
        ) == ["T"]


class TestCOMSOLRuntimeConfig:
    """Tests for COMSOL runtime configuration guardrails."""

    def test_run_doctor_returns_structured_checks(self, tmp_path, monkeypatch):
        from comsol_agent.cli.config import Config
        from comsol_agent.diagnostics import run_doctor

        config = Config()
        config.llm.provider = "deepseek"
        config.llm.model = "deepseek-v4-flash"
        config.llm.api_key = "sk-test"
        config.comsol.executable_path = str(tmp_path / "missing-comsol")
        monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,166.111.237.134")

        result = run_doctor(config)
        checks = {check["name"]: check for check in result["checks"]}

        assert result["status"] in {"ok", "warn", "fail"}
        assert "llm" in checks
        assert checks["llm"]["details"]["api_key_present"] is True
        assert checks["comsol_config"]["status"] == "fail"
        assert checks["proxy"]["details"]["direct_target_present"] is True

    @pytest.mark.asyncio
    async def test_run_deep_doctor_can_check_llm_without_comsol(self, monkeypatch):
        from collections.abc import AsyncIterator
        from typing import Any

        import comsol_agent.llm.router as router
        from comsol_agent.cli.config import Config
        from comsol_agent.diagnostics import run_deep_doctor
        from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolDefinition

        captured = {}

        class FakeProvider(LLMProvider):
            async def generate(
                self,
                messages: list[dict[str, Any]],
                tools: list[ToolDefinition] | None = None,
                **kwargs: Any,
            ) -> LLMResponse:
                captured.update(kwargs)
                return LLMResponse(
                    text="COMSOL Agent LLM OK",
                    finish_reason="stop",
                    usage={"total_tokens": 4},
                )

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

        monkeypatch.setattr(router, "create_provider", lambda *args, **kwargs: FakeProvider("fake"))

        config = Config()
        config.llm.provider = "deepseek"
        config.llm.model = "deepseek-v4-flash"
        config.llm.api_key = "sk-test"
        result = await run_deep_doctor(
            config,
            check_llm=True,
            check_comsol=False,
            timeout_seconds=1,
        )
        checks = {check["name"]: check for check in result["checks"]}

        assert result["deep"] is True
        assert checks["llm_api"]["status"] == "ok"
        assert checks["llm_api"]["details"]["usage"] == {"total_tokens": 4}
        assert captured["extra_body"] == {"thinking": {"type": "disabled"}}

    def test_comsol_client_validates_configured_executable_before_mph_import(self, tmp_path):
        from comsol_agent.tools.comsol.client import COMSOLClient

        COMSOLClient.reset_instance()
        client = COMSOLClient.get_instance()
        missing = tmp_path / "missing-comsol"

        with pytest.raises(FileNotFoundError, match="Configured COMSOL executable not found"):
            client.start(executable_path=missing)

        assert client.is_running is False
        COMSOLClient.reset_instance()

    def test_comsol_parameter_tools_use_mph_parameter_api(self):
        from comsol_agent.tools.comsol.client import COMSOLClient, ModelHandle
        from comsol_agent.tools.comsol.model_ops import (
            comsol_list_parameters,
            comsol_set_parameter,
        )

        class FakeMPhModel:
            def __init__(self):
                self.values = {}

            def parameter(self, name, value=None, *, evaluate=False):
                if value is None:
                    return self.values[name]
                self.values[name] = value
                return None

            def parameters(self, evaluate=False):
                return dict(self.values)

        COMSOLClient.reset_instance()
        client = COMSOLClient.get_instance()
        client._started = True
        client._mph_client = object()
        client._models["fake"] = ModelHandle(name="fake", mph_model=FakeMPhModel())

        set_result = comsol_set_parameter("fake", "L", "1[mm]")
        list_result = comsol_list_parameters("fake")

        assert set_result["success"] is True
        assert list_result["success"] is True
        assert list_result["parameters"] == [
            {"name": "L", "value": "1[mm]", "description": ""}
        ]
        COMSOLClient.reset_instance()

    def test_comsol_execute_java_strips_java_comments_and_runs_multiline_code(self):
        from comsol_agent.tools.comsol.client import COMSOLClient, ModelHandle

        class FakeJavaModel:
            def __init__(self):
                self.values = {}

            def param(self):
                return self

            def set(self, name, value):
                self.values[name] = value

        COMSOLClient.reset_instance()
        client = COMSOLClient.get_instance()
        fake_model = FakeJavaModel()
        client._started = True
        client._mph_client = object()
        client._models["fake"] = ModelHandle(name="fake", java_model=fake_model)

        output = client.execute_java(
            "model.param().set('power', '10[W]');\n"
            "model.param().set('T_ambient', '293.15[K]');\n"
            "// Add geometry, material, physics, mesh, and study before solve.",
            model_name="fake",
        )

        assert output == "Code executed successfully (no output)."
        assert fake_model.values == {
            "power": "10[W]",
            "T_ambient": "293.15[K]",
        }
        COMSOLClient.reset_instance()

    def test_comsol_execute_java_tool_returns_structured_success(self):
        from comsol_agent.tools.comsol.client import COMSOLClient, ModelHandle
        from comsol_agent.tools.comsol.solve import comsol_execute_java

        class FakeJavaModel:
            def __init__(self):
                self.values = {}

            def param(self):
                return self

            def set(self, name, value):
                self.values[name] = value

        COMSOLClient.reset_instance()
        client = COMSOLClient.get_instance()
        fake_model = FakeJavaModel()
        client._started = True
        client._mph_client = object()
        client._models["fake"] = ModelHandle(name="fake", java_model=fake_model)

        result = comsol_execute_java(
            "model.param().set('power', '10[W]');",
            model_name="fake",
        )

        assert result["success"] is True
        assert result["stdout"] == "Code executed successfully (no output)."
        assert result["error"] is None
        assert result["exception_type"] is None
        assert result["error_type"] is None
        assert result["modified"] is True
        assert client.get_model("fake").is_modified is True
        COMSOLClient.reset_instance()

    def test_comsol_execute_java_tool_classifies_api_errors(self):
        from comsol_agent.tools.comsol.client import COMSOLClient, ModelHandle
        from comsol_agent.tools.comsol.solve import comsol_execute_java

        COMSOLClient.reset_instance()
        client = COMSOLClient.get_instance()
        client._started = True
        client._mph_client = object()
        client._models["fake"] = ModelHandle(name="fake", java_model=object())

        result = comsol_execute_java("model.no_such_method();", model_name="fake")

        assert result["success"] is False
        assert result["stdout"] == ""
        assert result["exception_type"] == "AttributeError"
        assert result["error_type"] == "API_ERROR"
        assert "no_such_method" in result["error"]
        assert result["modified"] is True
        COMSOLClient.reset_instance()

    def test_comsol_execute_java_tool_can_validate_before_execution(self):
        from comsol_agent.tools.comsol.solve import comsol_execute_java

        result = comsol_execute_java("System.exit(0);", validate_first=True)

        assert result["success"] is False
        assert result["exception_type"] == "ValidationError"
        assert result["error_type"] == "VALIDATION_ERROR"
        assert result["modified"] is False
        assert any("System.exit" in error for error in result["validation"]["errors"])

    def test_comsol_evaluate_array_sample_is_flat_and_compact(self):
        np = pytest.importorskip("numpy")
        from comsol_agent.tools.comsol.solve import _sample_array

        sample = _sample_array(np.arange(24).reshape(3, 8), max_values=6)

        assert sample == [0, 1, 2, "...", 21, 22, 23]

    def test_comsol_plot_falls_back_to_java_image_export(self, tmp_path):
        from comsol_agent.tools.comsol.client import COMSOLClient, ModelHandle
        from comsol_agent.tools.comsol.evaluate import comsol_plot

        class FakeMPhModel:
            def export(self, export_type, filepath):
                raise RuntimeError('Node "exports/image" does not exist in model tree.')

        class FakeExportFeature:
            def __init__(self):
                self.values = {}

            def set(self, key, value):
                self.values[key] = value

            def run(self):
                Path(self.values["pngfilename"]).write_bytes(b"\x89PNG\r\n\x1a\n")

        class FakeExportList:
            def __init__(self):
                self.features = {}

            def tags(self):
                return list(self.features)

            def create(self, tag, export_type):
                self.features[tag] = FakeExportFeature()

            def remove(self, tag):
                self.features.pop(tag, None)

        class FakePlotGroup:
            def __init__(self, tag):
                self.tag = tag
                self.features = {}
                self.ran = False

            def getType(self):
                return "PlotGroup2D"

            def create(self, tag, feature_type):
                self.features[tag] = FakePlotFeature(feature_type)

            def feature(self, tag):
                return self.features[tag]

            def run(self):
                self.ran = True

        class FakePlotFeature:
            def __init__(self, feature_type):
                self.feature_type = feature_type
                self.values = {}

            def set(self, key, value):
                self.values[key] = value

        class FakeNumericalResult:
            def getType(self):
                return "MaxVolume"

        class FakeResult:
            def __init__(self):
                self.exports = FakeExportList()
                self.nodes = {"max_von_mises": FakeNumericalResult()}

            def tags(self):
                return list(self.nodes)

            def create(self, tag, result_type):
                self.nodes[tag] = FakePlotGroup(tag)

            def export(self, tag=None):
                if tag is None:
                    return self.exports
                return self.exports.features[tag]

        class FakeJavaModel:
            def __init__(self):
                self.fake_result = FakeResult()

            def result(self, tag=None):
                if tag is not None:
                    return self.fake_result.nodes[tag]
                return self.fake_result

        COMSOLClient.reset_instance()
        client = COMSOLClient.get_instance()
        client._started = True
        client._mph_client = object()
        client._models["fake"] = ModelHandle(
            name="fake",
            java_model=FakeJavaModel(),
            mph_model=FakeMPhModel(),
        )

        target = tmp_path / "plot.png"
        result = comsol_plot("fake", expression="solid.mises", filename=str(target))

        assert result["success"] is True
        assert result["export_method"] == "java:Image2D"
        assert client._models["fake"].java_model.fake_result.nodes["pg_codex"].ran is True
        assert (
            client._models["fake"]
            .java_model.fake_result.nodes["pg_codex"]
            .features["plot_codex"]
            .values["expr"]
            == "solid.mises"
        )
        assert target.read_bytes().startswith(b"\x89PNG")
        COMSOLClient.reset_instance()

    def test_comsol_plot_creates_3d_plot_group_for_3d_models(self, tmp_path):
        from comsol_agent.tools.comsol.client import COMSOLClient, ModelHandle
        from comsol_agent.tools.comsol.evaluate import comsol_plot

        class FakeMPhModel:
            def export(self, export_type, filepath):
                raise RuntimeError('Node "exports/image" does not exist in model tree.')

        class FakeExportFeature:
            def __init__(self):
                self.values = {}

            def set(self, key, value):
                self.values[key] = value

            def run(self):
                Path(self.values["pngfilename"]).write_bytes(b"\x89PNG\r\n\x1a\n")

        class FakeExportList:
            def __init__(self):
                self.features = {}

            def tags(self):
                return list(self.features)

            def create(self, tag, export_type):
                self.features[tag] = FakeExportFeature()

            def remove(self, tag):
                self.features.pop(tag, None)

        class FakePlotGroup:
            def __init__(self, result_type):
                self.result_type = result_type
                self.features = {}
                self.ran = False

            def getType(self):
                return self.result_type

            def create(self, tag, feature_type):
                self.features[tag] = FakePlotFeature(feature_type)

            def feature(self, tag):
                return self.features[tag]

            def run(self):
                self.ran = True

        class FakePlotFeature:
            def __init__(self, feature_type):
                self.feature_type = feature_type
                self.values = {}

            def set(self, key, value):
                self.values[key] = value

        class FakeResult:
            def __init__(self):
                self.exports = FakeExportList()
                self.nodes = {}

            def tags(self):
                return list(self.nodes)

            def create(self, tag, result_type):
                self.nodes[tag] = FakePlotGroup(result_type)

            def export(self, tag=None):
                if tag is None:
                    return self.exports
                return self.exports.features[tag]

        class FakeGeomList:
            def tags(self):
                return ["geom1"]

        class FakeGeom:
            def getSDim(self):
                return 3

        class FakeJavaModel:
            def __init__(self):
                self.fake_result = FakeResult()

            def result(self, tag=None):
                if tag is not None:
                    return self.fake_result.nodes[tag]
                return self.fake_result

            def geom(self, tag=None):
                if tag is None:
                    return FakeGeomList()
                return FakeGeom()

        COMSOLClient.reset_instance()
        client = COMSOLClient.get_instance()
        client._started = True
        client._mph_client = object()
        client._models["fake3d"] = ModelHandle(
            name="fake3d",
            java_model=FakeJavaModel(),
            mph_model=FakeMPhModel(),
        )

        target = tmp_path / "plot.png"
        result = comsol_plot("fake3d", expression="solid.mises", filename=str(target))

        assert result["success"] is True
        plot_group = client._models["fake3d"].java_model.fake_result.nodes["pg_codex"]
        assert plot_group.getType() == "PlotGroup3D"
        assert plot_group.features["plot_codex"].values["expr"] == "solid.mises"
        assert target.read_bytes().startswith(b"\x89PNG")
        COMSOLClient.reset_instance()


class TestFileOps:
    """Tests for file and shell safety boundaries."""

    @pytest.mark.asyncio
    async def test_file_read_uses_allowed_paths_and_line_numbers(self, tmp_path, monkeypatch):
        from comsol_agent.tools.file_ops import file_read

        sample = tmp_path / "sample.txt"
        sample.write_text("alpha\nbeta\n", encoding="utf-8")
        monkeypatch.setenv("COMSOL_AGENT_ALLOWED_PATHS", str(tmp_path))

        result = await file_read(str(sample))

        assert result["success"] is True
        assert "1 | alpha" in result["content"]
        assert "2 | beta" in result["content"]

    @pytest.mark.asyncio
    async def test_file_read_rejects_paths_outside_allowed_roots(self, tmp_path, monkeypatch):
        from comsol_agent.tools.file_ops import file_read

        sample = tmp_path / "outside.txt"
        sample.write_text("secret\n", encoding="utf-8")
        monkeypatch.delenv("COMSOL_AGENT_ALLOWED_PATHS", raising=False)

        result = await file_read(str(sample))

        assert result["success"] is False
        assert "outside allowed roots" in result["error"]

    @pytest.mark.asyncio
    async def test_shell_execute_rejects_privileged_and_dangerous_commands(self):
        from comsol_agent.tools.file_ops import shell_execute

        sudo_result = await shell_execute("sudo whoami")
        rm_result = await shell_execute("rm -rf /")

        assert sudo_result["success"] is False
        assert "Privileged" in sudo_result["error"]
        assert rm_result["success"] is False
        assert "Dangerous recursive deletion" in rm_result["error"]

    @pytest.mark.asyncio
    async def test_shell_execute_uses_allowed_working_dir(self, tmp_path, monkeypatch):
        from comsol_agent.tools.file_ops import shell_execute

        monkeypatch.setenv("COMSOL_AGENT_ALLOWED_PATHS", str(tmp_path))

        result = await shell_execute("pwd", working_dir=str(tmp_path))

        assert result["success"] is True
        assert result["stdout"] == str(tmp_path)
