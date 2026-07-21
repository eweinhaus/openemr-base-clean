#!/usr/bin/env python3
"""
Minimal stub Copilot sidecar — stdlib only.

Validates COPILOT_INTERNAL_SECRET and emits hybrid SSE (progress → clinical → done).
Replaced by PRD 03 LangGraph sidecar.
"""

from __future__ import annotations

import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

HOST = "0.0.0.0"
PORT = 8080
SECRET_HEADER = "X-Copilot-Internal-Secret"
CORRELATION_HEADER = "X-Correlation-Id"


def required_secret() -> str:
    secret = os.environ.get("COPILOT_INTERNAL_SECRET")
    if not secret:
        print("COPILOT_INTERNAL_SECRET is required", file=sys.stderr)
        sys.exit(1)
    return secret


def format_sse(event: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, str]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class StubHandler(BaseHTTPRequestHandler):
    server_secret: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.address_string(), self.log_date_time_string(), fmt % args)
        )

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/chat":
            self.send_error(404)
            return

        provided = self.headers.get(SECRET_HEADER, "")
        if not provided or not hmac.compare_digest(provided, self.server_secret):
            send_json(self, 401, {"error": "unauthorized"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            send_json(self, 400, {"error": "invalid_json"})
            return

        if not isinstance(body, dict):
            send_json(self, 400, {"error": "invalid_json"})
            return

        correlation_id = body.get("correlation_id") or self.headers.get(CORRELATION_HEADER) or ""
        message = body.get("message", "")
        pid = body.get("pid")

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        self.wfile.write(format_sse("progress", {"message": "Working…"}))
        self.wfile.flush()

        time.sleep(0.2)

        clinical_text = f"Stub sidecar: received {message} (pid={pid})"
        self.wfile.write(format_sse("clinical", {"text": clinical_text}))
        self.wfile.flush()

        self.wfile.write(format_sse("done", {"correlation_id": correlation_id}))
        self.wfile.flush()


def main() -> None:
    secret = required_secret()
    StubHandler.server_secret = secret

    server = HTTPServer((HOST, PORT), StubHandler)
    print(f"Stub sidecar listening on {HOST}:{PORT}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
