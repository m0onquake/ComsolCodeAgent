"""Versioned storage for runtime and long-term V2 memory."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from pydantic import Field

from comsol_agent.v2.contracts.models import ContractModel

from .contracts import (
    MEMORY_SCHEMA_VERSION,
    DeletionReceipt,
    MemoryLayer,
    MemoryRecord,
    MemoryStatus,
    RuntimeMemoryEntry,
)


class MemoryStoreError(RuntimeError):
    """Base error for deterministic memory store failures."""


class DuplicateMemoryError(MemoryStoreError):
    pass


class MemoryNotFoundError(MemoryStoreError):
    pass


class StaleMemoryWriteError(MemoryStoreError):
    pass


class UngovernedMemoryWriteError(MemoryStoreError):
    pass


class MemorySnapshot(ContractModel):
    schema_version: str = MEMORY_SCHEMA_VERSION
    records: list[MemoryRecord] = Field(default_factory=list)
    tombstones: list[DeletionReceipt] = Field(default_factory=list)


class RuntimeMemory:
    """Run-local Working memory plus conversation-local Session memory."""

    def __init__(self) -> None:
        self._entries: dict[MemoryLayer, list[RuntimeMemoryEntry]] = {
            MemoryLayer.WORKING: [],
            MemoryLayer.SESSION: [],
        }

    def append(self, entry: RuntimeMemoryEntry) -> None:
        self._entries[entry.layer].append(entry.model_copy(deep=True))

    def entries(self, layer: MemoryLayer) -> tuple[RuntimeMemoryEntry, ...]:
        if layer not in self._entries:
            raise ValueError("Only working and session layers are runtime memory")
        return tuple(entry.model_copy(deep=True) for entry in self._entries[layer])

    def clear_working(self) -> None:
        self._entries[MemoryLayer.WORKING].clear()

    def clear_session(self) -> None:
        self._entries[MemoryLayer.WORKING].clear()
        self._entries[MemoryLayer.SESSION].clear()


class MemoryRepository:
    """In-process reference repository with explicit indexes and tombstones."""

    def __init__(self, snapshot: MemorySnapshot | None = None) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._tombstones: dict[str, DeletionReceipt] = {}
        self._by_status: dict[MemoryStatus, set[str]] = defaultdict(set)
        self._by_domain: dict[str, set[str]] = defaultdict(set)
        self._by_topology: dict[str, set[str]] = defaultdict(set)
        self._by_hash: dict[str, set[str]] = defaultdict(set)
        self._relations: dict[str, set[str]] = defaultdict(set)
        if snapshot:
            if snapshot.schema_version != MEMORY_SCHEMA_VERSION:
                raise MemoryStoreError(
                    f"unsupported memory schema {snapshot.schema_version!r}"
                )
            for record in snapshot.records:
                self._insert(record, persist=False)
            self._tombstones = {item.record_id: item for item in snapshot.tombstones}

    def add(self, record: MemoryRecord) -> str:
        if record.id in self._records or record.id in self._tombstones:
            raise DuplicateMemoryError(record.id)
        if record.status != MemoryStatus.QUARANTINED:
            raise UngovernedMemoryWriteError(
                "new long-term records must enter through quarantine"
            )
        self._insert(record)
        return record.id

    def get(self, record_id: str) -> MemoryRecord | None:
        record = self._records.get(record_id)
        return record.model_copy(deep=True) if record else None

    def require(self, record_id: str) -> MemoryRecord:
        record = self.get(record_id)
        if record is None:
            raise MemoryNotFoundError(record_id)
        return record

    def replace(
        self,
        record: MemoryRecord,
        *,
        expected_status: MemoryStatus | None = None,
        governed_transition: bool = False,
    ) -> None:
        current = self._records.get(record.id)
        if current is None:
            raise MemoryNotFoundError(record.id)
        if expected_status is not None and current.status != expected_status:
            raise StaleMemoryWriteError(
                f"{record.id} status is {current.status}, expected {expected_status}"
            )
        if record.status != current.status and not governed_transition:
            raise UngovernedMemoryWriteError(
                "status changes require MemoryGovernance"
            )
        self._deindex(current)
        self._records[record.id] = record.model_copy(deep=True)
        self._index(record)
        self._changed()

    def records(
        self,
        *,
        statuses: Iterable[MemoryStatus] | None = None,
        domain: str | None = None,
        topology: str | None = None,
    ) -> tuple[MemoryRecord, ...]:
        ids = set(self._records)
        if statuses is not None:
            allowed: set[str] = set()
            for status in statuses:
                allowed.update(self._by_status[status])
            ids.intersection_update(allowed)
        if domain is not None:
            ids.intersection_update(self._by_domain[domain])
        if topology is not None:
            ids.intersection_update(self._by_topology[topology])
        return tuple(self._records[item].model_copy(deep=True) for item in sorted(ids))

    def by_content_hash(self, sha256: str) -> tuple[MemoryRecord, ...]:
        return tuple(
            self._records[item].model_copy(deep=True)
            for item in sorted(self._by_hash.get(sha256, set()))
        )

    def related(self, record_ids: Iterable[str]) -> frozenset[str]:
        related: set[str] = set()
        for record_id in record_ids:
            related.update(self._relations.get(record_id, set()))
        return frozenset(related)

    def delete(self, record_id: str, reason: str) -> DeletionReceipt:
        record = self._records.pop(record_id, None)
        if record is None:
            raise MemoryNotFoundError(record_id)
        self._deindex(record)
        digest = hashlib.sha256(
            record.provenance.model_dump_json().encode("utf-8")
        ).hexdigest()
        receipt = DeletionReceipt(
            record_id=record_id,
            reason=reason,
            provenance_digest=digest,
        )
        self._tombstones[record_id] = receipt
        self._changed()
        return receipt.model_copy(deep=True)

    def tombstone(self, record_id: str) -> DeletionReceipt | None:
        item = self._tombstones.get(record_id)
        return item.model_copy(deep=True) if item else None

    def snapshot(self) -> MemorySnapshot:
        return MemorySnapshot(
            records=[self._records[key].model_copy(deep=True) for key in sorted(self._records)],
            tombstones=[
                self._tombstones[key].model_copy(deep=True)
                for key in sorted(self._tombstones)
            ],
        )

    def _insert(self, record: MemoryRecord, *, persist: bool = True) -> None:
        self._records[record.id] = record.model_copy(deep=True)
        self._index(record)
        if persist:
            self._changed()

    def _index(self, record: MemoryRecord) -> None:
        self._by_status[record.status].add(record.id)
        self._by_domain[record.compatibility.domain].add(record.id)
        if record.compatibility.topology_signature:
            self._by_topology[record.compatibility.topology_signature].add(record.id)
        if record.provenance.code_hash:
            self._by_hash[record.provenance.code_hash].add(record.id)
        for relation in record.relations:
            self._relations[record.id].add(relation.target_id)
            self._relations[relation.target_id].add(record.id)

    def _deindex(self, record: MemoryRecord) -> None:
        for index, key in (
            (self._by_status, record.status),
            (self._by_domain, record.compatibility.domain),
            (self._by_topology, record.compatibility.topology_signature),
            (self._by_hash, record.provenance.code_hash),
        ):
            if key is not None:
                index[key].discard(record.id)
        for relation in record.relations:
            self._relations[record.id].discard(relation.target_id)
            self._relations[relation.target_id].discard(record.id)

    def _changed(self) -> None:
        """Persistence hook."""


class JsonMemoryRepository(MemoryRepository):
    """Atomic, versioned JSON snapshot store for a trusted local memory root."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        snapshot = None
        if self.path.exists():
            snapshot = MemorySnapshot.model_validate_json(self.path.read_text(encoding="utf-8"))
        super().__init__(snapshot)

    def _changed(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.snapshot().model_dump_json(indent=2)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def export_json(self) -> str:
        """Return canonical content for migrations and diagnostics."""
        return json.dumps(
            self.snapshot().model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
