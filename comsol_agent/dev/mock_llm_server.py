"""Tiny OpenAI-compatible mock LLM server for local API wiring tests.

Run with:
    python3 -m comsol_agent.dev.mock_llm_server --port 8008

Then configure:
    COMSOL_AGENT_PROVIDER=openai
    OPENAI_API_KEY=mock
    COMSOL_AGENT_BASE_URL=http://127.0.0.1:8008/v1
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def build_chat_completion_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic OpenAI chat-completions style response."""
    model = str(payload.get("model") or "mock-llm")
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    last_user = _last_user_message(messages)
    tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []

    content = (
        "[mock-llm] Received the request successfully. "
        f"Model={model}; messages={len(messages)}; tools={len(tools)}. "
        f"Last user message: {last_user[:240]}"
    )

    prompt_tokens = max(1, sum(len(str(message.get("content", ""))) for message in messages) // 4)
    completion_tokens = max(1, len(content) // 4)
    return {
        "id": f"chatcmpl-mock-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


class MockLLMHandler(BaseHTTPRequestHandler):
    """HTTP handler for a small subset of the OpenAI-compatible API."""

    server_version = "COMSOLAgentMockLLM/0.1"

    def do_GET(self) -> None:
        if self.path in {"/health", "/v1/health"}:
            self._send_json({"ok": True, "service": "mock-llm"})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if self.path not in {"/chat/completions", "/v1/chat/completions"}:
            self._send_json({"error": f"unsupported path: {self.path}"}, status=404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(body)
        except Exception as exc:
            self._send_json({"error": f"invalid JSON payload: {exc}"}, status=400)
            return

        if payload.get("stream"):
            self._send_json({"error": "streaming is not implemented in mock server"}, status=400)
            return

        self._send_json(build_chat_completion_response(payload))

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[mock-llm] {self.address_string()} - {fmt % args}")

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str = "127.0.0.1", port: int = 8008) -> None:
    """Run the mock LLM server until interrupted."""
    server = ThreadingHTTPServer((host, port), MockLLMHandler)
    print(f"Mock LLM server listening on http://{host}:{port}/v1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping mock LLM server.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local OpenAI-compatible mock LLM server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", default=8008, type=int, help="Port to bind.")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


def _last_user_message(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


if __name__ == "__main__":
    main()
