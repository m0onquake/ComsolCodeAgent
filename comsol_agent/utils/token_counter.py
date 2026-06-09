"""Token counting utilities for context management."""

from __future__ import annotations

from typing import Any


def estimate_tokens(text: str, model: str = "gpt-4o") -> int:
    """Estimate token count for a text string.

    Uses tiktoken if available, otherwise falls back to char-based estimation.
    """
    try:
        import tiktoken

        try:
            enc = tiktoken.encoding_for_model(model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        # Rough fallback: ~4 characters per token for English text
        return max(1, len(text) // 4)


def estimate_messages_tokens(
    messages: list[dict[str, Any]], model: str = "gpt-4o"
) -> int:
    """Estimate total token count for a list of messages."""
    total = 0
    for msg in messages:
        total += 4  # Message framing overhead
        for key, value in msg.items():
            if isinstance(value, str):
                total += estimate_tokens(value, model)
            elif isinstance(value, (list, dict)):
                import json

                total += estimate_tokens(json.dumps(value, ensure_ascii=False), model)
            elif value is not None:
                total += estimate_tokens(str(value), model)
    total += 2  # Assistant priming
    return max(1, total)


def format_token_count(count: int) -> str:
    """Format a token count for display."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    elif count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)
