from __future__ import annotations

import http.client
import json
from pathlib import Path
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time
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
    wake_levoit_service,
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

    @patch("airmonitor.status_web.os.kill")
    @patch("airmonitor.status_web.subprocess.run")
    def test_wake_levoit_service_signals_the_running_pid(self, mocked_run, mocked_kill):
        mocked_run.return_value = subprocess.CompletedProcess([], 0, stdout="4242\n", stderr="")

        wake_levoit_service()

        mocked_run.assert_called_once_with(
            ["systemctl", "show", "airmonitor-levoit.service", "-p", "MainPID", "--value"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        mocked_kill.assert_called_once_with(4242, signal.SIGUSR1)

    @patch("airmonitor.status_web.os.kill")
    @patch("airmonitor.status_web.subprocess.run")
    def test_wake_levoit_service_is_a_noop_when_service_is_not_running(self, mocked_run, mocked_kill):
        mocked_run.return_value = subprocess.CompletedProcess([], 0, stdout="0\n", stderr="")

        wake_levoit_service()  # MainPID=0 means "not running" -- must not raise or signal PID 0

        mocked_kill.assert_not_called()

    @patch("airmonitor.status_web.os.kill", side_effect=ProcessLookupError)
    @patch("airmonitor.status_web.subprocess.run")
    def test_wake_levoit_service_swallows_failures(self, mocked_run, _mocked_kill):
        """Best-effort only: the manual override is already persisted by the
        time this runs, so a failure here must never surface as an error --
        the change still applies on the next normal poll cycle regardless."""

        mocked_run.return_value = subprocess.CompletedProcess([], 0, stdout="4242\n", stderr="")

        wake_levoit_service()  # must not raise

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
        # _backup_job_state is a module-level singleton (single-admin
        # appliance, no per-request job tracking needed) -- reset it so
        # tests don't observe state a previous test left behind.
        import airmonitor.status_web as status_web

        status_web._backup_job_state.update(
            status="idle", result=None, error=None, started_at=None, finished_at=None
        )

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
    def test_backup_run_starts_a_background_job_instead_of_blocking(self, _mocked_user):
        """Regression test for the actual production incident: create_backup()
        can take 30s+ against a live database and only gets slower as the
        database grows. A synchronous version of this endpoint either needs
        an ever-increasing nginx timeout or eventually times out with a 504
        (which happened in production). It must now return almost
        immediately regardless of how long the backup itself takes."""

        started = time.monotonic()
        response, data = self._request(
            "POST", "/api/backup/run",
            headers={"Origin": "http://testorigin", "X-AirMonitor-Action": "backup-run"},
            body=b"{}",
        )
        elapsed = time.monotonic() - started
        self.assertEqual(response.status, 202)
        self.assertEqual(json.loads(data), {"ok": True, "status": "running"})
        self.assertLess(elapsed, 2.0)

    @patch("airmonitor.status_web.grafana_user", return_value=ADMIN_USER)
    def test_backup_run_job_completes_and_is_visible_via_status(self, _mocked_user):
        response, _data = self._request(
            "POST", "/api/backup/run",
            headers={"Origin": "http://testorigin", "X-AirMonitor-Action": "backup-run"},
            body=b"{}",
        )
        self.assertEqual(response.status, 202)

        deadline = time.monotonic() + 5.0
        status = None
        while time.monotonic() < deadline:
            response, data = self._request("GET", "/api/backup/status")
            status = json.loads(data)
            if status["status"] != "running":
                break
            time.sleep(0.05)

        self.assertEqual(status["status"], "done")
        self.assertTrue(Path(status["result"]["path"]).exists())
        self.assertGreater(status["result"]["size_bytes"], 0)

    @patch("airmonitor.status_web.grafana_user", return_value=None)
    def test_backup_status_rejects_unauthenticated_requests(self, _mocked_user):
        response, _data = self._request("GET", "/api/backup/status")
        self.assertEqual(response.status, 403)

    @patch("airmonitor.status_web.grafana_user", return_value=ADMIN_USER)
    def test_backup_status_reports_idle_before_any_run(self, _mocked_user):
        response, data = self._request("GET", "/api/backup/status")
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(data)["status"], "idle")

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

    @patch("airmonitor.status_web.grafana_user", return_value=ADMIN_USER)
    def test_backup_download_rejects_mismatched_origin(self, _mocked_user):
        response, _data = self._request(
            "GET", "/api/backup/download",
            headers={"Origin": "http://attacker.example", "X-AirMonitor-Action": "backup-download"},
        )
        self.assertEqual(response.status, 403)

    @patch("airmonitor.status_web.subprocess.run")
    @patch("airmonitor.status_web.grafana_user", return_value=ADMIN_USER)
    def test_backup_download_succeeds_without_an_origin_header(self, _mocked_user, mocked_run):
        """Regression test: Safari (confirmed live in production) doesn't
        send an Origin header on a same-origin GET fetch(), unlike POST where
        it's spec-guaranteed. The download must still work in that case --
        the custom X-AirMonitor-Action header is the real CSRF defense here,
        not Origin."""

        mocked_run.return_value = subprocess.CompletedProcess([], 0, stdout=b"PK\x03\x04fake-bundle-bytes", stderr=b"")

        response, data = self._request(
            "GET", "/api/backup/download",
            headers={"X-AirMonitor-Action": "backup-download"},
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(data, b"PK\x03\x04fake-bundle-bytes")

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
        mocked_run.assert_called_once()
        self.assertEqual(mocked_run.call_args.args[0][0], "sudo")

    @patch("airmonitor.status_web.subprocess.run")
    @patch("airmonitor.status_web.create_backup")
    @patch("airmonitor.status_web.grafana_user", return_value=ADMIN_USER)
    def test_backup_download_does_not_trigger_a_fresh_backup(self, _mocked_user, mocked_create_backup, mocked_run):
        """Regression test for the decoupling fix: download bundles whatever
        backup already exists (the daily timer, or a prior Backup Now click)
        rather than taking a new one itself -- that's the whole point of
        separating the two, since create_backup() is the slow, size-scaling
        operation and bundling is cheap. A user who wants a fresh bundle
        clicks Backup Now first."""

        mocked_run.return_value = subprocess.CompletedProcess([], 0, stdout=b"PK\x03\x04fake-bundle-bytes", stderr=b"")

        response, _data = self._request(
            "GET", "/api/backup/download",
            headers={"Origin": "http://testorigin", "X-AirMonitor-Action": "backup-download"},
        )

        self.assertEqual(response.status, 200)
        mocked_create_backup.assert_not_called()

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


class FilterControlWakeSignalTests(unittest.TestCase):
    """A manual on/auto/off change wakes airmonitor-levoit immediately (see
    wake_levoit_service) instead of leaving it to notice on its next
    scheduled poll -- Bento needs no such nudge, since its own service is
    already fully event-driven off MQTT with no polling delay."""

    ADMIN_USER = {"login": "admin", "isGrafanaAdmin": True}

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.database = str(Path(self.tmpdir.name) / "airmonitor.sqlite3")

        self.server = StatusServer(("127.0.0.1", 0), self.database, public_origin="http://testorigin")
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

    @patch("airmonitor.status_web.wake_levoit_service")
    @patch("airmonitor.status_web.grafana_user", return_value=ADMIN_USER)
    def test_levoit_override_wakes_the_service(self, _mocked_user, mocked_wake):
        response, _data = self._request(
            "POST", "/api/filters/control",
            headers={"Origin": "http://testorigin", "X-AirMonitor-Action": "filter-control"},
            body=b'{"filter_id": "levoit", "mode": "on"}',
        )
        self.assertEqual(response.status, 200)
        mocked_wake.assert_called_once()

    @patch("airmonitor.status_web.wake_levoit_service")
    @patch("airmonitor.status_web.grafana_user", return_value=ADMIN_USER)
    def test_bento_override_does_not_wake_levoit(self, _mocked_user, mocked_wake):
        response, _data = self._request(
            "POST", "/api/filters/control",
            headers={"Origin": "http://testorigin", "X-AirMonitor-Action": "filter-control"},
            body=b'{"filter_id": "bento", "mode": "on"}',
        )
        self.assertEqual(response.status, 200)
        mocked_wake.assert_not_called()


if __name__ == "__main__":
    unittest.main()
