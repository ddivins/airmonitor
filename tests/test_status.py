from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from pathlib import Path
import tempfile
import unittest

from airmonitor.status import SERVICES, collect_alerts, collect_backup_status, collect_status


def build_database(path, sampled_at: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE sgx_voc_samples (id INTEGER PRIMARY KEY, sampled_at TEXT, gas_ppm REAL, temperature_c REAL, humidity_rh REAL);
        CREATE TABLE sps30_samples (id INTEGER PRIMARY KEY, sampled_at TEXT, mass_pm1_0 REAL, mass_pm2_5 REAL, mass_pm4_0 REAL, mass_pm10 REAL);
        CREATE TABLE prints (id INTEGER PRIMARY KEY, started_at TEXT, last_seen_at TEXT, printer_available TEXT,
            printer_connected INTEGER, printer_active INTEGER, last_gcode_state TEXT, filament_type TEXT,
            filament_name TEXT, subtask_name TEXT, chamber_temperature_c REAL);
        CREATE TABLE filter_control_state (filter_id TEXT, manual_mode TEXT, automation_request TEXT,
            actual_state TEXT, effective_state TEXT, reason TEXT, updated_at TEXT);
        CREATE TABLE levoit_samples (id INTEGER PRIMARY KEY, sampled_at TEXT, device_name TEXT, power_state TEXT,
            mode TEXT, fan_level INTEGER, pm2_5 REAL, air_quality INTEGER, filter_life_percent INTEGER);
    """)
    conn.execute("INSERT INTO sgx_voc_samples VALUES (1, ?, 0.42, 23.5, 45.0)", (sampled_at,))
    conn.execute("INSERT INTO sps30_samples VALUES (1, ?, 1.1, 3.2, 4.3, 5.4)", (sampled_at,))
    conn.execute("INSERT INTO prints VALUES (1, ?, ?, 'online', 1, 0, 'IDLE', 'PETG', 'Blue PETG', NULL, 36.5)", (sampled_at, sampled_at))
    conn.execute("INSERT INTO filter_control_state VALUES ('bento', 'auto', 'off', 'off', 'off', 'idle', ?)", (sampled_at,))
    conn.execute("INSERT INTO levoit_samples VALUES (1, ?, '400S', 'on', 'manual', 2, 4.0, 1, 93)", (sampled_at,))
    conn.commit()
    conn.close()


def host_metrics(_database: str) -> dict[str, float | int]:
    return {"disk_total_bytes": 1000, "disk_used_bytes": 400, "disk_used_percent": 40.0,
            "database_size_bytes": 100, "uptime_seconds": 3600, "cpu_temperature_c": 45.0}


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "airmonitor.sqlite3"
        self.now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_collect_status_uses_fresh_normalized_state(self):
        build_database(self.database, (self.now - timedelta(seconds=10)).isoformat().replace("+00:00", "Z"))
        result = collect_status(str(self.database), now=self.now, service_reader=lambda _name: "active", host_reader=host_metrics)

        self.assertEqual(result["overall"], "healthy")
        self.assertEqual(result["readings"]["sgx"]["gas_ppm"], 0.42)
        self.assertEqual(result["readings"]["sps30"]["mass_pm2_5"], 3.2)
        self.assertEqual(result["readings"]["sps30"]["mass_pm1_0"], 1.1)
        self.assertEqual(result["readings"]["sps30"]["mass_pm4_0"], 4.3)
        self.assertEqual(result["levoit"]["fan_level"], 2)
        self.assertEqual(result["levoit"]["pm2_5"], 4.0)
        self.assertEqual(result["printer"]["filament_type"], "PETG")
        self.assertEqual(result["printer"]["chamber_temperature_c"], 36.5)
        self.assertEqual(result["freshness"]["sgx"]["age_seconds"], 10)
        self.assertEqual(set(result["services"]), set(SERVICES))

    def test_collect_status_reports_stale_sensors_offline(self):
        build_database(self.database, (self.now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"))
        errors = {
            "airmonitor-voc.service": "SGX read failed: timeout",
            "airmonitor-sps30.service": "SPS30 unavailable: permission denied",
        }
        result = collect_status(
            str(self.database),
            now=self.now,
            service_reader=lambda _name: "active",
            error_reader=errors.get,
            host_reader=host_metrics,
        )

        self.assertEqual(result["overall"], "offline")
        self.assertIn("One or more sensor streams are stale", result["warnings"])
        self.assertEqual(result["freshness"]["sgx"]["error"], "SGX read failed: timeout")
        self.assertEqual(result["freshness"]["sps30"]["error"], "SPS30 unavailable: permission denied")


def build_alert_events(path, *, open_fired_at: str, resolved_fired_at: str, resolved_at: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE alert_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_key TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            value REAL,
            threshold REAL,
            fired_at TEXT NOT NULL,
            resolved_at TEXT
        );
    """)
    conn.execute(
        "INSERT INTO alert_events (alert_key, level, message, value, threshold, fired_at, resolved_at) "
        "VALUES ('sgx_gas_ppm', 'critical', 'VOC critical', 12.0, 10.0, ?, NULL)",
        (open_fired_at,),
    )
    conn.execute(
        "INSERT INTO alert_events (alert_key, level, message, value, threshold, fired_at, resolved_at) "
        "VALUES ('sps30_stale', 'warning', 'SPS30 stale', NULL, NULL, ?, ?)",
        (resolved_fired_at, resolved_at),
    )
    conn.commit()
    conn.close()


class AlertsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "airmonitor.sqlite3"
        self.now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_collect_alerts_separates_open_from_resolved(self):
        build_alert_events(
            self.database,
            open_fired_at="2026-07-14T11:00:00Z",
            resolved_fired_at="2026-07-14T09:00:00Z",
            resolved_at="2026-07-14T09:30:00Z",
        )
        result = collect_alerts(str(self.database), now=self.now)

        self.assertEqual(len(result["open"]), 1)
        self.assertEqual(result["open"][0]["alert_key"], "sgx_gas_ppm")
        self.assertEqual(result["open"][0]["level"], "critical")
        self.assertEqual(result["open"][0]["value"], 12.0)

        self.assertEqual(len(result["resolved"]), 1)
        self.assertEqual(result["resolved"][0]["alert_key"], "sps30_stale")
        self.assertEqual(result["resolved"][0]["resolved_at"], "2026-07-14T09:30:00Z")
        self.assertIsNone(result["database_error"])
        self.assertFalse(result["open"][0]["acknowledged"])

    def test_collect_alerts_marks_acknowledged_open_alerts(self):
        from airmonitor.database import acknowledge_alert_event, connect, init_db

        build_alert_events(
            self.database,
            open_fired_at="2026-07-14T11:00:00Z",
            resolved_fired_at="2026-07-14T09:00:00Z",
            resolved_at="2026-07-14T09:30:00Z",
        )
        conn = connect(str(self.database))
        init_db(conn)
        acknowledge_alert_event(conn, alert_key="sgx_gas_ppm", note="waiting on part")
        conn.close()

        result = collect_alerts(str(self.database), now=self.now)
        self.assertTrue(result["open"][0]["acknowledged"])
        self.assertEqual(result["open"][0]["acknowledgement_note"], "waiting on part")

    def test_collect_alerts_reports_no_alerts_cleanly(self):
        conn = sqlite3.connect(self.database)
        conn.execute("CREATE TABLE alert_events (id INTEGER PRIMARY KEY, alert_key TEXT, level TEXT, message TEXT, value REAL, threshold REAL, fired_at TEXT, resolved_at TEXT)")
        conn.commit()
        conn.close()

        result = collect_alerts(str(self.database), now=self.now)

        self.assertEqual(result["open"], [])
        self.assertEqual(result["resolved"], [])
        self.assertIsNone(result["database_error"])

    def test_collect_alerts_respects_history_limit(self):
        conn = sqlite3.connect(self.database)
        conn.execute(
            "CREATE TABLE alert_events (id INTEGER PRIMARY KEY, alert_key TEXT, level TEXT, message TEXT, "
            "value REAL, threshold REAL, fired_at TEXT, resolved_at TEXT)"
        )
        for i in range(5):
            conn.execute(
                "INSERT INTO alert_events (alert_key, level, message, fired_at, resolved_at) VALUES (?, 'warning', 'x', ?, ?)",
                (f"alert-{i}", f"2026-07-14T0{i}:00:00Z", f"2026-07-14T0{i}:05:00Z"),
            )
        conn.commit()
        conn.close()

        result = collect_alerts(str(self.database), now=self.now, limit=2)
        self.assertEqual(len(result["resolved"]), 2)
        # Most recently resolved first.
        self.assertEqual(result["resolved"][0]["alert_key"], "alert-4")

    def test_collect_alerts_reports_database_error_without_raising(self):
        result = collect_alerts(str(self.database / "does-not-exist" / "x.sqlite3"), now=self.now)
        self.assertEqual(result["open"], [])
        self.assertEqual(result["resolved"], [])
        self.assertIsNotNone(result["database_error"])


class BackupStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.backup_dir = Path(self.temp_dir.name) / "backups"
        self.backup_dir.mkdir()
        self.now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _touch_backup(self, stamp: str, size: int = 1000) -> None:
        path = self.backup_dir / f"airmonitor-{stamp}.sqlite3.gz"
        path.write_bytes(b"0" * size)

    def test_collect_backup_status_reports_empty_directory(self):
        result = collect_backup_status(str(self.backup_dir), now=self.now)
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["latest_at"])
        self.assertTrue(result["stale"])

    def test_collect_backup_status_reports_the_most_recent_backup(self):
        self._touch_backup("20260713T000000Z", size=500)
        self._touch_backup("20260714T110000Z", size=1234)  # 1 hour before self.now

        result = collect_backup_status(str(self.backup_dir), now=self.now)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["latest_at"], "2026-07-14T11:00:00Z")
        self.assertEqual(result["latest_size_bytes"], 1234)
        self.assertAlmostEqual(result["age_seconds"], 3600, delta=1)
        self.assertFalse(result["stale"])

    def test_collect_backup_status_flags_a_stale_backup(self):
        self._touch_backup("20260710T120000Z")  # 4 days before self.now

        result = collect_backup_status(str(self.backup_dir), now=self.now)

        self.assertTrue(result["stale"])

    def test_collect_backup_status_ignores_missing_directory(self):
        result = collect_backup_status(str(self.backup_dir / "does-not-exist"), now=self.now)
        self.assertEqual(result["count"], 0)
        self.assertTrue(result["stale"])
