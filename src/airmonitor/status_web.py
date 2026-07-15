"""AirMonitor appliance UI with public status and authenticated administration."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import mimetypes
import os
from pathlib import PurePosixPath
import subprocess
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from airmonitor.status import DEFAULT_DATABASE, collect_status


STATIC = files("airmonitor").joinpath("status_static")
GRAFANA_API = os.environ.get("AIRMONITOR_GRAFANA_API", "http://127.0.0.1:3000")
PUBLIC_ORIGIN = os.environ.get("AIRMONITOR_PUBLIC_ORIGIN", "https://airmonitor.example.com")
CONTROL_HELPER = os.environ.get("AIRMONITOR_CONTROL_HELPER", "/usr/local/sbin/airmonitor-service-control")
CONTROLLED_SERVICES = (
    "airmonitor.service",
    "airmonitor-sps30.service",
    "airmonitor-printer-mqtt.service",
    "airmonitor-bento.service",
    "airmonitor-levoit.service",
    "grafana-server.service",
    "mosquitto.service",
)
CONTROL_ACTIONS = ("start", "stop", "restart", "enable", "disable")
SERVICE_ACTIONS = {
    "airmonitor.service": CONTROL_ACTIONS,
    "airmonitor-sps30.service": CONTROL_ACTIONS,
    "airmonitor-printer-mqtt.service": CONTROL_ACTIONS,
    "airmonitor-bento.service": CONTROL_ACTIONS,
    "airmonitor-levoit.service": CONTROL_ACTIONS,
    "grafana-server.service": ("restart",),
    "mosquitto.service": ("restart",),
}


def grafana_user(cookie: str | None, api_url: str = GRAFANA_API) -> dict | None:
    """Resolve the current browser session against Grafana, the identity source."""
    if not cookie:
        return None
    request = Request(f"{api_url.rstrip('/')}/api/user", headers={"Cookie": cookie})
    try:
        with urlopen(request, timeout=3) as response:
            if response.status != 200:
                return None
            value = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and value.get("login") else None


def service_enabled(service: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-enabled", service],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"
    return (result.stdout or result.stderr).strip() or "unknown"


def service_status(service: str) -> str:
    """Return systemctl-compatible status text for an allowlisted service."""
    if service not in CONTROLLED_SERVICES:
        raise ValueError("Unsupported service")
    try:
        result = subprocess.run(
            ["systemctl", "status", "--no-pager", "--full", service],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("systemctl status unavailable") from error
    return (result.stdout or result.stderr).strip()


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

    def _json(self, status: int, value: object) -> None:
        self._send(status, json.dumps(value, separators=(",", ":")).encode(), "application/json; charset=utf-8")

    def _current_user(self) -> dict | None:
        return grafana_user(self.headers.get("Cookie"), self.server.grafana_api)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        request_url = urlsplit(self.path)
        path = request_url.path
        if path == "/api/status":
            self._json(200, collect_status(self.server.database))
            return
        if path == "/api/session":
            user = self._current_user()
            if not user:
                self._json(200, {"authenticated": False})
                return
            admin = bool(user.get("isGrafanaAdmin"))
            self._json(200, {
                "authenticated": True,
                "user": {
                    "login": user.get("login"),
                    "name": user.get("name") or user.get("login"),
                    "email": user.get("email"),
                    "role": "Admin" if admin else user.get("orgRole", "Viewer"),
                    "admin": admin,
                },
                "services": {
                    name: {"enabled": service_enabled(name), "actions": SERVICE_ACTIONS[name]}
                    for name in CONTROLLED_SERVICES
                } if admin else {},
            })
            return
        if path == "/api/services/status":
            user = self._current_user()
            if not user or not bool(user.get("isGrafanaAdmin")):
                self._json(403, {"error": "Grafana administrator access required"})
                return
            service = parse_qs(request_url.query).get("service", [None])[0]
            if service not in CONTROLLED_SERVICES:
                self._json(400, {"error": "Unsupported service"})
                return
            try:
                output = service_status(service)
            except RuntimeError as error:
                self._json(503, {"error": str(error)})
                return
            self._json(200, {"service": service, "output": output})
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
        cache = "no-store" if name == "index.html" else "public, max-age=3600"
        self._send(200, body, content_type, cache)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/api/services/control":
            self._json(404, {"error": "Not found"})
            return
        if self.headers.get("Origin") != self.server.public_origin or self.headers.get("X-AirMonitor-Action") != "service-control":
            self._json(403, {"error": "Request origin rejected"})
            return
        user = self._current_user()
        if not user or not bool(user.get("isGrafanaAdmin")):
            self._json(403, {"error": "Grafana administrator access required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 4096:
            self._json(400, {"error": "Invalid request body"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "Invalid JSON"})
            return
        service = payload.get("service") if isinstance(payload, dict) else None
        action = payload.get("action") if isinstance(payload, dict) else None
        if service not in SERVICE_ACTIONS or action not in SERVICE_ACTIONS[service]:
            self._json(400, {"error": "Unsupported service or action"})
            return
        try:
            result = subprocess.run(
                ["sudo", self.server.control_helper, action, service],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._json(503, {"error": "Service control helper unavailable"})
            return
        if result.returncode:
            self._json(500, {"error": (result.stderr or result.stdout).strip() or "Service action failed"})
            return
        try:
            output = service_status(service)
        except RuntimeError:
            output = "Service action succeeded, but systemctl status was unavailable."
        self._json(200, {"ok": True, "service": service, "action": action, "output": output})

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


class StatusServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        database: str,
        *,
        grafana_api: str = GRAFANA_API,
        public_origin: str = PUBLIC_ORIGIN,
        control_helper: str = CONTROL_HELPER,
    ):
        super().__init__(address, StatusHandler)
        self.database = database
        self.grafana_api = grafana_api
        self.public_origin = public_origin
        self.control_helper = control_helper


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
