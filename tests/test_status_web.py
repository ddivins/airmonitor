from __future__ import annotations

import http.client
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from airmonitor.status_web import (
    NO_STORE_FILENAMES,
    SERVICE_ACTIONS,
    STATIC_FILENAMES,
    StatusServer,
    cached_update_check,
    grafana_user,
    service_enabled,
    service_status,
    set_filter_mode,
)


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"login":"admin","email":"admin@example.com","isGrafanaAdmin":true}'


class StatusWebTests(unittest.TestCase):
    def test_grafana_user_requires_cookie(self):
        self.assertIsNone(grafana_user(None))

    @patch("airmonitor.status_web.urlopen", return_value=FakeResponse())
    def test_grafana_user_uses_grafana_as_identity_source(self, mocked_urlopen):
        user = grafana_user("grafana_session=abc", "http://grafana.test")
        self.assertEqual(user["login"], "admin")
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://grafana.test/api/user")
        self.assertEqual(request.headers["Cookie"], "grafana_session=abc")

    @patch("airmonitor.status_web.subprocess.run")
    def test_service_enabled_is_read_only(self, mocked_run):
        self.assertEqual(service_enabled("airmonitor-voc.service"), "target managed")
        mocked_run.assert_not_called()

    @patch("airmonitor.status_web.subprocess.run")
    def test_service_status_matches_systemctl_output(self, mocked_run):
        mocked_run.return_value = subprocess.CompletedProcess([], 0, stdout="● airmonitor-voc.service - AirMonitor VOC\n   Active: active\n", stderr="")
        output = service_status("airmonitor-voc.service")
        self.assertIn("Active: active", output)
        self.assertEqual(mocked_run.call_args.args[0], ["systemctl", "status", "--no-pager", "--full", "airmonitor-voc.service"])

    def test_service_status_rejects_non_airmonitor_service(self):
        with self.assertRaises(ValueError):
            service_status("ssh.service")

    def test_infrastructure_services_are_restart_only(self):
        self.assertEqual(SERVICE_ACTIONS["airmonitor-export.service"], ("restart",))
        self.assertEqual(SERVICE_ACTIONS["grafana-server.service"], ("restart",))
        self.assertEqual(SERVICE_ACTIONS["mosquitto.service"], ("restart",))

    def test_application_target_has_lifecycle_controls(self):
        self.assertEqual(SERVICE_ACTIONS["airmonitor.target"], ("start", "stop", "restart"))

    def test_target_managed_members_have_no_enablement_controls(self):
        self.assertEqual(SERVICE_ACTIONS["airmonitor-sps30.service"], ("start", "stop", "restart"))

    def test_filter_mode_is_persisted_and_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "airmonitor.sqlite3")
            record = set_filter_mode(database, "bento", "on")
            self.assertEqual(record["manual_mode"], "on")
            self.assertEqual(record["effective_state"], "on")
            self.assertEqual(record["reason"], "manual override: on")

    def test_filter_mode_rejects_unknown_values(self):
        with self.assertRaises(ValueError):
            set_filter_mode(":memory:", "bento", "turbo")

    def test_control_helper_rejects_unknown_service_before_systemctl(self):
        helper = Path(__file__).parents[1] / "tools" / "airmonitor-service-control"
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "called"
            fake_systemctl = Path(directory) / "systemctl"
            fake_systemctl.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
            fake_systemctl.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", str(helper), "start", "ssh.service"],
                env={"PATH": directory},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 64)
            self.assertFalse(marker.exists())

    def test_control_helper_rejects_disable_for_application_target(self):
        helper = Path(__file__).parents[1] / "tools" / "airmonitor-service-control"
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "called"
            fake_systemctl = Path(directory) / "systemctl"
            fake_systemctl.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
            fake_systemctl.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", str(helper), "disable", "airmonitor.target"],
                env={"PATH": directory},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 64)
            self.assertFalse(marker.exists())

    def test_control_helper_limits_error_output_to_sensor_services(self):
        helper = Path(__file__).parents[1] / "tools" / "airmonitor-service-control"
        result = subprocess.run(
            ["/bin/sh", str(helper), "errors", "airmonitor-printer-mqtt.service"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("limited to sensor services", result.stderr)

    def test_alerts_page_and_script_are_servable(self):
        self.assertIn("alerts.html", STATIC_FILENAMES)
        self.assertIn("alerts.js", STATIC_FILENAMES)

    def test_grafana_banner_stylesheet_is_servable(self):
        self.assertIn("grafana-banner.css", STATIC_FILENAMES)

    def test_dashboard_shell_pages_are_never_cached(self):
        self.assertIn("index.html", NO_STORE_FILENAMES)
        self.assertIn("alerts.html", NO_STORE_FILENAMES)
        # login.html intentionally keeps its prior cached behavior.
        self.assertNotIn("login.html", NO_STORE_FILENAMES)

    def test_cached_update_check_debounces_the_network_call(self):
        import airmonitor.status_web as status_web

        status_web._update_check_cache["result"] = None
        status_web._update_check_cache["checked_at"] = 0.0
        with patch("airmonitor.status_web.check_for_update") as mocked:
            mocked.return_value = {"update_available": False}
            first = cached_update_check()
            second = cached_update_check()
        self.assertEqual(first, second)
        mocked.assert_called_once()

    def test_cached_update_check_refreshes_after_ttl_expires(self):
        import time

        import airmonitor.status_web as status_web

        status_web._update_check_cache["result"] = {"update_available": False}
        # A relative offset, not an absolute value: time.monotonic()'s epoch is
        # arbitrary (often process/boot start), so it can be small in a
        # short-lived test process -- "far in the past" must be computed
        # relative to "now", not assumed via a literal like 0.0.
        status_web._update_check_cache["checked_at"] = time.monotonic() - (status_web.UPDATE_CHECK_TTL_SECONDS + 10)
        with patch("airmonitor.status_web.check_for_update") as mocked:
            mocked.return_value = {"update_available": True}
            result = cached_update_check()
        self.assertEqual(result, {"update_available": True})
        mocked.assert_called_once()


class BackupBundleEndpointTests(unittest.TestCase):
    """Backup Now and Download Bundle are admin-only, sensitive endpoints (the
    bundle contains every credential the appliance holds), so these exercise
    the actual HTTP routing/auth/CSRF logic end to end rather than just the
    underlying pure functions like the rest of this file does."""

    ADMIN_USER = {"login": "admin", "isGrafanaAdmin": True}

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.database = str(Path(self.tmpdir.name) / "airmonitor.sqlite3")
        self.backup_dir = str(Path(self.tmpdir.name) / "backups")
        conn = sqlite3.connect(self.database)
        conn.execute("CREATE TABLE placeholder (id INTEGER)")
        conn.commit()
        conn.close()

        self.server = StatusServer(
            ("127.0.0.1", 0),
            self.database,
            public_origin="http://testorigin",
            backup_dir=self.backup_dir,
        )
        self.addCleanup(self.server.server_close)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.thread.join(timeout=2)))

    def _request(self, method: str, path: str, *, headers: dict | None = None, body: bytes | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response, response.read()
        finally:
            conn.close()

    @patch("airmonitor.status_web.grafana_user", return_value=None)
    def test_backup_run_rejects_unauthenticated_requests(self, _mocked_user):
        response, _data = self._request(
            "POST", "/api/backup/run",
            headers={"Origin": "http://testorigin", "X-AirMonitor-Action": "backup-run"},
            body=b"{}",
        )
        self.assertEqual(response.status, 403)

    @patch("airmonitor.status_web.grafana_user", return_value=ADMIN_USER)
    def test_backup_run_rejects_missing_csrf_header(self, _mocked_user):
        response, _data = self._request("POST", "/api/backup/run", body=b"{}")
        self.assertEqual(response.status, 403)

    @patch("airmonitor.status_web.grafana_user", return_value=ADMIN_USER)
    def test_backup_run_creates_a_real_backup(self, _mocked_user):
        response, data = self._request(
            "POST", "/api/backup/run",
            headers={"Origin": "http://testorigin", "X-AirMonitor-Action": "backup-run"},
            body=b"{}",
        )
        self.assertEqual(response.status, 200)
        payload = json.loads(data)
        self.assertTrue(payload["ok"])
        self.assertTrue(Path(payload["path"]).exists())
        self.assertGreater(payload["size_bytes"], 0)

    @patch("airmonitor.status_web.grafana_user", return_value=None)
    def test_backup_download_rejects_unauthenticated_requests(self, _mocked_user):
        response, _data = self._request(
            "GET", "/api/backup/download",
            headers={"Origin": "http://testorigin", "X-AirMonitor-Action": "backup-download"},
        )
        self.assertEqual(response.status, 403)

    @patch("airmonitor.status_web.grafana_user", return_value=ADMIN_USER)
    def test_backup_download_rejects_missing_csrf_header(self, _mocked_user):
        """A plain <a href> or <img src> navigation can't set a custom header,
        so requiring one here means the download can only be triggered by
        same-origin JS (fetch), not by a cross-site link tricking an admin's
        browser into downloading the bundle."""

        response, _data = self._request("GET", "/api/backup/download")
        self.assertEqual(response.status, 403)

    @patch("airmonitor.status_web.subprocess.run")
    @patch("airmonitor.status_web.grafana_user", return_value=ADMIN_USER)
    def test_backup_download_streams_zip_with_attachment_header(self, _mocked_user, mocked_run):
        mocked_run.return_value = subprocess.CompletedProcess([], 0, stdout=b"PK\x03\x04fake-bundle-bytes", stderr=b"")

        response, data = self._request(
            "GET", "/api/backup/download",
            headers={"Origin": "http://testorigin", "X-AirMonitor-Action": "backup-download"},
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/zip")
        self.assertIn("attachment; filename=", response.getheader("Content-Disposition"))
        self.assertEqual(data, b"PK\x03\x04fake-bundle-bytes")
        # A fresh backup is taken before the bundle helper runs, so a download
        # always includes the current database, not whatever the last daily
        # timer run happened to produce.
        self.assertTrue(any(Path(self.backup_dir).glob("airmonitor-*.sqlite3.gz")))
        mocked_run.assert_called_once()
        self.assertEqual(mocked_run.call_args.args[0][0], "sudo")

    @patch("airmonitor.status_web.subprocess.run")
    @patch("airmonitor.status_web.grafana_user", return_value=ADMIN_USER)
    def test_backup_download_reports_bundle_helper_failure(self, _mocked_user, mocked_run):
        mocked_run.return_value = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"permission denied")

        response, data = self._request(
            "GET", "/api/backup/download",
            headers={"Origin": "http://testorigin", "X-AirMonitor-Action": "backup-download"},
        )

        self.assertEqual(response.status, 500)
        self.assertIn("permission denied", json.loads(data)["error"])


if __name__ == "__main__":
    unittest.main()
