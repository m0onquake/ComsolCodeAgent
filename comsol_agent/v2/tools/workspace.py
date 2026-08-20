"""Workspace-confined search, read, exact patch, and rollback operations."""

from __future__ import annotations

import difflib
import hashlib
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .models import (
    AppliedPatch,
    CheckpointRef,
    FileRead,
    PatchSet,
    SearchMatch,
    WorkspaceErrorClass,
    WorkspaceToolError,
)


@dataclass(frozen=True, slots=True)
class _FileState:
    content: bytes | None
    mode: int | None


class Workspace:
    """A filesystem authority rooted at one resolved directory.

    Paths are always workspace-relative. Symlink components are rejected so a
    trusted-looking path cannot redirect a read or write outside the root.
    """

    _IGNORED_PARTS = frozenset({".git", ".pytest_cache", ".ruff_cache", "__pycache__"})

    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int = 1_000_000,
        max_checkpoint_bytes: int = 10_000_000,
    ) -> None:
        root_path = Path(root).resolve(strict=True)
        if not root_path.is_dir():
            raise ValueError("workspace root must be a directory")
        self.root = root_path
        self.max_file_bytes = max_file_bytes
        self.max_checkpoint_bytes = max_checkpoint_bytes
        self._checkpoints: dict[str, dict[str, _FileState]] = {}

    def resolve(self, relative_path: str | Path, *, must_exist: bool = True) -> Path:
        raw = Path(relative_path)
        if raw.is_absolute():
            raise WorkspaceToolError(
                WorkspaceErrorClass.PATH_OUTSIDE_WORKSPACE,
                "absolute paths are not accepted by workspace tools",
            )
        candidate = self.root / raw
        current = self.root
        for part in raw.parts:
            if part in ("", "."):
                continue
            if part == "..":
                raise WorkspaceToolError(
                    WorkspaceErrorClass.PATH_OUTSIDE_WORKSPACE,
                    f"path escapes workspace: {relative_path}",
                )
            current = current / part
            if current.is_symlink():
                raise WorkspaceToolError(
                    WorkspaceErrorClass.SYMLINK_REJECTED,
                    f"symlink path component rejected: {relative_path}",
                )
        resolved_candidate = candidate.resolve(strict=False)
        if not resolved_candidate.is_relative_to(self.root):
            raise WorkspaceToolError(
                WorkspaceErrorClass.PATH_OUTSIDE_WORKSPACE,
                f"path escapes workspace: {relative_path}",
            )
        if must_exist and not candidate.exists():
            raise WorkspaceToolError(
                WorkspaceErrorClass.PATH_NOT_FOUND,
                f"path does not exist: {relative_path}",
            )
        return candidate

    def search(
        self,
        query: str,
        *,
        include: tuple[str, ...] = ("*",),
        regex: bool = False,
        max_results: int = 200,
    ) -> list[SearchMatch]:
        if not query:
            raise WorkspaceToolError(
                WorkspaceErrorClass.INVALID_REQUEST, "search query cannot be empty"
            )
        matcher = re.compile(query) if regex else None
        matches: list[SearchMatch] = []
        for path in sorted(self.root.rglob("*")):
            relative = path.relative_to(self.root)
            if any(part in self._IGNORED_PARTS for part in relative.parts):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            if not any(relative.match(pattern) for pattern in include):
                continue
            try:
                text = self._read_text(path)
            except WorkspaceToolError as exc:
                if exc.error_class in {
                    WorkspaceErrorClass.BINARY_FILE,
                    WorkspaceErrorClass.FILE_TOO_LARGE,
                }:
                    continue
                raise
            for line_number, line in enumerate(text.splitlines(), start=1):
                found = matcher.search(line) if matcher else None
                column = found.start() + 1 if found else line.find(query) + 1
                if column <= 0:
                    continue
                matches.append(
                    SearchMatch(
                        path=relative.as_posix(),
                        line=line_number,
                        column=column,
                        text=line,
                    )
                )
                if len(matches) >= max_results:
                    return matches
        return matches

    def read(self, path: str, *, start_line: int = 1, end_line: int | None = None) -> FileRead:
        candidate = self.resolve(path)
        if not candidate.is_file():
            raise WorkspaceToolError(
                WorkspaceErrorClass.PATH_NOT_FILE, f"path is not a file: {path}"
            )
        text = self._read_text(candidate)
        lines = text.splitlines(keepends=True)
        if start_line < 1 or (end_line is not None and end_line < start_line):
            raise WorkspaceToolError(
                WorkspaceErrorClass.INVALID_REQUEST, "invalid requested line range"
            )
        stop = len(lines) if end_line is None else min(end_line, len(lines))
        content = "".join(lines[start_line - 1 : stop])
        return FileRead(
            path=candidate.relative_to(self.root).as_posix(),
            content=content,
            start_line=start_line,
            end_line=stop,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )

    def apply_patch(self, patch: PatchSet) -> AppliedPatch:
        prepared: dict[Path, tuple[str, str]] = {}
        display_paths: list[str] = []
        for replacement in patch.replacements:
            candidate = self.resolve(replacement.path)
            if not candidate.is_file():
                raise WorkspaceToolError(
                    WorkspaceErrorClass.PATH_NOT_FILE,
                    f"patch target is not a file: {replacement.path}",
                )
            if candidate in prepared:
                original, current = prepared[candidate]
            else:
                original = self._read_text(candidate)
                current = original
            actual_count = current.count(replacement.old)
            if actual_count != replacement.expected_count:
                raise WorkspaceToolError(
                    WorkspaceErrorClass.PATCH_CONFLICT,
                    f"expected {replacement.expected_count} exact occurrence(s) in "
                    f"{replacement.path}, found {actual_count}",
                )
            updated = current.replace(
                replacement.old, replacement.new, replacement.expected_count
            )
            prepared[candidate] = (original, updated)
            display_paths.append(candidate.relative_to(self.root).as_posix())

        checkpoint = self.create_checkpoint(
            tuple(path.relative_to(self.root).as_posix() for path in prepared)
        )
        try:
            for candidate, (_, updated) in prepared.items():
                temporary = candidate.with_name(f".{candidate.name}.{uuid4().hex}.tmp")
                temporary.write_text(updated, encoding="utf-8")
                os.chmod(temporary, candidate.stat().st_mode)
                os.replace(temporary, candidate)
        except Exception:
            self.rollback(checkpoint.checkpoint_id)
            raise
        else:
            self.discard_checkpoint(checkpoint.checkpoint_id)

        diff_parts: list[str] = []
        for candidate, (original, updated) in prepared.items():
            relative = candidate.relative_to(self.root).as_posix()
            diff_parts.extend(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    updated.splitlines(keepends=True),
                    fromfile=f"a/{relative}",
                    tofile=f"b/{relative}",
                )
            )
        return AppliedPatch(
            description=patch.description,
            paths=sorted(set(display_paths)),
            diff="".join(diff_parts),
            evidence=patch.evidence,
        )

    def create_checkpoint(self, paths: Iterable[str]) -> CheckpointRef:
        states: dict[str, _FileState] = {}
        total_bytes = 0
        for relative in sorted(set(paths)):
            candidate = self.resolve(relative, must_exist=False)
            if candidate.exists():
                if not candidate.is_file():
                    raise WorkspaceToolError(
                        WorkspaceErrorClass.PATH_NOT_FILE,
                        f"checkpoint target is not a file: {relative}",
                    )
                content = candidate.read_bytes()
                total_bytes += len(content)
                state = _FileState(content=content, mode=candidate.stat().st_mode)
            else:
                state = _FileState(content=None, mode=None)
            if total_bytes > self.max_checkpoint_bytes:
                raise WorkspaceToolError(
                    WorkspaceErrorClass.FILE_TOO_LARGE,
                    "checkpoint exceeds configured byte budget",
                )
            states[relative] = state
        checkpoint_id = uuid4().hex
        self._checkpoints[checkpoint_id] = states
        return CheckpointRef(checkpoint_id=checkpoint_id, paths=list(states))

    def rollback(self, checkpoint_id: str) -> CheckpointRef:
        states = self._checkpoints.pop(checkpoint_id, None)
        if states is None:
            raise WorkspaceToolError(
                WorkspaceErrorClass.CHECKPOINT_NOT_FOUND,
                f"unknown checkpoint: {checkpoint_id}",
            )
        for relative, state in states.items():
            candidate = self.resolve(relative, must_exist=False)
            if state.content is None:
                if candidate.exists() and candidate.is_file():
                    candidate.unlink()
                continue
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(state.content)
            if state.mode is not None:
                os.chmod(candidate, state.mode)
        return CheckpointRef(checkpoint_id=checkpoint_id, paths=list(states))

    def discard_checkpoint(self, checkpoint_id: str) -> None:
        if self._checkpoints.pop(checkpoint_id, None) is None:
            raise WorkspaceToolError(
                WorkspaceErrorClass.CHECKPOINT_NOT_FOUND,
                f"unknown checkpoint: {checkpoint_id}",
            )

    def _read_text(self, path: Path) -> str:
        size = path.stat().st_size
        if size > self.max_file_bytes:
            raise WorkspaceToolError(
                WorkspaceErrorClass.FILE_TOO_LARGE,
                f"file exceeds configured byte limit: {path.relative_to(self.root)}",
            )
        content = path.read_bytes()
        if b"\x00" in content:
            raise WorkspaceToolError(
                WorkspaceErrorClass.BINARY_FILE,
                f"binary file rejected: {path.relative_to(self.root)}",
            )
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceToolError(
                WorkspaceErrorClass.BINARY_FILE,
                f"non-UTF-8 file rejected: {path.relative_to(self.root)}",
            ) from exc
