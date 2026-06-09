"""SQLite archive store for session timeline, memories, and templates."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ArchiveSession:
    """Persisted session timeline row."""

    id: str
    name: str | None
    created_at: str
    updated_at: str
    summary: str | None = None


@dataclass
class ArchiveMemory:
    """Persisted memory card."""

    id: int
    session_id: str
    type: str
    content: str
    token_count: int
    created_at: str
    embedding: list[float] | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class SimulationTemplate:
    """Persisted simulation/code template."""

    id: int
    name: str
    domain: str | None
    java_code: str
    params: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass
class SimulationArtifact:
    """Persisted simulation artifact index row."""

    id: int
    run_id: str
    kind: str
    model_name: str | None
    source: dict[str, Any]
    json_path: str
    csv_path: str | None
    manifest_path: str
    executed_cases: int
    truncated: bool
    created_at: str
    metadata: dict[str, Any] | None = None


class ArchiveStore:
    """Small SQLite-backed archive aligned with the architecture document."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def upsert_session(
        self,
        session_id: str,
        *,
        name: str | None = None,
        summary: str | None = None,
        created_at: str | None = None,
    ) -> ArchiveSession:
        """Create or update a session row."""
        now = _utc_now()
        created = created_at or now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, name, created_at, updated_at, summary)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = COALESCE(excluded.name, sessions.name),
                    updated_at = excluded.updated_at,
                    summary = COALESCE(excluded.summary, sessions.summary)
                """,
                (session_id, name, created, now, summary),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> ArchiveSession:
        """Return a session by id."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, created_at, updated_at, summary FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Session not found: {session_id}")
        return ArchiveSession(**dict(row))

    def list_sessions(self, limit: int = 50) -> list[ArchiveSession]:
        """List recent sessions."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, created_at, updated_at, summary
                FROM sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [ArchiveSession(**dict(row)) for row in rows]

    def search_sessions(self, query: str, limit: int = 20) -> list[ArchiveSession]:
        """Search sessions by id, name, or summary."""
        like = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, created_at, updated_at, summary
                FROM sessions
                WHERE id LIKE ? OR name LIKE ? OR summary LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
        return [ArchiveSession(**dict(row)) for row in rows]

    def get_session_overview(self, session_id: str) -> dict[str, Any]:
        """Return one session plus compact memory statistics."""
        session = self.get_session(session_id)
        with self._connect() as conn:
            memory_count = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            last_memory_at = conn.execute(
                "SELECT MAX(created_at) FROM memories WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            type_rows = conn.execute(
                """
                SELECT type, COUNT(*) AS count
                FROM memories
                WHERE session_id = ?
                GROUP BY type
                ORDER BY count DESC, type ASC
                """,
                (session_id,),
            ).fetchall()

        return {
            "session": session,
            "memory_count": int(memory_count or 0),
            "last_memory_at": last_memory_at,
            "memory_types": {str(row["type"]): int(row["count"]) for row in type_rows},
        }

    def add_memory(
        self,
        session_id: str,
        *,
        memory_type: str,
        content: str,
        token_count: int = 0,
        embedding: list[float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArchiveMemory:
        """Insert a memory card for a session."""
        self.upsert_session(session_id)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memories
                    (session_id, type, content, embedding, token_count, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    memory_type,
                    content,
                    json.dumps(embedding) if embedding is not None else None,
                    token_count,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    _utc_now(),
                ),
            )
            memory_id = int(cursor.lastrowid)
        return self.get_memory(memory_id)

    def get_memory(self, memory_id: int) -> ArchiveMemory:
        """Return a memory by id."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, type, content, embedding, token_count, metadata, created_at
                FROM memories
                WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Memory not found: {memory_id}")
        return _memory_from_row(row)

    def list_memories(
        self,
        *,
        session_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 50,
    ) -> list[ArchiveMemory]:
        """List memories by recency with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if memory_type is not None:
            clauses.append("type = ?")
            params.append(memory_type)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, session_id, type, content, embedding, token_count, metadata, created_at
                FROM memories
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_memory_from_row(row) for row in rows]

    def search_memories(self, query: str, limit: int = 10) -> list[ArchiveMemory]:
        """Simple text search placeholder before vector retrieval is enabled."""
        like = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, type, content, embedding, token_count, metadata, created_at
                FROM memories
                WHERE content LIKE ? OR type LIKE ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (like, like, limit),
            ).fetchall()
        return [_memory_from_row(row) for row in rows]

    def add_template(
        self,
        *,
        name: str,
        java_code: str,
        domain: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> SimulationTemplate:
        """Insert or update a simulation template by name."""
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO templates (name, domain, java_code, params, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    domain = excluded.domain,
                    java_code = excluded.java_code,
                    params = excluded.params,
                    updated_at = excluded.updated_at
                """,
                (
                    name,
                    domain,
                    java_code,
                    json.dumps(params or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_template(name)

    def get_template(self, name: str) -> SimulationTemplate:
        """Return a template by name."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, domain, java_code, params, created_at, updated_at
                FROM templates
                WHERE name = ?
                """,
                (name,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Template not found: {name}")
        return _template_from_row(row)

    def list_templates(
        self,
        *,
        domain: str | None = None,
        limit: int = 50,
    ) -> list[SimulationTemplate]:
        """List templates with optional domain filter."""
        if domain is None:
            sql = """
                SELECT id, name, domain, java_code, params, created_at, updated_at
                FROM templates
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
            """
            params: tuple[Any, ...] = (limit,)
        else:
            sql = """
                SELECT id, name, domain, java_code, params, created_at, updated_at
                FROM templates
                WHERE domain = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
            """
            params = (domain, limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_template_from_row(row) for row in rows]

    def search_templates(
        self,
        query: str,
        *,
        domain: str | None = None,
        limit: int = 20,
    ) -> list[SimulationTemplate]:
        """Search templates by name, domain, code, or serialized parameters."""
        like = f"%{query}%"
        clauses = ["(name LIKE ? OR domain LIKE ? OR java_code LIKE ? OR params LIKE ?)"]
        params: list[Any] = [like, like, like, like]
        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, name, domain, java_code, params, created_at, updated_at
                FROM templates
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_template_from_row(row) for row in rows]

    def index_simulation_artifact(
        self,
        manifest: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> SimulationArtifact:
        """Insert or update a simulation artifact manifest index row."""
        run_id = str(manifest["run_id"])
        kind = str(manifest.get("kind") or "simulation_artifact")
        model_name = manifest.get("model_name")
        created_at = str(manifest.get("created_at") or _utc_now())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO simulation_artifacts
                    (
                        run_id, kind, model_name, source, json_path, csv_path,
                        manifest_path, executed_cases, truncated, created_at, metadata
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    kind = excluded.kind,
                    model_name = excluded.model_name,
                    source = excluded.source,
                    json_path = excluded.json_path,
                    csv_path = excluded.csv_path,
                    manifest_path = excluded.manifest_path,
                    executed_cases = excluded.executed_cases,
                    truncated = excluded.truncated,
                    metadata = excluded.metadata
                """,
                (
                    run_id,
                    kind,
                    model_name,
                    json.dumps(manifest.get("source") or {}, ensure_ascii=False),
                    str(manifest.get("json_path") or ""),
                    manifest.get("csv_path"),
                    str(manifest.get("manifest_path") or ""),
                    int(manifest.get("executed_cases") or 0),
                    1 if manifest.get("truncated") else 0,
                    created_at,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        return self.get_simulation_artifact(run_id)

    def get_simulation_artifact(self, run_id: str) -> SimulationArtifact:
        """Return a simulation artifact by run id."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id, run_id, kind, model_name, source, json_path, csv_path,
                    manifest_path, executed_cases, truncated, created_at, metadata
                FROM simulation_artifacts
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Simulation artifact not found: {run_id}")
        return _simulation_artifact_from_row(row)

    def list_simulation_artifacts(
        self,
        *,
        kind: str | None = None,
        model_name: str | None = None,
        limit: int = 50,
    ) -> list[SimulationArtifact]:
        """List recent simulation artifacts with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if model_name is not None:
            clauses.append("model_name = ?")
            params.append(model_name)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    id, run_id, kind, model_name, source, json_path, csv_path,
                    manifest_path, executed_cases, truncated, created_at, metadata
                FROM simulation_artifacts
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_simulation_artifact_from_row(row) for row in rows]

    def search_simulation_artifacts(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> list[SimulationArtifact]:
        """Search simulation artifacts by run id, model, source, paths, or metadata."""
        like = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, run_id, kind, model_name, source, json_path, csv_path,
                    manifest_path, executed_cases, truncated, created_at, metadata
                FROM simulation_artifacts
                WHERE
                    run_id LIKE ?
                    OR kind LIKE ?
                    OR model_name LIKE ?
                    OR source LIKE ?
                    OR json_path LIKE ?
                    OR csv_path LIKE ?
                    OR manifest_path LIKE ?
                    OR metadata LIKE ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (like, like, like, like, like, like, like, like, limit),
            ).fetchall()
        return [_simulation_artifact_from_row(row) for row in rows]

    def delete_simulation_artifact(self, run_id: str) -> bool:
        """Delete a simulation artifact index row by run id."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM simulation_artifacts WHERE run_id = ?",
                (run_id,),
            )
            return cursor.rowcount > 0

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    summary TEXT
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding TEXT,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_memories_session
                    ON memories(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_memories_type
                    ON memories(type, created_at);

                CREATE TABLE IF NOT EXISTS templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    domain TEXT,
                    java_code TEXT NOT NULL,
                    params TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_templates_domain
                    ON templates(domain, updated_at);

                CREATE TABLE IF NOT EXISTS simulation_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    model_name TEXT,
                    source TEXT NOT NULL DEFAULT '{}',
                    json_path TEXT NOT NULL,
                    csv_path TEXT,
                    manifest_path TEXT NOT NULL,
                    executed_cases INTEGER NOT NULL DEFAULT 0,
                    truncated INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_simulation_artifacts_kind
                    ON simulation_artifacts(kind, created_at);
                CREATE INDEX IF NOT EXISTS idx_simulation_artifacts_model
                    ON simulation_artifacts(model_name, created_at);
                """
            )


def _memory_from_row(row: sqlite3.Row) -> ArchiveMemory:
    data = dict(row)
    embedding = data.get("embedding")
    metadata = data.get("metadata")
    data["embedding"] = json.loads(embedding) if embedding else None
    data["metadata"] = json.loads(metadata) if metadata else {}
    return ArchiveMemory(**data)


def _template_from_row(row: sqlite3.Row) -> SimulationTemplate:
    data = dict(row)
    data["params"] = json.loads(data["params"]) if data.get("params") else {}
    return SimulationTemplate(**data)


def _simulation_artifact_from_row(row: sqlite3.Row) -> SimulationArtifact:
    data = dict(row)
    data["source"] = json.loads(data["source"]) if data.get("source") else {}
    data["metadata"] = json.loads(data["metadata"]) if data.get("metadata") else {}
    data["truncated"] = bool(data["truncated"])
    return SimulationArtifact(**data)
