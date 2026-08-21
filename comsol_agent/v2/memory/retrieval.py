"""Hybrid structured, keyword, vector, relation, and hash retrieval."""

from __future__ import annotations

import fnmatch
import hashlib
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Protocol

from .contracts import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    RepairCase,
    RetrievalHit,
    RetrievalQuery,
    RetrievalRejection,
    RetrievalResult,
    RetrievalWeights,
    VerifiedCase,
)
from .governance import MemoryGovernance, compatibility_decision, freshness_score
from .store import MemoryRepository

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]")


class Vectorizer(Protocol):
    def embed(self, text: str) -> Sequence[float]: ...


class HashingVectorizer:
    """Dependency-free deterministic embedding for the reference implementation."""

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions < 8:
            raise ValueError("dimensions must be at least 8")
        self.dimensions = dimensions

    def embed(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self.dimensions
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return tuple(vector)


class ReferenceCatalog:
    """Verifies current artifact presence and optional content hashes by URI."""

    def __init__(self, artifacts: dict[str, str | None]) -> None:
        self.artifacts = dict(artifacts)

    def __call__(self, record: MemoryRecord) -> tuple[bool, list[str]]:
        expected = _artifact_expectations(record)
        reasons: list[str] = []
        for uri, expected_hash in expected.items():
            if uri not in self.artifacts:
                reasons.append(f"artifact missing: {uri}")
                continue
            actual_hash = self.artifacts[uri]
            if expected_hash and actual_hash != expected_hash:
                reasons.append(f"artifact hash mismatch: {uri}")
        return not reasons, reasons


class HybridRetriever:
    """Hard-filter first, fuse configurable retrieval channels second."""

    def __init__(
        self,
        repository: MemoryRepository,
        *,
        weights: RetrievalWeights | None = None,
        vectorizer: Vectorizer | None = None,
        reference_validator: Callable[[MemoryRecord], tuple[bool, list[str]]] | None = None,
        governance: MemoryGovernance | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.weights = weights or RetrievalWeights()
        self.vectorizer = vectorizer or HashingVectorizer()
        self.reference_validator = reference_validator
        self.governance = governance
        self.now = now or (lambda: datetime.now(UTC))

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        candidates = self.repository.records(
            statuses=query.statuses,
            domain=query.domain,
        )
        accepted: list[tuple[MemoryRecord, bool, bool, list[str]]] = []
        rejected: list[RetrievalRejection] = []
        for record in candidates:
            reasons = self._hard_filter(record, query)
            decision = compatibility_decision(
                record,
                query.compatibility,
                domain=query.domain,
                topology_signature=query.topology_signature,
            )
            if not decision.compatible:
                reasons.extend(decision.reasons)
            references_checked = self.reference_validator is not None
            references_valid = False
            reference_reasons: list[str] = []
            if self.reference_validator is not None:
                references_valid, reference_reasons = self.reference_validator(record)
                if not references_valid and record.status in {
                    MemoryStatus.VERIFIED,
                    MemoryStatus.ACTIVE,
                }:
                    if self.governance is not None:
                        self.governance.mark_needs_revalidation(record.id, reference_reasons)
                if not references_valid:
                    reasons.extend(reference_reasons)
            elif record.status in {MemoryStatus.VERIFIED, MemoryStatus.ACTIVE}:
                reasons.append("reference validator unavailable")
            executable = (
                record.executable
                and decision.compatible
                and decision.complete
                and references_checked
                and references_valid
            )
            if query.require_executable and not executable:
                if not decision.complete:
                    reasons.extend(decision.reasons)
                if not references_checked:
                    reasons.append("reference validator unavailable")
                if not record.executable:
                    reasons.append("record has not passed executable promotion gates")
            if reasons:
                rejected.append(
                    RetrievalRejection(record_id=record.id, reasons=_unique(reasons))
                )
                continue
            accepted.append(
                (record, executable, references_checked, reference_reasons)
            )

        corpus = [_search_text(record) for record, *_ in accepted]
        keyword_scores = bm25_scores(query.text, corpus)
        query_vector = self.vectorizer.embed(query.text)
        related = self.repository.related(query.related_ids)
        hits: list[RetrievalHit] = []
        for index, (record, executable, references_checked, reasons) in enumerate(accepted):
            channels = {
                "structured": _structured_score(record, query),
                "keyword": keyword_scores[index],
                "vector": cosine(query_vector, self.vectorizer.embed(corpus[index])),
                "relation": _relation_score(record, query.related_ids, related),
            }
            score = (
                self.weights.structured * channels["structured"]
                + self.weights.keyword * channels["keyword"]
                + self.weights.vector * channels["vector"]
                + self.weights.relation * channels["relation"]
                + self.weights.quality * record.quality.audit_score
                + self.weights.freshness
                * freshness_score(record.validated_at, self.now())
                + self.weights.adoption * record.quality.adoption_success_rate
            )
            hits.append(
                RetrievalHit(
                    record=record,
                    score=max(0.0, score),
                    channel_scores=channels,
                    executable=executable,
                    compatibility_checked=True,
                    references_checked=references_checked,
                    reasons=reasons,
                )
            )
        hits.sort(key=lambda item: (-item.score, item.record.id))
        return RetrievalResult(query=query, hits=hits[: query.top_k], rejected=rejected)

    @staticmethod
    def _hard_filter(record: MemoryRecord, query: RetrievalQuery) -> list[str]:
        reasons: list[str] = []
        if query.types and record.type not in query.types:
            reasons.append("memory type is outside the requested pool")
        if record.status in {
            MemoryStatus.QUARANTINED,
            MemoryStatus.NEEDS_REVALIDATION,
            MemoryStatus.INVALIDATED,
        }:
            reasons.append(f"status {record.status} is not retrievable")
        if record.type == MemoryType.REPAIR_CASE:
            if query.error_signature is None:
                reasons.append("repair cases require an error signature")
            elif isinstance(record.structured, RepairCase) and not _error_matches(
                record.structured, query
            ):
                reasons.append("repair error signature mismatch")
        return reasons


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def bm25_scores(query: str, documents: Sequence[str]) -> list[float]:
    if not documents:
        return []
    query_terms = tokenize(query)
    tokenized = [tokenize(document) for document in documents]
    average_length = sum(len(document) for document in tokenized) / len(tokenized) or 1.0
    document_frequency = Counter(
        term for document in tokenized for term in set(document)
    )
    raw: list[float] = []
    for document in tokenized:
        frequencies = Counter(document)
        score = 0.0
        for term in query_terms:
            frequency = frequencies[term]
            if not frequency:
                continue
            inverse = math.log(
                1 + (len(documents) - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            denominator = frequency + 1.5 * (
                0.25 + 0.75 * len(document) / average_length
            )
            score += inverse * frequency * 2.5 / denominator
        raw.append(score)
    maximum = max(raw, default=0.0)
    return [value / maximum if maximum else 0.0 for value in raw]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vector dimensions differ")
    score = sum(a * b for a, b in zip(left, right, strict=True))
    return max(0.0, min(1.0, score))


def _search_text(record: MemoryRecord) -> str:
    fields = [record.summary]
    structured = record.structured
    if isinstance(structured, VerifiedCase):
        fields.extend([structured.normalized_request, *structured.keywords])
    elif isinstance(structured, RepairCase):
        fields.extend(
            [
                structured.root_cause,
                structured.error_signature.error_class,
                structured.error_signature.exception or "",
                structured.error_signature.feature_pattern or "",
                *structured.keywords,
            ]
        )
    else:
        fields.extend(str(value) for value in structured.values())
    return " ".join(fields)


def _structured_score(record: MemoryRecord, query: RetrievalQuery) -> float:
    score = 0.35
    if record.compatibility.topology_signature == query.topology_signature:
        score += 0.35
    if isinstance(record.structured, VerifiedCase) and query.parameters:
        distances = []
        for key, desired in query.parameters.items():
            prior = record.structured.parameters.get(key)
            if prior is not None:
                scale = max(abs(desired), abs(prior), 1e-12)
                distances.append(min(1.0, abs(desired - prior) / scale))
        if distances:
            score += 0.30 * (1.0 - sum(distances) / len(distances))
    elif isinstance(record.structured, RepairCase):
        score += 0.30
    return min(1.0, score)


def _relation_score(
    record: MemoryRecord, seeds: Iterable[str], related: frozenset[str]
) -> float:
    seed_set = set(seeds)
    if record.id in seed_set:
        return 1.0
    if record.id in related:
        return 0.8
    targets = {relation.target_id for relation in record.relations}
    return 0.6 if targets.intersection(seed_set) else 0.0


def _error_matches(repair: RepairCase, query: RetrievalQuery) -> bool:
    actual = query.error_signature
    if actual is None:
        return False
    expected = repair.error_signature
    if expected.error_class != actual.error_class or expected.stage != actual.stage:
        return False
    if expected.exception and expected.exception != actual.exception:
        return False
    if expected.feature_pattern:
        if not actual.feature_pattern:
            return False
        return fnmatch.fnmatchcase(actual.feature_pattern, expected.feature_pattern)
    return True


def _artifact_expectations(record: MemoryRecord) -> dict[str, str | None]:
    expectations: dict[str, str | None] = {}
    if record.content_ref:
        expectations[record.content_ref] = None
    for citation in record.citations:
        if citation.uri:
            expectations[citation.uri] = None
    structured = record.structured
    if isinstance(structured, VerifiedCase):
        for artifact in [structured.baseline_code, *structured.artifacts]:
            expectations[artifact.uri] = artifact.sha256
    elif isinstance(structured, RepairCase):
        expectations[structured.patch_ref.uri] = structured.patch_ref.sha256
    return expectations


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
