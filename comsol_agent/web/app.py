"""FastAPI entry point for the local COMSOL Agent presentation UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError as exc:  # pragma: no cover - exercised by the console entry point
    raise RuntimeError(
        "Web dependencies are missing. Install with: pip install -e '.[web]'"
    ) from exc

from comsol_agent.v2.web import BearingV2Driver, V2SessionManager
from comsol_agent.web.demo_case import build_demo_case
from comsol_agent.web.runtime import WebSessionManager

STATIC_ROOT = Path(__file__).resolve().parent / "static"
manager = WebSessionManager()
v2_manager = V2SessionManager(BearingV2Driver())
app = FastAPI(title="COMSOL Bearing Agent Showcase", version="0.1.0")


class ChatRequest(BaseModel):
    requirement: str
    mode: str = "demo"
    session_id: str | None = None


class V2SessionRequest(BaseModel):
    requirement: str
    mode: str = "live"


class V2CancelRequest(BaseModel):
    reason: str = "cancelled by user"


def _sse(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or event.get("kind") or "message")
    return f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_ROOT / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict[str, Any]:
    demo = build_demo_case()
    return {"status": "ok", "demo_available": demo["available"]}


@app.get("/api/demo")
def demo() -> dict[str, Any]:
    payload = build_demo_case()
    return {
        "title": payload["title"],
        "requirement": payload["requirement"],
        "available": payload["available"],
        "metrics": payload["metrics"],
    }


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    if req.mode not in {"demo", "live"}:
        raise HTTPException(status_code=422, detail="mode must be 'demo' or 'live'")

    async def stream():
        async for event in manager.stream(
            req.requirement,
            mode=req.mode,
            session_id=req.session_id,
        ):
            yield _sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/sessions/{session_id}")
def session(session_id: str) -> dict[str, Any]:
    try:
        return manager.get(session_id).snapshot()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


@app.post("/api/v2/sessions", status_code=202)
async def create_v2_session(req: V2SessionRequest) -> dict[str, Any]:
    """Start a real V2 turn; plan_only never claims COMSOL evidence."""
    try:
        return await v2_manager.create(req.requirement, mode=req.mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v2/sessions/{session_id}/turns", status_code=202)
async def create_v2_turn(session_id: str, req: V2SessionRequest) -> dict[str, Any]:
    try:
        return await v2_manager.submit_turn(session_id, req.requirement, mode=req.mode)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="V2 session not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v2/sessions/{session_id}")
def v2_session(session_id: str) -> dict[str, Any]:
    try:
        return v2_manager.snapshot(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="V2 session not found") from exc


@app.get("/api/v2/sessions/{session_id}/events")
async def v2_events(session_id: str, after: int = 0) -> StreamingResponse:
    try:
        v2_manager.snapshot(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="V2 session not found") from exc

    async def stream():
        async for event in v2_manager.events(session_id, after=after):
            yield _sse(event.model_dump(mode="json"))

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v2/sessions/{session_id}/pause")
async def pause_v2_session(session_id: str) -> dict[str, Any]:
    return await _v2_control(v2_manager.pause, session_id)


@app.post("/api/v2/sessions/{session_id}/resume")
async def resume_v2_session(session_id: str) -> dict[str, Any]:
    return await _v2_control(v2_manager.resume, session_id)


@app.post("/api/v2/sessions/{session_id}/cancel")
async def cancel_v2_session(
    session_id: str, req: V2CancelRequest
) -> dict[str, Any]:
    try:
        return await v2_manager.cancel(session_id, req.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="V2 session not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v2/sessions/{session_id}/artifacts/{artifact_id}")
def v2_artifact_file(session_id: str, artifact_id: str) -> FileResponse:
    try:
        item, path = v2_manager.artifact(session_id, artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="V2 artifact not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail="V2 artifact file is missing") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(path, media_type=item.media_type, filename=item.name)


async def _v2_control(operation, session_id: str) -> dict[str, Any]:
    try:
        return await operation(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="V2 session not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/artifacts/{session_id}")
def artifacts(session_id: str) -> dict[str, Any]:
    try:
        snapshot = manager.get(session_id).snapshot()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return {
        "session_id": session_id,
        "items": snapshot["artifacts"],
        "metrics": snapshot["metrics"],
        "roller_loads": snapshot["roller_loads"],
        "code": snapshot["code"],
    }


@app.get("/api/artifacts/{session_id}/{artifact_id}")
def artifact_file(session_id: str, artifact_id: str) -> FileResponse:
    try:
        session_obj = manager.get(session_id)
        artifact = session_obj.artifacts[artifact_id]
    except (KeyError, IndexError) as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc
    if not artifact.path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file is missing")
    return FileResponse(artifact.path)


app.mount("/static", StaticFiles(directory=str(STATIC_ROOT)), name="static")


def main() -> None:
    """Run the local showcase server."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("Install web dependencies with: pip install -e '.[web]'") from exc
    uvicorn.run("comsol_agent.web.app:app", host="127.0.0.1", port=7860, reload=False)
