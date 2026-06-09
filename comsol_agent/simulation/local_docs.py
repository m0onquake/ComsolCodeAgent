"""Local document indexing and search for offline RAG scaffolding."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DocumentChunk:
    """A searchable local documentation chunk."""

    id: str
    source: str
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

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

    def retrieve_api_docs(
        self,
        query: str,
        *,
        limit: int = 5,
        domain: str | None = None,
        snippet_chars: int = 700,
    ) -> list[dict[str, Any]]:
        """Return compact, source-grounded snippets for repair/code generation."""
        results = self.search(query, limit=max(limit * 3, limit))
        snippets: list[dict[str, Any]] = []
        for result in results:
            metadata = result.chunk.metadata
            if domain and metadata.get("domain") not in {domain, None, "general"}:
                continue
            snippet = _compact_snippet(result.chunk.content, query, max_chars=snippet_chars)
            snippets.append(
                {
                    "citation": f"{result.chunk.source}#{result.chunk.id}",
                    "source": result.chunk.source,
                    "title": result.chunk.title,
                    "snippet": snippet,
                    "score": result.score,
                    "matched_terms": list(result.matched_terms),
                    "metadata": metadata,
                    "api_symbols": metadata.get("api_symbols", []),
                    "domain": metadata.get("domain"),
                    "comsol_versions": metadata.get("comsol_versions", []),
                }
            )
            if len(snippets) >= limit:
                break
        return snippets


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
            metadata = _metadata_for_chunk(path, title, piece)
            chunks.append(
                DocumentChunk(
                    id=f"{path.stem}:{counter}",
                    source=source,
                    title=title or path.name,
                    content=piece.strip(),
                    metadata=metadata,
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


def _metadata_for_chunk(path: Path, title: str, content: str) -> dict[str, Any]:
    text = f"{title}\n{content}"
    api_symbols = _extract_api_symbols(text)
    return {
        "source_name": path.name,
        "heading_path": title,
        "domain": _infer_domain(text),
        "api_symbols": api_symbols,
        "api_classes": _extract_api_classes(text),
        "api_functions": api_symbols,
        "comsol_versions": _extract_comsol_versions(text),
    }


def _infer_domain(text: str) -> str:
    lowered = text.lower()
    domain_terms = {
        "thermal": ("thermal", "heat", "temperature", "conduction", "convection"),
        "structural": ("structural", "solid mechanics", "stress", "strain", "deformation"),
        "fluid": ("fluid", "flow", "velocity", "pressure", "reynolds", "laminar"),
        "electromagnetic": ("electromagnetic", "electric", "magnetic", "voltage", "current"),
    }
    scores = {
        domain: sum(1 for term in terms if term in lowered)
        for domain, terms in domain_terms.items()
    }
    best_domain, best_score = max(scores.items(), key=lambda item: item[1])
    return best_domain if best_score else "general"


def _extract_api_symbols(text: str) -> list[str]:
    patterns = (
        r"\bmodel(?:\.[A-Za-z_]\w*\([^)]*\))+",
        r"\bcomsol_[A-Za-z_]\w+",
        r"\bsimulation_[A-Za-z_]\w+",
        r"\bCOMSOLClient\.[A-Za-z_]\w+\(\)",
        r"\b[A-Za-z_]\w+\(\)",
    )
    symbols: set[str] = set()
    for pattern in patterns:
        for match in re.findall(pattern, text):
            symbol = _normalize_api_symbol(match.strip())
            if symbol and len(symbol) <= 120:
                symbols.add(symbol)
    return sorted(symbols)


def _normalize_api_symbol(symbol: str) -> str:
    return re.sub(r"\([^)]*\)", "()", symbol)


def _extract_comsol_versions(text: str) -> list[str]:
    versions = set()
    for match in re.findall(r"\bCOMSOL\s+(?:Multiphysics\s+)?([5-6]\.\d)\b", text, flags=re.IGNORECASE):
        versions.add(match)
    for match in re.findall(r"\bv([5-6]\d)\b", text, flags=re.IGNORECASE):
        versions.add(f"{match[0]}.{match[1:]}")
    return sorted(versions)


def _extract_api_classes(text: str) -> list[str]:
    classes = set(re.findall(r"\b(?:COMSOLClient|ModelHandle|[A-Z][A-Za-z0-9_]*(?:Sequence|Feature|Model))\b", text))
    return sorted(classes)


def _compact_snippet(content: str, query: str, *, max_chars: int) -> str:
    text = " ".join(content.split())
    if len(text) <= max_chars:
        return text
    query_terms = _terms(query)
    lowered = text.lower()
    first_hit = min(
        (lowered.find(term) for term in query_terms if lowered.find(term) >= 0),
        default=0,
    )
    start = max(0, first_hit - max_chars // 3)
    end = min(len(text), start + max_chars)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet += "..."
    return snippet
