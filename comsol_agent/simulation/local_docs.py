"""Local document indexing and search for offline RAG scaffolding."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DocumentChunk:
    """A searchable local documentation chunk."""

    id: str
    source: str
    title: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchResult:
    """A scored local documentation result."""

    chunk: DocumentChunk
    score: float
    matched_terms: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["chunk"] = self.chunk.to_dict()
        return data


class LocalDocumentIndex:
    """In-memory local document index using deterministic keyword scoring."""

    def __init__(self, chunks: list[DocumentChunk]):
        self.chunks = chunks

    @classmethod
    def from_paths(
        cls,
        paths: list[Path],
        *,
        chunk_chars: int = 1600,
    ) -> "LocalDocumentIndex":
        chunks: list[DocumentChunk] = []
        for path in paths:
            chunks.extend(_chunk_markdown(path, chunk_chars=chunk_chars))
        return cls(chunks)

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        query_terms = _terms(query)
        if not query_terms:
            return []

        results: list[SearchResult] = []
        for chunk in self.chunks:
            content_terms = _terms(f"{chunk.title}\n{chunk.content}")
            matched = tuple(sorted(query_terms & content_terms))
            if not matched:
                continue
            score = len(matched) / max(1, len(query_terms))
            if chunk.title and any(term in _terms(chunk.title) for term in matched):
                score += 0.2
            results.append(SearchResult(chunk=chunk, score=round(score, 3), matched_terms=matched))

        results.sort(key=lambda item: (item.score, len(item.matched_terms)), reverse=True)
        return results[:limit]


def build_index_from_directory(
    directory: str | Path,
    *,
    pattern: str = "*.md",
    chunk_chars: int = 1600,
) -> LocalDocumentIndex:
    """Build an index from markdown-like files under a workspace directory."""
    base = Path(directory).expanduser().resolve()
    cwd = Path.cwd().resolve()
    try:
        base.relative_to(cwd)
    except ValueError as exc:
        raise ValueError(f"Document directory must be inside the workspace: {base}") from exc
    if not base.exists():
        raise FileNotFoundError(f"Document directory not found: {base}")
    if not base.is_dir():
        raise ValueError(f"Document path is not a directory: {base}")

    paths = sorted(path for path in base.glob(pattern) if path.is_file())
    return LocalDocumentIndex.from_paths(paths, chunk_chars=chunk_chars)


def _chunk_markdown(path: Path, *, chunk_chars: int) -> list[DocumentChunk]:
    text = path.read_text(encoding="utf-8", errors="replace")
    sections = _split_markdown_sections(text)
    chunks: list[DocumentChunk] = []
    source = str(path)
    counter = 1
    for title, content in sections:
        for piece in _split_by_size(content, chunk_chars):
            chunks.append(
                DocumentChunk(
                    id=f"{path.stem}:{counter}",
                    source=source,
                    title=title or path.name,
                    content=piece.strip(),
                )
            )
            counter += 1
    return chunks


def _split_markdown_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match and current_lines:
            sections.append((current_title, current_lines))
            current_title = match.group(2).strip()
            current_lines = [line]
        else:
            if match and not current_title:
                current_title = match.group(2).strip()
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, current_lines))
    return [(title, "\n".join(lines)) for title, lines in sections]


def _split_by_size(text: str, chunk_chars: int) -> list[str]:
    if len(text) <= chunk_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + chunk_chars])
        start += chunk_chars
    return chunks


def _terms(text: str) -> set[str]:
    ignored = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "into",
        "your",
        "you",
        "are",
    }
    return {
        word.lower()
        for word in re.findall(r"[\w.-]+", text)
        if len(word) >= 3 and word.lower() not in ignored
    }
