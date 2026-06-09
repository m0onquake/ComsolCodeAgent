"""LLM factory and router for selecting the appropriate provider."""

from __future__ import annotations

from dataclasses import dataclass

from .base import LLMProvider


ROUTING_RULES: dict[str, str] = {
    "code_generation": "strong_model",
    "code_repair": "strong_model",
    "text_response": "strong_model",
    "summarization": "fast_model",
    "error_classification": "medium_model",
    "memory_compaction": "fast_model",
}

FALLBACK_CHAIN: dict[str, list[str]] = {
    "openai": ["anthropic"],
    "anthropic": ["openai"],
    "deepseek": ["openai", "anthropic"],
}

DEFAULT_MODEL_TIERS: dict[str, dict[str, str]] = {
    "openai": {
        "strong_model": "gpt-4o",
        "medium_model": "gpt-4o-mini",
        "fast_model": "gpt-4o-mini",
    },
    "anthropic": {
        "strong_model": "claude-sonnet-4-20250514",
        "medium_model": "claude-3-5-haiku-20241022",
        "fast_model": "claude-3-5-haiku-20241022",
    },
    "deepseek": {
        "strong_model": "deepseek-v4-pro",
        "medium_model": "deepseek-v4-flash",
        "fast_model": "deepseek-v4-flash",
    },
}


@dataclass(frozen=True)
class RoutePlan:
    """Offline routing decision before constructing real providers."""

    task_type: str
    model_tier: str
    provider_chain: list[str]
    models_by_provider: dict[str, str]

    @property
    def primary_provider(self) -> str:
        return self.provider_chain[0]

    @property
    def primary_model(self) -> str:
        return self.models_by_provider[self.primary_provider]


def plan_route(
    task_type: str,
    *,
    preferred_provider: str = "openai",
    preferred_model: str | None = None,
    enabled_providers: list[str] | None = None,
) -> RoutePlan:
    """Plan model/provider routing without touching external SDKs or API keys."""
    provider = preferred_provider.lower()
    model_tier = ROUTING_RULES.get(task_type, "strong_model")

    if enabled_providers is None:
        enabled = [provider, *FALLBACK_CHAIN.get(provider, [])]
    else:
        enabled = [p.lower() for p in enabled_providers]
        if provider in enabled:
            enabled = [provider, *[p for p in enabled if p != provider]]

    provider_chain = []
    for candidate in enabled:
        if candidate not in DEFAULT_MODEL_TIERS:
            continue
        if candidate not in provider_chain:
            provider_chain.append(candidate)

    if not provider_chain:
        raise ValueError(
            "No supported providers available. Supported providers: "
            f"{sorted(DEFAULT_MODEL_TIERS)}"
        )

    models_by_provider = {
        candidate: (
            preferred_model
            if candidate == provider and preferred_model
            else DEFAULT_MODEL_TIERS[candidate][model_tier]
        )
        for candidate in provider_chain
    }

    return RoutePlan(
        task_type=task_type,
        model_tier=model_tier,
        provider_chain=provider_chain,
        models_by_provider=models_by_provider,
    )


def create_provider_from_plan(
    plan: RoutePlan,
    *,
    provider_index: int = 0,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs,
) -> LLMProvider:
    """Instantiate a provider selected by an offline route plan."""
    provider_type = plan.provider_chain[provider_index]
    return create_provider(
        provider_type=provider_type,
        model=plan.models_by_provider[provider_type],
        api_key=api_key,
        base_url=base_url,
        **kwargs,
    )


def create_provider(
    provider_type: str,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs,
) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        provider_type: One of 'openai', 'anthropic', or 'deepseek'.
        model: Model name. If None, uses provider default.
        api_key: API key. If None, reads from environment.
        base_url: Optional custom base URL (e.g. for proxies).
        **kwargs: Additional provider-specific args.

    Returns:
        An LLMProvider instance.

    Raises:
        ValueError: If provider_type is unknown.
    """
    import os

    provider_type = provider_type.lower()

    if provider_type == "openai":
        from .openai import OpenAIProvider

        default_model = "gpt-4o"
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError(
                "OpenAI API key not found. Set OPENAI_API_KEY env var or pass api_key."
            )
        return OpenAIProvider(
            model=model or default_model,
            api_key=key,
            base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
            **kwargs,
        )

    elif provider_type == "deepseek":
        from .openai import OpenAIProvider

        default_model = "deepseek-v4-flash"
        key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise ValueError(
                "DeepSeek API key not found. Set DEEPSEEK_API_KEY env var or pass api_key."
            )
        return OpenAIProvider(
            model=model or default_model,
            api_key=key,
            base_url=base_url or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
            **kwargs,
        )

    elif provider_type == "anthropic":
        from .anthropic import AnthropicProvider

        default_model = "claude-sonnet-4-20250514"
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError(
                "Anthropic API key not found. Set ANTHROPIC_API_KEY env var or pass api_key."
            )
        return AnthropicProvider(
            model=model or default_model,
            api_key=key,
            base_url=base_url,
            **kwargs,
        )

    else:
        raise ValueError(
            f"Unknown provider type: {provider_type}. "
            f"Supported: 'openai', 'anthropic', 'deepseek'"
        )
