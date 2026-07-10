from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
import unittest


def load_generator():
    path = Path(__file__).parents[1] / "tools" / "generate-grafana-dashboard.py"
    spec = importlib.util.spec_from_file_location("generate_grafana_dashboard", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GrafanaDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = load_generator()

    def test_dashboard_is_light_mode_and_uses_airmonitor_datasource(self):
        dashboard = self.generator.build()

        self.assertEqual(dashboard["style"], "light")
        self.assertEqual(dashboard["uid"], "airmonitor-live")
        for panel in dashboard["panels"]:
            self.assertEqual(panel["datasource"]["uid"], "airmonitor-sqlite")

    def test_all_panel_queries_match_schema(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(
                """
                CREATE TABLE sgx_voc_samples (
                    id INTEGER PRIMARY KEY,
                    sampled_at TEXT,
                    gas_ppm REAL,
                    temperature_c REAL,
                    humidity_rh REAL,
                    print_id INTEGER
                );
                CREATE TABLE prints (
                    id INTEGER PRIMARY KEY,
                    started_at TEXT,
                    ended_at TEXT,
                    last_seen_at TEXT,
                    started_gcode_state TEXT,
                    last_gcode_state TEXT,
                    ended_gcode_state TEXT,
                    subtask_name TEXT,
                    filament_type TEXT,
                    filament_emission_class TEXT,
                    room_filter_recommended INTEGER
                );
                CREATE TABLE filter_control_state (
                    filter_id TEXT,
                    manual_mode TEXT,
                    automation_request TEXT,
                    actual_state TEXT,
                    effective_state TEXT,
                    reason TEXT,
                    updated_at TEXT
                );
                """
            )
            for sql in self.generator.SQL.values():
                compact = self.generator.compact_sql(sql).rstrip(";")
                conn.execute(f"SELECT * FROM ({compact}) LIMIT 1").fetchall()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
