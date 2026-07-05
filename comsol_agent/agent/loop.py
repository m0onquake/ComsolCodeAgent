"""Agent main loop — orchestrates the conversation between user, LLM, and tools.

This is the heart of the COMSOL Agent. Each user turn may involve multiple
LLM↔Tool roundtrips before returning a final response.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from comsol_agent.agent.prompt import build_system_prompt
from comsol_agent.agent.tool_registry import (
    get_tool_definitions,
    get_tool_handler,
    validate_tool_arguments,
)
from comsol_agent.cli.config import Config
from comsol_agent.llm.base import LLMProvider, LLMResponse, ToolCall, ToolResult
from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.memory.compaction import compact_messages
from comsol_agent.memory.retrieval import build_memory_context_message, retrieve_memories
from comsol_agent.memory.requirements import RequirementState
from comsol_agent.memory.session_store import SessionStore
from comsol_agent.repair.analyzer import build_diagnosis_prompt, suggest_diagnosis
from comsol_agent.repair.detector import detect_tool_error, format_repair_notice
from comsol_agent.repair.fixer import build_fix_prompt
from comsol_agent.repair.planner import format_repair_plan_message, plan_repair_action
from comsol_agent.simulation.local_docs import build_index_from_directory
from comsol_agent.simulation.skills import build_skill_context_message, match_skills
from comsol_agent.utils.logger import log
from comsol_agent.utils.token_counter import estimate_messages_tokens


def _is_authentication_error(exc: Exception) -> bool:
    """Best-effort auth error detection across LLM SDKs."""
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    auth_markers = ("auth", "unauthorized", "permission", "api key", "apikey")
    return any(marker in name or marker in message for marker in auth_markers)


def _tool_call_signature(tool_call: ToolCall) -> str:
    """Return a stable signature for repeated failed-tool-call detection."""
    try:
        arguments = json.dumps(tool_call.arguments or {}, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        arguments = str(tool_call.arguments)
    return f"{tool_call.name}:{arguments}"


@dataclass
class ConversationTurn:
    """Records a single turn in the conversation history."""

    role: str  # 'user', 'assistant', 'tool'
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    token_count: int = 0


@dataclass
class AgentState:
    """Mutable state for the agent session."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    turns: list[ConversationTurn] = field(default_factory=list)
    requirement_state: RequirementState = field(default_factory=RequirementState)
    repair_reports: list[dict[str, Any]] = field(default_factory=list)
    total_tokens_used: int = 0
    tool_iterations_this_turn: int = 0


class AgentLoop:
    """Main agent loop that processes user input and orchestrates tool calls.

    Usage:
        config = load_config()
        provider = create_provider(config.llm.provider, ...)
        agent = AgentLoop(provider, config)
        response = await agent.run("Load model.mph and solve")
    """

    DEFAULT_MAX_TOOL_ITERATIONS = 50

    def __init__(
        self,
        llm_provider: LLMProvider,
        config: Config,
        on_tool_call: Callable[[str, dict], None] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
        session_store: SessionStore | None = None,
        archive_store: ArchiveStore | None = None,
    ):
        """
        Args:
            llm_provider: The LLM provider to use.
            config: Agent configuration.
            on_tool_call: Callback for tool execution events.
            on_text_chunk: Callback for streaming text chunks.
            on_thinking: Callback for thinking/reasoning events.
        """
        self.llm = llm_provider
        self.config = config
        self.state = AgentState()
        self.on_tool_call = on_tool_call
        self.on_text_chunk = on_text_chunk
        self.on_thinking = on_thinking
        self.session_store = session_store
        self.archive_store = archive_store
        self.max_tool_iterations = max(
            1,
            int(getattr(config.agent, "max_tool_iterations", self.DEFAULT_MAX_TOOL_ITERATIONS)),
        )
        self.llm_max_retries = max(1, int(getattr(config.agent, "llm_max_retries", 3)))

        # Background context that persists
        self.extra_context: str | None = None
        self.simulation_domain: str | None = None

        # Initialize system message
        self._init_system_message()

    def _init_system_message(self) -> None:
        """Build and set the system message."""
        system_prompt = build_system_prompt(
            extra_context=self.extra_context,
            simulation_domain=self.simulation_domain,
        )
        self.state.messages.append({"role": "system", "content": system_prompt})

    def reset(self) -> None:
        """Reset the conversation (clear history, keep system message)."""
        self.state = AgentState()
        self._init_system_message()
        self._save_session_snapshot(event="reset")

    async def run(self, user_input: str) -> str:
        """Process a user message and return the agent's final response.

        Args:
            user_input: The user's natural language input.

        Returns:
            The agent's final text response.
        """
        # Add user message
        self._append_message({"role": "user", "content": user_input})
        self.state.requirement_state.observe_user_message(user_input)
        self._inject_retrieved_memory(user_input)
        self._inject_skill_context(user_input)
        self.state.tool_iterations_this_turn = 0

        log.info(f"Processing user input ({len(user_input)} chars)")

        final_response = ""
        repeated_failed_tool_calls: dict[str, int] = {}

        for iteration in range(self.max_tool_iterations):
            self.state.tool_iterations_this_turn = iteration + 1

            # Check token usage and trigger compaction if needed
            await self._maybe_compact()

            # Build tools list
            tools = get_tool_definitions()

            # Get LLM response
            log.info(f"Agent iteration {iteration + 1} (tokens: ~{estimate_messages_tokens(self.state.messages)})")

            response = await self._generate_with_retry(
                messages=self.state.messages,
                tools=tools,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
            )

            # Track usage
            if response.usage:
                self.state.total_tokens_used += response.usage.get("total_tokens", 0)

            # If text response (no tool calls), we're done
            if response.is_text:
                final_response = response.text or ""
                self._append_message({
                    "role": "assistant",
                    "content": final_response,
                })
                break

            # Process tool calls
            if response.is_tool_calls:
                stop_after_tool_batch = False
                # Record assistant message with tool calls
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": response.text or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in response.tool_calls
                    ],
                }
                self._append_message(assistant_msg)

                # Execute each tool call
                for tc in response.tool_calls:
                    tool_result = await self._execute_tool(tc)
                    if tool_result.is_error:
                        signature = _tool_call_signature(tc)
                        repeated_failed_tool_calls[signature] = repeated_failed_tool_calls.get(signature, 0) + 1
                        if repeated_failed_tool_calls[signature] >= 3:
                            final_response = (
                                "Stopped after the same tool call failed repeatedly. "
                                f"Tool `{tc.name}` was called with the same arguments "
                                f"{repeated_failed_tool_calls[signature]} times; inspect the last tool error before retrying."
                            )
                            stop_after_tool_batch = True
                    self._append_message({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": tool_result.output,
                    })

                    if tool_result.is_error and self.config.agent.auto_repair:
                        self._record_repair_detection(tc, tool_result)
                if stop_after_tool_batch:
                    self._append_message({
                        "role": "assistant",
                        "content": final_response,
                    })
                    break

            # Safety: if we hit the max iterations, force a final response
            if iteration >= self.max_tool_iterations - 1:
                log.warning(
                    f"Hit max tool iterations ({self.max_tool_iterations}). Requesting summary."
                )
                final_response = await self._force_final_response()
                break

        if not final_response:
            final_response = "I've completed the requested operations."

        self._save_session_snapshot(event="turn_completed")
        return final_response

    async def _execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single tool call and return the result."""
        tool_call = self._prepare_tool_call(tool_call)
        handler = get_tool_handler(tool_call.name)

        if handler is None:
            error_msg = f"Unknown tool: {tool_call.name}"
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=json.dumps({"success": False, "error": error_msg}),
                is_error=True,
            )

        validation_errors = validate_tool_arguments(tool_call.name, tool_call.arguments)
        if validation_errors:
            error_msg = "; ".join(validation_errors)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=json.dumps({"success": False, "error": error_msg}),
                is_error=True,
            )

        if self.on_tool_call:
            self.on_tool_call(tool_call.name, tool_call.arguments)

        try:
            result = await handler(**tool_call.arguments)
            output = json.dumps(result, ensure_ascii=False, default=str)
            is_error = isinstance(result, dict) and not result.get("success", True)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=output,
                is_error=is_error,
            )
        except Exception as e:
            log.error(f"Tool {tool_call.name} raised exception: {e}")
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=json.dumps({"success": False, "error": str(e)}),
                is_error=True,
            )

    def _prepare_tool_call(self, tool_call: ToolCall) -> ToolCall:
        """Inject deterministic requirement memory into selected tool calls."""
        if tool_call.name not in {"simulation_plan_generated_code", "simulation_plan_modeling_request"}:
            return tool_call

        arguments = dict(tool_call.arguments or {})
        known_params = arguments.get("known_params")
        if known_params is not None and not isinstance(known_params, dict):
            return tool_call

        if tool_call.name == "simulation_plan_modeling_request":
            memory_params = self.state.requirement_state.to_modeling_request().executable_params
            merged_params = dict(memory_params)
            for key, value in (known_params or {}).items():
                if value in (None, ""):
                    continue
                merged_params[str(key).strip()] = str(value).strip()
        else:
            merged_params = self.state.requirement_state.merge_known_params(known_params)
        if merged_params:
            arguments["known_params"] = merged_params

        return ToolCall(id=tool_call.id, name=tool_call.name, arguments=arguments)

    async def _maybe_compact(self) -> None:
        """Check if context compaction is needed and perform it."""
        tokens = estimate_messages_tokens(self.state.messages, self.config.llm.model)
        max_context = max(1, int(self.config.memory.context_window_tokens))

        if tokens > int(max_context * self.config.memory.compaction_threshold):
            log.info(f"Context compaction triggered ({tokens}/{max_context} tokens)")
            result = self.compact_context(manual=False)
            if not result["changed"] and tokens > max_context * 0.95:
                log.warning("Context nearly full; deterministic compaction could not reduce it.")

    async def _force_final_response(self) -> str:
        """Force the LLM to provide a final text summary."""
        self._append_message({
            "role": "user",
            "content": "You've reached the maximum number of tool calls for this turn. "
                       "Please provide a final summary of what you've accomplished and what remains.",
        })
        response = await self._generate_with_retry(
            messages=self.state.messages,
            tools=None,  # No tools — force text response
        )
        text = response.text or "Operation completed (summary unavailable)."
        self._append_message({"role": "assistant", "content": text})
        return text

    async def _generate_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Call the LLM provider with exponential backoff for transient failures."""
        last_error: Exception | None = None
        for attempt in range(self.llm_max_retries):
            try:
                return await self.llm.generate(messages=messages, tools=tools, **kwargs)
            except Exception as exc:
                if _is_authentication_error(exc):
                    raise

                last_error = exc
                if attempt >= self.llm_max_retries - 1:
                    break

                wait_seconds = 2 ** attempt
                log.warning(
                    "LLM call failed on attempt %s/%s: %s. Retrying in %ss.",
                    attempt + 1,
                    self.llm_max_retries,
                    exc,
                    wait_seconds,
                )
                await asyncio.sleep(wait_seconds)

        assert last_error is not None
        raise RuntimeError(
            f"LLM API call failed after {self.llm_max_retries} attempts: {last_error}"
        ) from last_error

    def get_conversation_summary(self) -> str:
        """Get a summary of the current conversation for display."""
        num_turns = len([m for m in self.state.messages if m["role"] == "user"])
        tokens = estimate_messages_tokens(self.state.messages, self.config.llm.model)
        return (
            f"Conversation: {num_turns} turns | "
            f"~{tokens:,} tokens | "
            f"{len(get_tool_definitions())} tools available"
        )

    def compact_context(self, manual: bool = False) -> dict[str, Any]:
        """Compact older context and return compaction statistics."""
        result = compact_messages(
            self.state.messages,
            model=self.config.llm.model,
            recency_zone_tokens=self.config.memory.recency_zone_tokens,
        )
        if result.changed:
            self.state.messages = result.messages
            self._save_session_snapshot(
                event="manual_compact" if manual else "auto_compact",
                extra_metadata={
                    "compaction_summary": result.summary,
                    "original_tokens": result.original_tokens,
                    "compacted_tokens": result.compacted_tokens,
                    "compressed_message_count": result.compressed_message_count,
                    "preserved_user_count": result.preserved_user_count,
                },
            )

        return {
            "changed": result.changed,
            "original_tokens": result.original_tokens,
            "compacted_tokens": result.compacted_tokens,
            "compressed_message_count": result.compressed_message_count,
            "preserved_user_count": result.preserved_user_count,
        }

    def _append_message(self, message: dict[str, Any]) -> None:
        """Append a raw message and mirror it into structured turn history."""
        self.state.messages.append(message)
        if message.get("role") == "system":
            return

        self.state.turns.append(
            ConversationTurn(
                role=message.get("role", ""),
                content=message.get("content"),
                tool_calls=message.get("tool_calls"),
                tool_call_id=message.get("tool_call_id"),
                tool_name=message.get("name"),
                token_count=estimate_messages_tokens([message], self.config.llm.model),
            )
        )

    def _inject_retrieved_memory(self, query: str) -> None:
        """Inject relevant archived memories for the current turn."""
        if self.archive_store is None:
            return

        try:
            memories = retrieve_memories(self.archive_store, query, limit=5)
            message = build_memory_context_message(memories)
            if message is not None:
                self._append_message(message)
        except Exception as exc:
            log.warning("Failed to retrieve memory context: %s", exc)

    def _inject_skill_context(self, query: str) -> None:
        """Inject local domain skill hints for the current turn."""
        try:
            message = build_skill_context_message(match_skills(query))
            if message is not None:
                self._append_message(message)
        except Exception as exc:
            log.warning("Failed to build skill context: %s", exc)

    def _record_repair_detection(self, tool_call: ToolCall, tool_result: ToolResult) -> None:
        """Run the deterministic detector for a failed tool call."""
        report = detect_tool_error(
            tool_name=tool_call.name,
            tool_output=tool_result.output,
            arguments=tool_call.arguments,
            context_messages=self.state.messages,
        )
        retrieved_docs = self._retrieve_repair_docs(report.message, report.code_snippet)
        diagnosis = suggest_diagnosis(report)
        repair_plan = plan_repair_action(report, diagnosis)
        report_dict = report.to_dict()
        report_dict["retrieved_docs"] = retrieved_docs
        report_dict["diagnosis_prompt"] = build_diagnosis_prompt(
            report,
            retrieved_docs=retrieved_docs,
            conversation_context=self._recent_text_context(),
        )
        report_dict["diagnosis"] = diagnosis.to_dict()
        report_dict["repair_plan"] = repair_plan.to_dict()
        if report.code_snippet:
            report_dict["fix_prompt"] = build_fix_prompt(
                original_code=report.code_snippet,
                diagnosis=diagnosis,
            )
        else:
            report_dict["fix_prompt"] = None
        report_dict["validation"] = {
            "requires_candidate_code": True,
            "requires_runtime": True,
            "details": "Repair generation needs an LLM-produced code candidate; validation needs runtime tool/COMSOL execution.",
        }
        self.state.repair_reports.append(report_dict)
        notice = (
            format_repair_notice(report)
            + "\n\nFallback diagnosis:\n"
            + f"Root cause: {diagnosis.root_cause}\n"
            + f"Fix strategy: {diagnosis.fix_strategy}"
            + "\n\n"
            + format_repair_plan_message(repair_plan)
        )
        self._append_message(
            {
                "role": "user",
                "content": notice,
            }
        )
        log.warning(
            "Tool %s returned %s: %s",
            tool_call.name,
            report.error_type.value,
            report.message[:200],
        )

    def _retrieve_repair_docs(self, message: str, code_snippet: str | None) -> list[str]:
        """Retrieve local docs for repair analysis without external embeddings."""
        docs_dir = Path.cwd() / "docs"
        if not docs_dir.exists():
            docs_dir = Path(__file__).resolve().parents[2] / "docs"
        if not docs_dir.exists():
            return []

        query = " ".join(part for part in (message, code_snippet or "") if part).strip()
        if not query:
            return []

        try:
            index = build_index_from_directory(docs_dir)
            snippets = index.retrieve_api_docs(query, limit=3, snippet_chars=1200)
        except Exception as exc:
            log.debug("Failed to retrieve local repair docs: %s", exc)
            return []

        docs: list[str] = []
        for snippet in snippets:
            docs.append(
                f"Source: {snippet['citation']}\n"
                f"Title: {snippet['title']}\n"
                f"Domain: {snippet.get('domain') or 'general'}\n"
                f"API symbols: {', '.join(snippet.get('api_symbols') or []) or '(none detected)'}\n"
                f"Matched terms: {', '.join(snippet.get('matched_terms') or [])}\n"
                f"{snippet['snippet']}"
            )
        return docs

    def _recent_text_context(self, *, limit: int = 6) -> str:
        """Return compact recent text context for repair prompt scaffolding."""
        lines: list[str] = []
        for message in self.state.messages[-limit:]:
            role = message.get("role", "unknown")
            content = message.get("content", "")
            if not content:
                continue
            text = str(content)
            if len(text) > 600:
                text = text[:597] + "..."
            lines.append(f"{role}: {text}")
        return "\n".join(lines) or "(No additional conversation context.)"

    def _save_session_snapshot(
        self,
        event: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist the current session state when a store is configured."""
        if self.session_store is None:
            return

        try:
            metadata = {"event": event}
            if extra_metadata:
                metadata.update(extra_metadata)
            self.session_store.save(
                state=self.state,
                provider=self.config.llm.provider,
                model=self.config.llm.model,
                metadata=metadata,
            )
        except Exception as exc:
            log.warning("Failed to save session snapshot: %s", exc)
