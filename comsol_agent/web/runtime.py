"""Session and streaming adapters between FastAPI and the existing AgentLoop."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from comsol_agent.agent.loop import AgentLoop
from comsol_agent.agent.tools_bootstrap import register_all_tools
from comsol_agent.cli.config import Config, get_config_dir, load_config
from comsol_agent.llm.router import create_provider_from_plan, plan_route
from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.memory.session_store import SessionStore
from comsol_agent.simulation.skills import seed_builtin_templates
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.web.demo_case import DEMO_STAGES, PROJECT_ROOT, build_demo_case


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _preview(value: Any, limit: int = 260) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class Artifact:
    id: str
    name: str
    kind: str
    path: Path

    def public(self, session_id: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "url": f"/api/artifacts/{session_id}/{self.id}",
            "size": self.path.stat().st_size if self.path.exists() else 0,
        }


@dataclass
class WebSession:
    id: str
    mode: str
    status: str = "idle"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    response: str = ""
    code: str = ""
    metrics: list[dict[str, Any]] = field(default_factory=list)
    roller_loads: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    agent: AgentLoop | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.id,
            "mode": self.mode,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "response": self.response,
            "code": self.code,
            "metrics": self.metrics,
            "roller_loads": self.roller_loads,
            "events": list(self.events),
            "artifacts": [item.public(self.id) for item in self.artifacts.values()],
        }


class WebSessionManager:
    """Own web sessions while delegating all live reasoning to AgentLoop."""

    def __init__(self, config: Config | None = None):
        self.config = config or load_config()
        self.sessions: dict[str, WebSession] = {}

    def get_or_create(self, session_id: str | None, mode: str) -> WebSession:
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        session = WebSession(id=session_id or str(uuid4()), mode=mode)
        self.sessions[session.id] = session
        return session

    def get(self, session_id: str) -> WebSession:
        if session_id not in self.sessions:
            raise KeyError(session_id)
        return self.sessions[session_id]

    async def stream(
        self,
        requirement: str,
        *,
        mode: str,
        session_id: str | None = None,
    ):
        session = self.get_or_create(session_id, mode)
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        def emit(event_type: str, **payload: Any) -> None:
            event = {"type": event_type, "timestamp": _utc_now(), **payload}
            session.events.append(event)
            session.updated_at = event["timestamp"]
            queue.put_nowait(event)

        async def worker() -> None:
            async with session.lock:
                try:
                    session.status = "running"
                    emit("session", session_id=session.id, mode=mode, status="running")
                    if mode == "demo":
                        await self._run_demo(session, emit)
                    else:
                        await self._run_live(session, requirement, emit)
                    session.status = "completed"
                    emit("complete", session=session.snapshot())
                except Exception as exc:
                    session.status = "failed"
                    emit("error", message=str(exc), error_type=exc.__class__.__name__)
                finally:
                    queue.put_nowait(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            if task.done():
                task.result()

    async def _run_demo(self, session: WebSession, emit: Callable[..., None]) -> None:
        case = build_demo_case()
        if not case["available"]:
            raise RuntimeError("演示案例产物不存在，请先生成 runtime_smoke 严格轴承案例。")
        delay = max(0.0, float(os.getenv("COMSOL_AGENT_WEB_DEMO_DELAY", "0.55")))
        session.code = case["code"]
        session.metrics = case["metrics"]
        session.roller_loads = case["roller_loads"]
        session.artifacts = {
            item["id"]: Artifact(item["id"], item["name"], item["kind"], item["path"])
            for item in case["artifacts"]
        }
        for index, (stage, title, detail) in enumerate(DEMO_STAGES, start=1):
            emit(
                "stage",
                stage=stage,
                title=title,
                detail=detail,
                index=index,
                total=len(DEMO_STAGES),
                status="running",
            )
            if delay:
                await asyncio.sleep(delay)
            emit("stage_result", stage=stage, title=title, status="passed")
            if stage == "codegen":
                emit("code", code=session.code)
            if stage in {"preload", "solve", "audit"}:
                emit(
                    "artifacts",
                    items=[item.public(session.id) for item in session.artifacts.values()],
                    metrics=session.metrics,
                    roller_loads=session.roller_loads,
                )
        session.response = (
            "严格自由生成案例已完成：12 个滚子的载荷分布与 +X 径向载荷方向一致，"
            "最终载荷、支承反力与外滚道接触均通过物理审计。"
        )
        emit("response", text=session.response)

    async def _run_live(
        self,
        session: WebSession,
        requirement: str,
        emit: Callable[..., None],
    ) -> None:
        if not requirement.strip():
            raise ValueError("需求描述不能为空。")
        if os.getenv("COMSOL_AGENT_WEB_AUTOSTART_COMSOL", "1") != "0":
            client = COMSOLClient.get_instance()
            if not client.is_running:
                emit(
                    "stage",
                    stage="runtime",
                    title="连接 COMSOL",
                    detail="正在启动本机 MPh/COMSOL 会话",
                    status="running",
                )
                try:
                    await asyncio.to_thread(
                        client.start,
                        version=self.config.comsol.version,
                        executable_path=self.config.comsol.executable_path,
                    )
                    emit("stage_result", stage="runtime", title="连接 COMSOL", status="passed")
                except Exception as exc:
                    emit("tool_result", name="comsol_start", failed=True, detail=str(exc))
        if session.agent is None:
            session.agent = self._build_agent(session, emit)
        else:
            self._attach_callbacks(session, emit)
        emit(
            "stage",
            stage="agent",
            title="Agent 执行",
            detail="进入自主规划与工具调用循环",
            status="running",
        )
        try:
            session.response = await session.agent.run(requirement)
        finally:
            # Keep completed COMSOL work visible even if a later LLM turn fails.
            self._collect_live_artifacts(session)
            self._emit_live_outputs(session, emit)
        emit("response", text=session.response)

    def _build_agent(self, session: WebSession, emit: Callable[..., None]) -> AgentLoop:
        register_all_tools()
        route = plan_route(
            "text_response",
            preferred_provider=self.config.llm.provider,
            preferred_model=self.config.llm.model,
        )
        provider = create_provider_from_plan(
            route,
            api_key=self.config.llm.api_key,
            base_url=self.config.llm.base_url,
        )
        app_dir = get_config_dir()
        archive_store = ArchiveStore(app_dir / "archive" / "archive.sqlite3")
        seed_builtin_templates(archive_store)
        session_store = SessionStore(
            app_dir / "sessions",
            session_id=f"web_{session.id}",
            archive_store=archive_store,
        )
        agent = AgentLoop(
            llm_provider=provider,
            config=self.config,
            session_store=session_store,
            archive_store=archive_store,
        )
        session.agent = agent
        self._attach_callbacks(session, emit)
        return agent

    def _attach_callbacks(self, session: WebSession, emit: Callable[..., None]) -> None:
        if session.agent is None:
            return

        def on_tool_call(name: str, args: dict[str, Any]) -> None:
            emit("tool_call", name=name, arguments=args, detail=_preview(args))
            self._capture_code(session, name, args)
            self._find_and_add_artifacts(session, args)
            self._emit_live_outputs(session, emit)

        def on_tool_result(name: str, output: str, failed: bool) -> None:
            emit("tool_result", name=name, failed=failed, detail=_preview(output))
            try:
                payload = json.loads(output)
            except (json.JSONDecodeError, TypeError):
                payload = output
            self._capture_code(session, name, payload)
            self._capture_metric(session, name, payload)
            self._find_and_add_artifacts(session, payload)
            self._emit_live_outputs(session, emit)

        session.agent.on_tool_call = on_tool_call
        session.agent.on_tool_result = on_tool_result

    def _emit_live_outputs(self, session: WebSession, emit: Callable[..., None]) -> None:
        if session.code:
            emit("code", code=session.code)
        emit(
            "artifacts",
            items=[item.public(session.id) for item in session.artifacts.values()],
            metrics=session.metrics,
            roller_loads=session.roller_loads,
        )

    @staticmethod
    def _capture_code(session: WebSession, tool_name: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        candidates: list[Any] = [payload.get("java_code")]
        template = payload.get("template")
        if isinstance(template, dict):
            candidates.append(template.get("java_code"))
        for code in candidates:
            if isinstance(code, str) and code.strip():
                # Keep the primary model program visible instead of replacing it
                # with a later one-line probe or repair snippet.
                if len(code) >= len(session.code):
                    session.code = code
                return

    @staticmethod
    def _capture_metric(session: WebSession, tool_name: str, payload: Any) -> None:
        valid_payload = isinstance(payload, dict) and payload.get("success")
        if tool_name != "comsol_evaluate" or not valid_payload:
            return
        expression = str(payload.get("expression", ""))
        match = re.search(r"/\s*1\s*\[([^\]]+)\]", expression)
        if not match:
            return
        unit = match.group(1)
        stats = payload.get("statistics")
        value = stats.get("max") if isinstance(stats, dict) else payload.get("value")
        if not isinstance(value, (int, float)):
            return
        metric = {
            "label": expression,
            "value": f"{value:.6g} {unit}",
            "expression": expression,
            "unit": unit,
            "tone": "blue",
        }
        session.metrics = [item for item in session.metrics if item.get("expression") != expression]
        session.metrics.append(metric)

    def _collect_live_artifacts(self, session: WebSession) -> None:
        if session.agent is None:
            return
        for message in session.agent.state.messages:
            role = message.get("role")
            if role == "tool":
                content = message.get("content")
                try:
                    payload = json.loads(content) if isinstance(content, str) else content
                except json.JSONDecodeError:
                    payload = content
                self._find_and_add_artifacts(session, payload)
            elif role == "assistant":
                for tool_call in message.get("tool_calls") or []:
                    self._find_and_add_artifacts(session, tool_call.get("arguments", {}))

    def _find_and_add_artifacts(self, session: WebSession, value: Any) -> None:
        candidates: set[Path] = set()
        self._find_paths(value, candidates)

        allowed_extensions = {
            ".png",
            ".jpg",
            ".jpeg",
            ".svg",
            ".json",
            ".csv",
            ".java",
            ".pyfrag",
            ".mph",
            ".md",
        }
        for path in sorted(candidates):
            resolved = path.expanduser().resolve()
            if not resolved.is_file() or resolved.suffix.lower() not in allowed_extensions:
                continue
            if not self._is_allowed_path(resolved):
                continue
            kind = self._kind_for_path(resolved)
            path_digest = hashlib.sha1(str(resolved).encode()).hexdigest()[:12]
            artifact_id = f"live_{path_digest}"
            session.artifacts[artifact_id] = Artifact(artifact_id, resolved.name, kind, resolved)
            if kind == "code" and not session.code:
                session.code = resolved.read_text(encoding="utf-8", errors="replace")

    def _find_paths(self, value: Any, paths: set[Path]) -> None:
        if isinstance(value, dict):
            for child in value.values():
                self._find_paths(child, paths)
        elif isinstance(value, list):
            for child in value:
                self._find_paths(child, paths)
        elif isinstance(value, str):
            if 1 < len(value) < 1200:
                candidate = Path(value)
                if candidate.is_absolute() or "/" in value:
                    paths.add(candidate if candidate.is_absolute() else PROJECT_ROOT / candidate)
            for match in re.findall(
                r"(?:[A-Za-z]:)?[/~][^\n\r\"']+?\.(?:png|jpe?g|svg|json|csv|java|pyfrag|mph|md)",
                value,
                flags=re.IGNORECASE,
            ):
                paths.add(Path(match))

    @staticmethod
    def _kind_for_path(path: Path) -> str:
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg"}:
            return "image"
        if path.suffix.lower() in {".java", ".pyfrag"}:
            return "code"
        return path.suffix.lower().lstrip(".") or "file"

    @staticmethod
    def _is_allowed_path(path: Path) -> bool:
        roots = (PROJECT_ROOT.resolve(), get_config_dir().resolve())
        return any(path == root or root in path.parents for root in roots)
