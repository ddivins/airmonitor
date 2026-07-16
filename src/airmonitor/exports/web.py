"""Public, same-origin HTTP service for bounded read-only print exports."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import logging
import mimetypes
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from typing import Callable, Iterable
from urllib.parse import parse_qs, urlsplit

from airmonitor.exports.renderers import (
    error_page,
    export_page,
    render_complete_zip,
    render_pdf,
    render_publication_png,
    render_raw_zip,
    render_xlsx,
    safe_stem,
)
from airmonitor.exports.repository import ExportNotFound, ExportRepository, ExportTooLarge
from airmonitor.status import DEFAULT_DATABASE


LOG = logging.getLogger("airmonitor.exports")
STATIC = files("airmonitor").joinpath("export_static")
FORMATTERS: dict[str, tuple[str, str, Callable]] = {
    "png": ("png", "image/png", render_publication_png),
    "pdf": ("pdf", "application/pdf", render_pdf),
    "xlsx": (
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        render_xlsx,
    ),
    "raw": ("zip", "application/zip", render_raw_zip),
    "complete": ("zip", "application/zip", render_complete_zip),
}


class ExportHandler(BaseHTTPRequestHandler):
    server_version = "AirMonitorExport"

    def do_HEAD(self) -> None:
        self._route(write_body=False)

    def do_GET(self) -> None:
        self._route(write_body=True)

    def _route(self, *, write_body: bool) -> None:
        request = urlsplit(self.path)
        if request.path == "/healthz":
            self._send(200, b'{"ok":true}', "application/json; charset=utf-8", write_body=write_body)
            return
        if request.path == "/assets/export.css":
            self._static("export.css", write_body=write_body)
            return
        if request.path == "/print":
            print_id = self._print_id(request.query)
            if print_id is None:
                self._error(400, "Select a print", "A positive integer print_id is required.", write_body)
                return
            try:
                report = self.server.repository.load(print_id)
            except ExportNotFound as error:
                self._error(404, "Print not found", str(error), write_body)
                return
            except (OSError, ExportTooLarge) as error:
                LOG.exception("Unable to load print %s", print_id)
                self._error(503, "Export unavailable", str(error), write_body)
                return
            self._send(200, export_page(report), "text/html; charset=utf-8", write_body=write_body)
            return
        if request.path == "/download":
            if not write_body:
                self._send(405, b"", "text/plain; charset=utf-8", write_body=False)
                return
            self._download(request.query)
            return
        self._error(404, "Not found", "The requested export route does not exist.", write_body)

    def _download(self, query: str) -> None:
        print_id = self._print_id(query)
        format_name = parse_qs(query).get("format", [""])[0]
        if print_id is None or format_name not in FORMATTERS:
            self._error(400, "Invalid export", "A valid print_id and export format are required.", True)
            return
        if not self.server.generation_lock.acquire(blocking=False):
            self._error(
                429,
                "Exporter busy",
                "Another report is being generated. Please try again in a moment.",
                True,
                retry_after=10,
            )
            return
        try:
            report = self.server.repository.load(print_id)
            extension, content_type, renderer = FORMATTERS[format_name]
            suffix = "-raw-data" if format_name == "raw" else "-complete" if format_name == "complete" else ""
            filename = f"{safe_stem(report)}{suffix}.{extension}"
            with TemporaryDirectory(prefix="airmonitor-export-") as directory:
                path = Path(directory) / filename
                renderer(report, path)
                self._send_file(path, content_type, filename)
        except ExportNotFound as error:
            self._error(404, "Print not found", str(error), True)
        except ExportTooLarge as error:
            self._error(413, "Export too large", str(error), True)
        except Exception:
            LOG.exception("Export generation failed for print %s format %s", print_id, format_name)
            self._error(
                500,
                "Export generation failed",
                "AirMonitor could not generate this file. The monitoring services continue to run.",
                True,
            )
        finally:
            self.server.generation_lock.release()

    @staticmethod
    def _print_id(query: str) -> int | None:
        raw = parse_qs(query).get("print_id", [None])[0]
        if raw is None or not raw.isascii() or not raw.isdigit():
            return None
        value = int(raw)
        return value if 0 < value <= 2_147_483_647 else None

    def _static(self, name: str, *, write_body: bool) -> None:
        try:
            body = STATIC.joinpath(name).read_bytes()
        except (FileNotFoundError, OSError):
            self._error(404, "Not found", "Static asset unavailable.", write_body)
            return
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._send(200, body, content_type, cache="public, max-age=3600", write_body=write_body)

    def _error(
        self,
        status: int,
        title: str,
        message: str,
        write_body: bool,
        *,
        retry_after: int | None = None,
    ) -> None:
        self._send(
            status,
            error_page(title, message, status),
            "text/html; charset=utf-8",
            write_body=write_body,
            retry_after=retry_after,
        )

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        cache: str = "no-store",
        write_body: bool,
        retry_after: int | None = None,
    ) -> None:
        self.send_response(status)
        self._security_headers(content_type, cache)
        self.send_header("Content-Length", str(len(body)))
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str, filename: str) -> None:
        size = path.stat().st_size
        self.send_response(200)
        self._security_headers(content_type, "private, no-store")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)

    def _security_headers(self, content_type: str, cache: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; img-src 'self'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'self'",
        )

    def log_message(self, format: str, *args: object) -> None:
        LOG.info("%s - %s", self.address_string(), format % args)


class ExportServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], database: str) -> None:
        super().__init__(address, ExportHandler)
        self.repository = ExportRepository(database)
        self.generation_lock = threading.BoundedSemaphore(1)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve public AirMonitor print exports")
    parser.add_argument("--host", default=os.environ.get("AIRMONITOR_EXPORT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AIRMONITOR_EXPORT_PORT", "8081")))
    parser.add_argument("--database", default=os.environ.get("AIRMONITOR_DATABASE", DEFAULT_DATABASE))
    args = parser.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(
        level=os.environ.get("AIRMONITOR_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    server = ExportServer((args.host, args.port), args.database)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
