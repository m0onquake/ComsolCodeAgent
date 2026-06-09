"""File system and shell execution tools for the agent."""

from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path


def _allowed_roots() -> list[Path]:
    """Return allowed filesystem roots for agent file and shell operations."""
    roots = [Path.cwd().resolve(), (Path.home() / ".comsol_agent").resolve()]
    extra = os.environ.get("COMSOL_AGENT_ALLOWED_PATHS", "")
    for raw_path in extra.split(os.pathsep):
        if raw_path.strip():
            roots.append(Path(raw_path).expanduser().resolve())
    return roots


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_allowed_path(path_value: str | None, *, must_exist: bool = False) -> tuple[Path | None, str | None]:
    """Resolve a path and ensure it is inside an allowed root."""
    path = Path(path_value or ".").expanduser().resolve()
    if must_exist and not path.exists():
        return None, f"Path not found: {path_value}"

    roots = _allowed_roots()
    if not any(_is_within(path, root) or path == root for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        return None, f"Path is outside allowed roots: {path}. Allowed roots: {allowed}"

    return path, None


def _format_with_line_numbers(lines: list[str], start: int = 1) -> str:
    """Return file content with stable line numbers for LLM consumption."""
    width = len(str(start + len(lines) - 1))
    return "".join(
        f"{line_no:>{width}} | {line}"
        for line_no, line in enumerate(lines, start=start)
    )


def _blocked_shell_reason(command: str) -> str | None:
    """Return a reason if a shell command violates the safety policy."""
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return f"Could not parse shell command safely: {exc}"

    if not parts:
        return "Empty command."

    executable = Path(parts[0]).name.lower()
    if executable in {"sudo", "su"}:
        return "Privileged shell commands are not allowed."

    if executable == "rm":
        flags = "".join(part for part in parts[1:] if part.startswith("-"))
        recursive = "r" in flags or "R" in flags
        forced = "f" in flags
        targets = [part for part in parts[1:] if not part.startswith("-")]
        dangerous_targets = {"/", "/*", "~", "~/", "$HOME", "${HOME}"}
        if recursive and forced and any(target in dangerous_targets for target in targets):
            return "Dangerous recursive deletion is not allowed."

    return None


async def file_read(filepath: str, max_lines: int = 500) -> dict:
    """Read a file from the filesystem.

    Args:
        filepath: Absolute path to the file.
        max_lines: Maximum number of lines to read.

    Returns:
        dict with file contents or error.
    """
    path, error = _resolve_allowed_path(filepath, must_exist=True)
    if error:
        return {"success": False, "error": error}
    assert path is not None
    if path.is_dir():
        return {"success": False, "error": f"Path is a directory: {filepath}"}

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        total_lines = len(lines)
        if total_lines > max_lines:
            lines = lines[:max_lines]
            truncated = True
        else:
            truncated = False

        content = _format_with_line_numbers(lines)
        result = {
            "success": True,
            "filepath": str(path),
            "content": content,
            "total_lines": total_lines,
        }
        if truncated:
            result["warning"] = f"File truncated. Showing {max_lines}/{total_lines} lines."
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def file_write(filepath: str, content: str) -> dict:
    """Write content to a file.

    Args:
        filepath: Absolute path for the output file.
        content: Content to write.

    Returns:
        dict with status.
    """
    path, error = _resolve_allowed_path(filepath)
    if error:
        return {"success": False, "error": error}
    assert path is not None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {
            "success": True,
            "filepath": str(path),
            "size_bytes": path.stat().st_size,
            "message": f"File written: {path} ({path.stat().st_size} bytes)",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def file_list(directory: str = ".", pattern: str = "*") -> dict:
    """List files in a directory.

    Args:
        directory: Directory to list.
        pattern: Glob pattern to filter by.

    Returns:
        dict with file list.
    """
    path, error = _resolve_allowed_path(directory, must_exist=True)
    if error:
        return {"success": False, "error": error}
    assert path is not None
    if not path.is_dir():
        return {"success": False, "error": f"Not a directory: {directory}"}

    try:
        files = list(path.glob(pattern))
        result = []
        for f in files[:200]:  # Limit to 200 entries
            stat = f.stat()
            result.append({
                "name": f.name,
                "path": str(f),
                "type": "directory" if f.is_dir() else "file",
                "size_bytes": stat.st_size if not f.is_dir() else None,
            })
        return {
            "success": True,
            "directory": str(path),
            "pattern": pattern,
            "count": len(result),
            "entries": result,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def shell_execute(command: str, working_dir: str | None = None, timeout: int = 120) -> dict:
    """Execute a shell command.

    Args:
        command: The shell command to run.
        working_dir: Working directory for the command.
        timeout: Timeout in seconds (max 600).

    Returns:
        dict with stdout, stderr, and return code.
    """
    timeout = min(timeout, 600)
    blocked_reason = _blocked_shell_reason(command)
    if blocked_reason:
        return {"success": False, "error": blocked_reason}

    cwd_path, error = _resolve_allowed_path(working_dir or ".", must_exist=True)
    if error:
        return {"success": False, "error": error}
    assert cwd_path is not None
    if not cwd_path.is_dir():
        return {"success": False, "error": f"Working directory is not a directory: {cwd_path}"}

    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd_path),
            ),
            timeout=None,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")

        # Truncate very long outputs
        max_len = 10000
        if len(stdout_str) > max_len:
            stdout_str = stdout_str[:max_len] + f"\n... (truncated, total {len(stdout_str)} chars)"
        if len(stderr_str) > max_len:
            stderr_str = stderr_str[:max_len] + f"\n... (truncated, total {len(stderr_str)} chars)"

        return {
            "success": proc.returncode == 0,
            "return_code": proc.returncode,
            "stdout": stdout_str.strip() or "(empty)",
            "stderr": stderr_str.strip() or "(empty)",
        }
    except asyncio.TimeoutError:
        return {"success": False, "error": f"Command timed out after {timeout}s: {command}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
