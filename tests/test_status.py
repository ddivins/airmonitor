from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from pathlib import Path
import tempfile
import unittest

from airmonitor.status import SERVICES, collect_status


def build_database(path, sampled_at: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE sgx_voc_samples (id INTEGER PRIMARY KEY, sampled_at TEXT, gas_ppm REAL, temperature_c REAL, humidity_rh REAL);
        CREATE TABLE sps30_samples (id INTEGER PRIMARY KEY, sampled_at TEXT, mass_pm1_0 REAL, mass_pm2_5 REAL, mass_pm4_0 REAL, mass_pm10 REAL);
        CREATE TABLE prints (id INTEGER PRIMARY KEY, started_at TEXT, last_seen_at TEXT, printer_available TEXT,
            printer_connected INTEGER, printer_active INTEGER, last_gcode_state TEXT, filament_type TEXT,
            filament_name TEXT, subtask_name TEXT);
        CREATE TABLE filter_control_state (filter_id TEXT, manual_mode TEXT, automation_request TEXT,
            actual_state TEXT, effective_state TEXT, reason TEXT, updated_at TEXT);
    """)
    conn.execute("INSERT INTO sgx_voc_samples VALUES (1, ?, 0.42, 23.5, 45.0)", (sampled_at,))
    conn.execute("INSERT INTO sps30_samples VALUES (1, ?, 1.1, 3.2, 4.3, 5.4)", (sampled_at,))
    conn.execute("INSERT INTO prints VALUES (1, ?, ?, 'online', 1, 0, 'IDLE', 'PETG', 'Blue PETG', NULL)", (sampled_at, sampled_at))
    conn.execute("INSERT INTO filter_control_state VALUES ('bento', 'auto', 'off', 'off', 'off', 'idle', ?)", (sampled_at,))
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
        self.assertEqual(result["printer"]["filament_type"], "PETG")
        self.assertEqual(result["freshness"]["sgx"]["age_seconds"], 10)
        self.assertEqual(set(result["services"]), set(SERVICES))

    def test_collect_status_reports_stale_sensors_offline(self):
        build_database(self.database, (self.now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"))
        result = collect_status(str(self.database), now=self.now, service_reader=lambda _name: "active", host_reader=host_metrics)

        self.assertEqual(result["overall"], "offline")
        self.assertIn("One or more sensor streams are stale", result["warnings"])
