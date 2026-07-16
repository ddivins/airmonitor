from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from airmonitor.status_web import SERVICE_ACTIONS, grafana_user, service_enabled, service_status, set_filter_mode


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


if __name__ == "__main__":
    unittest.main()
