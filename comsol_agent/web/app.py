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

from comsol_agent.web.demo_case import build_demo_case
from comsol_agent.web.runtime import WebSessionManager

STATIC_ROOT = Path(__file__).resolve().parent / "static"
manager = WebSessionManager()
app = FastAPI(title="COMSOL Bearing Agent Showcase", version="0.1.0")


class ChatRequest(BaseModel):
    requirement: str
    mode: str = "demo"
    session_id: str | None = None


def _sse(event: dict[str, Any]) -> str:
    event_type = str(event.get("type", "message"))
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
