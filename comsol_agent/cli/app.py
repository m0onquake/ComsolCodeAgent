"""Main CLI application — the REPL (Read-Eval-Print Loop).

This is the primary user interface. It handles:
- Interactive input (via prompt_toolkit)
- Slash command dispatch
- Agent loop invocation
- Rich output rendering
"""

from __future__ import annotations

import sys
from pathlib import Path

from comsol_agent.agent.loop import AgentLoop
from comsol_agent.agent.tools_bootstrap import register_all_tools
from comsol_agent.cli.commands import CommandResult, handle_command
from comsol_agent.cli.config import Config, load_config
from comsol_agent.cli.renderer import (
    console,
    render_agent_response,
    render_error,
    render_goodbye,
    render_info,
    render_status_bar,
    render_tool_call,
    render_tool_result,
    render_warning,
    render_welcome,
    show_header,
)
from comsol_agent.llm.router import create_provider_from_plan, plan_route
from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.memory.session_store import SessionStore
from comsol_agent.simulation.skills import seed_builtin_templates
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.utils.logger import log, setup_logger
from comsol_agent.utils.token_counter import estimate_messages_tokens


class CLIApp:
    """Main CLI application for the COMSOL Agent."""

    def __init__(self, config: Config | None = None):
        self.config = config or load_config()
        self.agent: AgentLoop | None = None
        self._running = False

        # Setup logging
        log_dir = Path.home() / ".comsol_agent" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        setup_logger(log_file=log_dir / "agent.log")

    async def start(self) -> None:
        """Start the CLI application: init providers, register tools, show UI."""
        register_all_tools()

        # Create LLM provider
        try:
            route_plan = plan_route(
                "text_response",
                preferred_provider=self.config.llm.provider,
                preferred_model=self.config.llm.model,
            )
            provider = create_provider_from_plan(
                route_plan,
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.base_url,
            )
        except ValueError as e:
            render_error(str(e))
            render_info(
                "Set your API key:\n"
                "  export OPENAI_API_KEY='sk-...'  (for OpenAI)\n"
                "  export ANTHROPIC_API_KEY='sk-ant-...'  (for Anthropic)\n"
                "  export DEEPSEEK_API_KEY='sk-...'  (for DeepSeek)\n"
                "Or create ~/.comsol_agent/config.yaml with provider settings."
            )
            return

        # Create agent
        app_dir = Path.home() / ".comsol_agent"
        archive_store = ArchiveStore(app_dir / "archive" / "archive.sqlite3")
        seed_builtin_templates(archive_store)
        session_store = SessionStore(
            app_dir / "sessions",
            archive_store=archive_store,
        )
        self.agent = AgentLoop(
            llm_provider=provider,
            config=self.config,
            on_tool_call=self._on_tool_call,
            session_store=session_store,
            archive_store=archive_store,
        )

        # Attempt COMSOL connection (non-blocking — fails gracefully)
        await self._try_start_comsol()

        # Show UI
        show_header(
            version="0.1.0",
            model=f"{self.config.llm.provider}/{self.config.llm.model}",
        )

        config_summary = (
            f"Provider: {self.config.llm.provider} | Model: {self.config.llm.model}"
        )
        render_welcome(config_summary)

        # Start REPL
        await self._repl()

    async def _repl(self) -> None:
        """Run the main Read-Eval-Print Loop."""
        self._running = True

        # Use prompt_toolkit for interactive input
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import FileHistory
            from prompt_toolkit.styles import Style

            history_path = Path.home() / ".comsol_agent" / ".history"
            history_path.parent.mkdir(parents=True, exist_ok=True)

            style = Style.from_dict({
                "prompt": "ansicyan bold",
            })

            session = PromptSession(
                history=FileHistory(str(history_path)),
                style=style,
            )

            while self._running:
                try:
                    user_input = await session.prompt_async(
                        [("class:prompt", "\n> ")],
                        multiline=False,
                    )
                except (EOFError, KeyboardInterrupt):
                    console.print()
                    self._running = False
                    break

                user_input = user_input.strip()
                if not user_input:
                    continue

                # Check for slash commands
                if user_input.startswith("/"):
                    result = await handle_command(user_input, self.agent, self.config)
                    if result == CommandResult.EXIT:
                        self._running = False
                    elif result == CommandResult.CLEAR:
                        continue
                    continue

                # Process through agent
                await self._process_input(user_input)

        except ImportError:
            # Fallback: simple input() loop without prompt_toolkit
            console.print("[dim]prompt-toolkit not available, using basic input.[/dim]")
            while self._running:
                try:
                    user_input = input("\n> ")
                except (EOFError, KeyboardInterrupt):
                    self._running = False
                    break

                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    result = await handle_command(user_input, self.agent, self.config)
                    if result == CommandResult.EXIT:
                        self._running = False
                    elif result == CommandResult.CLEAR:
                        continue
                    continue

                await self._process_input(user_input)

    async def _process_input(self, user_input: str) -> None:
        """Process a single user message through the agent.

        Args:
            user_input: The user's text input.
        """
        try:
            response = await self.agent.run(user_input)
            render_agent_response(response)
        except Exception as e:
            log.error(f"Agent error: {e}", exc_info=True)
            render_error(f"Agent encountered an error: {e}")

        # Show status bar
        if self.config.ui.show_token_usage:
            tokens = estimate_messages_tokens(
                self.agent.state.messages, self.config.llm.model
            )
            render_status_bar(
                token_count=tokens,
                tool_iterations=self.agent.state.tool_iterations_this_turn,
                total_turns=len(
                    [m for m in self.agent.state.messages if m["role"] == "user"]
                ),
            )

    def _on_tool_call(self, name: str, arguments: dict) -> None:
        """Callback when a tool is about to be executed."""
        # Filter out verbose arguments for display
        display_args = dict(arguments)
        for k in ("java_code", "content"):
            if k in display_args and isinstance(display_args[k], str):
                val = display_args[k]
                if len(val) > 50:
                    display_args[k] = val[:47] + "..."

        render_tool_call(name, display_args, status="running")

    async def _try_start_comsol(self) -> None:
        """Try to start the COMSOL session. Warn if it fails."""
        client = COMSOLClient.get_instance()
        if client.is_running:
            return

        try:
            kwargs = {}
            if self.config.comsol.version:
                kwargs["version"] = self.config.comsol.version
            if self.config.comsol.executable_path:
                kwargs["executable_path"] = self.config.comsol.executable_path
            client.start(**kwargs)
            render_info(
                f"COMSOL session started (version: {client._mph_client.version if client._mph_client else 'unknown'})"
            )
        except ImportError:
            render_warning(
                "MPh package not installed. COMSOL features unavailable.\n"
                "  Install: pip install MPh\n"
                "  COMSOL must be installed and licensed separately."
            )
        except Exception as e:
            render_warning(
                f"Could not start COMSOL session: {e}\n"
                "You can still chat, but simulation tools won't work.\n"
                "Configure COMSOL path in ~/.comsol_agent/config.yaml"
            )

    async def stop(self) -> None:
        """Gracefully stop the application."""
        self._running = False
        client = COMSOLClient.get_instance()
        if client.is_running:
            try:
                client.stop()
            except Exception:
                pass
        render_goodbye()
