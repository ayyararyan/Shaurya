"""ANL-03 read-only dashboard server.

Three GET routes and nothing else. There is no POST/PUT/DELETE handler and no order-path
import anywhere in this module, so the server cannot place, modify, or influence an order
even by accident (D19, and `ANL.md`'s "dashboards and servers are read-only").
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from shaurya.analytics.dashboard import build_history_payload, build_payload, render_html
from shaurya.analytics.surface_feed import SurfaceEngine

ALLOWED_METHODS = ("GET", "HEAD")


class DashboardState:
    """Thread-safe view over the engine for the HTTP thread pool."""

    def __init__(self, engine: SurfaceEngine, *, title: str, source: str) -> None:
        self.engine = engine
        self.title = title
        self.source = source
        self._lock = threading.Lock()

    def payload(self) -> dict[str, Any]:
        with self._lock:
            return build_payload(self.engine, title=self.title, source=self.source)

    def history(self, index: int) -> dict[str, Any]:
        with self._lock:
            return build_history_payload(self.engine, index)

    def html(self) -> str:
        return render_html(self.payload())


class _Handler(BaseHTTPRequestHandler):
    server_version = "ShauryaANL03/1.0"
    state: DashboardState

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(self.state.html().encode(), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/state":
            body = json.dumps(self.state.payload(), default=str).encode()
            self._send(body, "application/json")
            return
        if parsed.path == "/api/history":
            raw = parse_qs(parsed.query).get("index", ["0"])[0]
            try:
                index = int(raw)
            except ValueError:
                self._send(b'{"error":"index must be an integer"}', "application/json", 400)
                return
            try:
                body = json.dumps(self.state.history(index), default=str).encode()
            except IndexError:
                self._send(b'{"error":"no snapshots yet"}', "application/json", 404)
                return
            self._send(body, "application/json")
            return
        self._send(b'{"error":"not found"}', "application/json", 404)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib signature
        self.do_GET()


def build_server(state: DashboardState, *, host: str, port: int) -> ThreadingHTTPServer:
    handler = type("_BoundHandler", (_Handler,), {"state": state})
    return ThreadingHTTPServer((host, port), handler)


def serve_in_background(
    state: DashboardState, *, host: str = "127.0.0.1", port: int = 8765
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = build_server(state, host=host, port=port)
    thread = threading.Thread(target=server.serve_forever, name="anl03-dashboard", daemon=True)
    thread.start()
    return server, thread
