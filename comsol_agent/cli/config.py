"""Configuration management for COMSOL Agent.

Reads from ~/.comsol_agent/config.yaml, with environment variable overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class LLMConfig:
    """LLM provider configuration."""

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = 8192
    temperature: float = 0.0


@dataclass
class COMSOLConfig:
    """COMSOL installation configuration."""

    # Path to comsol executable (e.g. /Applications/COMSOL62/Multiphysics/bin/comsol)
    executable_path: str | None = None
    # COMSOL version (e.g. "6.2")
    version: str | None = None


@dataclass
class AgentConfig:
    """Agent behavior configuration."""

    max_tool_iterations: int = 50
    llm_max_retries: int = 3
    auto_repair: bool = True
    max_repair_attempts: int = 3


@dataclass
class MemoryConfig:
    """Memory system configuration."""

    context_window_tokens: int = 180000
    core_memory_max_tokens: int = 500
    buffer_max_rounds: int = 20
    recency_zone_tokens: int = 8000
    compaction_threshold: float = 0.8  # 80% of context window
    archive_path: str | None = None  # Default: ~/.comsol_agent/archive


@dataclass
class UIConfig:
    """UI configuration."""

    show_token_usage: bool = True
    theme: str = "dark"


@dataclass
class Config:
    """Master configuration for COMSOL Agent."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    comsol: COMSOLConfig = field(default_factory=COMSOLConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    ui: UIConfig = field(default_factory=UIConfig)


def get_config_dir() -> Path:
    """Get the config directory (~/.comsol_agent)."""
    path = Path.home() / ".comsol_agent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_config_path() -> Path:
    """Get the config file path."""
    return get_config_dir() / "config.yaml"


def _apply_env_overrides(config: Config) -> Config:
    """Apply environment variable overrides to config."""
    if os.environ.get("OPENAI_API_KEY"):
        config.llm.provider = "openai"
        config.llm.api_key = os.environ["OPENAI_API_KEY"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        if config.llm.provider == "openai" and not config.llm.api_key:
            config.llm.provider = "anthropic"
        config.llm.api_key = config.llm.api_key or os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("DEEPSEEK_API_KEY"):
        if config.llm.provider == "openai" and not config.llm.api_key:
            config.llm.provider = "deepseek"
            config.llm.model = "deepseek-v4-flash"
        config.llm.api_key = config.llm.api_key or os.environ["DEEPSEEK_API_KEY"]
    if os.environ.get("COMSOL_AGENT_MODEL"):
        config.llm.model = os.environ["COMSOL_AGENT_MODEL"]
    if os.environ.get("COMSOL_AGENT_PROVIDER"):
        config.llm.provider = os.environ["COMSOL_AGENT_PROVIDER"]
    if os.environ.get("COMSOL_AGENT_BASE_URL"):
        config.llm.base_url = os.environ["COMSOL_AGENT_BASE_URL"]
    if os.environ.get("DEEPSEEK_BASE_URL") and config.llm.provider == "deepseek":
        config.llm.base_url = os.environ["DEEPSEEK_BASE_URL"]
    if os.environ.get("COMSOL_EXECUTABLE"):
        config.comsol.executable_path = os.environ["COMSOL_EXECUTABLE"]
    if os.environ.get("COMSOL_VERSION"):
        config.comsol.version = os.environ["COMSOL_VERSION"]
    return config


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from file and environment.

    Priority: env vars > config file > defaults
    """
    config = Config()
    path = config_path or get_config_path()

    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if "llm" in data:
            for k, v in data["llm"].items():
                if hasattr(config.llm, k):
                    setattr(config.llm, k, v)
        if "comsol" in data:
            for k, v in data["comsol"].items():
                if hasattr(config.comsol, k):
                    setattr(config.comsol, k, v)
        if "agent" in data:
            for k, v in data["agent"].items():
                if hasattr(config.agent, k):
                    setattr(config.agent, k, v)
        if "memory" in data:
            for k, v in data["memory"].items():
                if hasattr(config.memory, k):
                    setattr(config.memory, k, v)
        if "ui" in data:
            for k, v in data["ui"].items():
                if hasattr(config.ui, k):
                    setattr(config.ui, k, v)

    return _apply_env_overrides(config)


def save_config(config: Config, config_path: Path | None = None) -> None:
    """Save configuration to file."""
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "llm": {
            "provider": config.llm.provider,
            "model": config.llm.model,
            "base_url": config.llm.base_url,
            "max_tokens": config.llm.max_tokens,
            "temperature": config.llm.temperature,
        },
        "comsol": {
            "executable_path": config.comsol.executable_path,
            "version": config.comsol.version,
        },
        "agent": {
            "max_tool_iterations": config.agent.max_tool_iterations,
            "llm_max_retries": config.agent.llm_max_retries,
            "auto_repair": config.agent.auto_repair,
            "max_repair_attempts": config.agent.max_repair_attempts,
        },
        "memory": {
            "context_window_tokens": config.memory.context_window_tokens,
            "core_memory_max_tokens": config.memory.core_memory_max_tokens,
            "buffer_max_rounds": config.memory.buffer_max_rounds,
            "recency_zone_tokens": config.memory.recency_zone_tokens,
            "compaction_threshold": config.memory.compaction_threshold,
            "archive_path": config.memory.archive_path,
        },
        "ui": {
            "show_token_usage": config.ui.show_token_usage,
            "theme": config.ui.theme,
        },
    }
    # Don't save api_key to file — it's from env
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
