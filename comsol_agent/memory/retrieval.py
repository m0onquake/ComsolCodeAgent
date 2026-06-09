"""Offline memory retrieval context helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from comsol_agent.memory.archive_store import ArchiveMemory, ArchiveStore


@dataclass
class RetrievedMemory:
    """Memory hit prepared for context injection."""

    id: int
    session_id: str
    type: str
    content: str
    metadata: dict[str, Any] | None = None


def retrieve_memories(
    archive_store: ArchiveStore,
    query: str,
    *,
    limit: int = 5,
    min_query_chars: int = 3,
) -> list[RetrievedMemory]:
    """Retrieve memories using SQLite text search before vector search is available."""
    normalized = query.strip()
    if len(normalized) < min_query_chars:
        return []

    seen: set[int] = set()
    results: list[ArchiveMemory] = []
    for search_term in [normalized, *_keywords(normalized)]:
        for memory in archive_store.search_memories(search_term, limit=limit):
            if memory.id in seen:
                continue
            seen.add(memory.id)
            results.append(memory)
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break
    return [_from_archive_memory(memory) for memory in results]


def build_memory_context_message(memories: list[RetrievedMemory]) -> dict[str, str] | None:
    """Build an OpenAI-style message containing retrieved memory context."""
    if not memories:
        return None

    lines = ["[Retrieved from memory]"]
    for index, memory in enumerate(memories, start=1):
        lines.append(
            f"{index}. ({memory.type}, session={memory.session_id}, id={memory.id}) "
            f"{_truncate(memory.content, 700)}"
        )

    return {
        "role": "user",
        "content": "\n".join(lines),
    }


def _from_archive_memory(memory: ArchiveMemory) -> RetrievedMemory:
    return RetrievedMemory(
        id=memory.id,
        session_id=memory.session_id,
        type=memory.type,
        content=memory.content,
        metadata=memory.metadata,
    )


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 16)] + "...[truncated]"


def _keywords(query: str) -> list[str]:
    words = re.findall(r"[\w.-]+", query)
    ignored = {"the", "and", "or", "about", "what", "this", "that", "with", "for"}
    return [word for word in words if len(word) >= 3 and word.lower() not in ignored]
