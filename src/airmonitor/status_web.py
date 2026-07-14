"""Small read-only HTTP service for the AirMonitor appliance landing page."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import mimetypes
import os
from pathlib import PurePosixPath
from typing import Iterable

from airmonitor.status import DEFAULT_DATABASE, collect_status


STATIC = files("airmonitor").joinpath("status_static")


class StatusHandler(BaseHTTPRequestHandler):
    server_version = "AirMonitorStatus"

    def _headers(self, status: int, content_type: str, length: int, cache: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; connect-src 'self'")
        self.end_headers()

    def _send(self, status: int, body: bytes, content_type: str, cache: str = "no-store") -> None:
        self._headers(status, content_type, len(body), cache)
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/status":
            body = json.dumps(collect_status(self.server.database), separators=(",", ":")).encode()
            self._send(200, body, "application/json; charset=utf-8")
            return
        if path == "/healthz":
            self._send(200, b'{"ok":true}', "application/json; charset=utf-8")
            return
        if path == "/":
            path = "/index.html"
        if path.startswith("/assets/"):
            path = path.removeprefix("/assets")
        name = PurePosixPath(path).name
        if name not in {"index.html", "app.js", "style.css", "airmonitor-logo-300px.webp", "favicon.ico"}:
            self._send(404, b"Not found\n", "text/plain; charset=utf-8")
            return
        resource = STATIC.joinpath(name)
        try:
            body = resource.read_bytes()
        except (FileNotFoundError, OSError):
            self._send(404, b"Not found\n", "text/plain; charset=utf-8")
            return
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._send(200, body, content_type, "public, max-age=3600")

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


class StatusServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], database: str):
        super().__init__(address, StatusHandler)
        self.database = database


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the AirMonitor status page")
    parser.add_argument("--host", default=os.environ.get("AIRMONITOR_STATUS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AIRMONITOR_STATUS_PORT", "8080")))
    parser.add_argument("--database", default=os.environ.get("AIRMONITOR_DATABASE", DEFAULT_DATABASE))
    args = parser.parse_args(list(argv) if argv is not None else None)
    server = StatusServer((args.host, args.port), args.database)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
