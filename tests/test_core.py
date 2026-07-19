"""Basic tests for COMSOL Agent core modules.

These tests verify imports, configuration loading, and basic agent logic.
COMSOL-specific tests require a local COMSOL installation and are marked accordingly.
"""

from __future__ import annotations

import json
import re
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
        assert "simulation_plan_bearing_modeling_request" in names
        assert "simulation_plan_bearing_contact" in names
        assert "simulation_plan_multiroller_bearing" in names
        assert "simulation_probe_3d_selection_binding" in names
        assert "simulation_plan_modeling_request" in names
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
        assert "simulation_plan_bearing_modeling_request" in prompt
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
    async def test_requirement_state_enriches_generated_code_known_params(self):
        from collections.abc import AsyncIterator
        from typing import Any

        from comsol_agent.agent.loop import AgentLoop
        from comsol_agent.agent.tools_bootstrap import register_all_tools
        from comsol_agent.cli.config import Config
        from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolCall, ToolDefinition

        register_all_tools()

        class GeneratedCodeProvider(LLMProvider):
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
                                id="call_plan",
                                name="simulation_plan_generated_code",
                                arguments={
                                    "user_request": "继续生成代码",
                                    "allow_defaults": False,
                                    "max_doc_results": 1,
                                },
                            )
                        ]
                    )
                return LLMResponse(text="Planned with remembered requirements.")

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

        agent = AgentLoop(GeneratedCodeProvider(), Config())
        response = await agent.run(
            "做一个3D圆柱滚子轴承结构仿真，材料用钢，固定内圈，外圈加1000[N]载荷，输出von Mises应力"
        )

        tool_messages = [msg for msg in agent.state.messages if msg["role"] == "tool"]
        payload = json.loads(tool_messages[0]["content"])
        remembered = payload["known_params"]

        assert response == "Planned with remembered requirements."
        assert remembered["geometry"]
        assert remembered["physics"]
        assert remembered["material"]
        assert remembered["boundary_conditions"]
        assert remembered["load_conditions"]
        assert remembered["outputs"]
        assert payload["validation_params"] == {}

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
        assert "requirement_state" in payload
        assert payload["messages"][-1]["content"] == "Stored response."
        assert [turn["role"] for turn in payload["turns"]] == ["user", "assistant"]

    def test_cli_app_imports(self):
        from comsol_agent.cli.app import CLIApp

        assert CLIApp is not None


class TestCompaction:
    """Tests for deterministic context compaction."""

    def test_requirement_state_accumulates_cross_turn_slots(self):
        from comsol_agent.memory.requirements import RequirementState

        state = RequirementState()
        state.observe_user_message("先做3D圆柱滚子轴承结构仿真，材料用钢，固定内圈，输出应力")
        state.observe_user_message("下一阶段要做真实几何实体绑定、接触收敛和非零应力校准")

        params = state.to_known_params()

        assert "3D" in params["geometry"]
        assert "钢" in params["material"]
        assert "固定内圈" in params["boundary_conditions"]
        assert "应力" in params["outputs"]
        assert "接触" in params["contact_requirements"]
        assert "实体绑定" in params["entity_binding"]
        assert "非零应力" in params["calibration"]

    def test_requirement_state_separates_modeling_request_params(self):
        from comsol_agent.memory.requirements import RequirementState

        state = RequirementState()
        state.observe_user_message("做一个PCB热仿真，chip_power=5[W]，对流系数convection_h=10[W/m^2/K]，输出最高温度")

        request = state.to_modeling_request()

        assert request.intent_slots["geometry"]
        assert request.intent_slots["load_conditions"]
        assert request.executable_params["chip_power"] == "5[W]"
        assert request.executable_params["convection_h"] == "10[W/m^2/K]"
        assert request.turn_count == 1

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

    def test_template_parameter_override_filters_intent_and_rebuilds_geometry_mesh(self):
        from comsol_agent.tools.simulation import _template_parameter_override_details

        details = _template_parameter_override_details(
            {
                "radial_load": "2000[N]",
                "contact_interference": "8[um]",
                "ball_diameter": "9[mm]",
                "bearing_type": "圆锥滚子轴承",
                "contact_policy": "真实接触",
                "cage_included": "true",
            }
        )
        code = details["java_code"]

        assert details["applied_params"] == {
            "ball_diameter": "9[mm]",
            "contact_interference": "8[um]",
            "radial_load": "2000[N]",
        }
        assert details["skipped_params"]["bearing_type"] == "not_unit_numeric_dimensionless_or_expression"
        assert "model.param().set('radial_load', '2000[N]');" in code
        assert "model.param().set('contact_interference', '8[um]');" in code
        assert "model.param().set('ball_diameter', '9[mm]');" in code
        assert "geom('geom1').run()" in code
        assert "mesh('mesh1').run()" in code

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
            _build_verified_3d_full_bearing_code,
            build_3d_bearing_code_generation_prompt,
            build_3d_bearing_execution_prompt,
            apply_bounded_3d_generated_code_repairs,
            apply_runtime_preflight_3d_repairs,
            _build_local_two_body_contact_smoke_code,
        )

        assert SCRIPT_SEGMENTED_3D_CODE_SPECS is SEGMENTED_3D_CODE_SPECS
        demo_source = Path(demo_script_file).read_text(encoding="utf-8")
        assert "def build_segmented_3d_generation_prompt(" not in demo_source
        assert "class Segmented3DCodeSpec" not in demo_source
        assert "def validate_3d_bearing_code_draft(" not in demo_source
        assert "def _build_3d_execution_context(" not in demo_source
        assert "roller1_outer_raceway_partition_with_3um_source_closure_diagnostic" in demo_source

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
        assert "sel_inner_bore_load_surface" in VERIFIED_3D_FULL_BEARING_CODE
        assert "sel_outer_support_xpos" in VERIFIED_3D_FULL_BEARING_CODE
        assert "selection().create('sel_outer_support_surface', 'Union')" in VERIFIED_3D_FULL_BEARING_CODE
        assert "selection('sel_outer_support_surface').set('xmin', '-41[mm]')" not in VERIFIED_3D_FULL_BEARING_CODE
        assert "'BoundaryLoad', 2" in VERIFIED_3D_FULL_BEARING_CODE
        assert "FperArea" in VERIFIED_3D_FULL_BEARING_CODE
        assert "inner_radial_displacement" in VERIFIED_3D_FULL_BEARING_CODE
        assert "'Displacement2', 2" in VERIFIED_3D_FULL_BEARING_CODE
        assert ".set('U0', ['inner_radial_displacement', '0', '0'])" in VERIFIED_3D_FULL_BEARING_CODE
        assert "sel_inner_ring_body" in VERIFIED_3D_FULL_BEARING_CODE
        assert "maxop_inner_ring" in VERIFIED_3D_FULL_BEARING_CODE
        assert "cpl('maxop_inner_ring').selection().named('sel_inner_ring_body')" in VERIFIED_3D_FULL_BEARING_CODE
        assert "probe_inner_ring_max_mises" in VERIFIED_3D_FULL_BEARING_CODE
        assert "BodyLoad" not in VERIFIED_3D_FULL_BEARING_CODE
        assert "sel_inner_load_region" not in VERIFIED_3D_FULL_BEARING_CODE
        assert "maxop_cage" in VERIFIED_3D_FULL_BEARING_CODE
        assert "probe_cage_max_mises" in VERIFIED_3D_FULL_BEARING_CODE
        assert "probe_cage_max_displacement" in VERIFIED_3D_FULL_BEARING_CODE
        assert "sel_roller_12_cage_contact" in VERIFIED_3D_FULL_BEARING_CODE
        assert "sel_cage_pocket_12_contact" in VERIFIED_3D_FULL_BEARING_CODE
        assert "cp_roller_12_cage_pocket" in VERIFIED_3D_FULL_BEARING_CODE
        assert "contact_roller_12_cage" in VERIFIED_3D_FULL_BEARING_CODE
        phase_shifted_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            roller_angular_offset_deg=15.0,
        )
        assert "feature('roller_1').set('pos', ['26.080[mm]', '6.988[mm]', '-roller_length/2'])" in phase_shifted_fixture
        assert "feature('roller_1').set('pos', ['27.000[mm]', '0.000[mm]', '-roller_length/2'])" in VERIFIED_3D_FULL_BEARING_CODE
        assert "roller1_outer_aux_raceway_patch" not in VERIFIED_3D_FULL_BEARING_CODE
        aux_patch_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            local_contact_patch_mode="roller1_outer_aux_patch",
        )
        assert "roller1_outer_aux_raceway_patch" in aux_patch_fixture
        assert "geom1_roller1_outer_aux_raceway_patch_bnd" in aux_patch_fixture
        assert "fix_roller1_outer_aux_raceway_patch" in aux_patch_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_roller1_outer_aux_raceway_patch_bnd'])" in aux_patch_fixture
        assert "local_contact_patch_mode=roller1_outer_aux_patch" in aux_patch_fixture
        seam_shift_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            local_contact_patch_mode="roller1_cylinder_seam_shift15",
        )
        assert "feature('roller_1').set('axis', ['0', '0', '1'])" in seam_shift_fixture
        assert "feature('roller_1').set('rot', '15[deg]')" in seam_shift_fixture
        assert "ROLLER1_CYLINDER_SEAM_SHIFT|roller=1|axis=0,0,1|rot=15[deg]" in seam_shift_fixture
        assert "feature('roller_2').set('rot', '15[deg]')" not in seam_shift_fixture
        assert "local_contact_patch_mode=roller1_cylinder_seam_shift15" in seam_shift_fixture
        retained_conformal_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            local_contact_patch_mode="roller1_outer_retained_conformal_patch",
        )
        assert "roller1_outer_retained_conformal_patch" in retained_conformal_fixture
        assert "roller1_outer_conformal_patch_outer" in retained_conformal_fixture
        assert "roller1_outer_conformal_patch_inner" in retained_conformal_fixture
        assert "ROLLER1_OUTER_RETAINED_CONFORMAL_PATCH_GEOM" in retained_conformal_fixture
        assert "ROLLER1_OUTER_RETAINED_CONFORMAL_PATCH_BIND" in retained_conformal_fixture
        assert "geom1_roller1_outer_retained_conformal_patch_bnd" in retained_conformal_fixture
        assert "fix_roller1_outer_retained_conformal_patch" in retained_conformal_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_roller1_outer_retained_conformal_patch_bnd'])" in retained_conformal_fixture
        assert "set('input', ['box_roller_2_outer_contact_patch', 'geom1_roller1_outer_retained_conformal_patch_bnd'])" not in retained_conformal_fixture
        assert "local_contact_patch_mode=roller1_outer_retained_conformal_patch" in retained_conformal_fixture
        assert "roller1_outer_retained_conformal_patch" not in VERIFIED_3D_FULL_BEARING_CODE
        retained_conformal_closure_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            local_contact_patch_mode="roller1_outer_retained_conformal_source_closure3um",
        )
        assert "ROLLER1_OUTER_SOURCE_CLOSURE" in retained_conformal_closure_fixture
        assert "combined_with=roller1_outer_retained_conformal_source_closure3um" in retained_conformal_closure_fixture
        assert "ROLLER1_OUTER_RETAINED_CONFORMAL_PATCH_GEOM" in retained_conformal_closure_fixture
        assert "source_closure3um=true" in retained_conformal_closure_fixture
        assert "ROLLER1_OUTER_RETAINED_CONFORMAL_PATCH_BIND" in retained_conformal_closure_fixture
        assert "geom1_roller1_outer_retained_conformal_patch_bnd" in retained_conformal_closure_fixture
        assert "fix_roller1_outer_retained_conformal_patch" in retained_conformal_closure_fixture
        assert "feature('roller_1').set('pos', ['27.003[mm]', '0.000[mm]', '-roller_length/2'])" in retained_conformal_closure_fixture
        assert "feature('roller_2').set('pos', ['23.383[mm]', '13.500[mm]', '-roller_length/2'])" in retained_conformal_closure_fixture
        assert "feature('roller_2').set('pos', ['23.386[mm]', '13.500[mm]', '-roller_length/2'])" not in retained_conformal_closure_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_roller_1_bnd'])" in retained_conformal_closure_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_roller1_outer_retained_conformal_patch_bnd'])" in retained_conformal_closure_fixture
        assert "set('input', ['box_roller_2_outer_contact_patch', 'geom1_roller1_outer_retained_conformal_patch_bnd'])" not in retained_conformal_closure_fixture
        assert "cp_roller_1_outer_raceway" in retained_conformal_closure_fixture
        assert "local_contact_patch_mode=roller1_outer_retained_conformal_source_closure3um" in retained_conformal_closure_fixture
        assert "roller1_outer_retained_conformal_target_with_3um_source_closure_diagnostic" in demo_source
        retained_conformal_narrow_closure_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            local_contact_patch_mode="roller1_outer_retained_conformal_narrow_source_closure3um",
        )
        assert "ROLLER1_OUTER_SOURCE_CLOSURE" in retained_conformal_narrow_closure_fixture
        assert "combined_with=roller1_outer_retained_conformal_narrow_source_closure3um" in retained_conformal_narrow_closure_fixture
        assert "ROLLER1_OUTER_RETAINED_CONFORMAL_PATCH_GEOM" in retained_conformal_narrow_closure_fixture
        assert "source_closure3um=true" in retained_conformal_narrow_closure_fixture
        assert "outer_box_tangential_half_width=0.9[mm]" in retained_conformal_narrow_closure_fixture
        assert "outer_box_tangential_half_width=1.8[mm]" not in retained_conformal_narrow_closure_fixture
        assert "ROLLER1_OUTER_RETAINED_CONFORMAL_PATCH_BIND" in retained_conformal_narrow_closure_fixture
        assert (
            "source=sel_roller_1_outer_contact|destination=sel_outer_raceway_1_contact|"
            "pair=cp_roller_1_outer_raceway"
        ) in retained_conformal_narrow_closure_fixture
        assert "geom1_roller1_outer_retained_conformal_patch_bnd" in retained_conformal_narrow_closure_fixture
        assert "fix_roller1_outer_retained_conformal_patch" in retained_conformal_narrow_closure_fixture
        assert "feature('roller_1').set('pos', ['27.003[mm]', '0.000[mm]', '-roller_length/2'])" in retained_conformal_narrow_closure_fixture
        assert "feature('roller_2').set('pos', ['23.383[mm]', '13.500[mm]', '-roller_length/2'])" in retained_conformal_narrow_closure_fixture
        assert "local_contact_patch_mode=roller1_outer_retained_conformal_narrow_source_closure3um" in retained_conformal_narrow_closure_fixture
        assert (
            "roller1_outer_retained_conformal_target_with_3um_source_closure_and_0p9mm_tangential_box_diagnostic"
            in demo_source
        )
        retained_conformal_equal_height_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            local_contact_patch_mode="roller1_outer_retained_conformal_equal_height_source_closure3um",
        )
        assert "ROLLER1_OUTER_SOURCE_CLOSURE" in retained_conformal_equal_height_fixture
        assert "combined_with=roller1_outer_retained_conformal_equal_height_source_closure3um" in retained_conformal_equal_height_fixture
        assert "roller1_outer_conformal_patch_outer').set('h', '16.4[mm]')" in retained_conformal_equal_height_fixture
        assert "roller1_outer_conformal_patch_inner').set('h', '16.4[mm]')" in retained_conformal_equal_height_fixture
        assert "roller1_outer_conformal_patch_inner').set('pos', ['0', '0', '-8.2[mm]'])" in retained_conformal_equal_height_fixture
        assert "source_closure3um=true" in retained_conformal_equal_height_fixture
        assert "ROLLER1_OUTER_RETAINED_CONFORMAL_PATCH_BIND" in retained_conformal_equal_height_fixture
        assert "geom1_roller1_outer_retained_conformal_patch_bnd" in retained_conformal_equal_height_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_roller_1_bnd'])" in retained_conformal_equal_height_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_roller1_outer_retained_conformal_patch_bnd'])" in retained_conformal_equal_height_fixture
        assert "set('input', ['box_roller_2_outer_contact_patch', 'geom1_roller1_outer_retained_conformal_patch_bnd'])" not in retained_conformal_equal_height_fixture
        assert "cp_roller_1_outer_raceway" in retained_conformal_equal_height_fixture
        assert "local_contact_patch_mode=roller1_outer_retained_conformal_equal_height_source_closure3um" in retained_conformal_equal_height_fixture
        assert "roller1_outer_retained_conformal_equal_height_target_with_3um_source_closure_diagnostic" in demo_source
        retained_conformal_sector_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            local_contact_patch_mode="roller1_outer_retained_conformal_sector_source_closure3um",
        )
        assert "ROLLER1_OUTER_SOURCE_CLOSURE" in retained_conformal_sector_fixture
        assert "combined_with=roller1_outer_retained_conformal_sector_source_closure3um" in retained_conformal_sector_fixture
        assert "roller1_outer_conformal_patch_annulus" in retained_conformal_sector_fixture
        assert "roller1_outer_conformal_patch_window" in retained_conformal_sector_fixture
        assert "roller1_outer_retained_conformal_patch', 'Intersection'" in retained_conformal_sector_fixture
        assert "sector=true" in retained_conformal_sector_fixture
        assert "source_closure3um=true" in retained_conformal_sector_fixture
        assert (
            "ROLLER1_OUTER_RETAINED_CONFORMAL_PATCH_BIND|source=sel_roller_1_outer_contact|"
            "destination=sel_outer_raceway_1_contact|pair=cp_roller_1_outer_raceway|"
            "box=box_roller_1_outer_contact_patch|source_closure3um=true"
        ) in retained_conformal_sector_fixture
        assert "geom1_roller1_outer_retained_conformal_patch_bnd" in retained_conformal_sector_fixture
        assert "feature('roller_1').set('pos', ['27.003[mm]', '0.000[mm]', '-roller_length/2'])" in retained_conformal_sector_fixture
        assert "feature('roller_2').set('pos', ['23.383[mm]', '13.500[mm]', '-roller_length/2'])" in retained_conformal_sector_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_roller_1_bnd'])" in retained_conformal_sector_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_roller1_outer_retained_conformal_patch_bnd'])" in retained_conformal_sector_fixture
        assert "set('input', ['box_roller_2_outer_contact_patch', 'geom1_roller1_outer_retained_conformal_patch_bnd'])" not in retained_conformal_sector_fixture
        assert "cp_roller_1_outer_raceway" in retained_conformal_sector_fixture
        assert "local_contact_patch_mode=roller1_outer_retained_conformal_sector_source_closure3um" in retained_conformal_sector_fixture
        assert "roller1_outer_retained_conformal_sector_target_with_3um_source_closure_diagnostic" in demo_source
        construction_partition_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            local_contact_patch_mode="roller1_outer_construction_partition_patch",
        )
        assert "partition_tool_roller1_outer_raceway_patch" in construction_partition_fixture
        assert "partition_tool_roller1_outer_source_patch" in construction_partition_fixture
        assert "partition_roller1_outer_raceway_construction_patch" in construction_partition_fixture
        assert "partition_roller1_outer_source_construction_patch" in construction_partition_fixture
        assert "ROLLER1_OUTER_CONSTRUCTION_PARTITION_PATCH_GEOM" in construction_partition_fixture
        assert "ROLLER1_OUTER_CONSTRUCTION_PARTITION_PATCH_BIND" in construction_partition_fixture
        assert "geom1_partition_roller1_outer_raceway_construction_patch_bnd" in construction_partition_fixture
        assert "geom1_partition_roller1_outer_source_construction_patch_bnd" in construction_partition_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_partition_roller1_outer_source_construction_patch_bnd'])" in construction_partition_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_partition_roller1_outer_raceway_construction_patch_bnd'])" in construction_partition_fixture
        assert "set('input', ['box_roller_2_outer_contact_patch', 'geom1_partition_roller1_outer_raceway_construction_patch_bnd'])" not in construction_partition_fixture
        assert "local_contact_patch_mode=roller1_outer_construction_partition_patch" in construction_partition_fixture
        assert "partition_roller1_outer_raceway_construction_patch" not in VERIFIED_3D_FULL_BEARING_CODE
        construction_partition_closure_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            local_contact_patch_mode="roller1_outer_construction_partition_source_closure3um",
        )
        assert "ROLLER1_OUTER_SOURCE_CLOSURE" in construction_partition_closure_fixture
        assert "combined_with=roller1_outer_construction_partition_source_closure3um" in construction_partition_closure_fixture
        assert "source_closure3um=true" in construction_partition_closure_fixture
        assert "partition_tool_roller1_outer_raceway_patch" in construction_partition_closure_fixture
        assert "partition_tool_roller1_outer_source_patch" in construction_partition_closure_fixture
        assert "partition_roller1_outer_raceway_construction_patch" in construction_partition_closure_fixture
        assert "partition_roller1_outer_source_construction_patch" in construction_partition_closure_fixture
        assert "ROLLER1_OUTER_CONSTRUCTION_PARTITION_PATCH_GEOM" in construction_partition_closure_fixture
        assert "ROLLER1_OUTER_CONSTRUCTION_PARTITION_PATCH_BIND" in construction_partition_closure_fixture
        assert "geom1_partition_roller1_outer_raceway_construction_patch_bnd" in construction_partition_closure_fixture
        assert "geom1_partition_roller1_outer_source_construction_patch_bnd" in construction_partition_closure_fixture
        assert "feature('roller_1').set('pos', ['27.003[mm]', '0.000[mm]', '-roller_length/2'])" in construction_partition_closure_fixture
        assert "feature('roller_2').set('pos', ['23.383[mm]', '13.500[mm]', '-roller_length/2'])" in construction_partition_closure_fixture
        assert "feature('roller_2').set('pos', ['23.386[mm]', '13.500[mm]', '-roller_length/2'])" not in construction_partition_closure_fixture
        assert "cp_roller_1_outer_raceway" in construction_partition_closure_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_partition_roller1_outer_source_construction_patch_bnd'])" in construction_partition_closure_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_partition_roller1_outer_raceway_construction_patch_bnd'])" in construction_partition_closure_fixture
        assert "set('input', ['box_roller_2_outer_contact_patch', 'geom1_partition_roller1_outer_raceway_construction_patch_bnd'])" not in construction_partition_closure_fixture
        assert "local_contact_patch_mode=roller1_outer_construction_partition_source_closure3um" in construction_partition_closure_fixture
        assert "roller1_outer_source_destination_construction_partition_with_3um_source_closure_diagnostic" in demo_source
        raceway_partition_only_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            local_contact_patch_mode="roller1_outer_raceway_partition_only",
        )
        assert "partition_tool_roller1_outer_raceway_only_patch" in raceway_partition_only_fixture
        assert "partition_roller1_outer_raceway_only_patch" in raceway_partition_only_fixture
        assert "ROLLER1_OUTER_RACEWAY_PARTITION_ONLY_GEOM" in raceway_partition_only_fixture
        assert "ROLLER1_OUTER_RACEWAY_PARTITION_ONLY_BIND" in raceway_partition_only_fixture
        assert "geom1_partition_roller1_outer_raceway_only_patch_bnd" in raceway_partition_only_fixture
        assert "geom1_partition_roller1_outer_source_construction_patch_bnd" not in raceway_partition_only_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_roller_1_bnd'])" in raceway_partition_only_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_partition_roller1_outer_raceway_only_patch_bnd'])" in raceway_partition_only_fixture
        assert "set('input', ['box_roller_2_outer_contact_patch', 'geom1_partition_roller1_outer_raceway_only_patch_bnd'])" not in raceway_partition_only_fixture
        assert "local_contact_patch_mode=roller1_outer_raceway_partition_only" in raceway_partition_only_fixture
        assert "partition_roller1_outer_raceway_only_patch" not in VERIFIED_3D_FULL_BEARING_CODE
        source_closure_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            local_contact_patch_mode="roller1_outer_raceway_partition_source_closure3um",
        )
        assert "ROLLER1_OUTER_SOURCE_CLOSURE" in source_closure_fixture
        assert "source_closure3um=true" in source_closure_fixture
        assert "partition_tool_roller1_outer_raceway_only_patch" in source_closure_fixture
        assert "partition_roller1_outer_raceway_only_patch" in source_closure_fixture
        assert "ROLLER1_OUTER_RACEWAY_PARTITION_ONLY_BIND" in source_closure_fixture
        assert "feature('roller_1').set('pos', ['27.003[mm]', '0.000[mm]', '-roller_length/2'])" in source_closure_fixture
        assert "feature('roller_2').set('pos', ['23.383[mm]', '13.500[mm]', '-roller_length/2'])" in source_closure_fixture
        assert "feature('roller_2').set('pos', ['23.386[mm]', '13.500[mm]', '-roller_length/2'])" not in source_closure_fixture
        assert "cp_roller_1_outer_raceway" in source_closure_fixture
        assert "geom1_partition_roller1_outer_source_construction_patch_bnd" not in source_closure_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_roller_1_bnd'])" in source_closure_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_partition_roller1_outer_raceway_only_patch_bnd'])" in source_closure_fixture
        assert "set('input', ['box_roller_2_outer_contact_patch', 'geom1_partition_roller1_outer_raceway_only_patch_bnd'])" not in source_closure_fixture
        assert "local_contact_patch_mode=roller1_outer_raceway_partition_source_closure3um" in source_closure_fixture
        assert "ROLLER1_OUTER_SOURCE_CLOSURE" not in VERIFIED_3D_FULL_BEARING_CODE
        narrow_destination_closure_fixture = _build_verified_3d_full_bearing_code(
            roller_count=12,
            local_contact_patch_mode="roller1_outer_raceway_narrow_partition_source_closure3um",
        )
        assert "ROLLER1_OUTER_SOURCE_CLOSURE" in narrow_destination_closure_fixture
        assert "combined_with=roller1_outer_raceway_narrow_partition_source_closure3um" in narrow_destination_closure_fixture
        assert "partition_tool_roller1_outer_raceway_narrow_closure_patch" in narrow_destination_closure_fixture
        assert "partition_roller1_outer_raceway_narrow_closure_patch" in narrow_destination_closure_fixture
        assert "ROLLER1_OUTER_RACEWAY_NARROW_PARTITION_SOURCE_CLOSURE_GEOM" in narrow_destination_closure_fixture
        assert "ROLLER1_OUTER_RACEWAY_NARROW_PARTITION_SOURCE_CLOSURE_BIND" in narrow_destination_closure_fixture
        assert "tool_size=0.35x1.2x16.4[mm]" in narrow_destination_closure_fixture
        assert "feature('roller_1').set('pos', ['27.003[mm]', '0.000[mm]', '-roller_length/2'])" in narrow_destination_closure_fixture
        assert "feature('roller_2').set('pos', ['23.383[mm]', '13.500[mm]', '-roller_length/2'])" in narrow_destination_closure_fixture
        assert "cp_roller_1_outer_raceway" in narrow_destination_closure_fixture
        assert "geom1_partition_roller1_outer_source_construction_patch_bnd" not in narrow_destination_closure_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_roller_1_bnd'])" in narrow_destination_closure_fixture
        assert "set('input', ['box_roller_1_outer_contact_patch', 'geom1_partition_roller1_outer_raceway_narrow_closure_patch_bnd'])" in narrow_destination_closure_fixture
        assert "set('input', ['box_roller_2_outer_contact_patch', 'geom1_partition_roller1_outer_raceway_narrow_closure_patch_bnd'])" not in narrow_destination_closure_fixture
        assert "local_contact_patch_mode=roller1_outer_raceway_narrow_partition_source_closure3um" in narrow_destination_closure_fixture
        assert "roller1_outer_raceway_narrow_partition_with_3um_source_closure_diagnostic" in demo_source
        assert "partition_roller1_outer_raceway_narrow_closure_patch" not in VERIFIED_3D_FULL_BEARING_CODE
        local_two_body_code = _build_local_two_body_contact_smoke_code(contact_interference="7[um]")
        assert "LOCAL_TWO_BODY_CONTACT_SMOKE_BUILT" in local_two_body_code
        assert "roller_radius_local', '4[mm] + 7[um]'" in local_two_body_code
        assert "sel_roller_1_outer_contact" in local_two_body_code
        assert "sel_outer_raceway_1_contact" in local_two_body_code
        assert "cp_roller_1_outer_raceway" in local_two_body_code
        assert "solid').feature('contact_roller_1_outer').set('pairs', ['cp_roller_1_outer_raceway'])" in local_two_body_code
        assert "set('useRelaxation', 'Always')" in local_two_body_code
        local_two_body_roller2_code = _build_local_two_body_contact_smoke_code(
            contact_interference="7[um]",
            roller_id=2,
        )
        assert "LOCAL_TWO_BODY_CONTACT_SMOKE_BUILT|roller=2" in local_two_body_roller2_code
        assert "geom1').feature('roller_2').set('pos', ['23.383[mm]', '13.500[mm]', '-roller_length/2'])" in local_two_body_roller2_code
        assert "sel_roller_2_outer_contact" in local_two_body_roller2_code
        assert "sel_outer_raceway_2_contact" in local_two_body_roller2_code
        assert "cp_roller_2_outer_raceway" in local_two_body_roller2_code
        assert "['0.866025403784*local_body_load', '0.5*local_body_load', '0']" in local_two_body_roller2_code

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
        old_inner_domain_load_code = (
            VERIFIED_3D_FULL_BEARING_CODE
            + "\nmodel.component('comp1').selection().create('sel_inner_load_region', 'Box');"
            + "\nmodel.component('comp1').physics('solid').create('legacy_load_inner', 'BodyLoad', 3);"
            + "\nmodel.component('comp1').physics('solid').feature('legacy_load_inner').selection().named('sel_inner_load_region');"
            + "\nmodel.component('comp1').physics('solid').feature('legacy_load_inner').set('FperVol', ['radial_load', '0', '0']);"
        )
        old_inner_domain_load_quality = validate_3d_bearing_code_draft(old_inner_domain_load_code)
        assert old_inner_domain_load_quality["success"] is False
        assert any("inner-bore BoundaryLoad" in error for error in old_inner_domain_load_quality["errors"])

        loop_family_code = VERIFIED_3D_FULL_BEARING_CODE + """
num_rollers = 12
for i in range(num_rollers):
    idx = i + 1
    sel_roller_body_tag = f'sel_roller_{idx}_body'
    sel_roller_inner_tag = f'sel_roller_{idx}_inner_contact'
    sel_roller_outer_tag = f'sel_roller_{idx}_outer_contact'
    sel_inner_raceway_tag = f'sel_inner_raceway_{idx}_contact'
    sel_outer_raceway_tag = f'sel_outer_raceway_{idx}_contact'
    probe_tag = f'probe_roller_{idx}_max_mises'
"""
        loop_family_quality = validate_3d_bearing_code_draft(
            loop_family_code,
            require_named_selections=True,
        )
        assert not any("sel_roller_1_body" in error for error in loop_family_quality["errors"])
        assert not any("probe_roller_1_max_mises" in error for error in loop_family_quality["errors"])
        from comsol_agent.simulation.bearing_3d import _has_segmented_loop_tag_evidence

        assert _has_segmented_loop_tag_evidence(
            "num_rollers = 12\nfor i in range(num_rollers):\n    idx = i + 1\n    tag = f'sel_roller_{idx}_body'\n",
            "sel_roller_",
            "_body",
        )

        binding_contract = selection_binding_contract()
        assert binding_contract["kind"] == "bearing_3d_selection_binding_contract"
        assert binding_contract["roller_count"] == VERIFIED_ROLLER_COUNT
        assert len(binding_contract["entries"]) == 5 + 7 * VERIFIED_ROLLER_COUNT
        assert any(
            entry["tag"] == "sel_inner_bore_load_surface" and entry["entitydim"] == 2
            for entry in binding_contract["entries"]
        )
        assert any(
            entry["tag"] == "sel_cage_pocket_12_contact" and entry["entitydim"] == 2
            for entry in binding_contract["entries"]
        )
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
        runtime_selection_report["sel_roller_1_inner_contact"]["entities"] = [183, 184, 185, 186]
        runtime_selection_report["sel_roller_1_outer_contact"]["entities"] = [185, 186, 187, 188]
        runtime_selection_report["sel_roller_1_cage_contact"]["entities"] = [183, 184, 187, 188]
        overlap_binding_audit = audit_3d_selection_binding(
            java_code=VERIFIED_3D_FULL_BEARING_CODE,
            selection_report=runtime_selection_report,
        )
        assert overlap_binding_audit["success"] is False
        assert overlap_binding_audit["contact_source_overlap_audit"]["overlap_count"] == 3
        assert any("Roller 1 contact source selections overlap" in error for error in overlap_binding_audit["errors"])
        runtime_selection_report["sel_roller_1_inner_contact"].pop("entities")
        runtime_selection_report["sel_roller_1_outer_contact"].pop("entities")
        runtime_selection_report["sel_roller_1_cage_contact"].pop("entities")
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
            contact_pair_count=VERIFIED_ROLLER_COUNT * 3,
        )
        assert contact_report["success"] is True
        assert contact_report["runtime_verified"] is True
        assert contact_report["quality_level"] == "contact_runtime_convergence_checked"
        unverified_contact_report = build_contact_convergence_report(
            metrics={"contact_pressure_guess": 1.95e6},
            selection_binding_audit=code_binding_audit,
            physical_result_audit=production_physical_audit,
            contact_pair_count=VERIFIED_ROLLER_COUNT * 3,
        )
        assert unverified_contact_report["success"] is True
        assert unverified_contact_report["runtime_verified"] is False
        assert any("Solve result was not provided" in warning for warning in unverified_contact_report["warnings"])
        code_only_contact_report = build_contact_convergence_report(
            solve_result={"success": True, "status": "Solve completed."},
            metrics={"contact_pressure_guess": 1.95e6},
            selection_binding_audit=code_binding_audit,
            physical_result_audit=production_physical_audit,
            contact_pair_count=VERIFIED_ROLLER_COUNT * 3,
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
model.component("comp1").pair("pair1").set("manualSelection", True)
model.component("comp1").physics("solid").feature().create("cp_extra", "Contact", 1)
model.component("comp1").physics("solid").feature("cp_extra").set("contact_pair", "pair1")
model.component("comp1").geom("geom1").run()
model.component("comp1").geom("geom1").finalize("assembly")
model.component("comp1").geom("geom1").selection().create("sel_r1_inner", "Explicit")
model.component("comp1").geom("geom1").selection("sel_r1_inner").set("entitydim", 2)
model.component("comp1").mesh().create("mesh1", "mesh1")
model.result("pg_stress3d").set("data", "dset1")
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
        cross_segment_repaired, cross_segment_reports, _ = apply_runtime_preflight_3d_repairs(
            "model.param().set('radial_load', '1000[N]')\n"
            "roller_radius = model.param().evaluate('roller_dia')/2\n"
            "model.param().set('contact_pressure_est', 'radial_load/(roller_length*roller_dia*num_rollers)')\n"
        )
        assert cross_segment_reports
        assert "model.param().set('roller_dia', '8[mm]')" in cross_segment_repaired
        assert "model.param().set('roller_length', '16[mm]')" in cross_segment_repaired
        assert "model.param().set('num_rollers', '12')" in cross_segment_repaired
        assert "FixedConstraint" not in preflight_repaired
        assert '"contact_pair"' not in preflight_repaired
        assert '.pair("cp_roller_inner_raceway").manualSelection(True)' in preflight_repaired
        assert "model.output().write" not in preflight_repaired
        assert ".mesh().create('mesh1')" in preflight_repaired
        assert '.set("data", "dset1")' not in preflight_repaired
        assert '.set("ax"' not in preflight_repaired
        assert ".finalize(" not in preflight_repaired
        assert ".feature('fin').set('action', 'assembly')" in preflight_repaired
        assert '.geom("geom1").selection()' not in preflight_repaired
        assert 'model.component("comp1").selection().create("sel_r1_inner", "Explicit")' in preflight_repaired
        assert "model_output_write_to_comment" in " ".join(preflight_reports[0]["changes"])
        assert "remove_unsupported_cylinder_axis_property" in " ".join(preflight_reports[0]["changes"])
        assert "geom_finalize_assembly_to_verified_fin_action" in " ".join(preflight_reports[0]["changes"])
        assert "geom_scoped_selection_create_to_component_selection" in " ".join(preflight_reports[0]["changes"])
        assert "mesh_create_self_geometry_to_plain_mesh" in " ".join(preflight_reports[0]["changes"])
        assert "remove_setup_stage_result_dataset_binding" in " ".join(preflight_reports[0]["changes"])
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

    def test_3d_staged_contact_solve_orders_raceway_before_cage(self, monkeypatch, tmp_path):
        from scripts import run_agent_3d_bearing_full_demo as demo

        setup_codes: list[str] = []
        solve_calls: list[str] = []

        def fake_execute_java(code: str, *, model_name: str):
            setup_codes.append(code)
            return {"success": True, "model_name": model_name, "status": "configured"}

        def fake_solve(model_name: str):
            solve_calls.append(model_name)
            return {"success": True, "model_name": model_name, "status": "solved"}

        def fake_evaluate(model_name: str, expression: str):
            return {
                "success": True,
                "model_name": model_name,
                "expression": expression,
                "statistics": {"max": 10.0, "mean": 1.0},
            }

        def fake_stage_plot(model_name: str, *, stage_name: str, output_dir):
            return {
                "success": True,
                "model_name": model_name,
                "stage": stage_name,
                "plot_type": "native_comsol_volume",
                "filepath": str(output_dir / f"{stage_name}.png"),
                "export_method": "java:Image2D:Volume",
                "dataset": "dset1",
            }

        monkeypatch.setattr(demo, "comsol_execute_java", fake_execute_java)
        monkeypatch.setattr(demo, "comsol_solve", fake_solve)
        monkeypatch.setattr(demo, "comsol_evaluate", fake_evaluate)
        monkeypatch.setattr(demo, "_export_native_3d_stage_volume_plot", fake_stage_plot)

        raceway_only = demo._run_3d_staged_contact_solve("staged_model")
        assert raceway_only["success"] is True
        assert raceway_only["run_full_cage_stage"] is False
        assert raceway_only["contact_stage_mode"] == "all_raceway"
        assert len(raceway_only["stages"]) == 3
        assert raceway_only["stages"][0]["contact_scope"] == "roller_inner_outer_raceway_only"
        assert raceway_only["stages"][1]["name"] == "raceway_contact_refined_preload"
        assert raceway_only["stages"][2]["name"] == "raceway_contact_radial_load_transfer"
        assert raceway_only["stages"][2]["inner_bore_load_active"] is True
        assert raceway_only["stages"][2]["displacement_preload_active"] is False
        assert raceway_only["stages"][0]["temporary_cage_stabilization_active"] is True
        assert "raceway_contact_active=True" in setup_codes[0]
        assert "staged_cage.active(False and staged_active)" in setup_codes[0]
        assert "staged_cage.active(False and staged_active)" in setup_codes[1]
        assert "fix_cage_stage_stabilization" in setup_codes[0]
        assert "temporary_cage_stabilization_active=" in setup_codes[0]
        assert "fix_cage_stage_stabilization').active(True)" in setup_codes[0]
        assert "feature('load_inner_bore').active(False)" in setup_codes[0]
        assert "feature('disp_inner_bore_preload').active(True)" in setup_codes[0]
        assert "feature('disp_inner_bore_preload').active(False)" in setup_codes[2]
        assert "inner_bore_load_active=" in setup_codes[0]
        assert "displacement_preload_active=" in setup_codes[0]
        assert "str(False)" in setup_codes[0]
        assert "plistarr" in setup_codes[0]
        assert "0.0001 0.0005 0.002" in setup_codes[0]
        assert "mesh_contact_size', '2.4[mm]'" in setup_codes[0]
        assert "('pn_penalty', '0.02*E_steel')" in setup_codes[0]
        assert "('zeroInitGap', 'on')" in setup_codes[0]
        assert "('tolcontact', '0.2[um]')" in setup_codes[0]
        assert raceway_only["stages"][0]["inner_ring_stress"]["success"] is True

        stage_plotted = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="all_raceway_preload_only",
            stage_plot_dir=tmp_path / "stage_plots",
        )
        assert stage_plotted["stage_plot_policy"] == "native_comsol_volume_plot_per_successful_stage"
        assert len(stage_plotted["stages"]) == 2
        assert all(stage["native_volume_plot"]["success"] for stage in stage_plotted["stages"])
        assert stage_plotted["stages"][0]["native_volume_plot"]["plot_type"] == "native_comsol_volume"

        high_visual = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="all_raceway_high_preload_visual",
            stage_plot_dir=tmp_path / "high_stage_plots",
        )
        assert high_visual["success"] is True
        assert high_visual["stages"][-1]["name"] == "raceway_contact_high_preload_visual"
        assert high_visual["stages"][-1]["inner_radial_displacement"] == "3[um]"
        assert high_visual["stages"][-1]["inner_bore_load_active"] is False
        assert high_visual["stages"][-1]["contact_penalty"] == "0.02*E_steel"
        assert high_visual["stages"][-1]["contact_tolerance"] == "0.2[um]"
        assert "not_radial_force_transfer" in high_visual["stages"][-1]["physical_acceptance"]
        assert not any("radial_load_transfer" in stage["name"] for stage in high_visual["stages"])

        reaction_codes: list[str] = []

        def fake_reaction_probe(model_name: str, *, selection_name: str):
            reaction_codes.append(f"{model_name}:{selection_name}")
            return {
                "success": True,
                "kind": "displacement_controlled_reaction_equivalent_probe",
                "selection": selection_name,
                "best_expression": "intop_displacement_reaction_probe(solid.RFx)",
                "best_reaction_force_n": 3000.0,
                "best_reaction_force_abs_n": 3000.0,
                "equivalent_pressure_pa": 1.3e6,
            }

        monkeypatch.setattr(demo, "_evaluate_displacement_reaction_equivalent", fake_reaction_probe)
        high_reaction = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="all_raceway_high_preload_reaction_equivalent",
            stage_plot_dir=tmp_path / "high_reaction_stage_plots",
        )
        assert high_reaction["success"] is True
        assert high_reaction["stages"][-1]["name"] == "raceway_contact_high_preload_reaction_equivalent"
        assert high_reaction["stages"][-1]["reaction_equivalent_requested"] is True
        assert high_reaction["stages"][-1]["reaction_probe_selection"] == "sel_inner_bore_load_surface"
        assert high_reaction["stages"][-1]["reaction_equivalent"]["success"] is True
        assert high_reaction["stages"][-1]["reaction_equivalent"]["best_reaction_force_abs_n"] == 3000.0
        assert reaction_codes[-1] == "staged_model:sel_inner_bore_load_surface"
        assert "reaction_equivalent" in high_reaction["stages"][-1]["physical_acceptance"]

        high_load_visual = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="all_raceway_high_load_visual",
            stage_plot_dir=tmp_path / "high_load_stage_plots",
        )
        assert high_load_visual["success"] is True
        assert high_load_visual["stages"][-1]["name"] == "raceway_contact_high_radial_load_visual"
        assert high_load_visual["stages"][-1]["sweep_parameter"] == "radial_load"
        assert high_load_visual["stages"][-1]["sweep_unit"] == "N"
        assert high_load_visual["stages"][-1]["inner_bore_load_active"] is True
        assert high_load_visual["stages"][-1]["displacement_preload_active"] is False
        assert "true_12_roller_raceway_contact" in high_load_visual["stages"][-1]["physical_acceptance"]

        guided_low_load = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="all_raceway_guided_low_load_transfer",
            stage_plot_dir=tmp_path / "guided_low_load_stage_plots",
        )
        assert guided_low_load["success"] is True
        assert guided_low_load["stages"][-1]["name"] == "raceway_contact_guided_low_radial_load_transfer"
        assert guided_low_load["stages"][-1]["inner_bore_load_active"] is True
        assert guided_low_load["stages"][-1]["weak_inner_guidance_active"] is True
        assert guided_low_load["stages"][-1]["weak_inner_guidance_k"] == "1e5[N/m^3]"
        assert "weak_inner_ring_load_guidance" in setup_codes[-1]
        assert "inner_bore_boundary_load_with_weak_inner_ring_guidance" in guided_low_load["stages"][-1]["load_application_fidelity"]
        assert "not_final_design_gate" in guided_low_load["stages"][-1]["load_application_fidelity"]

        guided_probe = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="all_raceway_guided_probe_1n",
            stage_plot_dir=tmp_path / "guided_probe_stage_plots",
        )
        assert guided_probe["success"] is True
        assert guided_probe["stages"][-1]["name"] == "raceway_contact_guided_probe_1n_boundary_load"
        assert guided_probe["stages"][-1]["preload_steps"] == "1"
        assert guided_probe["stages"][-1]["solver_maxsegiter"] == "30"

        setup_codes.clear()
        continuous = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="all_raceway_continuous_boundary_load",
            stage_plot_dir=tmp_path / "continuous_boundary_stage_plots",
        )
        assert continuous["success"] is True
        assert len(continuous["stages"]) == 3
        assert continuous["stages"][0]["name"] == "continuous_boundary_load_contact_closure_1n"
        assert continuous["stages"][0]["inner_bore_load_active"] is True
        assert continuous["stages"][0]["displacement_preload_active"] is True
        assert continuous["stages"][0]["radial_load_value"] == "1[N]"
        assert continuous["stages"][-1]["name"] == "continuous_boundary_load_high_ramp_retained_preload"
        assert continuous["stages"][-1]["sweep_parameter"] == "radial_load"
        assert continuous["stages"][-1]["preload_steps"] == "100 250 500 1000 2000 3000"
        assert continuous["stages"][-1]["inner_bore_load_active"] is True
        assert continuous["stages"][-1]["displacement_preload_active"] is True
        assert continuous["stages"][-1]["weak_inner_guidance_active"] is True
        assert "retained_displacement_preload" in continuous["stages"][-1]["load_application_fidelity"]
        assert "model.param().set('radial_load', '1[N]')" in setup_codes[0]
        assert "model.param().set('radial_load', '3000[N]')" in setup_codes[-1]
        assert "feature('load_inner_bore').active(True)" in setup_codes[0]
        assert "feature('disp_inner_bore_preload').active(True)" in setup_codes[-1]

        setup_codes.clear()
        split_control = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="all_raceway_split_control_boundary_load",
            stage_plot_dir=tmp_path / "split_control_stage_plots",
        )
        assert split_control["success"] is True
        assert len(split_control["stages"]) == 3
        assert split_control["stages"][0]["name"] == "split_control_boundary_load_contact_closure_0p1n"
        assert split_control["stages"][0]["inner_bore_load_active"] is True
        assert split_control["stages"][0]["displacement_preload_active"] is True
        assert split_control["stages"][0]["displacement_preload_selection"] == "sel_inner_raceway_contact"
        assert split_control["stages"][0]["radial_load_value"] == "0.1[N]"
        assert split_control["stages"][-1]["name"] == "split_control_boundary_load_high_ramp"
        assert split_control["stages"][-1]["preload_steps"] == "100 250 500 1000 2000 3000"
        assert split_control["stages"][-1]["inner_bore_load_active"] is True
        assert split_control["stages"][-1]["weak_inner_guidance_active"] is True
        assert "split_raceway_displacement_closure" in split_control["stages"][-1]["load_application_fidelity"]
        assert "selection().named('sel_inner_raceway_contact')" in setup_codes[0]
        assert "displacement_preload_selection=' + 'sel_inner_raceway_contact'" in setup_codes[0]

        setup_codes.clear()
        group_boundary = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load",
            stage_plot_dir=tmp_path / "group_boundary_stage_plots",
        )
        assert group_boundary["success"] is True
        assert len(group_boundary["stages"]) == 13
        assert group_boundary["stages"][0]["name"] == "load_side_3_roller_boundary_load_0p1n"
        assert group_boundary["stages"][0]["active_rollers"] == [12, 1, 2]
        assert group_boundary["stages"][0]["inner_bore_load_active"] is True
        assert group_boundary["stages"][0]["displacement_preload_active"] is False
        assert group_boundary["stages"][0]["displacement_preload_selection"] == "sel_inner_raceway_contact"
        assert group_boundary["stages"][0]["sweep_parameter"] == "radial_load"
        assert group_boundary["stages"][0]["preload_steps"] == "0.001 0.005 0.01 0.05 0.1"
        assert group_boundary["stages"][0]["radial_load_value"] == "0.1[N]"
        assert group_boundary["stages"][0]["temporary_active_roller_stabilization_active"] is True
        assert group_boundary["stages"][0]["active_roller_stabilization_mode"] == "spring"
        assert group_boundary["stages"][0]["active_roller_stabilization_k"] == "1e10[N/m^3]"
        assert group_boundary["stages"][0]["weak_roller_foundation_k"] == "1e8[N/m^3]"
        assert [stage["radial_load_value"] for stage in group_boundary["stages"][:11]] == [
            "0.1[N]",
            "0.101[N]",
            "0.105[N]",
            "0.12[N]",
            "0.15[N]",
            "0.2[N]",
            "0.5[N]",
            "1[N]",
            "5[N]",
            "20[N]",
            "50[N]",
        ]
        assert group_boundary["stages"][1]["use_parametric_sweep"] is False
        assert group_boundary["stages"][1]["reuse_existing_solver"] is False
        assert group_boundary["stages"][1]["preload_steps"] == "0.101"
        assert group_boundary["stages"][7]["name"] == "load_side_3_roller_boundary_load_1n"
        assert group_boundary["stages"][7]["preload_steps"] == "1"
        assert group_boundary["stages"][11]["active_rollers"] == [11, 12, 1, 2, 3, 4]
        assert len(group_boundary["stages"][12]["active_rollers"]) == 12
        assert group_boundary["stages"][12]["name"] == "all_12_roller_boundary_load_50n"
        assert group_boundary["stages"][-1]["inner_bore_load_active"] is True

        assert group_boundary["stages"][-1]["displacement_preload_active"] is False
        assert group_boundary["stages"][-1]["weak_inner_guidance_active"] is True
        assert group_boundary["stages"][-1]["temporary_active_roller_stabilization_active"] is True
        assert group_boundary["stages"][-1]["weak_roller_foundation_k"] == "5e7[N/m^3]"
        assert "group_ramped" in group_boundary["stages"][-1]["load_application_fidelity"]
        assert "not_design_gate" in group_boundary["stages"][-1]["load_application_fidelity"]
        assert "active_roller_ids = set([1, 2, 12])" in setup_codes[0]
        assert "('useparam', 'off')" in setup_codes[1]
        assert "('plistarr', ['0.101'])" in setup_codes[1]
        assert "else:\n    for staged_key, staged_value in [" in setup_codes[1]
        assert "model.study('std1').createAutoSequences('sol')" in setup_codes[1]
        assert "active_roller_ids = set([1, 2, 3, 4, 11, 12])" in setup_codes[11]
        assert "active_roller_ids = set([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])" in setup_codes[12]
        assert len(setup_codes) == 13
        assert "model.param().set('radial_load', '50[N]')" in setup_codes[-1]
        assert "feature('load_inner_bore').active(True)" in setup_codes[0]
        assert "feature('disp_inner_bore_preload').active(False)" in setup_codes[0]
        assert "active_roller_stabilization_mode=' + 'spring'" in setup_codes[0]
        assert "staged_spring_stabilized = staged_active and True and 'spring' == 'spring'" in setup_codes[0]

        setup_codes.clear()
        soft_guidance = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_soft_guidance",
            stage_plot_dir=tmp_path / "soft_guidance_stage_plots",
        )
        assert soft_guidance["success"] is True
        assert soft_guidance["contact_stage_mode"] == "load_side_group_boundary_load_soft_guidance"
        assert len(soft_guidance["stages"]) == 4
        assert [stage["name"] for stage in soft_guidance["stages"]] == [
            "soft_guidance_3_roller_boundary_load_0p1n_bootstrap",
            "soft_guidance_3_roller_boundary_load_0p1n_singlepoint",
            "soft_guidance_3_roller_boundary_load_0p1n_k1e4",
            "soft_guidance_3_roller_boundary_load_0p101n_k1e4",
        ]
        assert [stage["radial_load_value"] for stage in soft_guidance["stages"]] == [
            "0.1[N]",
            "0.1[N]",
            "0.1[N]",
            "0.101[N]",
        ]
        assert soft_guidance["stages"][0]["weak_inner_guidance_k"] == "5e4[N/m^3]"
        assert soft_guidance["stages"][1]["weak_inner_guidance_k"] == "5e4[N/m^3]"
        assert soft_guidance["stages"][2]["weak_inner_guidance_k"] == "1e4[N/m^3]"
        assert soft_guidance["stages"][3]["weak_inner_guidance_k"] == "1e4[N/m^3]"
        assert soft_guidance["stages"][1]["use_parametric_sweep"] is False
        assert soft_guidance["stages"][2]["guidance_diagnostic_role"] == "soften_weak_inner_guidance_only"
        assert soft_guidance["stages"][3]["guidance_diagnostic_role"] == "load_increment_after_soft_guidance"
        assert "soft_weak_guidance" in soft_guidance["stages"][-1]["load_application_fidelity"]
        assert "model.param().set('weak_inner_guidance_k', '1e4[N/m^3]')" in setup_codes[2]
        assert "('plistarr', ['0.101'])" in setup_codes[3]
        assert "active_roller_ids = set([1, 2, 12])" in setup_codes[-1]
        assert "if not False:" in setup_codes[1]
        assert "staged_foundation.set('kPerArea', ['active_roller_stabilization_k'" in setup_codes[0]
        assert "model.param().set('active_roller_stabilization_k', '1e10[N/m^3]')" in setup_codes[0]
        assert "feature(fix_tag).active(staged_roller_fixed)" in setup_codes[0]

        setup_codes.clear()
        contact_relaxation = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_contact_relaxation",
            stage_plot_dir=tmp_path / "contact_relaxation_stage_plots",
        )
        assert contact_relaxation["success"] is True
        assert contact_relaxation["contact_stage_mode"] == "load_side_group_boundary_load_contact_relaxation"
        assert [stage["name"] for stage in contact_relaxation["stages"]] == [
            "contact_relaxation_3_roller_boundary_load_0p1n_bootstrap",
            "contact_relaxation_3_roller_boundary_load_0p1n_penalty1e5",
            "contact_relaxation_3_roller_boundary_load_0p101n_penalty1e5",
        ]
        assert contact_relaxation["stages"][0]["contact_penalty"] == "5e-5*E_steel"
        assert contact_relaxation["stages"][1]["contact_penalty"] == "1e-5*E_steel"
        assert contact_relaxation["stages"][2]["radial_load_value"] == "0.101[N]"
        assert contact_relaxation["stages"][1]["use_parametric_sweep"] is False
        assert contact_relaxation["stages"][1]["weak_inner_guidance_k"] == "5e4[N/m^3]"
        assert contact_relaxation["stages"][1]["contact_relaxation_diagnostic_role"] == "soften_contact_penalty_only_same_load"
        assert "contact_penalty_relaxation" in contact_relaxation["stages"][-1]["load_application_fidelity"]
        assert "('pn_penalty', '1e-5*E_steel')" in setup_codes[1]
        assert "('plistarr', ['0.101'])" in setup_codes[2]
        assert "active_roller_ids = set([1, 2, 12])" in setup_codes[-1]

        setup_codes.clear()
        single_solve = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101",
            stage_plot_dir=tmp_path / "single_solve_0p101_stage_plots",
        )
        assert single_solve["success"] is True
        assert single_solve["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101"
        assert len(single_solve["stages"]) == 1
        stage = single_solve["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_parametric"
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["inner_body_load_active"] is False
        assert stage["displacement_preload_active"] is False
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101"
        assert stage["radial_load_value"] == "0.101[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["reuse_existing_solver"] is False
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["weak_inner_guidance_k"] == "5e4[N/m^3]"
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["active_roller_stabilization_mode"] == "spring"
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p101n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "not_final" in stage["physical_acceptance"]
        assert "('useparam', 'on')" in setup_codes[0]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.101[N]')" in setup_codes[0]
        assert "active_roller_ids = set([1, 2, 12])" in setup_codes[0]
        assert stage["contact_pair_endpoint_overrides"] == {}
        assert len(setup_codes) == 1

        setup_codes.clear()
        actual_area_load = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_actual_area_load",
            stage_plot_dir=tmp_path / "single_solve_0p101_actual_area_stage_plots",
        )
        assert actual_area_load["success"] is True
        assert actual_area_load["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_actual_area_load"
        assert len(actual_area_load["stages"]) == 1
        stage = actual_area_load["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_actual_area_load"
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["radial_load_value"] == "0.101[N]"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101"
        assert stage["contact_penalty"] == "5e-5*E_steel"
        assert stage["contact_relaxation"] == "0.12"
        assert stage["contact_tolerance"] == "3[um]"
        assert stage["inner_bore_load_active"] is True
        assert stage["inner_body_load_active"] is False
        assert stage["displacement_preload_active"] is False
        assert stage["active_roller_stabilization_active"] is True
        assert stage["active_roller_stabilization_mode"] == "spring"
        assert stage["active_roller_stabilization_k"] == "1e10[N/m^3]"
        assert stage["weak_roller_foundation_active"] is True
        assert stage["weak_roller_foundation_k"] == "1e8[N/m^3]"
        assert stage["weak_inner_guidance_active"] is True
        assert stage["weak_inner_guidance_k"] == "5e4[N/m^3]"
        assert stage["contact_pair_endpoint_overrides"] == {}
        assert stage["contact_patch_box_overrides"] == {}
        assert stage["raceway_partition_patch_overrides"] == {}
        assert stage["inner_bore_load_pressure_expression"] == "radial_load/(4.863178789249815e-3[m^2])"
        assert stage["solver_formulation_diagnostic_role"] == (
            "single_solve_0p101_actual_inner_bore_selection_area_pressure_only"
        )
        assert "actual_area_pressure_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "model.param().set('radial_load', '0.101[N]')" in setup_codes[0]
        assert (
            "model.param().set('inner_bore_load_pressure', "
            "'radial_load/(4.863178789249815e-3[m^2])')"
        ) in setup_codes[0]
        assert "'|inner_bore_load_pressure_expression=' + 'radial_load/(4.863178789249815e-3[m^2])'" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        actual_area_singlepoint = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_actual_area_singlepoint",
            stage_plot_dir=tmp_path / "single_solve_0p101_actual_area_singlepoint_stage_plots",
        )
        assert actual_area_singlepoint["success"] is True
        assert (
            actual_area_singlepoint["contact_stage_mode"]
            == "load_side_group_boundary_load_single_solve_0p101_actual_area_singlepoint"
        )
        assert len(actual_area_singlepoint["stages"]) == 1
        stage = actual_area_singlepoint["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_actual_area_singlepoint"
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["radial_load_value"] == "0.101[N]"
        assert stage["preload_steps"] == "0.101"
        assert stage["use_parametric_sweep"] is False
        assert stage["reuse_existing_solver"] is False
        assert stage["contact_penalty"] == "5e-5*E_steel"
        assert stage["contact_relaxation"] == "0.12"
        assert stage["contact_tolerance"] == "3[um]"
        assert stage["inner_bore_load_active"] is True
        assert stage["inner_body_load_active"] is False
        assert stage["displacement_preload_active"] is False
        assert stage["active_roller_stabilization_active"] is True
        assert stage["active_roller_stabilization_mode"] == "spring"
        assert stage["active_roller_stabilization_k"] == "1e10[N/m^3]"
        assert stage["weak_roller_foundation_active"] is True
        assert stage["weak_roller_foundation_k"] == "1e8[N/m^3]"
        assert stage["weak_inner_guidance_active"] is True
        assert stage["weak_inner_guidance_k"] == "5e4[N/m^3]"
        assert stage["contact_pair_endpoint_overrides"] == {}
        assert stage["contact_patch_box_overrides"] == {}
        assert stage["raceway_partition_patch_overrides"] == {}
        assert stage["inner_bore_load_pressure_expression"] == "radial_load/(4.863178789249815e-3[m^2])"
        assert stage["solver_formulation_diagnostic_role"] == (
            "single_solve_0p101_actual_area_pressure_singlepoint_no_radial_load_parametric_sweep"
        )
        assert "actual_area_pressure_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "model.param().set('radial_load', '0.101[N]')" in setup_codes[0]
        assert (
            "model.param().set('inner_bore_load_pressure', "
            "'radial_load/(4.863178789249815e-3[m^2])')"
        ) in setup_codes[0]
        assert "('useparam', 'off')" in setup_codes[0]
        assert "('plistarr', ['0.101'])" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        actual_area_fine_bootstrap = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_actual_area_fine_bootstrap",
            stage_plot_dir=tmp_path / "single_solve_0p101_actual_area_fine_bootstrap_stage_plots",
        )
        assert actual_area_fine_bootstrap["success"] is True
        assert (
            actual_area_fine_bootstrap["contact_stage_mode"]
            == "load_side_group_boundary_load_single_solve_0p101_actual_area_fine_bootstrap"
        )
        assert len(actual_area_fine_bootstrap["stages"]) == 1
        stage = actual_area_fine_bootstrap["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_actual_area_fine_bootstrap"
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["radial_load_value"] == "0.101[N]"
        assert stage["preload_steps"] == (
            "1e-5 5e-5 1e-4 5e-4 0.001 0.002 0.005 0.01 0.02 0.05 0.08 0.1 0.1005 0.101"
        )
        assert stage["contact_penalty"] == "5e-5*E_steel"
        assert stage["contact_relaxation"] == "0.12"
        assert stage["contact_tolerance"] == "3[um]"
        assert stage["inner_bore_load_active"] is True
        assert stage["inner_body_load_active"] is False
        assert stage["displacement_preload_active"] is False
        assert stage["active_roller_stabilization_active"] is True
        assert stage["active_roller_stabilization_mode"] == "spring"
        assert stage["active_roller_stabilization_k"] == "1e10[N/m^3]"
        assert stage["weak_roller_foundation_active"] is True
        assert stage["weak_roller_foundation_k"] == "1e8[N/m^3]"
        assert stage["weak_inner_guidance_active"] is True
        assert stage["weak_inner_guidance_k"] == "5e4[N/m^3]"
        assert stage["contact_pair_endpoint_overrides"] == {}
        assert stage["contact_patch_box_overrides"] == {}
        assert stage["raceway_partition_patch_overrides"] == {}
        assert stage["inner_bore_load_pressure_expression"] == "radial_load/(4.863178789249815e-3[m^2])"
        assert stage["solver_formulation_diagnostic_role"] == (
            "single_solve_0p101_actual_area_pressure_fine_radial_load_bootstrap_only"
        )
        assert "actual_area_pressure_fine_bootstrap_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "model.param().set('radial_load', '0.101[N]')" in setup_codes[0]
        assert (
            "model.param().set('inner_bore_load_pressure', "
            "'radial_load/(4.863178789249815e-3[m^2])')"
        ) in setup_codes[0]
        assert (
            "('plistarr', ['1e-5 5e-5 1e-4 5e-4 0.001 0.002 0.005 0.01 0.02 0.05 0.08 0.1 0.1005 0.101'])"
        ) in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        actual_area_fixed_active_bootstrap = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_actual_area_fixed_active_bootstrap",
            stage_plot_dir=tmp_path / "single_solve_0p101_actual_area_fixed_active_bootstrap_stage_plots",
        )
        assert actual_area_fixed_active_bootstrap["success"] is True
        assert (
            actual_area_fixed_active_bootstrap["contact_stage_mode"]
            == "load_side_group_boundary_load_single_solve_0p101_actual_area_fixed_active_bootstrap"
        )
        assert len(actual_area_fixed_active_bootstrap["stages"]) == 1
        stage = actual_area_fixed_active_bootstrap["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_actual_area_fixed_active_bootstrap"
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["radial_load_value"] == "0.101[N]"
        assert stage["preload_steps"] == (
            "1e-5 5e-5 1e-4 5e-4 0.001 0.002 0.005 0.01 0.02 0.05 0.08 0.1 0.1005 0.101"
        )
        assert stage["inner_bore_load_pressure_expression"] == "radial_load/(4.863178789249815e-3[m^2])"
        assert stage["contact_penalty"] == "5e-5*E_steel"
        assert stage["contact_relaxation"] == "0.12"
        assert stage["contact_tolerance"] == "3[um]"
        assert stage["active_roller_stabilization_active"] is True
        assert stage["active_roller_stabilization_mode"] == "fixed"
        assert stage["active_roller_stabilization_k"] == "1e10[N/m^3]"
        assert stage["weak_inner_guidance_active"] is True
        assert stage["weak_inner_guidance_k"] == "5e4[N/m^3]"
        assert stage["contact_pair_endpoint_overrides"] == {}
        assert stage["contact_patch_box_overrides"] == {}
        assert stage["raceway_partition_patch_overrides"] == {}
        assert stage["solver_formulation_diagnostic_role"] == (
            "single_solve_0p101_actual_area_pressure_fixed_active_roller_bootstrap_only"
        )
        assert "actual_area_pressure_fixed_active_bootstrap_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "model.param().set('radial_load', '0.101[N]')" in setup_codes[0]
        assert (
            "model.param().set('inner_bore_load_pressure', "
            "'radial_load/(4.863178789249815e-3[m^2])')"
        ) in setup_codes[0]
        assert "'|active_roller_stabilization_mode=' + 'fixed'" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        actual_area_after_bootstrap = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_actual_area_after_nominal_bootstrap",
            stage_plot_dir=tmp_path / "single_solve_0p101_actual_area_after_bootstrap_stage_plots",
        )
        assert actual_area_after_bootstrap["success"] is True
        assert (
            actual_area_after_bootstrap["contact_stage_mode"]
            == "load_side_group_boundary_load_single_solve_0p101_actual_area_after_nominal_bootstrap"
        )
        assert len(actual_area_after_bootstrap["stages"]) == 2
        bootstrap_stage, actual_area_stage = actual_area_after_bootstrap["stages"]
        assert bootstrap_stage["name"] == "single_solve_3_roller_boundary_load_0p101n_parametric"
        assert bootstrap_stage["inner_bore_load_pressure_expression"] == "inner_bore_load_pressure"
        assert actual_area_stage["name"] == (
            "single_solve_3_roller_boundary_load_0p101n_actual_area_after_nominal_bootstrap"
        )
        assert actual_area_stage["active_rollers"] == [12, 1, 2]
        assert actual_area_stage["radial_load_value"] == "0.101[N]"
        assert actual_area_stage["preload_steps"] == "0.101"
        assert actual_area_stage["use_parametric_sweep"] is False
        assert actual_area_stage["inner_bore_load_pressure_expression"] == (
            "radial_load/(4.863178789249815e-3[m^2])"
        )
        assert actual_area_stage["contact_penalty"] == "5e-5*E_steel"
        assert actual_area_stage["contact_relaxation"] == "0.12"
        assert actual_area_stage["contact_tolerance"] == "3[um]"
        assert actual_area_stage["active_roller_stabilization_active"] is True
        assert actual_area_stage["active_roller_stabilization_mode"] == "spring"
        assert actual_area_stage["weak_inner_guidance_active"] is True
        assert actual_area_stage["weak_inner_guidance_k"] == "5e4[N/m^3]"
        assert actual_area_stage["solver_formulation_diagnostic_role"] == (
            "actual_area_pressure_after_nominal_pressure_bootstrap_only"
        )
        assert "actual_area_pressure_after_nominal_bootstrap" in actual_area_stage["load_application_fidelity"]
        assert "model.param().set('radial_load', '0.101[N]')" in setup_codes[1]
        assert (
            "model.param().set('inner_bore_load_pressure', "
            "'radial_load/(4.863178789249815e-3[m^2])')"
        ) in setup_codes[1]
        assert "('useparam', 'off')" in setup_codes[1]
        assert len(setup_codes) == 2

        setup_codes.clear()
        pair_swap = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_pair_swap",
            stage_plot_dir=tmp_path / "single_solve_0p101_pair_swap_stage_plots",
        )
        assert pair_swap["success"] is True
        assert pair_swap["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_pair_swap"
        assert len(pair_swap["stages"]) == 1
        stage = pair_swap["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_pair_swap"
        assert stage["active_rollers"] == [12, 1, 2]
        overrides = stage["contact_pair_endpoint_overrides"]
        assert sorted(overrides) == ["cp_roller_1_inner_raceway", "cp_roller_1_outer_raceway"]
        assert overrides["cp_roller_1_inner_raceway"] == {
            "source": "sel_inner_raceway_1_contact",
            "destination": "sel_roller_1_inner_contact",
        }
        assert overrides["cp_roller_1_outer_raceway"] == {
            "source": "sel_outer_raceway_1_contact",
            "destination": "sel_roller_1_outer_contact",
        }
        assert "roller1_pair_endpoint_swap" in stage["physical_acceptance"]
        assert "CONTACT_PAIR_ENDPOINT_OVERRIDE" in setup_codes[0]
        assert "cp_roller_1_inner_raceway" in setup_codes[0]
        assert "sel_inner_raceway_1_contact" in setup_codes[0]
        assert "contact_pair_endpoint_overrides=" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        patch_shrink = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_patch_shrink",
            stage_plot_dir=tmp_path / "single_solve_0p101_patch_shrink_stage_plots",
        )
        assert patch_shrink["success"] is True
        assert patch_shrink["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_patch_shrink"
        assert len(patch_shrink["stages"]) == 1
        stage = patch_shrink["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_patch_shrink"
        assert stage["active_rollers"] == [12, 1, 2]
        overrides = stage["contact_patch_box_overrides"]
        assert sorted(overrides) == [
            "box_roller_1_inner_contact_patch",
            "box_roller_1_outer_contact_patch",
        ]
        assert overrides["box_roller_1_inner_contact_patch"]["xmin"] == "22.6[mm]"
        assert overrides["box_roller_1_inner_contact_patch"]["xmax"] == "23.4[mm]"
        assert overrides["box_roller_1_outer_contact_patch"]["xmin"] == "30.6[mm]"
        assert overrides["box_roller_1_outer_contact_patch"]["xmax"] == "31.4[mm]"
        assert stage["contact_pair_endpoint_overrides"] == {}
        assert stage["contact_feature_property_overrides"] == {}
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_roller1_contact_patch_box_shrink_only"
        assert "roller1_patch_shrink" in stage["load_application_fidelity"]
        assert "CONTACT_PATCH_BOX_OVERRIDE" in setup_codes[0]
        assert "box_roller_1_inner_contact_patch" in setup_codes[0]
        assert "22.6[mm]" in setup_codes[0]
        assert "contact_patch_box_overrides=" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        box_intersection_rebuild = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_box_intersection_rebuild",
            stage_plot_dir=tmp_path / "single_solve_0p101_box_intersection_rebuild_stage_plots",
        )
        assert box_intersection_rebuild["success"] is True
        assert box_intersection_rebuild["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_box_intersection_rebuild"
        assert len(box_intersection_rebuild["stages"]) == 1
        stage = box_intersection_rebuild["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_box_intersection_rebuild"
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["raceway_partition_patch_overrides"] == {}
        assert stage["raceway_selection_entity_overrides"] == {}
        overrides = stage["contact_patch_box_overrides"]
        assert overrides["box_roller_1_outer_contact_patch"]["xmin"] == "26.4[mm]"
        assert overrides["box_roller_1_outer_contact_patch"]["xmax"] == "27.6[mm]"
        assert overrides["box_roller_1_outer_contact_patch"]["zmin"] == "-8.6[mm]"
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_roller1_box_intersection_contact_patch_rebuild_only"
        assert "box_intersection_rebuild" in stage["load_application_fidelity"]
        assert "CONTACT_PATCH_BOX_OVERRIDE" in setup_codes[0]
        assert "box_roller_1_outer_contact_patch" in setup_codes[0]
        assert "26.4[mm]" in setup_codes[0]
        assert "raceway_partition_patch_overrides={}" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        outer_x31_box_intersection = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_outer_x31_box_intersection",
            stage_plot_dir=tmp_path / "single_solve_0p101_outer_x31_box_intersection_stage_plots",
        )
        assert outer_x31_box_intersection["success"] is True
        assert outer_x31_box_intersection["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_outer_x31_box_intersection"
        assert len(outer_x31_box_intersection["stages"]) == 1
        stage = outer_x31_box_intersection["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_outer_x31_box_intersection"
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["raceway_partition_patch_overrides"] == {}
        assert stage["raceway_selection_entity_overrides"] == {}
        overrides = stage["contact_patch_box_overrides"]
        assert overrides["box_roller_1_outer_contact_patch"]["xmin"] == "30.4[mm]"
        assert overrides["box_roller_1_outer_contact_patch"]["xmax"] == "31.6[mm]"
        assert overrides["box_roller_1_outer_contact_patch"]["zmax"] == "8.6[mm]"
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_roller1_outer_raceway_x31_box_intersection_only"
        assert "outer_x31_box_intersection" in stage["load_application_fidelity"]
        assert "CONTACT_PATCH_BOX_OVERRIDE" in setup_codes[0]
        assert "box_roller_1_outer_contact_patch" in setup_codes[0]
        assert "31.6[mm]" in setup_codes[0]
        assert "raceway_partition_patch_overrides={}" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        partitioned_raceway_patch = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch",
            stage_plot_dir=tmp_path / "single_solve_0p101_partitioned_raceway_patch_stage_plots",
        )
        assert partitioned_raceway_patch["success"] is True
        assert partitioned_raceway_patch["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch"
        assert len(partitioned_raceway_patch["stages"]) == 1
        stage = partitioned_raceway_patch["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_partitioned_raceway_patch"
        assert stage["active_rollers"] == [12, 1, 2]
        partition_overrides = stage["raceway_partition_patch_overrides"]
        assert sorted(partition_overrides) == [
            "partition_roller_1_inner_raceway_patch",
            "partition_roller_1_outer_raceway_patch",
        ]
        assert partition_overrides["partition_roller_1_inner_raceway_patch"]["target_object"] == "inner_ring"
        assert partition_overrides["partition_roller_1_outer_raceway_patch"]["target_object"] == "outer_ring"
        assert partition_overrides["partition_roller_1_inner_raceway_patch"]["selection_tag"] == "sel_inner_raceway_1_contact"
        assert partition_overrides["partition_roller_1_outer_raceway_patch"]["selection_tag"] == "sel_outer_raceway_1_contact"
        assert partition_overrides["partition_roller_1_inner_raceway_patch"]["tool_pos"] == ["23.0[mm]", "0[mm]", "0[mm]"]
        assert partition_overrides["partition_roller_1_outer_raceway_patch"]["tool_pos"] == ["31.0[mm]", "0[mm]", "0[mm]"]
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_roller1_geometry_partitioned_raceway_patch_only"
        assert "partitioned_raceway_patch" in stage["load_application_fidelity"]
        assert "RACEWAY_PARTITION_PATCH_RUN" in setup_codes[0]
        assert "model.component('comp1').geom('geom1').create(partition_tag, 'Partition')" in setup_codes[0]
        assert "partition_tool_roller_1_inner_raceway_patch" in setup_codes[0]
        assert "raceway_partition_patch_overrides=" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        partitioned_raceway_patch_rebind = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_rebind",
            stage_plot_dir=tmp_path / "single_solve_0p101_partitioned_raceway_patch_rebind_stage_plots",
        )
        assert partitioned_raceway_patch_rebind["success"] is True
        assert partitioned_raceway_patch_rebind["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_rebind"
        assert len(partitioned_raceway_patch_rebind["stages"]) == 1
        stage = partitioned_raceway_patch_rebind["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_partitioned_raceway_patch_rebind"
        assert stage["active_rollers"] == [12, 1, 2]
        partition_overrides = stage["raceway_partition_patch_overrides"]
        assert partition_overrides["partition_roller_1_inner_raceway_patch"]["pair_tag"] == "cp_roller_1_inner_raceway"
        assert partition_overrides["partition_roller_1_outer_raceway_patch"]["pair_tag"] == "cp_roller_1_outer_raceway"
        assert partition_overrides["partition_roller_1_inner_raceway_patch"]["explicit_selection_entities"] == [131, 134, 140, 141, 148, 151]
        assert partition_overrides["partition_roller_1_outer_raceway_patch"]["explicit_selection_entities"] == [8, 9, 11, 15, 25, 26]
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_roller1_geometry_partitioned_raceway_patch_explicit_rebind"
        assert "partitioned_raceway_patch_explicit_rebind" in stage["load_application_fidelity"]
        assert "RACEWAY_PARTITION_PATCH_EXPLICIT_SELECTION" in setup_codes[0]
        assert "RACEWAY_PARTITION_PATCH_PAIR_REBIND" in setup_codes[0]
        assert "destination().named(selection_tag)" in setup_codes[0]
        assert "explicit_selection_entities" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        partitioned_raceway_patch_min_entities = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_min_entities",
            stage_plot_dir=tmp_path / "single_solve_0p101_partitioned_raceway_patch_min_entities_stage_plots",
        )
        assert partitioned_raceway_patch_min_entities["success"] is True
        assert partitioned_raceway_patch_min_entities["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_min_entities"
        assert len(partitioned_raceway_patch_min_entities["stages"]) == 1
        stage = partitioned_raceway_patch_min_entities["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_partitioned_raceway_patch_min_entities"
        assert stage["active_rollers"] == [12, 1, 2]
        partition_overrides = stage["raceway_partition_patch_overrides"]
        assert partition_overrides["partition_roller_1_inner_raceway_patch"]["explicit_selection_entities"] == [140, 141]
        assert partition_overrides["partition_roller_1_outer_raceway_patch"]["explicit_selection_entities"] == [25, 26]
        assert partition_overrides["partition_roller_1_inner_raceway_patch"]["keeptool"] == "off"
        assert partition_overrides["partition_roller_1_outer_raceway_patch"]["keeptool"] == "off"
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_roller1_partitioned_raceway_patch_min_entities_keeptool_off"
        assert "partitioned_raceway_patch_min_entities" in stage["load_application_fidelity"]
        assert "RACEWAY_PARTITION_PATCH_EXPLICIT_SELECTION" in setup_codes[0]
        assert "RACEWAY_PARTITION_PATCH_PAIR_REBIND" in setup_codes[0]
        assert "'keeptool', raceway_partition_payload.get('keeptool', 'on')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        full_raceway_destination = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_full_raceway_destination",
            stage_plot_dir=tmp_path / "single_solve_0p101_full_raceway_destination_stage_plots",
        )
        assert full_raceway_destination["success"] is True
        assert full_raceway_destination["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_full_raceway_destination"
        assert len(full_raceway_destination["stages"]) == 1
        stage = full_raceway_destination["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_full_raceway_destination"
        assert stage["active_rollers"] == [12, 1, 2]
        overrides = stage["contact_pair_endpoint_overrides"]
        assert sorted(overrides) == [
            "cp_roller_12_inner_raceway",
            "cp_roller_12_outer_raceway",
            "cp_roller_1_inner_raceway",
            "cp_roller_1_outer_raceway",
            "cp_roller_2_inner_raceway",
            "cp_roller_2_outer_raceway",
        ]
        assert overrides["cp_roller_1_inner_raceway"] == {"destination": "sel_inner_raceway_contact"}
        assert overrides["cp_roller_1_outer_raceway"] == {"destination": "sel_outer_raceway_contact"}
        assert overrides["cp_roller_2_inner_raceway"] == {"destination": "sel_inner_raceway_contact"}
        assert overrides["cp_roller_12_outer_raceway"] == {"destination": "sel_outer_raceway_contact"}
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_full_raceway_pair_destination_only"
        assert "full_raceway_destination" in stage["load_application_fidelity"]
        assert "CONTACT_PAIR_ENDPOINT_OVERRIDE" in setup_codes[0]
        assert "cp_roller_12_outer_raceway" in setup_codes[0]
        assert "sel_outer_raceway_contact" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        entity_raceway_override = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_entity_raceway_override",
            stage_plot_dir=tmp_path / "single_solve_0p101_entity_raceway_override_stage_plots",
        )
        assert entity_raceway_override["success"] is True
        assert entity_raceway_override["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_entity_raceway_override"
        assert len(entity_raceway_override["stages"]) == 1
        stage = entity_raceway_override["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_entity_raceway_override"
        assert stage["active_rollers"] == [12, 1, 2]
        overrides = stage["raceway_selection_entity_overrides"]
        assert overrides["sel_inner_raceway_1_contact"] == [132, 133]
        assert overrides["sel_outer_raceway_2_contact"] == [9]
        assert overrides["sel_outer_raceway_12_contact"] == [8]
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_explicit_raceway_entity_override_from_saved_mph_geometry_moments"
        assert "explicit_raceway_entity_override" in stage["load_application_fidelity"]
        assert "RACEWAY_SELECTION_ENTITY_OVERRIDE" in setup_codes[0]
        assert "RACEWAY_SELECTION_ENTITY_REBIND" in setup_codes[0]
        assert "destination().named(raceway_selection_tag)" in setup_codes[0]
        assert "selection().create(raceway_selection_tag, 'Explicit')" in setup_codes[0]
        assert "sel_inner_raceway_1_contact" in setup_codes[0]
        assert "132" in setup_codes[0]
        assert stage["contact_pair_endpoint_overrides"] == {}
        assert len(setup_codes) == 1

        setup_codes.clear()
        roller1_outer_entity_override = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override",
            stage_plot_dir=tmp_path / "single_solve_0p101_roller1_outer_entity_override_stage_plots",
        )
        assert roller1_outer_entity_override["success"] is True
        assert roller1_outer_entity_override["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override"
        assert len(roller1_outer_entity_override["stages"]) == 1
        stage = roller1_outer_entity_override["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_outer_entity_override"
        assert stage["active_rollers"] == [12, 1, 2]
        overrides = stage["raceway_selection_entity_overrides"]
        assert overrides == {"sel_outer_raceway_1_contact": [8, 9]}
        assert "sel_inner_raceway_1_contact" not in overrides
        assert "sel_outer_raceway_2_contact" not in overrides
        assert "sel_outer_raceway_12_contact" not in overrides
        assert stage["solver_formulation_diagnostic_role"] == (
            "single_solve_0p101_roller1_outer_destination_explicit_entity_override_only"
        )
        assert "roller1_outer_destination_entity_override" in stage["load_application_fidelity"]
        assert "RACEWAY_SELECTION_ENTITY_OVERRIDE" in setup_codes[0]
        assert "RACEWAY_SELECTION_ENTITY_REBIND" in setup_codes[0]
        assert "destination().named(raceway_selection_tag)" in setup_codes[0]
        assert "selection().create(raceway_selection_tag, 'Explicit')" in setup_codes[0]
        assert "sel_outer_raceway_1_contact" in setup_codes[0]
        assert "sel_inner_raceway_1_contact" not in setup_codes[0]
        assert "sel_outer_raceway_2_contact" not in setup_codes[0]
        assert "sel_outer_raceway_12_contact" not in setup_codes[0]
        assert "8" in setup_codes[0]
        assert "9" in setup_codes[0]
        assert stage["contact_pair_endpoint_overrides"] == {}
        assert len(setup_codes) == 1

        setup_codes.clear()
        retained_conformal_entity_override = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override",
            roller1_outer_entity_override_entities=(13, 14, 18, 19),
            stage_plot_dir=tmp_path / "single_solve_0p101_retained_conformal_entity_override_stage_plots",
        )
        assert retained_conformal_entity_override["success"] is True
        assert len(retained_conformal_entity_override["stages"]) == 1
        stage = retained_conformal_entity_override["stages"][0]
        assert stage["raceway_selection_entity_overrides"] == {
            "sel_outer_raceway_1_contact": [13, 14, 18, 19]
        }
        assert stage["entity_override_source"] == "saved_solved_mph_entity_transfer_probe_nonzero_integrals"
        assert stage["solver_formulation_diagnostic_role"].endswith("_from_entity_transfer_probe")
        assert "13" in setup_codes[0]
        assert "14" in setup_codes[0]
        assert "18" in setup_codes[0]
        assert "19" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        roller1_gapoffset = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_gapoffset_minus3um",
            stage_plot_dir=tmp_path / "single_solve_0p101_roller1_gapoffset_stage_plots",
        )
        assert roller1_gapoffset["success"] is True
        assert roller1_gapoffset["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_gapoffset_minus3um"
        assert len(roller1_gapoffset["stages"]) == 1
        stage = roller1_gapoffset["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_gapoffset_minus3um"
        assert stage["active_rollers"] == [12, 1, 2]
        overrides = stage["contact_feature_property_overrides"]
        assert overrides == {
            "contact_roller_1_inner": {"gapoffset": "-3[um]"},
            "contact_roller_1_outer": {"gapoffset": "-3[um]"},
        }
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_roller1_contact_gapoffset_minus3um_only"
        assert "roller1_gapoffset_minus3um" in stage["load_application_fidelity"]
        assert "CONTACT_FEATURE_PROPERTY_OVERRIDE" in setup_codes[0]
        assert "contact_roller_1_inner" in setup_codes[0]
        assert "gapoffset" in setup_codes[0]
        assert "-3[um]" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        roller1_source_offset = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_minus3um",
            stage_plot_dir=tmp_path / "single_solve_0p101_roller1_source_offset_stage_plots",
        )
        assert roller1_source_offset["success"] is True
        assert roller1_source_offset["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_minus3um"
        assert len(roller1_source_offset["stages"]) == 1
        stage = roller1_source_offset["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_source_offset_minus3um"
        assert stage["active_rollers"] == [12, 1, 2]
        overrides = stage["contact_feature_property_overrides"]
        assert overrides == {
            "contact_roller_1_inner": {"source_offset": "-3[um]"},
            "contact_roller_1_outer": {"source_offset": "-3[um]"},
        }
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_roller1_contact_source_offset_minus3um_only"
        assert "roller1_source_offset_minus3um" in stage["load_application_fidelity"]
        assert "CONTACT_FEATURE_PROPERTY_OVERRIDE" in setup_codes[0]
        assert "contact_roller_1_inner" in setup_codes[0]
        assert "source_offset" in setup_codes[0]
        assert "-3[um]" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        roller1_source_offset_plus = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_plus3um",
            stage_plot_dir=tmp_path / "single_solve_0p101_roller1_source_offset_plus_stage_plots",
        )
        assert roller1_source_offset_plus["success"] is True
        assert roller1_source_offset_plus["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_plus3um"
        assert len(roller1_source_offset_plus["stages"]) == 1
        stage = roller1_source_offset_plus["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_source_offset_plus3um"
        assert stage["active_rollers"] == [12, 1, 2]
        overrides = stage["contact_feature_property_overrides"]
        assert overrides == {
            "contact_roller_1_inner": {"source_offset": "3[um]"},
            "contact_roller_1_outer": {"source_offset": "3[um]"},
        }
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_roller1_contact_source_offset_plus3um_only"
        assert "roller1_source_offset_plus3um" in stage["load_application_fidelity"]
        assert "CONTACT_FEATURE_PROPERTY_OVERRIDE" in setup_codes[0]
        assert "contact_roller_1_inner" in setup_codes[0]
        assert "source_offset" in setup_codes[0]
        assert "3[um]" in setup_codes[0]
        assert "-3[um]" not in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        roller1_offset = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_offset_minus3um",
            stage_plot_dir=tmp_path / "single_solve_0p101_roller1_offset_stage_plots",
        )
        assert roller1_offset["success"] is True
        assert roller1_offset["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_offset_minus3um"
        assert len(roller1_offset["stages"]) == 1
        stage = roller1_offset["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_offset_minus3um"
        assert stage["active_rollers"] == [12, 1, 2]
        overrides = stage["contact_feature_property_overrides"]
        assert overrides == {
            "contact_roller_1_inner": {"offset": "-3[um]"},
            "contact_roller_1_outer": {"offset": "-3[um]"},
        }
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_roller1_contact_offset_minus3um_only"
        assert "roller1_offset_minus3um" in stage["load_application_fidelity"]
        assert "CONTACT_FEATURE_PROPERTY_OVERRIDE" in setup_codes[0]
        assert "contact_roller_1_inner" in setup_codes[0]
        assert "offset" in setup_codes[0]
        assert "-3[um]" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        roller1_offset_plus = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_roller1_offset_plus3um",
            stage_plot_dir=tmp_path / "single_solve_0p101_roller1_offset_plus_stage_plots",
        )
        assert roller1_offset_plus["success"] is True
        assert roller1_offset_plus["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_roller1_offset_plus3um"
        assert len(roller1_offset_plus["stages"]) == 1
        stage = roller1_offset_plus["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_roller1_offset_plus3um"
        assert stage["active_rollers"] == [12, 1, 2]
        overrides = stage["contact_feature_property_overrides"]
        assert overrides == {
            "contact_roller_1_inner": {"offset": "3[um]"},
            "contact_roller_1_outer": {"offset": "3[um]"},
        }
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_roller1_contact_offset_plus3um_only"
        assert "roller1_offset_plus3um" in stage["load_application_fidelity"]
        assert "CONTACT_FEATURE_PROPERTY_OVERRIDE" in setup_codes[0]
        assert "contact_roller_1_inner" in setup_codes[0]
        assert "offset" in setup_codes[0]
        assert "3[um]" in setup_codes[0]
        assert "-3[um]" not in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        active_spring_softened = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p101_active_spring1e9",
            stage_plot_dir=tmp_path / "single_solve_0p101_active_spring1e9_stage_plots",
        )
        assert active_spring_softened["success"] is True
        assert active_spring_softened["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p101_active_spring1e9"
        assert len(active_spring_softened["stages"]) == 1
        stage = active_spring_softened["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p101n_active_spring1e9"
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["radial_load_value"] == "0.101[N]"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101"
        assert stage["contact_penalty"] == "5e-5*E_steel"
        assert stage["active_roller_stabilization_active"] is True
        assert stage["active_roller_stabilization_mode"] == "spring"
        assert stage["active_roller_stabilization_k"] == "1e9[N/m^3]"
        assert stage["weak_roller_foundation_k"] == "1e8[N/m^3]"
        assert stage["contact_pair_endpoint_overrides"] == {}
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_0p101_active_roller_spring_softened_only"
        assert "active_spring1e9" in stage["load_application_fidelity"]
        assert "model.param().set('active_roller_stabilization_k', '1e9[N/m^3]')" in setup_codes[0]
        assert "model.param().set('radial_load', '0.101[N]')" in setup_codes[0]
        assert "('pn_penalty', '5e-5*E_steel')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p12 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p12",
            stage_plot_dir=tmp_path / "single_solve_0p12_stage_plots",
        )
        assert single_solve_0p12["success"] is True
        assert single_solve_0p12["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p12"
        assert len(single_solve_0p12["stages"]) == 1
        stage = single_solve_0p12["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p12n_parametric"
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12"
        assert stage["radial_load_value"] == "0.12[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["reuse_existing_solver"] is False
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p12_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p12n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "not_final" in stage["physical_acceptance"]
        assert "('useparam', 'on')" in setup_codes[0]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.12[N]')" in setup_codes[0]
        assert "active_roller_ids = set([1, 2, 12])" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p13 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p13",
            stage_plot_dir=tmp_path / "single_solve_0p13_stage_plots",
        )
        assert single_solve_0p13["success"] is True
        assert single_solve_0p13["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p13"
        assert len(single_solve_0p13["stages"]) == 1
        stage = single_solve_0p13["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p13n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13"
        assert stage["radial_load_value"] == "0.13[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p13_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p13n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.13[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p14 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p14",
            stage_plot_dir=tmp_path / "single_solve_0p14_stage_plots",
        )
        assert single_solve_0p14["success"] is True
        assert single_solve_0p14["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p14"
        assert len(single_solve_0p14["stages"]) == 1
        stage = single_solve_0p14["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p14n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14"
        assert stage["radial_load_value"] == "0.14[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p14_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p14n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.14[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p145 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p145",
            stage_plot_dir=tmp_path / "single_solve_0p145_stage_plots",
        )
        assert single_solve_0p145["success"] is True
        assert single_solve_0p145["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p145"
        assert len(single_solve_0p145["stages"]) == 1
        stage = single_solve_0p145["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p145n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145"
        assert stage["radial_load_value"] == "0.145[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p145_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p145n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.145[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p1475 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p1475",
            stage_plot_dir=tmp_path / "single_solve_0p1475_stage_plots",
        )
        assert single_solve_0p1475["success"] is True
        assert single_solve_0p1475["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p1475"
        assert len(single_solve_0p1475["stages"]) == 1
        stage = single_solve_0p1475["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p1475n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475"
        assert stage["radial_load_value"] == "0.1475[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p1475_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p1475n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.1475[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p14875 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p14875",
            stage_plot_dir=tmp_path / "single_solve_0p14875_stage_plots",
        )
        assert single_solve_0p14875["success"] is True
        assert single_solve_0p14875["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p14875"
        assert len(single_solve_0p14875["stages"]) == 1
        stage = single_solve_0p14875["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p14875n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875"
        assert stage["radial_load_value"] == "0.14875[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p14875_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p14875n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "not_final" in stage["physical_acceptance"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.14875[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p149375 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p149375",
            stage_plot_dir=tmp_path / "single_solve_0p149375_stage_plots",
        )
        assert single_solve_0p149375["success"] is True
        assert single_solve_0p149375["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p149375"
        assert len(single_solve_0p149375["stages"]) == 1
        stage = single_solve_0p149375["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p149375n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375"
        assert stage["radial_load_value"] == "0.149375[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p149375_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p149375n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "not_final" in stage["physical_acceptance"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.149375[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p15_fine = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p15_fine",
            stage_plot_dir=tmp_path / "single_solve_0p15_fine_stage_plots",
        )
        assert single_solve_0p15_fine["success"] is True
        assert single_solve_0p15_fine["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p15_fine"
        assert len(single_solve_0p15_fine["stages"]) == 1
        stage = single_solve_0p15_fine["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p15n_fine_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15"
        assert stage["radial_load_value"] == "0.15[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p15_fine_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p15n_fine_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "not_final" in stage["physical_acceptance"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.15[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p1625 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p1625",
            stage_plot_dir=tmp_path / "single_solve_0p1625_stage_plots",
        )
        assert single_solve_0p1625["success"] is True
        assert single_solve_0p1625["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p1625"
        assert len(single_solve_0p1625["stages"]) == 1
        stage = single_solve_0p1625["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p1625n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625"
        assert stage["radial_load_value"] == "0.1625[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p1625_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p1625n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "not_final" in stage["physical_acceptance"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.1625[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p175 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p175",
            stage_plot_dir=tmp_path / "single_solve_0p175_stage_plots",
        )
        assert single_solve_0p175["success"] is True
        assert single_solve_0p175["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p175"
        assert len(single_solve_0p175["stages"]) == 1
        stage = single_solve_0p175["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p175n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175"
        assert stage["radial_load_value"] == "0.175[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p175_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p175n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "not_final" in stage["physical_acceptance"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.175[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p1875 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p1875",
            stage_plot_dir=tmp_path / "single_solve_0p1875_stage_plots",
        )
        assert single_solve_0p1875["success"] is True
        assert single_solve_0p1875["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p1875"
        assert len(single_solve_0p1875["stages"]) == 1
        stage = single_solve_0p1875["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p1875n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875"
        assert stage["radial_load_value"] == "0.1875[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p1875_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p1875n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "not_final" in stage["physical_acceptance"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.1875[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p19375 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p19375",
            stage_plot_dir=tmp_path / "single_solve_0p19375_stage_plots",
        )
        assert single_solve_0p19375["success"] is True
        assert single_solve_0p19375["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p19375"
        assert len(single_solve_0p19375["stages"]) == 1
        stage = single_solve_0p19375["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p19375n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875 0.19375"
        assert stage["radial_load_value"] == "0.19375[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p19375_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p19375n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "not_final" in stage["physical_acceptance"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875 0.19375'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.19375[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p196875 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p196875",
            stage_plot_dir=tmp_path / "single_solve_0p196875_stage_plots",
        )
        assert single_solve_0p196875["success"] is True
        assert single_solve_0p196875["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p196875"
        assert len(single_solve_0p196875["stages"]) == 1
        stage = single_solve_0p196875["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p196875n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875 0.19375 0.196875"
        assert stage["radial_load_value"] == "0.196875[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p196875_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p196875n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "not_final" in stage["physical_acceptance"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875 0.19375 0.196875'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.196875[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p1984375 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p1984375",
            stage_plot_dir=tmp_path / "single_solve_0p1984375_stage_plots",
        )
        assert single_solve_0p1984375["success"] is True
        assert single_solve_0p1984375["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p1984375"
        assert len(single_solve_0p1984375["stages"]) == 1
        stage = single_solve_0p1984375["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p1984375n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875 0.19375 0.196875 0.1984375"
        assert stage["radial_load_value"] == "0.1984375[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p1984375_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p1984375n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "not_final" in stage["physical_acceptance"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875 0.19375 0.196875 0.1984375'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.1984375[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p2_fine = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p2_fine",
            stage_plot_dir=tmp_path / "single_solve_0p2_fine_stage_plots",
        )
        assert single_solve_0p2_fine["success"] is True
        assert single_solve_0p2_fine["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p2_fine"
        assert len(single_solve_0p2_fine["stages"]) == 1
        stage = single_solve_0p2_fine["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p2n_fine_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875 0.19375 0.196875 0.1984375 0.2"
        assert stage["radial_load_value"] == "0.2[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p2_fine_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p2n_fine_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "not_final" in stage["physical_acceptance"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875 0.19375 0.196875 0.1984375 0.2'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.2[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p15 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p15",
            stage_plot_dir=tmp_path / "single_solve_0p15_stage_plots",
        )
        assert single_solve_0p15["success"] is True
        assert single_solve_0p15["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p15"
        assert len(single_solve_0p15["stages"]) == 1
        stage = single_solve_0p15["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p15n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.15"
        assert stage["radial_load_value"] == "0.15[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p15_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p15n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.15'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.15[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_0p2 = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_0p2",
            stage_plot_dir=tmp_path / "single_solve_0p2_stage_plots",
        )
        assert single_solve_0p2["success"] is True
        assert single_solve_0p2["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_0p2"
        assert len(single_solve_0p2["stages"]) == 1
        stage = single_solve_0p2["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_0p2n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.15 0.2"
        assert stage["radial_load_value"] == "0.2[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_0p2_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_0p2n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.15 0.2'])" in setup_codes[0]
        assert "model.param().set('radial_load', '0.2[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        single_solve_1n = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_single_solve_1n",
            stage_plot_dir=tmp_path / "single_solve_1n_stage_plots",
        )
        assert single_solve_1n["success"] is True
        assert single_solve_1n["contact_stage_mode"] == "load_side_group_boundary_load_single_solve_1n"
        assert len(single_solve_1n["stages"]) == 1
        stage = single_solve_1n["stages"][0]
        assert stage["name"] == "single_solve_3_roller_boundary_load_1n_parametric"
        assert stage["preload_steps"] == "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.15 0.2 0.5 1"
        assert stage["radial_load_value"] == "1[N]"
        assert stage["use_parametric_sweep"] is True
        assert stage["active_rollers"] == [12, 1, 2]
        assert stage["inner_bore_load_active"] is True
        assert stage["cage_contact_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == "single_solve_parametric_to_1n_no_prior_bootstrap_or_cross_stage_solver_edit"
        assert "single_solve_parametric_1n_diagnostic" in stage["load_application_fidelity"]
        assert "not_design_gate" in stage["load_application_fidelity"]
        assert "('plistarr', ['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.15 0.2 0.5 1'])" in setup_codes[0]
        assert "model.param().set('radial_load', '1[N]')" in setup_codes[0]
        assert len(setup_codes) == 1

        setup_codes.clear()
        micro_continuation = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_micro_continuation",
            stage_plot_dir=tmp_path / "micro_continuation_stage_plots",
        )
        assert micro_continuation["success"] is True
        assert micro_continuation["contact_stage_mode"] == "load_side_group_boundary_load_micro_continuation"
        assert [stage["name"] for stage in micro_continuation["stages"]] == [
            "micro_continuation_3_roller_boundary_load_0p1n_bootstrap",
            "micro_continuation_3_roller_boundary_load_0p101n_parametric",
        ]
        assert micro_continuation["stages"][1]["preload_steps"] == "0.1 0.1005 0.101"
        assert micro_continuation["stages"][1]["use_parametric_sweep"] is True
        assert micro_continuation["stages"][1]["contact_penalty"] == "5e-5*E_steel"
        assert micro_continuation["stages"][1]["weak_inner_guidance_k"] == "5e4[N/m^3]"
        assert micro_continuation["stages"][1]["active_roller_stabilization_mode"] == "spring"
        assert micro_continuation["stages"][1]["solver_formulation_diagnostic_role"] == "micro_parametric_continuation_after_bootstrap_only"
        assert "micro_parametric_continuation" in micro_continuation["stages"][-1]["load_application_fidelity"]
        assert "('useparam', 'on')" in setup_codes[1]
        assert "('plistarr', ['0.1 0.1005 0.101'])" in setup_codes[1]
        assert "model.study('std1').createAutoSequences('sol')" in setup_codes[1]
        assert "active_roller_ids = set([1, 2, 12])" in setup_codes[-1]

        setup_codes.clear()
        fixed_stabilization = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_boundary_load_fixed_stabilization",
            stage_plot_dir=tmp_path / "fixed_stabilization_stage_plots",
        )
        assert fixed_stabilization["success"] is True
        assert fixed_stabilization["contact_stage_mode"] == "load_side_group_boundary_load_fixed_stabilization"
        assert [stage["name"] for stage in fixed_stabilization["stages"]] == [
            "fixed_stabilization_3_roller_boundary_load_0p1n_bootstrap",
            "fixed_stabilization_3_roller_boundary_load_0p1n_fixed_active",
            "fixed_stabilization_3_roller_boundary_load_0p101n_fixed_active",
        ]
        assert fixed_stabilization["stages"][0]["active_roller_stabilization_mode"] == "spring"
        assert fixed_stabilization["stages"][1]["active_roller_stabilization_mode"] == "fixed"
        assert fixed_stabilization["stages"][2]["radial_load_value"] == "0.101[N]"
        assert fixed_stabilization["stages"][1]["use_parametric_sweep"] is False
        assert fixed_stabilization["stages"][1]["stabilization_diagnostic_role"] == "switch_active_roller_stabilization_from_spring_to_fixed_only"
        assert "fixed_active_roller_stabilization" in fixed_stabilization["stages"][-1]["load_application_fidelity"]
        assert "not_design_gate" in fixed_stabilization["stages"][-1]["physical_acceptance"]
        assert "staged_roller_fixed = (not staged_active) or (True and 'fixed' == 'fixed' and staged_active)" in setup_codes[1]
        assert "('useparam', 'off')" in setup_codes[1]
        assert "('plistarr', ['0.101'])" in setup_codes[2]

        setup_codes.clear()
        preclosed_boundary = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_group_preclosed_boundary_load",
            stage_plot_dir=tmp_path / "preclosed_boundary_stage_plots",
        )
        assert preclosed_boundary["success"] is True
        assert len(preclosed_boundary["stages"]) == 7
        assert preclosed_boundary["stages"][0]["name"] == "load_side_3_roller_compaction_preload"
        assert preclosed_boundary["stages"][4]["name"] == "all_12_roller_group_compaction_preload"
        assert preclosed_boundary["stages"][5]["name"] == "preclosed_boundary_load_probe_0p001n"
        assert preclosed_boundary["stages"][-1]["name"] == "preclosed_boundary_load_high_ramp"
        assert preclosed_boundary["stages"][-1]["inner_bore_load_active"] is True
        assert preclosed_boundary["stages"][-1]["inner_body_load_active"] is False
        assert preclosed_boundary["stages"][5]["displacement_preload_active"] is True
        assert preclosed_boundary["stages"][-1]["displacement_preload_active"] is False
        assert preclosed_boundary["stages"][5]["radial_load_value"] == "0.001[N]"
        assert preclosed_boundary["stages"][-1]["radial_load_value"] == "3000[N]"
        assert preclosed_boundary["stages"][-1]["sweep_parameter"] == "radial_load"
        assert preclosed_boundary["stages"][5]["preload_steps"] == "0.001"
        assert preclosed_boundary["stages"][-1]["preload_steps"] == "5 10 25 50 100 250 500 1000 2000 3000"
        assert preclosed_boundary["stages"][5]["active_roller_stabilization_active"] is True
        assert preclosed_boundary["stages"][5]["active_roller_stabilization_mode"] == "spring"
        assert preclosed_boundary["stages"][5]["reuse_existing_solver"] is True
        assert preclosed_boundary["stages"][5]["use_parametric_sweep"] is False
        assert "if not True:" in setup_codes[5]
        assert "if False:" in setup_codes[5]
        assert "if not True:" in setup_codes[-1]
        assert preclosed_boundary["stages"][-1]["displacement_preload_selection"] == "sel_inner_raceway_contact"
        assert "release_displacement_preload" in preclosed_boundary["stages"][-1]["load_application_fidelity"]
        assert "retained_displacement_preload" in preclosed_boundary["stages"][5]["load_application_fidelity"]
        assert "model.param().set('radial_load', '3000[N]')" in setup_codes[-1]
        assert "feature('load_inner_bore').active(True)" in setup_codes[-1]
        assert "feature('load_inner_body_visual').active(False)" in setup_codes[-1]

        high_body_visual = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="all_raceway_high_body_load_visual",
            stage_plot_dir=tmp_path / "high_body_stage_plots",
        )
        assert high_body_visual["success"] is True
        assert high_body_visual["stages"][-1]["name"] == "raceway_contact_high_body_load_visual"
        assert high_body_visual["stages"][-1]["inner_body_load_active"] is True
        assert high_body_visual["stages"][-1]["inner_bore_load_active"] is False
        assert high_body_visual["stages"][-1]["weak_roller_foundation_active"] is False
        assert "body_load" in high_body_visual["stages"][-1]["load_application_fidelity"]
        assert "not_final_design_load" in high_body_visual["stages"][-1]["physical_acceptance"]

        setup_codes.clear()
        solve_calls.clear()
        full_cage = demo._run_3d_staged_contact_solve("staged_model", run_full_cage_stage=True)
        assert full_cage["success"] is True
        assert len(full_cage["stages"]) == 4
        assert full_cage["stages"][-1]["contact_scope"] == "roller_inner_outer_raceway_plus_cage_pockets"
        assert full_cage["stages"][-1]["temporary_cage_stabilization_active"] is False
        assert "staged_cage.active(False and staged_active)" in setup_codes[0]
        assert "staged_cage.active(False and staged_active)" in setup_codes[1]
        assert "staged_cage.active(True and staged_active)" in setup_codes[3]
        assert "temporary_cage_stabilization_active=" in setup_codes[3]

        assert "fix_cage_stage_stabilization').active(False)" in setup_codes[3]
        assert "staged_inner.active(staged_active)" in setup_codes[3]
        assert "staged_outer.active(staged_active)" in setup_codes[3]

        setup_codes.clear()
        solve_calls.clear()
        load_side = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="load_side_then_all",
        )
        assert load_side["success"] is True
        assert load_side["contact_stage_mode"] == "load_side_then_all"
        assert load_side["stages"][0]["name"] == "single_load_roller_contact_closure_bootstrap"
        assert load_side["stages"][0]["active_rollers"] == [1]
        assert load_side["stages"][0]["sweep_parameter"] == "radial_load"
        assert load_side["stages"][0]["inner_bore_load_active"] is True
        assert load_side["stages"][0]["displacement_preload_active"] is False
        assert load_side["stages"][0]["temporary_active_roller_stabilization_active"] is True
        assert load_side["stages"][0]["physical_acceptance"] == "bootstrap_only_not_final_physical_contact_validation"
        assert load_side["stages"][0]["inactive_roller_stabilization_active"] is True
        assert load_side["stages"][1]["name"] == "single_load_roller_radial_load_ramp"
        assert load_side["stages"][1]["temporary_active_roller_stabilization_active"] is False
        assert load_side["stages"][2]["active_rollers"] == [12, 1, 2]
        assert "active_roller_ids = set([1])" in setup_codes[0]
        assert "('pname', ['radial_load'])" in setup_codes[0]
        assert "('punit', ['N'])" in setup_codes[0]
        assert "temporary_active_roller_stabilization_active=' + str(True)" in setup_codes[0]
        assert "staged_roller_fixed = (not staged_active) or (True and 'fixed' == 'fixed' and staged_active)" in setup_codes[0]
        assert "staged_roller_fixed = (not staged_active) or (False and 'fixed' == 'fixed' and staged_active)" in setup_codes[1]
        assert "fix_roller_' + str(staged_index) + '_stage_stabilization" in setup_codes[0]
        assert len(solve_calls) == 6

        setup_codes.clear()
        solve_calls.clear()
        single_smoke = demo._run_3d_staged_contact_solve(
            "staged_model",
            contact_stage_mode="single_roller_displacement_preload",
        )
        assert single_smoke["success"] is True
        assert single_smoke["contact_stage_mode"] == "single_roller_displacement_preload"
        assert single_smoke["stages"][0]["name"] == "single_roller_physical_displacement_preload"
        assert single_smoke["stages"][0]["active_rollers"] == [1]
        assert single_smoke["stages"][0]["inner_bore_load_active"] is False
        assert single_smoke["stages"][0]["displacement_preload_active"] is True
        assert single_smoke["stages"][0]["temporary_active_roller_stabilization_active"] is False
        assert single_smoke["stages"][0]["physical_acceptance"].startswith("candidate_physical_smoke")
        assert single_smoke["stages"][1]["sweep_parameter"] == "radial_load"
        assert single_smoke["stages"][2]["active_rollers"] == [1]
        assert "active_roller_ids = set([1])" in setup_codes[0]
        assert "('pname', ['inner_radial_displacement'])" in setup_codes[0]
        assert "staged_roller_fixed = (not staged_active) or (False and 'fixed' == 'fixed' and staged_active)" in setup_codes[0]
        assert len(solve_calls) == 3

    def test_legacy_raceway_highload_direct_contract(self, monkeypatch, tmp_path):
        from scripts import run_agent_3d_bearing_full_demo as demo

        def fake_solve(model_name: str):
            return {"success": True, "model_name": model_name, "status": "solved"}

        def fake_evaluate(model_name: str, expression: str):
            if expression == "solid.mises":
                return {
                    "success": True,
                    "model_name": model_name,
                    "expression": expression,
                    "statistics": {"max": 3.2e6, "mean": 7.4e5, "min": 0.0},
                }
            if expression == "solid.disp":
                return {
                    "success": True,
                    "model_name": model_name,
                    "expression": expression,
                    "statistics": {"max": 3.0e-3, "mean": 7.0e-4, "min": 0.0},
                }
            return {"success": True, "model_name": model_name, "expression": expression, "value": 1.95e6}

        def fake_stage_plot(model_name: str, *, stage_name: str, output_dir):
            return {
                "success": True,
                "model_name": model_name,
                "stage": stage_name,
                "plot_type": "native_comsol_volume",
                "filepath": str(output_dir / f"{stage_name}.png"),
                "export_method": "java:Image2D:Volume",
                "dataset": "dset1",
                "png_quality": {"success": True},
            }

        monkeypatch.setattr(demo, "comsol_solve", fake_solve)
        monkeypatch.setattr(demo, "comsol_evaluate", fake_evaluate)
        monkeypatch.setattr(demo, "_export_native_3d_stage_volume_plot", fake_stage_plot)
        monkeypatch.setattr(demo, "_render_stress_projection_from_open_model", lambda model_name, plot_path: {"success": True, "filepath": str(plot_path)})
        monkeypatch.setattr(demo, "comsol_save_model", lambda model_name, path: {"success": True, "saved_to": path})

        result = demo._run_legacy_raceway_highload_direct("legacy_model", artifact_root=tmp_path)
        assert result["success"] is True
        assert result["contact_scope"] == "all_12_rollers_inner_outer_raceway_only_24_contact_pairs"
        assert result["cage_contact_active"] is False
        assert "BodyLoad" in result["physical_contact_validation"]["warnings"][1]
        assert result["physical_contact_validation"]["global_max_von_mises_pa"] == 3.2e6
        assert result["native_volume_plot"]["plot_type"] == "native_comsol_volume"
        assert result["requested_stage_image"]["success"] is True
        assert result["requested_stage_image"]["request_class"] == "high_load_12roller_native_comsol_stress_image"
        assert result["requested_stage_image"]["selected_stage"] == "legacy_raceway_highload_direct"
        assert result["requested_stage_image"]["native_comsol_png"].endswith("legacy_raceway_highload_direct.png")
        assert result["requested_stage_image"]["max_von_mises_pa"] == 3.2e6
        assert result["requested_stage_image"]["contact_pressure_est_pa"] == 1.95e6
        assert result["requested_stage_image"]["production_ready"] is False
        assert "full boundary-load/cage high-load stage" in result["requested_stage_image"]["stage_selection_reason"]

    def test_requested_stage_image_selects_high_load_and_rejects_low_preload(self):
        from scripts import run_agent_3d_bearing_full_demo as demo

        low_only = {
            "stages": [
                {
                    "name": "raceway_contact_refined_preload",
                    "solve": {"success": True},
                    "native_volume_plot": {
                        "success": True,
                        "filepath": "/tmp/refined.png",
                        "plot_type": "native_comsol_volume",
                    },
                    "stress": {"success": True, "statistics": {"max": 9.0e3}},
                    "displacement": {"success": True, "statistics": {"max": 2.0e-4}},
                    "contact_pressure": {"success": True, "value": 1.0e2},
                    "inner_bore_load_active": False,
                    "displacement_preload_active": True,
                    "physical_acceptance": "accepted_all_12_roller_raceway_contact_displacement_preload_smoke",
                }
            ]
        }
        rejected = demo._select_requested_stage_image_from_staged_solve(low_only)
        assert rejected["success"] is False
        assert rejected["image_role"] == "best_available_native_stage_is_not_high_load"
        assert rejected["native_comsol_png"] is None
        assert rejected["best_available_native_comsol_png"] == "/tmp/refined.png"
        assert "must not be presented" in rejected["stage_selection_reason"]

        implausible_singlepoint = {
            "stages": [
                low_only["stages"][0],
                {
                    "name": "soft_guidance_3_roller_boundary_load_0p1n_singlepoint",
                    "solve": {"success": True},
                    "native_volume_plot": {
                        "success": True,
                        "filepath": "/tmp/exploded.png",
                        "plot_type": "native_comsol_volume",
                    },
                    "stress": {"success": True, "statistics": {"max": 1.4e13}},
                    "displacement": {"success": True, "statistics": {"max": 20.0}},
                    "contact_pressure": {"success": True, "value": 65.0},
                    "inner_bore_load_active": True,
                    "displacement_preload_active": False,
                    "weak_inner_guidance_active": True,
                    "load_application_fidelity": "inner_bore_boundary_load_load_side_three_roller_soft_weak_guidance_diagnostic_not_design_gate",
                },
            ]
        }
        plausible_fallback = demo._select_requested_stage_image_from_staged_solve(implausible_singlepoint)
        assert plausible_fallback["success"] is False
        assert plausible_fallback["image_role"] == "best_available_native_stage_is_not_high_load"
        assert plausible_fallback["best_available_stage"] == "raceway_contact_refined_preload"
        assert plausible_fallback["best_available_native_comsol_png"] == "/tmp/refined.png"
        assert plausible_fallback["rejected_converged_stage_count"] == 1

        all_implausible = {
            "stages": [implausible_singlepoint["stages"][1]]
        }
        rejected_implausible = demo._select_requested_stage_image_from_staged_solve(all_implausible)
        assert rejected_implausible["success"] is False
        assert rejected_implausible["image_role"] == "no_physically_plausible_converged_native_comsol_stage_available"
        assert rejected_implausible["best_available_rejected_stage"] == "soft_guidance_3_roller_boundary_load_0p1n_singlepoint"
        assert any("implausibly high" in error for error in rejected_implausible["best_available_rejected_reasons"])

        high_continuation = {
            "stages": [
                low_only["stages"][0],
                {
                    "name": "continuous_boundary_load_high_ramp_retained_preload",
                    "solve": {"success": True},
                    "native_volume_plot": {
                        "success": True,
                        "filepath": "/tmp/high.png",
                        "plot_type": "native_comsol_volume",
                        "png_quality": {"success": True},
                    },
                    "stress": {"success": True, "statistics": {"max": 2.5e6}},
                    "displacement": {"success": True, "statistics": {"max": 4.0e-4}},
                    "contact_pressure": {"success": True, "value": 3.1e6},
                    "contact_scope": "all_12_rollers_inner_outer_raceway_true_contact_inner_bore_boundary_load_high_ramp_retained_preload",
                    "inner_bore_load_active": True,
                    "active_rollers": list(range(1, 13)),
                    "per_roller_probe_results": [
                        {"roller": f"roller_{index}", "success": True, "value": 2.0e6 + index}
                        for index in range(1, 13)
                    ],
                    "displacement_preload_active": True,
                    "weak_inner_guidance_active": True,
                    "load_application_fidelity": "inner_bore_boundary_load_high_ramp_with_retained_displacement_preload_and_weak_inner_guidance_not_design_gate",
                    "physical_acceptance": "continuous_high_load_boundary_load_diagnostic_requires_mpa_stress_native_png_and_explicit_stabilization_warning",
                },
            ]
        }
        selected = demo._select_requested_stage_image_from_staged_solve(high_continuation)
        assert selected["success"] is True
        assert selected["selected_stage"] == "continuous_boundary_load_high_ramp_retained_preload"
        assert selected["native_comsol_png"] == "/tmp/high.png"
        assert selected["max_von_mises_pa"] == 2.5e6
        assert selected["contact_pressure_est_pa"] == 3.1e6
        assert selected["production_ready"] is False
        assert "not a final design-grade" in selected["stage_selection_reason"]

        split_high = {
            "stages": [
                {
                    "name": "split_control_boundary_load_high_ramp",
                    "solve": {"success": True},
                    "native_volume_plot": {
                        "success": True,
                        "filepath": "/tmp/split-high.png",
                        "plot_type": "native_comsol_volume",
                    },
                    "stress": {"success": True, "statistics": {"max": 3.0e6}},
                    "displacement": {"success": True, "statistics": {"max": 5.0e-4}},
                    "contact_pressure": {"success": True, "value": 3.3e6},
                    "inner_bore_load_active": True,
                    "active_rollers": list(range(1, 13)),
                    "per_roller_probe_results": [
                        {"roller": f"roller_{index}", "success": True, "value": 2.5e6 + index}
                        for index in range(1, 13)
                    ],
                    "displacement_preload_active": True,
                    "displacement_preload_selection": "sel_inner_raceway_contact",
                    "weak_inner_guidance_active": True,
                    "load_application_fidelity": "inner_bore_boundary_load_high_ramp_with_split_raceway_displacement_closure_and_weak_guidance_not_design_gate",
                    "physical_acceptance": "split_control_high_load_boundary_load_diagnostic_requires_mpa_stress_native_png_and_explicit_stabilization_warning",
                }
            ]
        }
        split_selected = demo._select_requested_stage_image_from_staged_solve(split_high)
        assert split_selected["success"] is True
        assert split_selected["selected_stage"] == "split_control_boundary_load_high_ramp"
        assert split_selected["native_comsol_png"] == "/tmp/split-high.png"
        assert split_selected["production_ready"] is False

        reaction_high = {
            "stages": [
                {
                    "name": "raceway_contact_high_preload_reaction_equivalent",
                    "solve": {"success": True},
                    "native_volume_plot": {
                        "success": True,
                        "filepath": "/tmp/reaction-high.png",
                        "plot_type": "native_comsol_volume",
                    },
                    "stress": {"success": True, "statistics": {"max": 1.2e6}},
                    "displacement": {"success": True, "statistics": {"max": 3.0e-6}},
                    "contact_pressure": {"success": True, "value": 1.95e6},
                    "reaction_equivalent": {
                        "success": True,
                        "best_reaction_force_abs_n": 3000.0,
                        "equivalent_pressure_pa": 1.3e6,
                    },
                    "inner_bore_load_active": False,
                    "displacement_preload_active": True,
                    "load_application_fidelity": "displacement_controlled_high_preload_with_reaction_probe_not_boundary_load_design_gate",
                    "physical_acceptance": "high_preload_reaction_equivalent_true_12_roller_raceway_contact_requires_reaction_probe_or_clear_failure",
                }
            ]
        }
        reaction_selected = demo._select_requested_stage_image_from_staged_solve(reaction_high)
        assert reaction_selected["success"] is True
        assert reaction_selected["selected_stage"] == "raceway_contact_high_preload_reaction_equivalent"
        assert reaction_selected["reaction_equivalent"]["best_reaction_force_abs_n"] == 3000.0

    def test_displacement_reaction_equivalent_probe_records_candidate_failures(self, monkeypatch):
        from scripts import run_agent_3d_bearing_full_demo as demo

        evaluated: list[str] = []

        def fake_execute_java(code: str, *, model_name: str):
            assert (
                "intop_displacement_reaction_probe" in code
                or "REACTION_EXPR_VALUE" in code
                or "REACTION_SURFACE_VALUE" in code
            )
            if "REACTION_EQUIVALENT_PROBE" in code:
                assert "sel_inner_bore_load_surface" in code
            return {"success": True, "model_name": model_name}

        def fake_evaluate(model_name: str, expression: str):
            evaluated.append(expression)
            if expression.startswith("abs("):
                return {"success": True, "model_name": model_name, "expression": expression, "value": 123.0}
            if "solid.RFx" in expression:
                return {"success": True, "model_name": model_name, "expression": expression, "value": -42.0}
            return {"success": False, "error": f"unknown expression: {expression}"}

        monkeypatch.setattr(demo, "comsol_execute_java", fake_execute_java)
        monkeypatch.setattr(demo, "comsol_evaluate", fake_evaluate)

        result = demo._evaluate_displacement_reaction_equivalent(
            "reaction_model",
            selection_name="sel_inner_bore_load_surface",
        )

        assert result["success"] is True
        assert result["best_expression"] == "intop_displacement_reaction_probe(solid.RFx)"
        assert result["best_reaction_force_abs_n"] == 42.0
        assert result["equivalent_pressure_pa"] == 123.0
        assert result["candidate_count"] == len(result["evaluations"])
        assert result["candidate_count"] > len(evaluated) - 1
        assert any("solid.RFy" in item["expression"] for item in result["evaluations"])
        assert any("comp1.intop_displacement_reaction_probe" in item["expression"] for item in result["evaluations"])
        assert any(item.get("method") == "java_intsurface" for item in result["evaluations"])
        assert any("solid.T_stressx" in item["expression"] for item in result["evaluations"])
        assert any("solid.sx*nx" in item["expression"] for item in result["evaluations"])
        assert result["candidate_audit"]["nonzero_success_count"] >= 1
        assert result["candidate_audit"]["method_counts"]["java_intsurface"] >= 1

    def test_displacement_reaction_equivalent_probe_can_use_surface_integral_fallback(self, monkeypatch):
        from scripts import run_agent_3d_bearing_full_demo as demo

        def fake_execute_java(code: str, *, model_name: str):
            if "REACTION_EQUIVALENT_PROBE" in code:
                return {"success": True, "model_name": model_name}
            if "REACTION_SURFACE_VALUE|tag=reaction_surface_probe_1|value=" in code:
                return {
                    "success": True,
                    "model_name": model_name,
                    "stdout": "REACTION_SURFACE_VALUE|tag=reaction_surface_probe_1|value=-55.0\n",
                }
            if "REACTION_EXPR_VALUE|tag=reaction_equivalent_pressure|value=" in code:
                return {
                    "success": True,
                    "model_name": model_name,
                    "stdout": "REACTION_EXPR_VALUE|tag=reaction_equivalent_pressure|value=456.0\n",
                }
            return {"success": False, "model_name": model_name, "error": "unknown operator"}

        def fake_evaluate(model_name: str, expression: str):
            return {"success": False, "model_name": model_name, "expression": expression, "error": "unknown operator"}

        monkeypatch.setattr(demo, "comsol_execute_java", fake_execute_java)
        monkeypatch.setattr(demo, "comsol_evaluate", fake_evaluate)

        result = demo._evaluate_displacement_reaction_equivalent(
            "reaction_model",
            selection_name="sel_inner_bore_load_surface",
        )

        assert result["success"] is True
        assert result["best_expression"] == "solid.RFx"
        assert result["best_method"] == "java_intsurface"
        assert result["best_reaction_force_abs_n"] == 55.0
        assert result["equivalent_pressure_pa"] == 456.0
        assert result["candidate_audit"]["nonzero_success_count"] == 1
        assert result["candidate_audit"]["unknown_operator_count"] >= 1

    def test_displacement_reaction_equivalent_probe_rejects_zero_surface_integral(self, monkeypatch):
        from scripts import run_agent_3d_bearing_full_demo as demo

        def fake_execute_java(code: str, *, model_name: str):
            if "REACTION_EQUIVALENT_PROBE" in code:
                return {
                    "success": True,
                    "model_name": model_name,
                    "stdout": (
                        "REACTION_EQUIVALENT_SETUP_JSON_START\n"
                        "{\"operator_exists\": true, \"selection_bound\": true, "
                        "\"selection_named\": {\"success\": true, \"value\": \"sel_inner_bore_load_surface\"}}\n"
                        "REACTION_EQUIVALENT_SETUP_JSON_END\n"
                    ),
                }
            if "REACTION_SURFACE_VALUE" in code:
                tag_match = re.search(r"REACTION_SURFACE_VALUE\|tag=([^|]+)\|value=", code)
                tag = tag_match.group(1) if tag_match else "reaction_surface_probe"
                return {
                    "success": True,
                    "model_name": model_name,
                    "stdout": f"REACTION_SURFACE_VALUE|tag={tag}|value=0.0\n",
                }
            return {"success": False, "model_name": model_name, "error": "unknown operator"}

        def fake_evaluate(model_name: str, expression: str):
            return {"success": False, "model_name": model_name, "expression": expression, "error": "unknown operator"}

        monkeypatch.setattr(demo, "comsol_execute_java", fake_execute_java)
        monkeypatch.setattr(demo, "comsol_evaluate", fake_evaluate)

        result = demo._evaluate_displacement_reaction_equivalent(
            "reaction_model",
            selection_name="sel_inner_bore_load_surface",
        )

        assert result["success"] is False
        assert result["evaluated_candidate_success_count"] > 0
        assert result["successful_candidate_count"] == 0
        assert result["best_reaction_force_abs_n"] is None
        assert result["setup_audit"]["success"] is True
        assert result["candidate_audit"]["zero_result_count"] > 0
        assert result["candidate_audit"]["nonzero_success_count"] == 0
        assert "nonzero reaction" in result["warning"]

    def test_stage_evidence_matrix_scans_summaries_and_marks_fidelity(self, tmp_path):
        from scripts import run_agent_3d_bearing_full_demo as demo

        run_dir = tmp_path / "runtime_smoke" / "bearing_case"
        run_dir.mkdir(parents=True)
        summary = {
            "model_name": "bearing_case",
            "contact_stage_mode": "load_side_group_boundary_load",
            "geometry_overrides": {
                "contact_interference": "20[um]",
                "cage_pocket_clearance": None,
            },
            "requested_stage_image": {
                "selected_stage": "all_12_roller_boundary_load_50n",
                "native_comsol_png": str(run_dir / "stage_plots" / "all_12.png"),
                "production_ready": False,
                "load_application_fidelity": "inner_bore_boundary_load_group_ramped_free_closure_single_solve_active_spring_stabilized_not_design_gate",
            },
            "physical_contact_validation": {"quality_level": "raceway_contact_physics_smoke"},
            "staged_contact_solve": {
                "contact_stage_mode": "load_side_group_boundary_load",
                "stages": [
                    {
                        "name": "load_side_3_roller_boundary_load_0p1n",
                        "solve": {"success": True},
                        "native_volume_plot": {
                            "success": True,
                            "filepath": str(run_dir / "stage_plots" / "three.png"),
                            "png_quality": {"success": True},
                        },
                        "stress": {"success": True, "statistics": {"max": 1.0e5}},
                        "inner_ring_stress": {"success": True, "value": 8.0e4},
                        "displacement": {"success": True, "statistics": {"max": 1.0e-6}},
                        "contact_pressure": {"success": True, "value": 5.0e4},
                        "inner_bore_load_active": True,
                        "inner_body_load_active": False,
                        "active_rollers": [12, 1, 2],
                        "cage_contact_active": False,
                        "weak_inner_guidance_active": True,
                        "temporary_active_roller_stabilization_active": True,
                        "active_roller_stabilization_mode": "spring",
                        "displacement_preload_active": False,
                        "per_roller_probe_results": [
                            {"roller": "roller_1", "success": True, "value": 1.1e5},
                            {"roller": "roller_2", "success": True, "value": 1.2e5},
                            {"roller": "roller_12", "success": True, "value": 1.3e5},
                        ],
                        "load_application_fidelity": "inner_bore_boundary_load_group_ramped_free_closure_single_solve_active_spring_stabilized_not_design_gate",
                    },
                    {
                        "name": "all_12_roller_boundary_load_50n",
                        "solve": {"success": True},
                        "native_volume_plot": {
                            "success": True,
                            "filepath": str(run_dir / "stage_plots" / "all_12.png"),
                            "png_quality": {"success": True},
                        },
                        "stress": {"success": True, "statistics": {"max": 2.0e6}},
                        "inner_ring_stress": {"success": True, "value": 1.8e6},
                        "displacement": {"success": True, "statistics": {"max": 2.0e-5}},
                        "contact_pressure": {"success": True, "value": 6.0e5},
                        "reaction_equivalent": {
                            "success": True,
                            "candidate_count": 12,
                            "successful_candidate_count": 1,
                            "best_expression": "comp1.intop_displacement_reaction_probe(solid.RFx)",
                            "best_reaction_force_abs_n": 50.0,
                        },
                        "inner_bore_load_active": True,
                        "inner_body_load_active": False,
                        "active_rollers": list(range(1, 13)),
                        "cage_contact_active": False,
                        "weak_inner_guidance_active": True,
                        "temporary_active_roller_stabilization_active": True,
                        "active_roller_stabilization_mode": "spring",
                        "displacement_preload_active": False,
                        "reaction_equivalent_requested": True,
                        "load_application_fidelity": "inner_bore_boundary_load_group_ramped_free_closure_single_solve_active_spring_stabilized_not_design_gate",
                    },
                    {
                        "name": "raceway_contact_high_preload_reaction_equivalent",
                        "solve": {"success": True},
                        "native_volume_plot": {
                            "success": True,
                            "filepath": str(run_dir / "stage_plots" / "preload.png"),
                            "png_quality": {"success": True},
                        },
                        "stress": {"success": True, "statistics": {"max": 3.0e6}},
                        "inner_ring_stress": {"success": True, "value": 2.8e6},
                        "displacement": {"success": True, "statistics": {"max": 3.0e-5}},
                        "contact_pressure": {"success": True, "value": 7.0e5},
                        "reaction_equivalent": {"success": True, "best_reaction_force_abs_n": 80.0},
                        "inner_bore_load_active": False,
                        "inner_body_load_active": False,
                        "active_rollers": list(range(1, 13)),
                        "cage_contact_active": False,
                        "weak_inner_guidance_active": False,
                        "temporary_active_roller_stabilization_active": False,
                        "active_roller_stabilization_mode": "fixed",
                        "displacement_preload_active": True,
                        "inner_radial_displacement": "3[um]",
                        "load_application_fidelity": "displacement_controlled_high_preload_with_reaction_probe_not_boundary_load_design_gate",
                    },
                    {
                        "name": "soft_guidance_3_roller_boundary_load_0p1n_singlepoint",
                        "solve": {"success": True},
                        "native_volume_plot": {
                            "success": True,
                            "filepath": str(run_dir / "stage_plots" / "exploded.png"),
                            "png_quality": {"success": True},
                        },
                        "stress": {"success": True, "statistics": {"max": 1.4e13}},
                        "inner_ring_stress": {"success": True, "value": 7.5e13},
                        "displacement": {"success": True, "statistics": {"max": 20.0}},
                        "contact_pressure": {"success": True, "value": 65.0},
                        "inner_bore_load_active": True,
                        "inner_body_load_active": False,
                        "active_rollers": [12, 1, 2],
                        "cage_contact_active": False,
                        "weak_inner_guidance_active": True,
                        "temporary_active_roller_stabilization_active": True,
                        "active_roller_stabilization_mode": "spring",
                        "displacement_preload_active": False,
                        "load_application_fidelity": "inner_bore_boundary_load_load_side_three_roller_soft_weak_guidance_diagnostic_not_design_gate",
                    },
                ],
            },
        }
        (run_dir / "direct_3d_bearing_summary.json").write_text(json.dumps(summary), encoding="utf-8")
        reaction_probe_dir = run_dir / "reaction_probe_post_mph"
        reaction_probe_dir.mkdir()
        (reaction_probe_dir / "reaction_probe_summary.json").write_text(json.dumps({
            "success": True,
            "kind": "bearing_3d_saved_mph_reaction_probe",
            "mph_path": str(run_dir / "stage_models" / "post_reaction_probe_configured.mph"),
            "selection_name": "sel_inner_bore_load_surface",
            "reaction_verified": True,
            "reaction_equivalent": {
                "success": True,
                "candidate_count": 40,
                "evaluated_candidate_success_count": 9,
                "successful_candidate_count": 0,
                "best_reaction_force_abs_n": 0.0,
                "setup_audit": {
                    "success": True,
                    "operator_exists": True,
                    "selection_bound": True,
                },
                "candidate_audit": {
                    "diagnostic_class_counts": {
                        "unknown_operator": 23,
                        "zero_result": 9,
                        "selection_error": 8,
                    },
                    "nonzero_success_count": 0,
                },
                "warning": "No probed COMSOL reaction-force expression evaluated to a nonzero reaction.",
            },
        }), encoding="utf-8")

        matrix = demo.build_stage_evidence_matrix(search_root=tmp_path / "runtime_smoke")

        assert matrix["summary_count"] == 1
        assert matrix["row_count"] == 4
        assert matrix["production_ready_count"] == 0
        assert matrix["reaction_verified_stage_count"] == 2
        assert matrix["saved_reaction_probe_report_count"] == 1
        assert matrix["saved_reaction_probe_verified_count"] == 0
        saved_probe = matrix["saved_reaction_probe_reports"][0]
        assert saved_probe["reaction_verified"] is False
        assert saved_probe["candidate_audit"]["diagnostic_class_counts"]["unknown_operator"] == 23
        all_12 = [row for row in matrix["rows"] if row["stage"] == "all_12_roller_boundary_load_50n"][0]
        assert all_12["boundary_load_active"] is True
        assert all_12["temporary_spring"] is True
        assert all_12["active_roller_count"] == 12
        assert all_12["production_ready"] is False
        assert all_12["geometry_overrides"]["contact_interference"] == "20[um]"
        load_side = [row for row in matrix["rows"] if row["stage"] == "load_side_3_roller_boundary_load_0p1n"][0]
        assert load_side["active_roller_probe_success_count"] == 3
        assert load_side["active_roller_nonzero_probe_count"] == 3
        assert load_side["active_roller_max_von_mises_pa"] == 1.3e5
        exploded = [row for row in matrix["rows"] if row["stage"] == "soft_guidance_3_roller_boundary_load_0p1n_singlepoint"][0]
        assert exploded["physical_plausibility_success"] is False
        assert matrix["highest_trust_stage"]["stage"] != "soft_guidance_3_roller_boundary_load_0p1n_singlepoint"
        assert matrix["preload_calibration"]["point_count"] == 1

        report = demo.write_stage_evidence_matrix_report(
            search_root=tmp_path / "runtime_smoke",
            output_dir=tmp_path / "reports",
        )
        assert Path(report["json_path"]).exists()
        assert Path(report["markdown_path"]).exists()
        markdown = Path(report["markdown_path"]).read_text(encoding="utf-8")
        assert "all_12_roller_boundary_load_50n" in markdown
        assert "Saved-MPH Reaction Probe Reports" in markdown
        assert "Source unevaluable / destination nonzero" in markdown
        assert "unknown_operator" not in markdown
        assert "reaction_probe_summary.json" in markdown

    def test_saved_mph_reaction_probe_requires_boundary_load_balance_for_verified_count(self, tmp_path):
        from scripts import run_agent_3d_bearing_full_demo as demo

        root = tmp_path / "runtime_smoke"

        def write_case(name: str, reaction_force_abs_n: float) -> None:
            run_dir = root / name
            run_dir.mkdir(parents=True)
            (run_dir / "direct_3d_bearing_summary.json").write_text(json.dumps({
                "model_name": name,
                "staged_contact_solve": {
                    "success": True,
                    "stages": [
                        {
                            "name": "single_solve_3_roller_boundary_load_0p101n_parametric",
                            "solve": {"success": True},
                            "native_volume_plot": {"success": True, "png_quality": {"success": True}},
                            "stress": {"success": True, "statistics": {"max": 1.0e5}},
                            "displacement": {"success": True, "statistics": {"max": 1.0e-6}},
                            "inner_bore_load_active": True,
                            "inner_body_load_active": False,
                            "radial_load_value": "0.101[N]",
                            "active_rollers": [12, 1, 2],
                            "cage_contact_active": False,
                            "weak_inner_guidance_active": True,
                            "temporary_active_roller_stabilization_active": True,
                            "active_roller_stabilization_mode": "spring",
                            "load_application_fidelity": "inner_bore_boundary_load_diagnostic_not_design_gate",
                        }
                    ],
                },
            }), encoding="utf-8")
            probe_dir = run_dir / "reaction_probe_solved_mph"
            probe_dir.mkdir()
            (probe_dir / "reaction_probe_summary.json").write_text(json.dumps({
                "success": True,
                "kind": "bearing_3d_saved_mph_reaction_probe",
                "mph_path": str(run_dir / "result.mph"),
                "selection_name": "sel_inner_bore_load_surface",
                "reaction_verified": True,
                "reaction_equivalent": {
                    "success": True,
                    "candidate_count": 40,
                    "evaluated_candidate_success_count": 9,
                    "successful_candidate_count": 3,
                    "best_expression": "solid.sx*nx+solid.sxy*ny+solid.sxz*nz",
                    "best_method": "java_intsurface",
                    "best_reaction_force_abs_n": reaction_force_abs_n,
                    "candidate_audit": {
                        "diagnostic_class_counts": {"nonzero_success": 3},
                        "nonzero_success_count": 3,
                    },
                },
            }), encoding="utf-8")

        write_case("mismatched_boundaryload_reaction", 594.5611858)
        write_case("balanced_boundaryload_reaction", 0.102)

        matrix = demo.build_stage_evidence_matrix(search_root=root)

        reports = {Path(report["path"]).parts[-3]: report for report in matrix["saved_reaction_probe_reports"]}
        mismatched = reports["mismatched_boundaryload_reaction"]
        balanced = reports["balanced_boundaryload_reaction"]
        assert mismatched["reaction_candidate_nonzero"] is True
        assert mismatched["reaction_verified"] is False
        assert mismatched["reaction_load_balance"]["success"] is False
        assert mismatched["reaction_load_balance"]["reaction_to_load_ratio"] > 5000
        assert balanced["reaction_candidate_nonzero"] is True
        assert balanced["reaction_verified"] is True
        assert balanced["reaction_load_balance"]["success"] is True
        assert matrix["saved_reaction_probe_report_count"] == 2
        assert matrix["saved_reaction_probe_verified_count"] == 1

    def test_stage_evidence_matrix_indexes_saved_boundary_load_probe_reports(self, tmp_path):
        from scripts import run_agent_3d_bearing_full_demo as demo

        root = tmp_path / "runtime_smoke"
        probe_dir = root / "bearing_boundaryload_audit" / "load_probe_solved_mph"
        probe_dir.mkdir(parents=True)
        (probe_dir / "load_probe_summary.json").write_text(json.dumps({
            "success": True,
            "kind": "bearing_3d_saved_mph_boundary_load_probe",
            "mph_path": str(root / "bearing_boundaryload_audit" / "result_packages" / "result.mph"),
            "selection_name": "sel_inner_bore_load_surface",
            "pressure_expression": "inner_bore_load_pressure",
            "area_m2": 2.0e-4,
            "pressure_pa": -505.0,
            "integrated_load_n": -0.101,
            "boundary_load_context": {
                "success": True,
                "radial_load_value": "0.101[N]",
                "applied_load_n": 0.101,
            },
            "load_balance": {
                "success": True,
                "integrated_load_n": -0.101,
                "applied_load_n": 0.101,
                "absolute_residual_n": 0.0,
                "relative_residual_to_load": 0.0,
                "integrated_to_load_ratio": 1.0,
            },
            "feature_audit": {
                "success": True,
                "properties": {"FperArea": {"success": True, "value": ["inner_bore_load_pressure", "0", "0"]}},
            },
        }), encoding="utf-8")

        matrix = demo.build_stage_evidence_matrix(search_root=root)

        assert matrix["saved_boundary_load_probe_report_count"] == 1
        assert matrix["saved_boundary_load_probe_balanced_count"] == 1
        report = matrix["saved_boundary_load_probe_reports"][0]
        assert report["balanced"] is True
        assert report["integrated_load_n"] == -0.101
        assert report["load_balance"]["integrated_to_load_ratio"] == 1.0

        rendered = demo._render_stage_evidence_matrix_markdown(matrix)
        assert "Saved-MPH BoundaryLoad Probe Reports" in rendered
        assert "inner_bore_load_pressure" in rendered
        assert "0.101" in rendered

    def test_stage_evidence_matrix_does_not_balance_configured_boundaryload_probe(self, tmp_path):
        from scripts import run_agent_3d_bearing_full_demo as demo

        root = tmp_path / "runtime_smoke"
        probe_dir = root / "bearing_boundaryload_configured" / "load_probe_configured_mph"
        probe_dir.mkdir(parents=True)
        (probe_dir / "load_probe_summary.json").write_text(json.dumps({
            "success": True,
            "kind": "bearing_3d_saved_mph_boundary_load_probe",
            "mph_path": str(
                root
                / "bearing_boundaryload_configured"
                / "stage_models"
                / "single_solve_3_roller_boundary_load_0p101n_actual_area_configured.mph"
            ),
            "selection_name": "sel_inner_bore_load_surface",
            "pressure_expression": "inner_bore_load_pressure",
            "area_m2": 4.863178789249815e-3,
            "integrated_load_n": 0.101,
            "load_balance": {
                "success": True,
                "integrated_load_n": 0.101,
                "applied_load_n": 0.101,
                "integrated_to_load_ratio": 1.0,
            },
        }), encoding="utf-8")

        matrix = demo.build_stage_evidence_matrix(search_root=root)

        assert matrix["saved_boundary_load_probe_report_count"] == 1
        assert matrix["saved_boundary_load_probe_balanced_count"] == 0
        report = matrix["saved_boundary_load_probe_reports"][0]
        assert report["balanced"] is False
        assert report["mph_solution_context"]["kind"] == "configured_checkpoint"

    def test_configured_boundaryload_actual_area_estimate_balances_static_input(self):
        from scripts import run_agent_3d_bearing_full_demo as demo

        estimate = demo._configured_boundary_load_estimate(
            pressure_expression="inner_bore_load_pressure",
            pressure_parameter={
                "success": True,
                "value": "radial_load/(4.863178789249815e-3[m^2])",
            },
            area_m2=4.863178789249815e-3,
            applied_load_n=0.101,
        )

        assert estimate["success"] is True
        assert estimate["role"] == "configured_parameter_expression_estimate_not_solution_field"
        assert estimate["configured_pressure_pa"] == pytest.approx(20.76830903755033)
        assert estimate["configured_integrated_load_n"] == pytest.approx(0.101)
        assert estimate["configured_load_balance"]["success"] is True

    def test_boundary_load_probe_uses_last_saved_mph_parametric_value(self):
        from scripts import run_agent_3d_bearing_full_demo as demo

        output = "REACTION_SURFACE_VALUES|tag=load|values=[1e-05, 0.001, 0.101]\n"

        assert demo._parse_java_numeric_list_probe(
            output,
            marker="REACTION_SURFACE_VALUES|tag=load|values=",
        ) == [1e-05, 0.001, 0.101]

        source = Path("scripts/run_agent_3d_bearing_full_demo.py").read_text(encoding="utf-8")
        assert "globals()['_flatten_numeric_values'] = _flatten_numeric_values" in source
        boundary_load_section = source.split("def probe_saved_boundary_load_mph(", 1)[1].split(
            "def _audit_boundary_load_feature_via_java",
            1,
        )[0]
        assert "solution_selection_policy" in boundary_load_section
        assert 'result_index="last"' in boundary_load_section

    def test_stage_evidence_matrix_flags_boundaryload_stress_plateau(self, tmp_path):
        from scripts import run_agent_3d_bearing_full_demo as demo

        run_dir = tmp_path / "runtime_smoke" / "bearing_plateau"
        run_dir.mkdir(parents=True)

        def stage(load: str, displacement: float) -> dict:
            return {
                "name": f"single_solve_3_roller_boundary_load_{load.replace('.', 'p')}n_parametric",
                "solve": {"success": True},
                "native_volume_plot": {
                    "success": True,
                    "filepath": str(run_dir / "stage_plots" / f"{load}.png"),
                    "png_quality": {"success": True},
                },
                "stress": {"success": True, "statistics": {"max": 6.526523284e6}},
                "inner_ring_stress": {"success": True, "value": 1.100733554e7},
                "displacement": {"success": True, "statistics": {"max": displacement}},
                "contact_pressure": {"success": True, "value": 100.0},
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "radial_load_value": f"{load}[N]",
                "active_rollers": [12, 1, 2],
                "cage_contact_active": False,
                "weak_inner_guidance_active": True,
                "temporary_active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "displacement_preload_active": False,
                "load_application_fidelity": (
                    f"inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_{load}n_diagnostic_not_design_gate"
                ),
            }

        summary = {
            "model_name": "bearing_plateau",
            "contact_stage_mode": "load_side_group_boundary_load_single_solve_plateau_test",
            "requested_stage_image": {"production_ready": False},
            "physical_contact_validation": {"quality_level": "raceway_contact_physics_smoke"},
            "staged_contact_solve": {
                "stages": [
                    stage("0.1", 2.0e-3),
                    stage("0.13", 3.1e-3),
                    stage("0.17", 5.2e-3),
                    stage("0.2", 6.5e-3),
                ]
            },
        }
        (run_dir / "direct_3d_bearing_summary.json").write_text(json.dumps(summary), encoding="utf-8")

        matrix = demo.build_stage_evidence_matrix(search_root=tmp_path / "runtime_smoke")

        assert matrix["converged_native_stage_count"] == 4
        assert matrix["highest_trust_stage"] is None
        for row in matrix["rows"]:
            assert row["physical_plausibility_success"] is False
            assert row["boundaryload_sequence_stress_plateau"] is True
            assert any("stress plateau" in error for error in row["physical_plausibility_errors"])

    def test_boundaryload_active_roller_distribution_gate_rejects_zero_active_roller(self, tmp_path):
        from scripts import run_agent_3d_bearing_full_demo as demo

        run_dir = tmp_path / "runtime_smoke" / "bearing_probe_distribution"
        run_dir.mkdir(parents=True)
        stage = {
            "name": "single_solve_3_roller_boundary_load_0p101n_probe_gate",
            "solve": {"success": True},
            "native_volume_plot": {
                "success": True,
                "filepath": str(run_dir / "stage_plots" / "probe_gate.png"),
                "png_quality": {"success": True},
            },
            "stress": {"success": True, "statistics": {"max": 6.526523284e6}},
            "inner_ring_stress": {"success": True, "value": 1.100733554e7},
            "displacement": {"success": True, "statistics": {"max": 2.214e-3}},
            "contact_pressure": {"success": True, "value": 65.7},
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "radial_load_value": "0.101[N]",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "weak_inner_guidance_active": True,
            "temporary_active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "displacement_preload_active": False,
            "pre_solve_model_save": {
                "success": True,
                "filepath": str(run_dir / "stage_models" / "single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph"),
            },
            "per_roller_probe_results": [
                {"roller": "roller_1", "success": True, "value": 0.0},
                {"roller": "roller_2", "success": True, "value": 6.5e6},
                {"roller": "roller_12", "success": True, "value": 6.4e6},
                *[
                    {"roller": f"roller_{index}", "success": True, "value": 0.0}
                    for index in range(3, 12)
                ],
            ],
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p101n_diagnostic_not_design_gate"
            ),
        }
        summary = {
            "model_name": "bearing_probe_distribution",
            "contact_stage_mode": "load_side_group_boundary_load_single_solve_0p101",
            "requested_stage_image": {"production_ready": False},
            "physical_contact_validation": {"quality_level": "raceway_contact_physics_smoke"},
            "staged_contact_solve": {"stages": [stage]},
        }
        (run_dir / "direct_3d_bearing_summary.json").write_text(json.dumps(summary), encoding="utf-8")
        diagnostic_dir = run_dir / "diagnostics_0p101n_probe_gate_single_solve"
        diagnostic_dir.mkdir()
        def contact_feature(tag: str, pair: str) -> dict:
            return {
                "tag": tag,
                "exists": True,
                "active": True,
                "type": "Contact",
                "properties": {
                    "pairs": {"success": True, "value": [pair]},
                    "pn_penalty": {"success": True, "value": ["5e-5*E_steel"]},
                    "useRelaxation": {"success": True, "value": ["Always"]},
                    "irlx": {"success": True, "value": ["0.12"]},
                    "tolcontact": {"success": True, "value": ["3[um]"]},
                    "zeroInitGap": {"success": True, "value": ["0"]},
                },
            }
        (diagnostic_dir / "stage_mph_diagnostic.json").write_text(json.dumps({
            "success": True,
            "mph_path": str(run_dir / "stage_models" / "single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph"),
            "audit": {
                "payload": {
                    "solid_feature_audit": [
                        {
                            "tag": "load_inner_bore",
                            "active": True,
                            "properties": {"FperArea": {"success": True, "value": ["inner_bore_load_pressure", "0", "0"]}},
                        },
                        contact_feature("contact_roller_1_inner", "cp_roller_1_inner_raceway"),
                        contact_feature("contact_roller_1_outer", "cp_roller_1_outer_raceway"),
                        {"tag": "contact_roller_1_cage", "active": False},
                        {"tag": "weak_roller_1_foundation", "active": True},
                        {"tag": "fix_roller_1_stage_stabilization", "active": False},
                        contact_feature("contact_roller_2_inner", "cp_roller_2_inner_raceway"),
                        contact_feature("contact_roller_2_outer", "cp_roller_2_outer_raceway"),
                        contact_feature("contact_roller_12_inner", "cp_roller_12_inner_raceway"),
                        contact_feature("contact_roller_12_outer", "cp_roller_12_outer_raceway"),
                    ],
                    "selection_audit": [
                        {
                            "tag": "sel_roller_1_body",
                            "exists": True,
                            "type": "Box",
                            "entity_count": 5,
                            "properties": {
                                "xmin": {"success": True, "value": "23[mm]"},
                                "xmax": {"success": True, "value": "31[mm]"},
                                "ymin": {"success": True, "value": "-4[mm]"},
                                "ymax": {"success": True, "value": "4[mm]"},
                                "zmin": {"success": True, "value": "-8[mm]"},
                                "zmax": {"success": True, "value": "8[mm]"},
                            },
                        },
                        {
                            "tag": "box_roller_1_inner_contact_patch",
                            "exists": True,
                            "type": "Box",
                            "entity_count": 14,
                            "properties": {
                                "xmin": {"success": True, "value": "21.8[mm]"},
                                "xmax": {"success": True, "value": "24.2[mm]"},
                                "ymin": {"success": True, "value": "-4.6[mm]"},
                                "ymax": {"success": True, "value": "4.6[mm]"},
                                "zmin": {"success": True, "value": "-8[mm]"},
                                "zmax": {"success": True, "value": "8[mm]"},
                            },
                        },
                        {
                            "tag": "box_roller_1_outer_contact_patch",
                            "exists": True,
                            "type": "Box",
                            "entity_count": 6,
                            "properties": {
                                "xmin": {"success": True, "value": "29.8[mm]"},
                                "xmax": {"success": True, "value": "32.2[mm]"},
                                "ymin": {"success": True, "value": "-4.6[mm]"},
                                "ymax": {"success": True, "value": "4.6[mm]"},
                                "zmin": {"success": True, "value": "-8[mm]"},
                                "zmax": {"success": True, "value": "8[mm]"},
                            },
                        },
                    ],
                    "contact_pair_audit": [
                        {
                            "tag": "cp_roller_1_inner_raceway",
                            "exists": True,
                            "source": {"named": {"success": True, "value": "sel_roller_1_inner_contact"}, "entity_count": 2},
                            "destination": {"named": {"success": True, "value": "sel_inner_raceway_1_contact"}, "entity_count": 2},
                        },
                        {
                            "tag": "cp_roller_1_outer_raceway",
                            "exists": True,
                            "source": {"named": {"success": True, "value": "sel_roller_1_outer_contact"}, "entity_count": 2},
                            "destination": {"named": {"success": True, "value": "sel_outer_raceway_1_contact"}, "entity_count": 1},
                        },
                    ],
                },
            },
        }), encoding="utf-8")
        contact_probe_dir = run_dir / "contact_probe_solved_mph"
        contact_probe_dir.mkdir()
        (contact_probe_dir / "contact_probe_summary.json").write_text(json.dumps({
            "success": True,
            "kind": "bearing_3d_saved_mph_contact_probe",
            "mph_path": str(run_dir / "result_packages" / "bearing_probe_distribution.mph"),
            "contact_probe": {
                "candidate_count": 60,
                "success_count": 60,
                "nonzero_count": 50,
                "contact_status_by_roller": {
                    "roller_1": {
                        "pair_specific_success_count": 2,
                        "pair_specific_nonzero_count": 0,
                        "pair_specific_nonzero_ratio": 0.0,
                    },
                    "roller_2": {
                        "pair_specific_success_count": 2,
                        "pair_specific_nonzero_count": 2,
                        "pair_specific_nonzero_ratio": 1.0,
                    },
                },
                "normal_orientation_by_roller": {
                    "roller_1": {
                        "source_destination_radial_normal_alignment": {
                            "inner": {
                                "source_radial_avg": 1.0,
                                "destination_radial_avg": -1.0,
                                "opposite_radial_sign": True,
                            },
                        },
                    },
                },
                "pair_transfer_by_roller": {
                    "roller_1": {
                        "destination_abs_tn_nonzero_count": 0,
                        "source_destination_transfer": {
                            "inner": {
                                "source_abs_Tn_integral": None,
                                "destination_abs_Tn_integral": 0.0,
                                "source_zero_destination_nonzero": False,
                                "source_unevaluable_destination_nonzero": False,
                            },
                            "outer": {
                                "source_abs_Tn_integral": None,
                                "destination_abs_Tn_integral": 12.5,
                                "source_zero_destination_nonzero": False,
                                "source_unevaluable_destination_nonzero": True,
                            },
                        },
                    },
                    "roller_2": {
                        "destination_abs_tn_nonzero_count": 2,
                    },
                },
                "by_roller": {
                    "roller_1": {
                        "source_destination_imbalance": {
                            "inner": {
                                "source_nonzero": False,
                                "destination_nonzero": True,
                                "source_zero_destination_nonzero": True,
                            },
                            "outer": {
                                "source_nonzero": False,
                                "destination_nonzero": True,
                                "source_zero_destination_nonzero": True,
                            },
                        },
                    },
                    "roller_2": {
                        "source_destination_imbalance": {
                            "inner": {
                                "source_nonzero": True,
                                "destination_nonzero": True,
                                "source_zero_destination_nonzero": False,
                            },
                        },
                    },
                },
            },
            "pair_enforcement_diagnostic": {
                "success": True,
                "zero_pair_specific_contact_pressure_rollers": ["roller_1"],
                "source_destination_imbalance_rollers": ["roller_1"],
                "nonzero_reference_rollers": ["roller_2"],
                "roller_states": {
                    "roller_1": {
                        "contact_feature_settings_match_nonzero_references": True,
                        "inner_pair": {
                            "source_named": "sel_roller_1_inner_contact",
                            "destination_named": "sel_inner_raceway_1_contact",
                        },
                    },
                },
                "recommendations": [
                    "Zero-carry rollers have solved-MPH source/destination imbalance and zero pair-specific normal pressure while their contact feature settings match nonzero neighboring rollers; prioritize contact normal/gap orientation or pair enforcement transfer over static feature-setting differences."
                ],
            },
        }), encoding="utf-8")

        matrix = demo.build_stage_evidence_matrix(search_root=tmp_path / "runtime_smoke")

        row = matrix["rows"][0]
        assert row["physical_plausibility_success"] is False
        assert row["active_roller_probe_success_count"] == 3
        assert row["active_roller_nonzero_probe_count"] == 2
        assert row["active_roller_nonzero_probe_ratio"] == pytest.approx(2 / 3)
        assert row["active_roller_zero_stress_rollers"] == ["roller_1"]
        assert row["active_roller_load_distribution_success"] is False
        distribution = matrix["boundaryload_distribution_diagnostics"]
        assert distribution["success"] is False
        assert distribution["zero_carry_row_count"] == 1
        assert distribution["zero_carry_rollers"] == {"roller_1": 1}
        assert distribution["focus_rows"][0]["stage"] == "single_solve_3_roller_boundary_load_0p101n_probe_gate"
        assert distribution["stage_mph_diagnostic_report_count"] == 1
        assert distribution["saved_contact_probe_report_count"] == 1
        assert matrix["saved_contact_probe_source_unevaluable_destination_nonzero_count"] == 1
        configured = distribution["focus_rows"][0]["configured_mph_diagnostic"]
        contact_probe = distribution["focus_rows"][0]["saved_contact_probe_diagnostic"]
        assert contact_probe["zero_carry_source_destination_imbalance"] == ["roller_1"]
        assert contact_probe["source_unevaluable_destination_nonzero_rollers"] == ["roller_1"]
        assert contact_probe["zero_carry_source_unevaluable_destination_nonzero"] == ["roller_1"]
        assert contact_probe["zero_carry_pair_specific_contact_pressure_zero"] == ["roller_1"]
        assert contact_probe["zero_carry_normal_orientation"]["roller_1"]["source_destination_radial_normal_alignment"]["inner"]["opposite_radial_sign"] is True
        assert contact_probe["zero_carry_pair_transfer"]["roller_1"]["destination_abs_tn_nonzero_count"] == 0
        pair_enforcement = contact_probe["pair_enforcement_diagnostic"]
        assert pair_enforcement["zero_pair_specific_contact_pressure_rollers"] == ["roller_1"]
        assert pair_enforcement["zero_carry_roller_states"]["roller_1"]["contact_feature_settings_match_nonzero_references"] is True
        assert contact_probe["nonzero_count"] == 50
        roller_state = configured["zero_carry_roller_feature_state"]["roller_1"]
        assert roller_state["body_selection_entity_count"] == 5
        assert roller_state["inner_contact_active"] is True
        assert roller_state["outer_contact_active"] is True
        assert roller_state["cage_contact_active"] is False
        assert roller_state["weak_foundation_active"] is True
        assert roller_state["fixed_stabilization_active"] is False
        assert roller_state["inner_pair"] == {
            "exists": True,
            "source_named": "sel_roller_1_inner_contact",
            "source_entity_count": 2,
            "destination_named": "sel_inner_raceway_1_contact",
            "destination_entity_count": 2,
        }
        assert roller_state["outer_pair"] == {
            "exists": True,
            "source_named": "sel_roller_1_outer_contact",
            "source_entity_count": 2,
            "destination_named": "sel_outer_raceway_1_contact",
            "destination_entity_count": 1,
        }
        assert roller_state["cage_pair"] is None
        assert roller_state["selection_geometry"]["roller_body"]["success"] is True
        assert roller_state["selection_geometry"]["roller_body"]["center_mm"]["x"] == pytest.approx(27.0)
        assert roller_state["load_angle_alignment"]["success"] is True
        assert roller_state["load_angle_alignment"]["angle_offset_deg"] == pytest.approx(0.0)
        assert roller_state["contact_patch_geometry"]["success"] is True
        assert roller_state["contact_patch_geometry"]["inner_patch_radial_offset_mm"] == pytest.approx(-4.0)
        assert roller_state["contact_patch_geometry"]["outer_patch_radial_offset_mm"] == pytest.approx(4.0)
        assert roller_state["contact_feature_settings_match_active_nonzero"] is True
        assert roller_state["contact_feature_settings"]["inner"]["properties"]["pn_penalty"] == "5e-5*E_steel"
        assert any("zero roller-side source response" in recommendation for recommendation in distribution["recommendations"])
        assert any("load-side roller distribution is incomplete" in error for error in row["physical_plausibility_errors"])
        assert matrix["highest_trust_stage"] is None

        selected = demo._select_requested_stage_image_from_staged_solve({"stages": [stage]})
        assert selected["success"] is False
        assert selected["image_role"] == "no_physically_plausible_converged_native_comsol_stage_available"
        assert any("load-side roller distribution is incomplete" in error for error in selected["best_available_rejected_reasons"])

    def test_stage_mph_diagnostic_writes_no_solve_artifacts(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from scripts import run_agent_3d_bearing_full_demo as demo

        mph_path = tmp_path / "stage_models" / "load_side_3_roller_boundary_load_0p2n_configured.mph"
        mph_path.parent.mkdir(parents=True)
        mph_path.write_text("fake mph placeholder", encoding="utf-8")

        class FakeClient:
            def __init__(self):
                self.is_running = False
                self.started = False
                self.stopped = False

            def start(self, **kwargs):
                self.started = True
                self.is_running = True

            def stop(self):
                self.stopped = True
                self.is_running = False

        fake_client = FakeClient()

        payload = {
            "study_tags": {"success": True, "value": ["std1"]},
            "solver_tags": {"success": True, "value": ["sol1"]},
            "solid_feature_tags": ["load_inner_bore", "weak_inner_ring_load_guidance"],
            "solid_feature_audit": [
                {
                    "tag": "load_inner_bore",
                    "exists": True,
                    "type": "BoundaryLoad",
                    "active": True,
                    "selection_named": {"success": True, "value": "sel_inner_bore_load_surface"},
                    "properties": {"FperArea": {"success": True, "value": ["-inner_bore_load_pressure", "0", "0"]}},
                }
            ],
            "selection_audit": [
                {
                    "tag": "sel_inner_bore_load_surface",
                    "exists": True,
                    "entity_count": 4,
                    "entities": {"success": True, "value": [1, 2, 3, 4]},
                }
            ],
            "coupling_audit": [
                {
                    "tag": "intop_displacement_reaction_probe",
                    "exists": False,
                    "error": "not found",
                }
            ],
            "study_audit": [{"tag": "std1", "features": []}],
            "solver_audit": [{"tag": "sol1", "features": []}],
        }

        def fake_execute_java(code: str, *, model_name: str):
            assert model_name == "loaded_stage_model"
            assert ".solve(" not in code
            return {
                "success": True,
                "model_name": model_name,
                "stdout": (
                    f"{demo.STAGE_MPH_DIAGNOSTIC_JSON_START}\n"
                    f"{json.dumps(payload)}\n"
                    f"{demo.STAGE_MPH_DIAGNOSTIC_JSON_END}\n"
                ),
            }

        monkeypatch.setattr(
            demo,
            "load_config",
            lambda: SimpleNamespace(comsol=SimpleNamespace(version=None, executable_path=None)),
        )
        monkeypatch.setattr(demo.COMSOLClient, "get_instance", staticmethod(lambda: fake_client))
        monkeypatch.setattr(demo.COMSOLClient, "reset_instance", staticmethod(lambda: None))
        monkeypatch.setattr(demo, "comsol_load_model", lambda filepath: {"success": True, "model_name": "loaded_stage_model", "filepath": filepath})
        monkeypatch.setattr(demo, "comsol_get_model_summary", lambda model_name: {"success": True, "model_name": model_name, "summary": {"studies": 1}})
        monkeypatch.setattr(demo, "comsol_execute_java", fake_execute_java)
        monkeypatch.setattr(demo, "comsol_close_model", lambda model_name, save=False: {"success": True, "model_name": model_name})

        report = demo.diagnose_stage_mph(
            mph_path=mph_path,
            output_dir=tmp_path / "diagnostics",
            cores=1,
        )

        assert report["success"] is True
        assert fake_client.started is True
        assert fake_client.stopped is True
        assert Path(report["json_path"]).exists()
        assert Path(report["markdown_path"]).exists()
        markdown = Path(report["markdown_path"]).read_text(encoding="utf-8")
        assert "load_inner_bore" in markdown
        assert "sel_inner_bore_load_surface" in markdown

    def test_actual_area_resume_from_solved_nominal_writes_failed_summary(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from scripts import run_agent_3d_bearing_full_demo as demo

        source_mph = tmp_path / "nominal_solved.mph"
        source_mph.write_text("fake nominal solved mph", encoding="utf-8")
        output_dir = tmp_path / "actual_area_resume"

        class FakeClient:
            def __init__(self):
                self.is_running = False
                self.started = False
                self.stopped = False

            def start(self, **kwargs):
                self.started = True
                self.is_running = True

            def stop(self):
                self.stopped = True
                self.is_running = False

        fake_client = FakeClient()
        configured: dict[str, object] = {}
        saved_paths: list[str] = []
        closed: list[str] = []

        def fake_set_state(model_name: str, **kwargs):
            configured["model_name"] = model_name
            configured.update(kwargs)
            return {"success": True, "model_name": model_name, "stdout": "configured actual area"}

        def fake_save_stage(model_name: str, *, stage_name: str, output_dir: Path | None):
            path = Path(output_dir) / f"{stage_name}_configured.mph"
            path.write_text("configured mph", encoding="utf-8")
            return {
                "success": True,
                "model_name": model_name,
                "stage": stage_name,
                "filepath": str(path),
                "saved_to": str(path),
            }

        def fake_save_model(model_name: str, filepath: str | None = None):
            assert filepath is not None
            saved_paths.append(filepath)
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            Path(filepath).write_text("failed mph", encoding="utf-8")
            return {"success": True, "model_name": model_name, "saved_to": filepath}

        monkeypatch.setattr(
            demo,
            "load_config",
            lambda: SimpleNamespace(comsol=SimpleNamespace(version=None, executable_path=None)),
        )
        monkeypatch.setattr(demo.COMSOLClient, "get_instance", staticmethod(lambda: fake_client))
        monkeypatch.setattr(demo.COMSOLClient, "reset_instance", staticmethod(lambda: None))
        monkeypatch.setattr(
            demo,
            "comsol_load_model",
            lambda filepath: {"success": True, "model_name": "loaded_nominal_model", "filepath": filepath},
        )
        monkeypatch.setattr(demo, "_set_3d_staged_contact_state", fake_set_state)
        monkeypatch.setattr(demo, "_save_stage_configured_mph", fake_save_stage)
        monkeypatch.setattr(demo, "comsol_solve", lambda model_name: {"success": False, "error": "Solve failed: timed out"})
        monkeypatch.setattr(demo, "comsol_save_model", fake_save_model)
        monkeypatch.setattr(
            demo,
            "comsol_close_model",
            lambda model_name, save=False: closed.append(model_name) or {"success": True, "model_name": model_name},
        )

        summary = demo.run_actual_area_resume_from_solved_nominal_mph(
            source_mph=source_mph,
            output_dir=output_dir,
            cores=1,
        )

        assert fake_client.started is True
        assert fake_client.stopped is True
        assert closed == ["loaded_nominal_model"]
        assert configured["model_name"] == "loaded_nominal_model"
        assert configured["active_rollers"] == [12, 1, 2]
        assert configured["radial_load_value"] == "0.101[N]"
        assert configured["inner_bore_load_pressure_expression"] == "radial_load/(4.863178789249815e-3[m^2])"
        assert configured["reuse_existing_solver"] is True
        assert configured["use_parametric_sweep"] is False
        assert configured["active_roller_stabilization_mode"] == "spring"
        assert configured["weak_inner_guidance_active"] is True
        assert summary["solve"]["success"] is False
        stage = summary["staged_contact_solve"]["stages"][0]
        assert stage["pre_solve_model_save"]["success"] is True
        assert stage["solve"]["error"] == "Solve failed: timed out"
        assert stage["temporary_active_roller_stabilization_active"] is True
        assert stage["temporary_cage_stabilization_active"] is True
        assert stage["weak_roller_foundation_active"] is True
        assert stage["load_application_fidelity"].endswith("diagnostic_not_design_gate")
        assert summary["physical_contact_validation"]["success"] is False
        assert summary["staged_contact_solve"]["final_solve"]["error"] == "Solve failed: timed out"
        assert any(
            "COMSOL solve did not converge" in error
            for error in summary["physical_contact_validation"]["errors"]
        )
        assert saved_paths and saved_paths[0].endswith("failed_3d_contact_model.mph")
        summary_path = output_dir / "direct_3d_bearing_summary.json"
        assert summary_path.exists()
        written = json.loads(summary_path.read_text(encoding="utf-8"))
        assert written["staged_contact_solve"]["contact_stage_mode"] == (
            "load_side_group_boundary_load_single_solve_0p101_actual_area_resume_from_solved_nominal"
        )

    def test_actual_area_resume_from_solved_nominal_can_rebuild_solver_sequence(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from scripts import run_agent_3d_bearing_full_demo as demo

        source_mph = tmp_path / "nominal_solved.mph"
        source_mph.write_text("fake nominal solved mph", encoding="utf-8")
        output_dir = tmp_path / "actual_area_resume_fresh_solver"

        class FakeClient:
            def __init__(self):
                self.is_running = False
                self.started = False
                self.stopped = False

            def start(self, **kwargs):
                self.started = True
                self.is_running = True

            def stop(self):
                self.stopped = True
                self.is_running = False

        fake_client = FakeClient()
        configured: dict[str, object] = {}
        rebuild_calls: list[str] = []

        def fake_set_state(model_name: str, **kwargs):
            configured["model_name"] = model_name
            configured.update(kwargs)
            return {"success": True, "model_name": model_name, "stdout": "configured actual area fresh solver"}

        def fake_save_stage(model_name: str, *, stage_name: str, output_dir: Path | None):
            path = Path(output_dir) / f"{stage_name}_configured.mph"
            path.write_text("configured mph", encoding="utf-8")
            return {"success": True, "model_name": model_name, "stage": stage_name, "saved_to": str(path)}

        monkeypatch.setattr(
            demo,
            "load_config",
            lambda: SimpleNamespace(comsol=SimpleNamespace(version=None, executable_path=None)),
        )
        monkeypatch.setattr(demo.COMSOLClient, "get_instance", staticmethod(lambda: fake_client))
        monkeypatch.setattr(demo.COMSOLClient, "reset_instance", staticmethod(lambda: None))
        monkeypatch.setattr(
            demo,
            "comsol_load_model",
            lambda filepath: {"success": True, "model_name": "loaded_nominal_model", "filepath": filepath},
        )
        monkeypatch.setattr(
            demo,
            "_remove_model_solver_sequences_via_java",
            lambda model_name: rebuild_calls.append(model_name) or {
                "success": True,
                "removed_solver_tags": ["sol1"],
                "solver_tags_before": ["sol1"],
                "solver_tags_after": [],
            },
        )
        monkeypatch.setattr(demo, "_set_3d_staged_contact_state", fake_set_state)
        monkeypatch.setattr(demo, "_save_stage_configured_mph", fake_save_stage)
        monkeypatch.setattr(demo, "comsol_solve", lambda model_name: {"success": False, "error": "Solve failed: timed out"})
        monkeypatch.setattr(demo, "comsol_save_model", lambda model_name, filepath=None: {"success": True, "saved_to": filepath})
        monkeypatch.setattr(demo, "comsol_close_model", lambda model_name, save=False: {"success": True, "model_name": model_name})

        summary = demo.run_actual_area_resume_from_solved_nominal_mph(
            source_mph=source_mph,
            output_dir=output_dir,
            cores=1,
            rebuild_solver_sequence=True,
        )

        assert fake_client.started is True
        assert fake_client.stopped is True
        assert rebuild_calls == ["loaded_nominal_model"]
        assert configured["reuse_existing_solver"] is False
        assert configured["use_parametric_sweep"] is False
        assert configured["radial_load_value"] == "0.101[N]"
        assert configured["inner_bore_load_pressure_expression"] == "radial_load/(4.863178789249815e-3[m^2])"
        stage = summary["staged_contact_solve"]["stages"][0]
        assert stage["name"].endswith("_fresh_solver")
        assert stage["solver_sequence_rebuild"]["success"] is True
        assert stage["solver_formulation_diagnostic_role"] == (
            "actual_area_pressure_resume_from_solved_nominal_fresh_solver_sequence_only"
        )
        assert summary["staged_contact_solve"]["policy"] == (
            "load_solved_nominal_mph_then_rebuild_solver_sequence_and_configure_actual_area_pressure_checkpoint"
        )
        assert summary["staged_contact_solve"]["contact_stage_mode"].endswith("_fresh_solver")
        assert summary["solve"]["success"] is False

    def test_actual_area_resume_from_solved_nominal_can_use_controlled_load_ramp(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from scripts import run_agent_3d_bearing_full_demo as demo

        source_mph = tmp_path / "nominal_solved.mph"
        source_mph.write_text("fake nominal solved mph", encoding="utf-8")
        output_dir = tmp_path / "actual_area_resume_load_ramp"
        ramp_steps = "0.001 0.005 0.01 0.02 0.05 0.08 0.1 0.1005 0.101"

        class FakeClient:
            def __init__(self):
                self.is_running = False
                self.started = False
                self.stopped = False

            def start(self, **kwargs):
                self.started = True
                self.is_running = True

            def stop(self):
                self.stopped = True
                self.is_running = False

        fake_client = FakeClient()
        configured: dict[str, object] = {}

        def fake_set_state(model_name: str, **kwargs):
            configured["model_name"] = model_name
            configured.update(kwargs)
            return {"success": True, "model_name": model_name, "stdout": "configured actual area load ramp"}

        def fake_save_stage(model_name: str, *, stage_name: str, output_dir: Path | None):
            path = Path(output_dir) / f"{stage_name}_configured.mph"
            path.write_text("configured mph", encoding="utf-8")
            return {"success": True, "model_name": model_name, "stage": stage_name, "saved_to": str(path)}

        monkeypatch.setattr(
            demo,
            "load_config",
            lambda: SimpleNamespace(comsol=SimpleNamespace(version=None, executable_path=None)),
        )
        monkeypatch.setattr(demo.COMSOLClient, "get_instance", staticmethod(lambda: fake_client))
        monkeypatch.setattr(demo.COMSOLClient, "reset_instance", staticmethod(lambda: None))
        monkeypatch.setattr(
            demo,
            "comsol_load_model",
            lambda filepath: {"success": True, "model_name": "loaded_nominal_model", "filepath": filepath},
        )
        monkeypatch.setattr(
            demo,
            "_remove_model_solver_sequences_via_java",
            lambda model_name: pytest.fail("load-ramp-only diagnostic must not rebuild solver sequences"),
        )
        monkeypatch.setattr(demo, "_set_3d_staged_contact_state", fake_set_state)
        monkeypatch.setattr(demo, "_save_stage_configured_mph", fake_save_stage)
        monkeypatch.setattr(demo, "comsol_solve", lambda model_name: {"success": False, "error": "Solve failed: timed out"})
        monkeypatch.setattr(demo, "comsol_save_model", lambda model_name, filepath=None: {"success": True, "saved_to": filepath})
        monkeypatch.setattr(demo, "comsol_close_model", lambda model_name, save=False: {"success": True, "model_name": model_name})

        summary = demo.run_actual_area_resume_from_solved_nominal_mph(
            source_mph=source_mph,
            output_dir=output_dir,
            cores=1,
            load_ramp_steps=ramp_steps,
        )

        assert fake_client.started is True
        assert fake_client.stopped is True
        assert configured["reuse_existing_solver"] is True
        assert configured["use_parametric_sweep"] is True
        assert configured["preload_steps"] == ramp_steps
        assert configured["radial_load_value"] == "0.101[N]"
        assert configured["inner_bore_load_pressure_expression"] == "radial_load/(4.863178789249815e-3[m^2])"
        stage = summary["staged_contact_solve"]["stages"][0]
        assert stage["name"].endswith("_load_ramp")
        assert stage["solver_formulation_diagnostic_role"] == (
            "actual_area_pressure_resume_from_solved_nominal_controlled_load_ramp_only"
        )
        assert summary["staged_contact_solve"]["policy"] == (
            "load_solved_nominal_mph_then_configure_actual_area_pressure_checkpoint_with_controlled_actual_area_load_ramp"
        )
        assert summary["staged_contact_solve"]["contact_stage_mode"].endswith("_load_ramp")
        assert summary["solve"]["success"] is False

    def test_actual_area_resume_from_solved_nominal_can_override_contact_zero_init_gap(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from scripts import run_agent_3d_bearing_full_demo as demo

        source_mph = tmp_path / "nominal_solved.mph"
        source_mph.write_text("fake nominal solved mph", encoding="utf-8")
        output_dir = tmp_path / "actual_area_resume_zero_init_gap"

        class FakeClient:
            def __init__(self):
                self.is_running = False
                self.started = False
                self.stopped = False

            def start(self, **kwargs):
                self.started = True
                self.is_running = True

            def stop(self):
                self.stopped = True
                self.is_running = False

        fake_client = FakeClient()
        configured: dict[str, object] = {}

        def fake_set_state(model_name: str, **kwargs):
            configured["model_name"] = model_name
            configured.update(kwargs)
            return {"success": True, "model_name": model_name, "stdout": "configured actual area zeroInitGap"}

        def fake_save_stage(model_name: str, *, stage_name: str, output_dir: Path | None):
            path = Path(output_dir) / f"{stage_name}_configured.mph"
            path.write_text("configured mph", encoding="utf-8")
            return {"success": True, "model_name": model_name, "stage": stage_name, "saved_to": str(path)}

        monkeypatch.setattr(
            demo,
            "load_config",
            lambda: SimpleNamespace(comsol=SimpleNamespace(version=None, executable_path=None)),
        )
        monkeypatch.setattr(demo.COMSOLClient, "get_instance", staticmethod(lambda: fake_client))
        monkeypatch.setattr(demo.COMSOLClient, "reset_instance", staticmethod(lambda: None))
        monkeypatch.setattr(
            demo,
            "comsol_load_model",
            lambda filepath: {"success": True, "model_name": "loaded_nominal_model", "filepath": filepath},
        )
        monkeypatch.setattr(
            demo,
            "_remove_model_solver_sequences_via_java",
            lambda model_name: pytest.fail("zeroInitGap-only diagnostic must not rebuild solver sequences"),
        )
        monkeypatch.setattr(demo, "_set_3d_staged_contact_state", fake_set_state)
        monkeypatch.setattr(demo, "_save_stage_configured_mph", fake_save_stage)
        monkeypatch.setattr(demo, "comsol_solve", lambda model_name: {"success": False, "error": "Solve failed: timed out"})
        monkeypatch.setattr(demo, "comsol_save_model", lambda model_name, filepath=None: {"success": True, "saved_to": filepath})
        monkeypatch.setattr(demo, "comsol_close_model", lambda model_name, save=False: {"success": True, "model_name": model_name})

        summary = demo.run_actual_area_resume_from_solved_nominal_mph(
            source_mph=source_mph,
            output_dir=output_dir,
            cores=1,
            contact_zero_init_gap_value="1",
        )

        assert fake_client.started is True
        assert fake_client.stopped is True
        assert configured["reuse_existing_solver"] is True
        assert configured["use_parametric_sweep"] is False
        assert configured["radial_load_value"] == "0.101[N]"
        assert configured["inner_bore_load_pressure_expression"] == "radial_load/(4.863178789249815e-3[m^2])"
        assert configured["contact_feature_property_overrides"] == {
            "contact_roller_1_inner": {"zeroInitGap": "1"},
            "contact_roller_1_outer": {"zeroInitGap": "1"},
            "contact_roller_2_inner": {"zeroInitGap": "1"},
            "contact_roller_2_outer": {"zeroInitGap": "1"},
            "contact_roller_12_inner": {"zeroInitGap": "1"},
            "contact_roller_12_outer": {"zeroInitGap": "1"},
        }
        stage = summary["staged_contact_solve"]["stages"][0]
        assert stage["name"].endswith("_zero_init_gap1")
        assert stage["solver_formulation_diagnostic_role"] == (
            "actual_area_pressure_resume_from_solved_nominal_contact_zero_init_gap_only"
        )
        assert summary["staged_contact_solve"]["policy"] == (
            "load_solved_nominal_mph_then_configure_actual_area_pressure_checkpoint_with_contact_zero_init_gap_1"
        )
        assert summary["staged_contact_solve"]["contact_stage_mode"].endswith("_zero_init_gap1")
        assert summary["solve"]["success"] is False

    def test_actual_area_resume_saved_probes_receive_boundary_load_context(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from scripts import run_agent_3d_bearing_full_demo as demo

        source_mph = tmp_path / "nominal_solved.mph"
        source_mph.write_text("fake nominal solved mph", encoding="utf-8")
        output_dir = tmp_path / "actual_area_resume_solved_probe_context"

        class FakeClient:
            def __init__(self):
                self.is_running = False

            def start(self, **kwargs):
                self.is_running = True

            def stop(self):
                self.is_running = False

        probe_contexts: dict[str, dict[str, object]] = {}

        monkeypatch.setattr(
            demo,
            "load_config",
            lambda: SimpleNamespace(comsol=SimpleNamespace(version=None, executable_path=None)),
        )
        monkeypatch.setattr(demo.COMSOLClient, "get_instance", staticmethod(lambda: FakeClient()))
        monkeypatch.setattr(demo.COMSOLClient, "reset_instance", staticmethod(lambda: None))
        monkeypatch.setattr(
            demo,
            "comsol_load_model",
            lambda filepath: {"success": True, "model_name": "loaded_nominal_model", "filepath": filepath},
        )
        monkeypatch.setattr(
            demo,
            "_set_3d_staged_contact_state",
            lambda model_name, **kwargs: {"success": True, "model_name": model_name, "stdout": "configured"},
        )
        monkeypatch.setattr(
            demo,
            "_save_stage_configured_mph",
            lambda model_name, *, stage_name, output_dir: {"success": True, "model_name": model_name, "saved_to": str(Path(output_dir) / f"{stage_name}.mph")},
        )
        monkeypatch.setattr(demo, "comsol_solve", lambda model_name: {"success": True, "model_name": model_name})
        monkeypatch.setattr(
            demo,
            "comsol_evaluate",
            lambda model_name, expression: {"success": True, "model_name": model_name, "expression": expression, "statistics": {"max": 1.0}},
        )
        monkeypatch.setattr(demo, "_evaluate_per_roller_probe_results", lambda model_name: [])
        monkeypatch.setattr(
            demo,
            "_active_roller_load_distribution_audit",
            lambda per_roller, *, active_rollers, boundary_load_active: {"success": True},
        )
        monkeypatch.setattr(
            demo,
            "_export_native_3d_stage_volume_plot",
            lambda model_name, *, stage_name, output_dir: {"success": True, "filepath": str(Path(output_dir) / f"{stage_name}.png")},
        )
        monkeypatch.setattr(demo, "comsol_save_model", lambda model_name, filepath=None: {"success": True, "saved_to": filepath})
        monkeypatch.setattr(demo, "comsol_close_model", lambda model_name, save=False: {"success": True})

        def fake_boundary_probe(**kwargs):
            probe_contexts["boundary"] = kwargs["boundary_load_context"]
            return {"success": True, "load_balance": {"success": True}}

        def fake_contact_probe(**kwargs):
            return {"success": True}

        def fake_reaction_probe(**kwargs):
            probe_contexts["reaction"] = kwargs["boundary_load_context"]
            return {"success": True, "reaction_load_balance": {"success": False}}

        monkeypatch.setattr(demo, "probe_saved_boundary_load_mph", fake_boundary_probe)
        monkeypatch.setattr(demo, "probe_saved_contact_mph", fake_contact_probe)
        monkeypatch.setattr(demo, "probe_saved_reaction_mph", fake_reaction_probe)

        summary = demo.run_actual_area_resume_from_solved_nominal_mph(
            source_mph=source_mph,
            output_dir=output_dir,
            cores=1,
            contact_zero_init_gap_value="1",
        )

        assert summary["solve"]["success"] is True
        assert probe_contexts["boundary"] == probe_contexts["reaction"]
        assert probe_contexts["boundary"]["success"] is True
        assert probe_contexts["boundary"]["applied_load_n"] == pytest.approx(0.101)
        assert probe_contexts["boundary"]["radial_load_value"] == "0.101[N]"
        assert probe_contexts["boundary"]["stage"].endswith("_zero_init_gap1")
        stage = summary["staged_contact_solve"]["stages"][0]
        assert stage["saved_boundary_load_probe"]["load_balance"]["success"] is True
        assert stage["saved_reaction_probe"]["reaction_load_balance"]["success"] is False
        assert summary["physical_contact_validation"]["errors"] == [
            "Saved-MPH support reaction/load balance did not pass."
        ]

    def test_actual_area_resume_can_disable_active_roller_stabilization_only(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from scripts import run_agent_3d_bearing_full_demo as demo

        source_mph = tmp_path / "nominal_solved.mph"
        source_mph.write_text("fake nominal solved mph", encoding="utf-8")
        output_dir = tmp_path / "actual_area_resume_zero_init_gap_no_active_stabilization"

        class FakeClient:
            def __init__(self):
                self.is_running = False
                self.started = False
                self.stopped = False

            def start(self, **kwargs):
                self.started = True
                self.is_running = True

            def stop(self):
                self.stopped = True
                self.is_running = False

        fake_client = FakeClient()
        configured: dict[str, object] = {}

        def fake_set_state(model_name: str, **kwargs):
            configured["model_name"] = model_name
            configured.update(kwargs)
            return {"success": True, "model_name": model_name, "stdout": "configured no active stabilization"}

        def fake_save_stage(model_name: str, *, stage_name: str, output_dir: Path | None):
            path = Path(output_dir) / f"{stage_name}_configured.mph"
            path.write_text("configured mph", encoding="utf-8")
            return {"success": True, "model_name": model_name, "stage": stage_name, "saved_to": str(path)}

        monkeypatch.setattr(
            demo,
            "load_config",
            lambda: SimpleNamespace(comsol=SimpleNamespace(version=None, executable_path=None)),
        )
        monkeypatch.setattr(demo.COMSOLClient, "get_instance", staticmethod(lambda: fake_client))
        monkeypatch.setattr(demo.COMSOLClient, "reset_instance", staticmethod(lambda: None))
        monkeypatch.setattr(
            demo,
            "comsol_load_model",
            lambda filepath: {"success": True, "model_name": "loaded_nominal_model", "filepath": filepath},
        )
        monkeypatch.setattr(
            demo,
            "_remove_model_solver_sequences_via_java",
            lambda model_name: pytest.fail("no-active-stabilization diagnostic must not rebuild solver sequences"),
        )
        monkeypatch.setattr(demo, "_set_3d_staged_contact_state", fake_set_state)
        monkeypatch.setattr(demo, "_save_stage_configured_mph", fake_save_stage)
        monkeypatch.setattr(demo, "comsol_solve", lambda model_name: {"success": False, "error": "Solve failed: timed out"})
        monkeypatch.setattr(demo, "comsol_save_model", lambda model_name, filepath=None: {"success": True, "saved_to": filepath})
        monkeypatch.setattr(demo, "comsol_close_model", lambda model_name, save=False: {"success": True, "model_name": model_name})

        summary = demo.run_actual_area_resume_from_solved_nominal_mph(
            source_mph=source_mph,
            output_dir=output_dir,
            cores=1,
            contact_zero_init_gap_value="1",
            disable_active_roller_stabilization=True,
        )

        assert fake_client.started is True
        assert fake_client.stopped is True
        assert configured["reuse_existing_solver"] is True
        assert configured["use_parametric_sweep"] is False
        assert configured["radial_load_value"] == "0.101[N]"
        assert configured["active_roller_stabilization_active"] is False
        assert configured["active_roller_stabilization_mode"] == "spring"
        assert configured["weak_roller_foundation_active"] is True
        assert configured["weak_roller_foundation_k"] == "1e8[N/m^3]"
        assert configured["weak_inner_guidance_active"] is True
        assert configured["weak_inner_guidance_k"] == "5e4[N/m^3]"
        assert configured["contact_feature_property_overrides"] == {
            "contact_roller_1_inner": {"zeroInitGap": "1"},
            "contact_roller_1_outer": {"zeroInitGap": "1"},
            "contact_roller_2_inner": {"zeroInitGap": "1"},
            "contact_roller_2_outer": {"zeroInitGap": "1"},
            "contact_roller_12_inner": {"zeroInitGap": "1"},
            "contact_roller_12_outer": {"zeroInitGap": "1"},
        }
        stage = summary["staged_contact_solve"]["stages"][0]
        assert stage["name"].endswith("_zero_init_gap1_no_active_stabilization")
        assert stage["active_roller_stabilization_active"] is False
        assert stage["temporary_active_roller_stabilization_active"] is False
        assert stage["weak_inner_guidance_active"] is True
        assert stage["solver_formulation_diagnostic_role"] == (
            "actual_area_pressure_resume_from_solved_nominal_disable_active_roller_stabilization_only"
        )
        assert summary["staged_contact_solve"]["policy"] == (
            "load_solved_nominal_mph_then_configure_actual_area_pressure_checkpoint"
            "_with_contact_zero_init_gap_1_with_no_active_roller_stabilization"
        )
        assert "temporary active-roller spring stabilization" not in " ".join(
            summary["physical_contact_validation"]["warnings"]
        )
        assert summary["solve"]["success"] is False

    def test_saved_mph_reaction_probe_writes_candidate_artifacts(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from scripts import run_agent_3d_bearing_full_demo as demo

        mph_path = tmp_path / "result_packages" / "bearing_reaction.mph"
        mph_path.parent.mkdir(parents=True)
        mph_path.write_text("fake solved mph placeholder", encoding="utf-8")

        class FakeClient:
            def __init__(self):
                self.is_running = False
                self.started = False
                self.stopped = False

            def start(self, **kwargs):
                self.started = True
                self.is_running = True

            def stop(self):
                self.stopped = True
                self.is_running = False

        fake_client = FakeClient()

        def fake_reaction_probe(model_name: str, *, selection_name: str):
            assert model_name == "loaded_reaction_model"
            assert selection_name == "sel_inner_bore_load_surface"
            return {
                "success": False,
                "kind": "displacement_controlled_reaction_equivalent_probe",
                "candidate_count": 40,
                "evaluated_candidate_success_count": 9,
                "successful_candidate_count": 0,
                "setup_audit": {
                    "success": True,
                    "operator_exists": True,
                    "opname": {"success": True, "value": "intop_displacement_reaction_probe"},
                    "selection_named": {"success": True, "value": "sel_inner_bore_load_surface"},
                },
                "candidate_audit": {
                    "diagnostic_class_counts": {"unknown_operator": 23, "zero_result": 9},
                    "nonzero_success_count": 0,
                },
                "warning": "No probed COMSOL reaction-force expression evaluated to a nonzero reaction.",
            }

        monkeypatch.setattr(
            demo,
            "load_config",
            lambda: SimpleNamespace(comsol=SimpleNamespace(version=None, executable_path=None)),
        )
        monkeypatch.setattr(demo.COMSOLClient, "get_instance", staticmethod(lambda: fake_client))
        monkeypatch.setattr(demo.COMSOLClient, "reset_instance", staticmethod(lambda: None))
        monkeypatch.setattr(demo, "comsol_load_model", lambda filepath: {"success": True, "model_name": "loaded_reaction_model", "filepath": filepath})
        monkeypatch.setattr(demo, "comsol_get_model_summary", lambda model_name: {"success": True, "model_name": model_name})
        monkeypatch.setattr(demo, "_evaluate_displacement_reaction_equivalent", fake_reaction_probe)
        monkeypatch.setattr(demo, "comsol_close_model", lambda model_name, save=False: {"success": True, "model_name": model_name})

        report = demo.probe_saved_reaction_mph(
            mph_path=mph_path,
            output_dir=tmp_path / "reaction_probe",
            selection_name="sel_inner_bore_load_surface",
            cores=1,
        )

        assert report["success"] is False
        assert report["reaction_verified"] is False
        assert report["candidate_audit"]["nonzero_success_count"] == 0
        assert fake_client.started is True
        assert fake_client.stopped is True
        assert Path(report["json_path"]).exists()
        markdown = Path(report["markdown_path"]).read_text(encoding="utf-8")
        assert "Reaction verified: `False`" in markdown
        assert "unknown_operator" in markdown

    def test_bearing_geometry_partition_api_probe_writes_artifacts(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from scripts import run_agent_3d_bearing_full_demo as demo

        class FakeClient:
            def __init__(self):
                self.is_running = False
                self.started = False
                self.stopped = False

            def start(self, **kwargs):
                self.started = True
                self.is_running = True

            def stop(self):
                self.stopped = True
                self.is_running = False

        fake_client = FakeClient()
        executed: dict[str, str] = {}
        closed: list[str] = []

        def fake_execute_java(code: str, *, model_name: str):
            executed["code"] = code
            executed["model_name"] = model_name
            payload = {
                "success": True,
                "kind": "bearing_3d_geometry_partition_api_probe",
                "candidate_count": 3,
                "create_success_count": 2,
                "run_success_count": 1,
                "valid_feature_types": ["Partition", "Intersection"],
                "runnable_feature_types": ["Intersection"],
                "rows": [
                    {
                        "feature_type": "Partition",
                        "create_success": True,
                        "run_attempt": {"success": False, "error": "Unknown property"},
                        "set_attempts": {"selection_input_set": {"success": True}},
                    },
                    {
                        "feature_type": "Intersection",
                        "create_success": True,
                        "run_attempt": {"success": True},
                        "set_attempts": {"selection_input_set": {"success": True}},
                    },
                    {
                        "feature_type": "Imprint",
                        "create_success": False,
                        "error": "Unknown feature type",
                    },
                ],
            }
            stdout = (
                demo.GEOMETRY_PARTITION_API_PROBE_JSON_START
                + "\n"
                + json.dumps(payload)
                + "\n"
                + demo.GEOMETRY_PARTITION_API_PROBE_JSON_END
            )
            return {"success": True, "stdout": stdout}

        monkeypatch.setattr(
            demo,
            "load_config",
            lambda: SimpleNamespace(comsol=SimpleNamespace(version=None, executable_path=None)),
        )
        monkeypatch.setattr(demo.COMSOLClient, "get_instance", staticmethod(lambda: fake_client))
        monkeypatch.setattr(demo.COMSOLClient, "reset_instance", staticmethod(lambda: None))
        monkeypatch.setattr(demo, "comsol_create_model", lambda model_name: {"success": True, "model_name": "created_partition_probe"})
        monkeypatch.setattr(demo, "comsol_execute_java", fake_execute_java)
        monkeypatch.setattr(demo, "comsol_close_model", lambda model_name, save=False: closed.append(model_name) or {"success": True})

        report = demo.probe_geometry_partition_api(
            output_dir=tmp_path / "partition_probe",
            model_name="requested_partition_probe",
            cores=1,
        )

        assert report["success"] is True
        assert report["model_name"] == "created_partition_probe"
        assert report["probe"]["valid_feature_types"] == ["Partition", "Intersection"]
        assert report["probe"]["runnable_feature_types"] == ["Intersection"]
        assert "PartitionObjects" in executed["code"]
        assert executed["model_name"] == "created_partition_probe"
        assert closed == ["created_partition_probe"]
        assert fake_client.started is True
        assert fake_client.stopped is True
        assert Path(report["json_path"]).exists()
        markdown = Path(report["markdown_path"]).read_text(encoding="utf-8")
        assert "Bearing 3D Geometry Partition API Probe" in markdown
        assert "Partition" in markdown
        assert "Intersection" in markdown

    def test_bearing_cylinder_seam_api_probe_writes_artifacts(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from scripts import run_agent_3d_bearing_full_demo as demo

        class FakeClient:
            def __init__(self):
                self.is_running = False
                self.started = False
                self.stopped = False

            def start(self, **kwargs):
                self.started = True
                self.is_running = True

            def stop(self):
                self.stopped = True
                self.is_running = False

        fake_client = FakeClient()
        executed: dict[str, str] = {}
        closed: list[str] = []

        def fake_execute_java(code: str, *, model_name: str):
            executed["code"] = code
            executed["model_name"] = model_name
            payload = {
                "success": True,
                "kind": "bearing_3d_cylinder_seam_api_probe",
                "run_result": {"success": True},
                "successful_properties": ["axis", "pos", "rot", "selresult"],
                "failed_properties": ["axistype"],
                "set_attempts": [
                    {
                        "feature": "roller_cyl",
                        "property": "rot",
                        "value": "15[deg]",
                        "set": {"success": True, "value": "15[deg]"},
                    },
                    {
                        "feature": "roller_cyl",
                        "property": "axistype",
                        "value": "z",
                        "set": {"success": False, "error": "Unknown property"},
                    },
                ],
            }
            stdout = (
                demo.CYLINDER_SEAM_API_PROBE_JSON_START
                + "\n"
                + json.dumps(payload)
                + "\n"
                + demo.CYLINDER_SEAM_API_PROBE_JSON_END
            )
            return {"success": True, "stdout": stdout}

        monkeypatch.setattr(
            demo,
            "load_config",
            lambda: SimpleNamespace(comsol=SimpleNamespace(version=None, executable_path=None)),
        )
        monkeypatch.setattr(demo.COMSOLClient, "get_instance", staticmethod(lambda: fake_client))
        monkeypatch.setattr(demo.COMSOLClient, "reset_instance", staticmethod(lambda: None))
        monkeypatch.setattr(demo, "comsol_create_model", lambda model_name: {"success": True, "model_name": "created_cylinder_probe"})
        monkeypatch.setattr(demo, "comsol_execute_java", fake_execute_java)
        monkeypatch.setattr(demo, "comsol_close_model", lambda model_name, save=False: closed.append(model_name) or {"success": True})

        report = demo.probe_cylinder_seam_api(
            output_dir=tmp_path / "cylinder_probe",
            model_name="requested_cylinder_probe",
            cores=1,
        )

        assert report["success"] is True
        assert report["model_name"] == "created_cylinder_probe"
        assert report["probe"]["successful_properties"] == ["axis", "pos", "rot", "selresult"]
        assert "Cylinder" in executed["code"]
        assert "rot" in executed["code"]
        assert "axis" in executed["code"]
        assert executed["model_name"] == "created_cylinder_probe"
        assert closed == ["created_cylinder_probe"]
        assert fake_client.started is True
        assert fake_client.stopped is True
        assert Path(report["json_path"]).exists()
        markdown = Path(report["markdown_path"]).read_text(encoding="utf-8")
        assert "Bearing 3D Cylinder Seam API Probe" in markdown
        assert "roller_1" in markdown
        assert "axistype" in markdown

    def test_saved_mph_contact_probe_writes_candidate_artifacts(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from scripts import run_agent_3d_bearing_full_demo as demo

        mph_path = tmp_path / "result_packages" / "bearing_contact_probe.mph"
        mph_path.parent.mkdir(parents=True)
        mph_path.write_text("fake solved mph placeholder", encoding="utf-8")

        class FakeClient:
            def __init__(self):
                self.is_running = False
                self.started = False
                self.stopped = False

            def start(self, **kwargs):
                self.started = True
                self.is_running = True

            def stop(self):
                self.stopped = True
                self.is_running = False

        fake_client = FakeClient()

        def fake_contact_probe(
            model_name: str,
            *,
            rollers: tuple[int, ...],
            entity_transfer: dict | None = None,
        ):
            assert model_name == "loaded_contact_model"
            assert rollers == (1, 2, 12)
            assert entity_transfer is None
            return {
                "success": True,
                "kind": "bearing_3d_saved_mph_contact_surface_candidate_probe",
                "candidate_count": 6,
                "success_count": 6,
                "nonzero_count": 4,
                "evaluations": [
                    {
                        "roller": 1,
                        "contact_label": "roller_1_inner_source",
                        "selection": "sel_roller_1_inner_contact",
                        "method": "java_maxsurface",
                        "expression": "solid.mises",
                        "success": True,
                        "value": 0.0,
                        "diagnostic_class": "zero_result",
                    },
                    {
                        "roller": 2,
                        "contact_label": "roller_2_inner_source",
                        "selection": "sel_roller_2_inner_contact",
                        "method": "java_maxsurface",
                        "expression": "solid.mises",
                        "success": True,
                        "value": 6.5e6,
                        "diagnostic_class": "nonzero_success",
                    },
                ],
                "by_roller": {
                    "roller_1": {"candidate_count": 2, "success_count": 2, "nonzero_count": 0},
                    "roller_2": {"candidate_count": 2, "success_count": 2, "nonzero_count": 2},
                },
                "contact_status_by_roller": {
                    "roller_1": {"pair_specific_success_count": 2, "pair_specific_nonzero_count": 0},
                    "roller_2": {"pair_specific_success_count": 2, "pair_specific_nonzero_count": 2},
                },
            }

        def fake_model_audit(model_name: str):
            assert model_name == "loaded_contact_model"
            return {
                "solid_feature_audit": [
                    {
                        "tag": "contact_roller_1_inner",
                        "exists": True,
                        "active": True,
                        "type": "Contact",
                        "properties": {
                            "pairs": {"success": True, "value": ["cp_roller_1_inner_raceway"]},
                            "pn_penalty": {"success": True, "value": "5e-5*E_steel"},
                            "useRelaxation": {"success": True, "value": "Always"},
                            "irlx": {"success": True, "value": "0.12"},
                            "tolcontact": {"success": True, "value": "3[um]"},
                            "zeroInitGap": {"success": True, "value": "0"},
                        },
                    },
                    {
                        "tag": "contact_roller_2_inner",
                        "exists": True,
                        "active": True,
                        "type": "Contact",
                        "properties": {
                            "pairs": {"success": True, "value": ["cp_roller_2_inner_raceway"]},
                            "pn_penalty": {"success": True, "value": "5e-5*E_steel"},
                            "useRelaxation": {"success": True, "value": "Always"},
                            "irlx": {"success": True, "value": "0.12"},
                            "tolcontact": {"success": True, "value": "3[um]"},
                            "zeroInitGap": {"success": True, "value": "0"},
                        },
                    },
                ],
                "contact_pair_audit": [
                    {
                        "tag": "cp_roller_1_inner_raceway",
                        "exists": True,
                        "source": {"named": {"success": True, "value": "sel_roller_1_inner_contact"}, "entity_count": 2},
                        "destination": {"named": {"success": True, "value": "sel_inner_raceway_1_contact"}, "entity_count": 2},
                    },
                    {
                        "tag": "cp_roller_2_inner_raceway",
                        "exists": True,
                        "source": {"named": {"success": True, "value": "sel_roller_2_inner_contact"}, "entity_count": 2},
                        "destination": {"named": {"success": True, "value": "sel_inner_raceway_2_contact"}, "entity_count": 2},
                    },
                ],
            }

        def fake_contact_feature_introspection(model_name: str, *, rollers: tuple[int, ...]):
            assert model_name == "loaded_contact_model"
            assert rollers == (1, 2, 12)
            return {
                "success": True,
                "kind": "bearing_3d_contact_feature_property_introspection",
                "feature_count": 4,
                "comparison": {
                    "offset_like_properties": ["zeroInitGap"],
                    "unsupported_offset_candidate_properties": {"gapoffset": ["contact_roller_1_inner"]},
                    "zero_carry_reference_differences": [],
                    "zero_carry_matches_reference_properties": True,
                },
                "rows": [
                    {
                        "tag": "contact_roller_1_inner",
                        "exists": True,
                        "property_names": {"success": True, "value": ["pairs", "pn_penalty", "zeroInitGap"]},
                    }
                ],
            }

        monkeypatch.setattr(
            demo,
            "load_config",
            lambda: SimpleNamespace(comsol=SimpleNamespace(version=None, executable_path=None)),
        )
        monkeypatch.setattr(demo.COMSOLClient, "get_instance", staticmethod(lambda: fake_client))
        monkeypatch.setattr(demo.COMSOLClient, "reset_instance", staticmethod(lambda: None))
        monkeypatch.setattr(demo, "comsol_load_model", lambda filepath: {"success": True, "model_name": "loaded_contact_model", "filepath": filepath})
        monkeypatch.setattr(demo, "comsol_get_model_summary", lambda model_name: {"success": True, "model_name": model_name})
        monkeypatch.setattr(demo, "_evaluate_saved_contact_surface_candidates", fake_contact_probe)
        monkeypatch.setattr(demo, "_run_stage_mph_model_audit", fake_model_audit)
        monkeypatch.setattr(demo, "_introspect_contact_feature_properties", fake_contact_feature_introspection)
        monkeypatch.setattr(demo, "comsol_close_model", lambda model_name, save=False: {"success": True, "model_name": model_name})

        report = demo.probe_saved_contact_mph(
            mph_path=mph_path,
            output_dir=tmp_path / "contact_probe",
            cores=1,
        )

        assert report["success"] is True
        assert report["contact_probe_success_count"] == 6
        assert report["contact_probe_nonzero_count"] == 4
        assert fake_client.started is True
        assert fake_client.stopped is True
        assert Path(report["json_path"]).exists()
        pair_diag = report["pair_enforcement_diagnostic"]
        assert pair_diag["zero_pair_specific_contact_pressure_rollers"] == ["roller_1"]
        assert pair_diag["nonzero_reference_rollers"] == ["roller_2"]
        assert pair_diag["roller_states"]["roller_1"]["inner_pair"]["source_named"] == "sel_roller_1_inner_contact"
        assert report["contact_feature_introspection"]["comparison"]["zero_carry_matches_reference_properties"] is True
        markdown = Path(report["markdown_path"]).read_text(encoding="utf-8")
        assert "Bearing 3D Saved MPH Contact Probe" in markdown
        assert "sel_roller_2_inner_contact" in markdown
        assert "Pair Enforcement Diagnostic" in markdown
        assert "Contact Feature Property Introspection" in markdown
        assert "gapoffset" in markdown

    def test_bearing_3d_entity_transfer_diagnostic_maps_nonzero_destination(self, monkeypatch):
        from scripts import run_agent_3d_bearing_full_demo as demo

        def fake_selection_entities(model_name: str, *, selection_name: str):
            assert model_name == "contact_model"
            assert selection_name == "sel_outer_raceway_1_contact"
            return {
                "success": True,
                "selection": selection_name,
                "entities": [13, 14],
                "entity_count": 2,
            }

        def fake_max(
            model_name: str,
            expression: str,
            *,
            entities: list[int],
            tag: str,
        ):
            assert model_name == "contact_model"
            entity = entities[0]
            values = {
                (13, "solid.Tn_cp_roller_1_outer_raceway"): 4.0,
                (13, "abs(solid.Tn_cp_roller_1_outer_raceway)"): 4.0,
                (13, "solid.Tn_cp_roller_1_outer_raceway_src"): 5.0,
                (13, "abs(solid.Tn_cp_roller_1_outer_raceway_src)"): 5.0,
                (13, "solid.p"): 8.0,
                (13, "solid.mises"): 12.0,
                (14, "solid.Tn_cp_roller_1_outer_raceway"): 0.0,
                (14, "abs(solid.Tn_cp_roller_1_outer_raceway)"): 0.0,
                (14, "solid.Tn_cp_roller_1_outer_raceway_src"): 0.0,
                (14, "abs(solid.Tn_cp_roller_1_outer_raceway_src)"): 0.0,
                (14, "solid.p"): 0.0,
                (14, "solid.mises"): 0.0,
            }
            return {
                "success": True,
                "expression": expression,
                "entities": entities,
                "value": values.get((entity, expression), 0.0),
                "method": "java_maxsurface_entities",
            }

        def fake_integral(
            model_name: str,
            expression: str,
            *,
            entities: list[int],
            tag: str,
        ):
            entity = entities[0]
            return {
                "success": True,
                "expression": expression,
                "entities": entities,
                "value": 4.0 if entity == 13 else 0.0,
                "method": "java_intsurface_entity",
            }

        monkeypatch.setattr(demo, "_get_selection_entities_via_java", fake_selection_entities)
        monkeypatch.setattr(demo, "_evaluate_surface_max_expression_on_entities_via_java", fake_max)
        monkeypatch.setattr(demo, "_evaluate_surface_integral_expression_on_entities_via_java", fake_integral)

        result = demo._evaluate_contact_entity_transfer(
            "contact_model",
            entity_transfer={
                "roller": 1,
                "contact_label": "roller_1_outer_raceway",
                "selection_name": "sel_outer_raceway_1_contact",
            },
        )

        assert result["success"] is True
        assert result["entity_count"] == 2
        assert result["nonzero_entities"]["abs_pair_Tn_max"] == [13]
        assert result["nonzero_entities"]["pair_Tn_src_max"] == [13]
        assert result["by_entity"]["13"]["pair_Tn_max"]["value"] == 4.0
        assert result["by_entity"]["13"]["pair_Tn_src_max"]["value"] == 5.0
        assert result["by_entity"]["14"]["pair_Tn_max"]["value"] == 0.0

    def test_contact_entity_transfer_expression_candidates_include_source_and_destination_aliases(self):
        from scripts import run_agent_3d_bearing_full_demo as demo

        expressions = demo._contact_entity_transfer_expression_candidates("cp_roller_1_outer_raceway")
        labels = {label for label, _expression, _method in expressions}
        expression_text = {expression for _label, expression, _method in expressions}

        assert "pair_Tn_max" in labels
        assert "pair_Tn_src_max" in labels
        assert "pair_Tn_src_prefix_max" in labels
        assert "pair_Tn_dst_max" in labels
        assert "solid.Tn_cp_roller_1_outer_raceway_src" in expression_text
        assert "solid.Tn_src_cp_roller_1_outer_raceway" in expression_text
        assert "solid.Tn_cp_roller_1_outer_raceway_dst" in expression_text

    def test_contact_pair_endpoint_consistency_accepts_expected_bindings(self):
        from scripts import run_agent_3d_bearing_full_demo as demo

        rows = []
        for roller in (1, 2, 12):
            for side in ("inner", "outer"):
                rows.append({
                    "tag": f"cp_roller_{roller}_{side}_raceway",
                    "exists": True,
                    "source": {
                        "named": {
                            "success": True,
                            "value": f"sel_roller_{roller}_{side}_contact",
                        },
                        "entity_count": 2,
                    },
                    "destination": {
                        "named": {
                            "success": True,
                            "value": f"sel_{side}_raceway_{roller}_contact",
                        },
                        "entity_count": 2,
                    },
                })

        summary = demo._summarize_contact_pair_endpoint_consistency(rows)

        assert summary["success"] is True
        assert summary["consistent_pair_count"] == 6
        assert summary["divergent_pair_tags"] == []
        assert summary["endpoint_rebind_justified"] is False

    def test_contact_pair_endpoint_consistency_flags_rebind_candidate(self):
        from scripts import run_agent_3d_bearing_full_demo as demo

        rows = [
            {
                "tag": "cp_roller_1_inner_raceway",
                "exists": True,
                "source": {
                    "named": {"success": True, "value": "sel_roller_1_inner_contact"},
                    "entity_count": 2,
                },
                "destination": {
                    "named": {"success": True, "value": "sel_inner_raceway_1_contact"},
                    "entity_count": 2,
                },
            },
            {
                "tag": "cp_roller_1_outer_raceway",
                "exists": True,
                "source": {
                    "named": {"success": True, "value": "sel_outer_raceway_1_contact"},
                    "entity_count": 4,
                },
                "destination": {
                    "named": {"success": True, "value": "sel_roller_1_outer_contact"},
                    "entity_count": 2,
                },
            },
        ]

        summary = demo._summarize_contact_pair_endpoint_consistency(
            rows,
            rollers=(1,),
        )

        assert summary["success"] is False
        assert summary["consistent_pair_count"] == 1
        assert summary["divergent_pair_tags"] == ["cp_roller_1_outer_raceway"]
        assert summary["endpoint_rebind_justified"] is True

    def test_bearing_3d_contact_feature_introspection_code_is_syntax_checked(self):
        from scripts import run_agent_3d_bearing_full_demo as demo

        code = demo._build_contact_feature_introspection_code(rollers=(1, 2, 12))

        compile(code, "contact_feature_introspection", "exec")
        assert "CONTACT_FEATURE_INTROSPECTION_JSON_START" in code
        assert "property_read_success_count" in code
        assert "gapoffset" in code

    def test_bearing_3d_contact_feature_introspection_normalizes_expected_tag_differences(self):
        from scripts import run_agent_3d_bearing_full_demo as demo

        def row(tag: str, pair: str) -> dict:
            return {
                "tag": tag,
                "exists": True,
                "property_names": {
                    "success": True,
                    "value": ["pairs", "pn", "pn_penalty", "offset", "source_offset", "pressureOffsetCtrl", "zeroInitGap"],
                },
                "properties": {
                    "pairs": {"success": True, "value": [pair]},
                    "pn": {
                        "success": True,
                        "value": [f"solid.{tag}.E_char/solid.hmin_dst"],
                    },
                    "pn_penalty": {"success": True, "value": ["5e-5*E_steel"]},
                    "offset": {"success": True, "value": ["0"]},
                    "source_offset": {"success": True, "value": ["0"]},
                    "pressureOffsetCtrl": {"success": True, "value": ["From contact pressure"]},
                    "zeroInitGap": {"success": True, "value": ["0"]},
                    "gapoffset": {"success": False, "error": "Unknown parameter X#gapoffset"},
                },
            }

        summary = demo._summarize_contact_feature_introspection({
            "rows": [
                row("contact_roller_1_inner", "cp_roller_1_inner_raceway"),
                row("contact_roller_2_inner", "cp_roller_2_inner_raceway"),
                row("contact_roller_12_inner", "cp_roller_12_inner_raceway"),
                row("contact_roller_1_outer", "cp_roller_1_outer_raceway"),
                row("contact_roller_2_outer", "cp_roller_2_outer_raceway"),
                row("contact_roller_12_outer", "cp_roller_12_outer_raceway"),
            ]
        })

        assert summary["zero_carry_matches_reference_properties"] is True
        assert summary["zero_carry_reference_differences"] == []
        assert "offset" in summary["offset_like_properties"]
        assert "source_offset" in summary["offset_like_properties"]
        assert "offset" in summary["readable_offset_candidate_properties"]["contact_roller_1_inner"]
        assert "source_offset" in summary["readable_offset_candidate_properties"]["contact_roller_1_inner"]
        assert "offset" not in summary["unsupported_offset_candidate_properties"]
        assert "source_offset" not in summary["unsupported_offset_candidate_properties"]
        assert summary["unsupported_offset_candidate_properties"]["gapoffset"] == [
            "contact_roller_1_inner",
            "contact_roller_2_inner",
            "contact_roller_12_inner",
            "contact_roller_1_outer",
            "contact_roller_2_outer",
            "contact_roller_12_outer",
        ]

    def test_saved_contact_probe_includes_pair_status_variable_candidates(self, monkeypatch):
        from scripts import run_agent_3d_bearing_full_demo as demo

        max_expressions: list[tuple[str, str]] = []
        integral_expressions: list[tuple[str, str]] = []

        def fake_max(model_name: str, expression: str, *, selection_name: str, tag: str):
            assert model_name == "contact_model"
            max_expressions.append((selection_name, expression))
            if expression == "solid.mises":
                value = 0.0 if selection_name == "sel_roller_1_inner_contact" else 5.0
                return {
                    "success": True,
                    "method": "java_maxsurface",
                    "expression": expression,
                    "selection": selection_name,
                    "value": value,
                }
            if expression == "solid.Tn_cp_roller_1_inner_raceway":
                return {
                    "success": True,
                    "method": "java_maxsurface",
                    "expression": expression,
                    "selection": selection_name,
                    "value": 12.0,
                }
            if expression == "solid.gap_cp_roller_1_inner_raceway":
                return {
                    "success": True,
                    "method": "java_maxsurface",
                    "expression": expression,
                    "selection": selection_name,
                    "value": float("inf"),
                }
            return {
                "success": False,
                "method": "java_maxsurface",
                "expression": expression,
                "selection": selection_name,
                "error": f"Unknown variable: {expression}",
            }

        def fake_integral(model_name: str, expression: str, *, selection_name: str, tag: str):
            assert model_name == "contact_model"
            integral_expressions.append((selection_name, expression))
            radial_centers = {
                "sel_roller_1_inner_contact": 0.02300,
                "sel_inner_raceway_1_contact": 0.02301,
                "sel_roller_1_outer_contact": 0.03100,
                "sel_outer_raceway_1_contact": 0.03102,
            }
            if expression == "1":
                value = 2.0
            elif expression == "x":
                value = 2.0 * radial_centers.get(selection_name, 0.0)
            elif expression in {"y", "z"}:
                value = 0.0
            elif expression == "nx":
                value = 2.0
            elif expression in {"ny", "nz"}:
                value = 0.0
            elif expression.startswith("x*("):
                value = 2.0 * radial_centers.get(selection_name, 0.0)
            elif expression.startswith("nx*("):
                value = 2.0
            elif expression == "abs(solid.Tn_cp_roller_1_inner_raceway)":
                value = 24.0
            elif expression == "solid.Tn_cp_roller_1_inner_raceway":
                value = -24.0
            else:
                value = 0.0
            return {
                "success": True,
                "method": "java_intsurface",
                "expression": expression,
                "selection": selection_name,
                "value": value,
            }

        def fake_selection_entities(model_name: str, *, selection_name: str):
            assert model_name == "contact_model"
            return {
                "success": True,
                "selection": selection_name,
                "entities": [101, 102],
                "entity_count": 2,
            }

        def fake_entity_integral(model_name: str, expression: str, *, entities: list[int], tag: str):
            assert model_name == "contact_model"
            entity = entities[0]
            radial_centers = {101: 0.0225, 102: 0.0235}
            if expression == "1":
                value = 1.0
            elif expression == "x":
                value = radial_centers.get(entity, 0.0)
            elif expression in {"y", "z"}:
                value = 0.0
            elif expression.startswith("x*("):
                value = radial_centers.get(entity, 0.0)
            else:
                value = 0.0
            return {
                "success": True,
                "method": "java_intsurface_entity",
                "expression": expression,
                "entities": entities,
                "value": value,
            }

        monkeypatch.setattr(demo, "_evaluate_surface_max_expression_via_java", fake_max)
        monkeypatch.setattr(demo, "_evaluate_surface_integral_expression_via_java", fake_integral)
        monkeypatch.setattr(demo, "_get_selection_entities_via_java", fake_selection_entities)
        monkeypatch.setattr(demo, "_evaluate_surface_integral_expression_on_entities_via_java", fake_entity_integral)

        result = demo._evaluate_saved_contact_surface_candidates("contact_model", rollers=(1,))

        assert result["success"] is True
        assert any(expr == "solid.Tn_cp_roller_1_inner_raceway" for _, expr in max_expressions)
        assert any(expr == "abs(solid.Tn_cp_roller_1_outer_raceway)" for _, expr in max_expressions)
        assert any(expr == "solid.active_cp_roller_1_inner_raceway" for _, expr in max_expressions)
        assert any(expr == "solid.lambdaN_cp_roller_1_outer_raceway" for _, expr in max_expressions)
        assert integral_expressions
        assert any(expr == "1" for _, expr in integral_expressions)
        assert any(expr == "nx" for _, expr in integral_expressions)
        assert any(expr == "x" for _, expr in integral_expressions)
        assert any(expr == "abs(solid.Tn_cp_roller_1_inner_raceway)" for _, expr in integral_expressions)
        assert result["candidate_audit"]["contact_status_candidate_count"] > 0
        assert result["candidate_audit"]["contact_status_success_count"] >= 2
        assert result["candidate_audit"]["infinite_result_count"] >= 1
        assert result["candidate_audit"]["unknown_variable_count"] > 0
        assert any(
            item["expression"] == "solid.Tn_cp_roller_1_inner_raceway"
            for item in result["candidate_audit"]["first_contact_variable_successes"]
        )
        discovery = result["contact_variable_discovery"]
        assert discovery["success"] is True
        assert "Tn" in discovery["useful_variables"]
        assert "Tn" in discovery["finite_nonzero_variables"]
        assert discovery["by_variable"]["Tn"]["finite_nonzero_count"] >= 1
        assert discovery["by_variable"]["Tn"]["pair_specific_finite_nonzero_count"] >= 1
        assert "roller_1" in discovery["by_variable"]["Tn"]["rollers_with_pair_specific_finite_nonzero"]
        assert "gap" in discovery["useful_variables"]
        assert discovery["by_variable"]["gap"]["infinite_count"] >= 1
        assert discovery["by_variable"]["active"]["unknown_variable_count"] >= 1
        assert discovery["by_roller"]["roller_1"]["Tn"]["pair_specific_finite_nonzero_count"] >= 1
        assert discovery["by_roller"]["roller_1"]["Tn"]["first_success"]["expression"] == "solid.Tn_cp_roller_1_inner_raceway"
        status = result["contact_status_by_roller"]["roller_1"]
        assert status["pair_specific_success_count"] >= 2
        assert status["pair_specific_nonzero_count"] >= 2
        assert status["by_contact_label"]["roller_1_inner_source"]["pair_specific"]["inner_raceway"]["Tn"]["value"] == 12.0
        normal = result["normal_orientation_by_roller"]["roller_1"]["by_contact_label"]["roller_1_inner_source"]
        assert normal["area_integral"] == 2.0
        assert normal["average_normal"]["radial"] == 1.0
        geometry = result["geometry_moments_by_roller"]["roller_1"]
        assert geometry["by_contact_label"]["roller_1_inner_source"]["centroid_m"]["radial"] == 0.023
        gap_proxy = geometry["source_destination_radial_gap_proxy"]["inner"]
        assert gap_proxy["both_centroids_available"] is True
        assert gap_proxy["abs_radial_delta_m"] == pytest.approx(1.0e-5)
        entity_geometry = result["entity_geometry_moments_by_roller"]["roller_1"]
        entity_rows = entity_geometry["by_contact_label"]["roller_1_inner_source"]["entity_centroid_rows"]
        assert [row["entity"] for row in entity_rows] == [101, 102]
        assert entity_rows[0]["centroid_m"]["radial"] == 0.0225
        assert entity_rows[1]["centroid_m"]["radial"] == 0.0235
        transfer = result["pair_transfer_by_roller"]["roller_1"]["by_contact_label"]["roller_1_inner_source"]
        assert transfer["abs_Tn_integral"]["value"] == 24.0
        assert result["pair_transfer_by_roller"]["roller_1"]["destination_abs_tn_nonzero_count"] >= 1

    def test_contact_transfer_does_not_call_unevaluable_source_zero(self):
        from scripts import run_agent_3d_bearing_full_demo as demo

        transfer = demo._pair_transfer_source_destination(
            {
                "abs_Tn_integral": {
                    "success": False,
                    "value": None,
                    "diagnostic_class": "selection_error",
                }
            },
            {
                "abs_Tn_integral": {
                    "success": True,
                    "value": 5.0,
                    "diagnostic_class": "nonzero_success",
                }
            },
        )

        assert transfer["source_evaluable"] is False
        assert transfer["source_unevaluable"] is True
        assert transfer["destination_evaluable"] is True
        assert transfer["destination_nonzero"] is True
        assert transfer["source_zero_destination_nonzero"] is False
        assert transfer["source_unevaluable_destination_nonzero"] is True

        imbalance = demo._contact_source_destination_imbalance(
            {
                "success_count": 0,
                "finite_success_count": 0,
                "nonzero_count": 0,
            },
            {
                "success_count": 1,
                "finite_success_count": 1,
                "nonzero_count": 1,
                "max_abs_value": 5.0,
            },
        )

        assert imbalance["source_evaluable"] is False
        assert imbalance["source_unevaluable"] is True
        assert imbalance["source_zero_destination_nonzero"] is False
        assert imbalance["source_unevaluable_destination_nonzero"] is True

    def test_boundary_entity_map_summarizes_radius_angle_and_nearest_roller(self):
        from scripts import run_agent_3d_bearing_full_demo as demo

        row = demo._summarize_boundary_entity_row(
            9,
            [
                {"success": True, "expression": "1", "value": 2.0},
                {"success": True, "expression": "x", "value": 0.0467653718},
                {"success": True, "expression": "y", "value": 0.027},
                {"success": True, "expression": "z", "value": 0.0},
            ],
            rollers=(1, 2, 12),
        )

        assert row["success"] is True
        assert row["radius_mm"] == pytest.approx(27.0, rel=1.0e-5)
        assert row["angle_deg"] == pytest.approx(30.0, rel=1.0e-5)
        assert row["nearest_roller"]["roller"] == 2
        assert row["nearest_roller"]["abs_angle_delta_deg"] == pytest.approx(0.0, abs=1.0e-4)

        summary = demo._summarize_boundary_entity_map(
            selection_name="geom1_outer_ring_bnd",
            rows=[row],
            rollers=(1, 2, 12),
        )

        assert summary["success"] is True
        assert summary["successful_entity_count"] == 1
        assert summary["nearest_entity_by_roller"]["roller_2"]["entity"] == 9

    def test_3d_physical_contact_validation_requires_inner_ring_stress(self):
        from scripts import run_agent_3d_bearing_full_demo as demo

        failed = demo._build_3d_physical_contact_validation(
            solve={"success": False, "error": "nonlinear contact did not converge"},
            final_stage={
                "name": "single_roller_physical_displacement_preload",
                "contact_scope": "single_load_side_roller_inner_outer_raceway_true_contact_displacement_preload",
                "active_rollers": [1],
                "cage_contact_active": False,
                "temporary_active_roller_stabilization_active": False,
                "temporary_cage_stabilization_active": True,
            },
        )
        assert failed["success"] is False
        assert failed["quality_level"] == "not_physical_contact_validated"
        assert failed["inner_ring_max_von_mises_pa"] is None
        assert any("COMSOL solve did not converge" in error for error in failed["errors"])

        passed = demo._build_3d_physical_contact_validation(
            solve={"success": True},
            stress={"success": True, "statistics": {"max": 20.0}},
            inner_ring_stress={"success": True, "value": 12.0},
            displacement={"success": True, "statistics": {"max": 1e-8}},
            png_quality={"success": True},
            final_stage={
                "name": "single_roller_physical_displacement_preload",
                "contact_scope": "single_load_side_roller_inner_outer_raceway_true_contact_displacement_preload",
                "active_rollers": [1],
                "cage_contact_active": False,
                "temporary_active_roller_stabilization_active": False,
                "temporary_cage_stabilization_active": True,
            },
        )
        assert passed["success"] is True
        assert passed["quality_level"] == "raceway_contact_physics_smoke"
        assert passed["inner_ring_max_von_mises_pa"] == 12.0

        guided = demo._build_3d_physical_contact_validation(
            solve={"success": True},
            stress={"success": True, "statistics": {"max": 20.0}},
            inner_ring_stress={"success": True, "value": 12.0},
            displacement={"success": True, "statistics": {"max": 1e-8}},
            png_quality={"success": True},
            final_stage={
                "name": "raceway_contact_guided_probe_1n_boundary_load",
                "contact_scope": "all_12_rollers_inner_outer_raceway_true_contact_inner_bore_boundary_load_with_weak_inner_guidance",
                "active_rollers": list(range(1, 13)),
                "cage_contact_active": False,
                "temporary_active_roller_stabilization_active": False,
                "temporary_cage_stabilization_active": True,
                "weak_inner_guidance_active": True,
            },
        )
        assert guided["success"] is True
        assert guided["final_stage"]["weak_inner_guidance_active"] is True
        assert any("Weak inner-ring guidance" in warning for warning in guided["warnings"])

        retained_preload = demo._build_3d_physical_contact_validation(
            solve={"success": True},
            stress={"success": True, "statistics": {"max": 2.0e6}},
            inner_ring_stress={"success": True, "value": 1.0e6},
            displacement={"success": True, "statistics": {"max": 1e-6}},
            png_quality={"success": True},
            final_stage={
                "name": "continuous_boundary_load_high_ramp_retained_preload",
                "contact_scope": "all_12_rollers_inner_outer_raceway_true_contact_inner_bore_boundary_load_high_ramp_retained_preload",
                "active_rollers": list(range(1, 13)),
                "cage_contact_active": False,
                "temporary_active_roller_stabilization_active": False,
                "temporary_cage_stabilization_active": True,
                "inner_bore_load_active": True,
                "displacement_preload_active": True,
                "weak_inner_guidance_active": True,
                "load_application_fidelity": "inner_bore_boundary_load_high_ramp_with_retained_displacement_preload_and_weak_inner_guidance_not_design_gate",
            },
        )
        assert retained_preload["success"] is True
        assert retained_preload["quality_level"] == "raceway_contact_physics_smoke"
        assert retained_preload["final_stage"]["displacement_preload_active"] is True
        assert any("retained prescribed inner-bore displacement" in warning for warning in retained_preload["warnings"])

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
        assert injected["selection_plan"]["global_selections"]["inner_bore_load_surface"] == "sel_inner_bore_load_surface"
        assert injected["selection_plan"]["roller_contact_sets"][0]["risk_probe"] == "probe_roller_1_max_mises"
        assert injected["selection_binding_contract"]["kind"] == "bearing_3d_selection_binding_contract"
        assert len(injected["selection_binding_contract"]["entries"]) == 5 + 7 * VERIFIED_ROLLER_COUNT
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
                    "inner_bore_load_surface": "sel_inner_bore_load_surface",
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
        listed_names = {template["name"] for template in listed["templates"]}
        assert listed["count"] >= 2
        assert {"thermal_heat_transfer_seed", "pcb_thermal_plate_seed"}.issubset(listed_names)
        assert searched["success"] is True
        searched_names = {template["name"] for template in searched["templates"]}
        assert "thermal_heat_transfer_seed" in searched_names
        assert "Offline keyword search" in searched["note"]
        thermal_seed = next(template for template in listed["templates"] if template["name"] == "thermal_heat_transfer_seed")
        assert "power" in thermal_seed["params"]
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
        assert calls[2][0] == "execute"
        assert "model.param().set('power'" in calls[2][2]
        assert "geom('geom1').run()" in calls[2][2]
        assert result["parameter_override"]["success"] is True
        assert calls[3] == ("close", "template_smoke_model", False)
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
        assert calls[2][0] == "execute"
        assert "model.param().set('radial_load', '3000[N]')" in calls[2][2]
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
        for entity_id, entry in enumerate(entries, start=101):
            probe_lines.append(f"SEL|{entry['tag']}|{entry['entitydim']}|1|{entity_id}|")
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
        assert "thermal_heat_transfer_seed" in {template["name"] for template in search_payload["templates"]}


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

    def test_model_family_registry_infers_non_bearing_families(self):
        from comsol_agent.simulation.model_families import infer_model_family

        assert infer_model_family("偏心轴转速3000rpm，输出应力和位移").name == "eccentric_shaft"
        assert infer_model_family("齿轮副啮合接触压力和齿根应力").name == "gear_pair"
        assert infer_model_family("PCB FR4板和芯片功率热仿真").name == "pcb_thermal_electric"

    def test_bearing_family_registry_covers_p12_topologies(self):
        from comsol_agent.simulation.bearing_families import get_bearing_family, list_bearing_families

        names = {spec.name for spec in list_bearing_families()}

        assert {
            "deep_groove_ball",
            "angular_contact_ball",
            "cylindrical_roller",
            "tapered_roller",
            "needle_roller",
            "thrust_bearing",
            "general_bearing",
        }.issubset(names)
        tapered = get_bearing_family("tapered_roller")
        assert tapered.rolling_element == "tapered_roller"
        assert "combined_radial_axial" in tapered.load_modes
        assert "frictional" in tapered.contact_policies
        assert tapered.quality_gate

    def test_simulation_plan_bearing_modeling_request_routes_deep_groove_real_contact(self):
        from comsol_agent.tools.simulation import simulation_plan_bearing_modeling_request

        result = simulation_plan_bearing_modeling_request(
            user_request="做深沟球轴承，1000N，真实接触，输出应力和接触压力",
            allow_defaults=True,
        )

        assert result["success"] is True
        assert result["bearing_family"] == "deep_groove_ball"
        assert result["rolling_element"] == "ball"
        assert result["load_mode"] == "radial"
        assert result["resolved_executable_params"]["radial_load"] == "1000[N]"
        assert result["template_policy"]["smoke_templates"] == [
            "bearing_contact_pair_seed",
            "bearing_contact_hertz_seed",
        ]
        assert result["quality_contract"]["smoke_fidelity_must_be_labeled"] is True

    def test_simulation_plan_bearing_modeling_request_routes_cylindrical_roller_staged_cage(self):
        from comsol_agent.tools.simulation import simulation_plan_bearing_modeling_request

        result = simulation_plan_bearing_modeling_request(
            user_request="做圆柱滚子轴承，12个滚子，带保持架，滚道先接触后保持架接触，输出应力",
            allow_defaults=True,
        )

        assert result["success"] is True
        assert result["bearing_family"] == "cylindrical_roller"
        assert result["rolling_element"] == "cylindrical_roller"
        assert result["resolved_executable_params"]["roller_count"] == "12"
        assert result["contact_policy"] in {
            "staged_contact_activation",
            "cage_pocket_contact_load_transfer",
        }
        assert "bearing_3d_cylindrical_roller_legacy_raceway_highload_direct" in result["template_policy"]["family_starter_templates"]
        assert any("run_agent_3d_bearing_full_demo.py" in step for step in result["next_tool_chain"])

    def test_simulation_plan_bearing_modeling_request_recommends_highload_visual_stage(self):
        from comsol_agent.tools.simulation import simulation_plan_bearing_modeling_request

        result = simulation_plan_bearing_modeling_request(
            user_request="做12个滚子的圆柱滚子轴承高载荷应力图，要COMSOL原生图片",
            allow_defaults=True,
        )

        assert result["success"] is True
        assert result["bearing_family"] == "cylindrical_roller"
        assert "bearing_3d_cylindrical_roller_legacy_raceway_highload_direct" in result["template_policy"]["family_starter_templates"]
        assert any("legacy_raceway_highload_direct" in step for step in result["next_tool_chain"])
        assert "high_load_visual" in result["quality_contract"]["default_assumptions"]

    def test_simulation_plan_bearing_modeling_request_rejects_tapered_ball_template_substitution(self):
        from comsol_agent.tools.simulation import simulation_plan_bearing_modeling_request

        result = simulation_plan_bearing_modeling_request(
            user_request="做圆锥滚子轴承，轴向和径向联合载荷，输出接触压力和应力",
            known_params={"radial_load": "2000[N]", "axial_load": "800[N]"},
            allow_defaults=False,
        )

        assert result["success"] is True
        assert result["bearing_family"] == "tapered_roller"
        assert result["rolling_element"] == "tapered_roller"
        assert result["load_mode"] == "combined_radial_axial"
        assert result["template_policy"]["reject_deep_groove_substitution"] is True
        assert "bearing_contact_pair_seed" not in json.dumps(result["template_policy"], ensure_ascii=False)
        assert "declared_unsupported_fidelity" in result["template_policy"]

    def test_simulation_plan_bearing_modeling_request_routes_thrust_axial_load(self):
        from comsol_agent.tools.simulation import simulation_plan_bearing_modeling_request

        result = simulation_plan_bearing_modeling_request(
            user_request="做推力轴承，轴向载荷，输出应力和接触压力",
            known_params={"axial_load": "1500[N]"},
            allow_defaults=False,
        )

        assert result["success"] is True
        assert result["bearing_family"] == "thrust_bearing"
        assert result["load_mode"] == "axial"
        assert result["template_policy"]["reject_deep_groove_substitution"] is True
        assert "bearing_contact_pair_seed" not in json.dumps(result["next_tool_chain"], ensure_ascii=False)

    def test_simulation_plan_bearing_modeling_request_distinguishes_contact_policy(self):
        from comsol_agent.tools.simulation import simulation_plan_bearing_modeling_request

        frictional = simulation_plan_bearing_modeling_request(
            user_request="做深沟球轴承摩擦接触，输出应力",
            allow_defaults=True,
        )
        frictionless = simulation_plan_bearing_modeling_request(
            user_request="做深沟球轴承无摩擦接触，输出应力",
            allow_defaults=True,
        )

        assert frictional["contact_policy"] == "frictional"
        assert frictionless["contact_policy"] == "frictionless"
        assert frictional["contact_policy"] != frictionless["contact_policy"]

    def test_bearing_modeling_request_keeps_intent_out_of_executable_params(self):
        from comsol_agent.tools.simulation import simulation_plan_bearing_modeling_request

        result = simulation_plan_bearing_modeling_request(
            user_request="做圆锥滚子轴承，带保持架，真实接触，输出应力",
            known_params={
                "bearing_type": "圆锥滚子轴承",
                "cage_included": "true",
                "contact_policy": "真实接触",
                "radial_load": "1000[N]",
            },
            allow_defaults=True,
        )

        executable = result["resolved_executable_params"]
        assert executable == {"radial_load": "1000[N]"}
        assert "圆锥滚子轴承" not in json.dumps(executable, ensure_ascii=False)
        assert "真实接触" not in json.dumps(executable, ensure_ascii=False)

    def test_simulation_plan_modeling_request_routes_pcb_without_bearing_templates(self):
        from comsol_agent.tools.simulation import simulation_plan_modeling_request

        result = simulation_plan_modeling_request(
            user_request="做 PCB 热仿真，FR4，两个 5W 芯片，底面对流散热，输出温升云图",
            known_params={
                "geometry": "PCB rectangular FR4 board",
                "material": "FR4 and copper",
                "boundary_conditions": "bottom convection",
                "load_conditions": "two 5[W] chips",
                "outputs": "maximum temperature and temperature plot",
                "executable_params": {"chip_power": "5[W]", "convection_h": "10[W/m^2/K]"},
            },
            allow_defaults=True,
        )

        assert result["success"] is True
        assert result["model_family"] == "pcb_thermal_electric"
        assert result["domain"] == "thermal"
        assert result["ready_to_generate"] is True
        assert result["known_params"] == {"chip_power": "5[W]", "convection_h": "10[W/m^2/K]"}
        assert result["template_policy"]["reject_unrelated_bearing_templates"] is True
        assert result["quality_contract"]["quality_gate"] == "validate_pcb_thermal_electric_code_draft"
        assert "simulation_plan_bearing_contact" not in result["next_tool_chain"]

    def test_pcb_thermal_plate_seed_is_registered_and_validates(self, tmp_path):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.simulation.skills import seed_builtin_templates
        from comsol_agent.tools.simulation import simulation_validate_template

        archive_path = tmp_path / "archive.sqlite3"
        archive = ArchiveStore(archive_path)
        templates = seed_builtin_templates(archive)
        names = {template.name for template in templates}

        assert "pcb_thermal_plate_seed" in names
        template = archive.get_template("pcb_thermal_plate_seed")
        assert template.domain == "thermal"
        assert template.params["board_length"] == "80[mm]"
        assert template.params["chip1_power"] == "5[W]"
        assert template.params["chip2_power"] == "5[W]"
        assert template.params["convection_h"] == "10[W/(m^2*K)]"

        result = simulation_validate_template(
            name="pcb_thermal_plate_seed",
            archive_path=str(archive_path),
        )

        assert result["success"] is True
        assert result["validation"]["errors"] == []

    def test_pcb_thermal_plate_seed_contains_engineering_pure_thermal_content(self):
        from comsol_agent.simulation.skills import get_skill

        skill = get_skill("pcb_thermal")
        code = skill.template_java_code.lower()

        assert skill.template_name == "pcb_thermal_plate_seed"
        assert "fr4 substrate" in code
        assert "copper_top" in code
        assert "copper_bottom" in code
        assert "chip1_pkg" in code
        assert "chip2_pkg" in code
        assert "heattransfer" in code
        assert "heatsource" in code
        assert "convectiveheatflux" in code
        assert "stationary" in code
        assert "pg_temperature" in code
        assert "max_board_temperature" in code
        assert "chip_hotspot_indicator" in code
        assert "selection().create('sel_chip1_pkg', 'box')" in code
        assert "selection().create('sel_copper_layers', 'union')" in code
        assert "selection().named('sel_chip1_pkg')" in code
        assert "cpl().create('maxop1', 'maximum')" in code
        assert "feature('conv_bottom').selection().named('sel_conv_bottom')" in code
        assert "feature('chip1_heat').selection().all()" not in code

    def test_simulation_plan_modeling_request_recommends_pcb_thermal_plate_seed(self, tmp_path):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.simulation.skills import seed_builtin_templates
        from comsol_agent.tools.simulation import simulation_plan_modeling_request

        archive_path = tmp_path / "archive.sqlite3"
        seed_builtin_templates(ArchiveStore(archive_path))

        result = simulation_plan_modeling_request(
            user_request="做 PCB 热仿真，FR4，两个 5W 芯片，底面对流散热",
            known_params={
                "geometry": "FR4 PCB with two chip packages and top/bottom copper layers",
                "material": "FR4, copper, and chip package thermal material",
                "boundary_conditions": "bottom and outside convection cooling",
                "load_conditions": "chip1_power=5[W], chip2_power=5[W]",
                "outputs": "temperature field and hotspot temperature",
                "executable_params": {"chip1_power": "5[W]", "chip2_power": "5[W]"},
            },
            allow_defaults=True,
            archive_path=str(archive_path),
        )

        candidate_names = {candidate["name"] for candidate in result["template_policy"]["candidates"]}

        assert result["success"] is True
        assert result["model_family"] == "pcb_thermal_electric"
        assert result["domain"] == "thermal"
        assert result["template_policy"]["use_template_if_fit"] is True
        assert "pcb_thermal_plate_seed" in result["template_policy"]["family_starter_templates"]
        assert "pcb_thermal_plate_seed" in candidate_names
        assert "bearing_contact_pair_seed" not in json.dumps(result["template_policy"], ensure_ascii=False)
        assert "simulation_plan_bearing_contact" not in result["next_tool_chain"]
        assert result["known_params"] == {"chip1_power": "5[W]", "chip2_power": "5[W]"}

    def test_model_family_registry_covers_p11_mvp_families(self):
        from comsol_agent.simulation.model_families import get_model_family, list_model_families

        names = {spec.name for spec in list_model_families()}

        assert {
            "bearing_contact",
            "eccentric_shaft",
            "gear_pair",
            "pcb_thermal_electric",
            "general",
        }.issubset(names)
        assert get_model_family("gear_pair").quality_gate == "validate_gear_pair_code_draft"
        assert get_model_family("pcb_thermal_electric").output_expressions
        assert get_model_family("pcb_thermal_electric").starter_templates == ("pcb_thermal_plate_seed",)
        assert "chip_hotspot_indicator" in get_model_family("pcb_thermal_electric").output_expressions

    def test_requirement_state_modeling_request_keeps_intent_out_of_executable_params(self):
        from comsol_agent.memory.requirements import RequirementState

        state = RequirementState()
        state.observe_user_message("做 PCB 热仿真，FR4，两个 5W 芯片，底面对流散热，输出温升")
        modeling_request = state.to_modeling_request()

        assert "pcb" in modeling_request.intent_slots["geometry"].lower()
        assert "fr4" in modeling_request.intent_slots["material"].lower()
        assert "geometry" not in modeling_request.executable_params
        assert "做 PCB" not in json.dumps(modeling_request.executable_params, ensure_ascii=False)

    def test_simulation_plan_modeling_request_routes_eccentric_shaft_without_bearing_template(self, tmp_path):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.tools.simulation import simulation_plan_modeling_request

        archive_path = tmp_path / "archive.sqlite3"
        ArchiveStore(archive_path).add_template(
            name="bearing_contact_pair_seed",
            domain="structural",
            java_code="model.param().set('radial_load', '1000[N]');",
            params={"radial_load": "1000[N]"},
        )

        result = simulation_plan_modeling_request(
            user_request="做一个偏心轴，钢材，3000 rpm，输出应力和位移",
            known_params={"rpm": "3000[1/min]"},
            allow_defaults=True,
            archive_path=str(archive_path),
        )

        assert result["success"] is True
        assert result["model_family"] == "eccentric_shaft"
        assert result["domain"] == "structural"
        assert result["ready_to_generate"] is True
        assert result["template_policy"]["reject_unrelated_bearing_templates"] is True
        assert result["template_policy"]["candidates"] == []
        assert "bearing_contact_pair_seed" not in json.dumps(result["next_tool_chain"], ensure_ascii=False)

    def test_simulation_plan_modeling_request_routes_gear_pair_without_bearing_contact_pair_seed(self, tmp_path):
        from comsol_agent.memory.archive_store import ArchiveStore
        from comsol_agent.tools.simulation import simulation_plan_modeling_request

        archive_path = tmp_path / "archive.sqlite3"
        ArchiveStore(archive_path).add_template(
            name="bearing_contact_pair_seed",
            domain="structural",
            java_code="model.param().set('radial_load', '1000[N]');",
            params={"radial_load": "1000[N]"},
        )

        result = simulation_plan_modeling_request(
            user_request="做简化齿轮副接触模型，给定扭矩，输出齿根应力和接触压力",
            known_params={"torque": "20[N*m]"},
            allow_defaults=True,
            archive_path=str(archive_path),
        )

        assert result["success"] is True
        assert result["model_family"] == "gear_pair"
        assert result["domain"] == "structural"
        assert result["template_policy"]["candidate_count"] == 0
        assert "bearing_contact_pair_seed" not in json.dumps(result["template_policy"], ensure_ascii=False)

    def test_simulation_plan_modeling_request_keeps_bearing_path(self):
        from comsol_agent.tools.simulation import simulation_plan_modeling_request

        result = simulation_plan_modeling_request(
            user_request="做一个轴承接触模型",
            allow_defaults=True,
        )

        assert result["success"] is True
        assert result["model_family"] == "bearing_contact"
        assert result["template_policy"]["family_starter_templates"] == [
            "bearing_contact_pair_seed",
            "bearing_contact_hertz_seed",
        ]
        assert "simulation_plan_bearing_contact" in result["next_tool_chain"]
        assert result["quality_contract"]["preserve_family_specific_checks"] is True

    def test_pcb_thermal_smoke_skip_comsol_writes_artifacts(self, tmp_path):
        from scripts.run_pcb_thermal_template_smoke import parse_args, run_smoke

        artifact_dir = tmp_path / "pcb_artifacts"
        archive_path = tmp_path / "pcb.sqlite3"
        args = parse_args(
            [
                "--skip-comsol",
                "--archive-path",
                str(archive_path),
                "--artifact-dir",
                str(artifact_dir),
                "--model-name",
                "pcb_unit_smoke",
            ]
        )

        result = run_smoke(args)

        assert result["success"] is True
        assert result["template_name"] == "pcb_thermal_plate_seed"
        assert result["stage"] == "offline_validate"
        assert result["validation"]["validation"]["errors"] == []
        assert Path(result["summary_json_path"]).exists()
        assert Path(result["report_markdown_path"]).exists()
        assert Path(result["manifest_path"]).exists()

    def test_pcb_thermal_smoke_audit_parser_checks_required_nodes(self):
        from scripts.run_pcb_thermal_template_smoke import (
            check_pcb_runtime_audit,
            parse_audit_stdout,
        )

        lines = []
        for kind, tags in {
            "component": ["comp1"],
            "geometry": ["geom1"],
            "geometry_feature": ["fr4_board", "copper_top", "copper_bottom", "chip1_pkg", "chip2_pkg"],
            "material": ["mat_fr4", "mat_copper", "mat_chip"],
            "physics": ["ht"],
            "physics_feature": ["chip1_heat", "chip2_heat", "conv_bottom", "conv_sides", "conv_chip_tops"],
            "mesh": ["mesh1"],
            "study": ["std1"],
            "study_feature": ["stat"],
            "result": ["pg_temperature"],
            "numerical": ["max_board_temperature", "chip_hotspot_indicator"],
            "coupling": ["maxop1"],
            "selection": [
                "sel_fr4_board",
                "sel_copper_layers",
                "sel_chip1_pkg",
                "sel_chip2_pkg",
                "sel_conv_bottom",
                "sel_conv_sides",
                "sel_conv_chip_tops",
            ],
        }.items():
            for tag in tags:
                lines.append(f"AUDIT|{kind}|{tag}|1|")

        audit = parse_audit_stdout("\n".join(lines))
        audit["success"] = True
        check = check_pcb_runtime_audit(audit)

        assert check["success"] is True
        assert check["counts"]["component_count"] == 1
        assert check["counts"]["physics_count"] == 1
        assert check["counts"]["selection_count"] >= 7

    def test_simulation_plan_modeling_request_asks_followups_when_defaults_disallowed(self):
        from comsol_agent.tools.simulation import simulation_plan_modeling_request

        result = simulation_plan_modeling_request(
            user_request="帮我做一个新的仿真模型",
            allow_defaults=False,
        )

        assert result["success"] is True
        assert result["model_family"] == "general"
        assert result["ready_to_generate"] is False
        assert result["missing_decisions"]
        assert result["follow_up_questions"]
        assert result["next_tool_chain"][0] == "ask_follow_up_questions"

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

    def test_comsol_solve_handles_unprintable_runtime_exception(self):
        from comsol_agent.tools.comsol.client import COMSOLClient, ModelHandle
        from comsol_agent.tools.comsol.solve import comsol_solve

        class UnprintableRuntimeError(Exception):
            def __str__(self):
                raise RuntimeError("JVM is not running")

        class FakeMPhModel:
            def solve(self, *args):
                raise UnprintableRuntimeError()

        COMSOLClient.reset_instance()
        client = COMSOLClient.get_instance()
        client._started = True
        client._mph_client = object()
        client._models["fake"] = ModelHandle(name="fake", mph_model=FakeMPhModel())

        result = comsol_solve("fake")

        assert result["success"] is False
        assert "Solve failed: UnprintableRuntimeError" in result["error"]
        assert "exception stringification failed" in result["error"]
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

    def test_png_quality_gate_rejects_blank_single_color_png(self, tmp_path):
        import binascii
        import struct
        import zlib

        from comsol_agent.tools.comsol.evaluate import inspect_png_quality

        def chunk(kind: bytes, data: bytes) -> bytes:
            payload = kind + data
            return struct.pack(">I", len(data)) + payload + struct.pack(">I", binascii.crc32(payload) & 0xFFFFFFFF)

        path = tmp_path / "blank.png"
        width, height = 4, 4
        row = b"\x00" + bytes([12, 34, 56]) * width
        raw = row * height
        png = bytearray(b"\x89PNG\r\n\x1a\n")
        png.extend(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        png.extend(chunk(b"IDAT", zlib.compress(raw)))
        png.extend(chunk(b"IEND", b""))
        path.write_bytes(bytes(png))

        result = inspect_png_quality(path)

        assert result["success"] is False
        assert "single-color" in result["error"]

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
