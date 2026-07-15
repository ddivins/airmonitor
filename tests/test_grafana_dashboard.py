from __future__ import annotations

import importlib.util
import json
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
        self.assertFalse(dashboard["editable"])
        self.assertEqual(dashboard["links"][0]["url"], "https://airmonitor.example.com/")
        for panel in dashboard["panels"]:
            self.assertEqual(panel["datasource"]["uid"], "airmonitor-sqlite")

        brand = dashboard["panels"][0]
        self.assertEqual(brand["type"], "text")
        self.assertIn("airmonitor-brand-300.png", brand["options"]["content"])

    def test_dashboard_uses_explicit_sqlite_plugin_query_model(self):
        dashboard = self.generator.build()

        self.assertEqual(dashboard["panels"][1]["type"], "timeseries")
        self.assertNotIn("stat", {panel["type"] for panel in dashboard["panels"]})
        for panel in dashboard["panels"]:
            for target in panel["targets"]:
                self.assertEqual(target["queryText"], target["rawQueryText"])
                self.assertNotIn("SELECT 4", target["queryText"].upper())
                self.assertIn(target["queryType"], {"table", "time series"})
                if panel["type"] == "timeseries":
                    self.assertEqual(target["queryType"], "time series")
                    self.assertEqual(target["timeColumns"], ["time"])
                else:
                    self.assertEqual(target["queryType"], "table")
                    self.assertEqual(target["timeColumns"], [])

    def test_all_committed_dashboards_are_read_only(self):
        dashboard_dir = Path(__file__).parents[1] / "grafana" / "dashboards"
        for path in dashboard_dir.glob("*.json"):
            with self.subTest(path=path.name):
                dashboard = json.loads(path.read_text(encoding="utf-8"))
                self.assertFalse(dashboard["editable"])

    def test_print_dashboard_places_environment_after_sensor_graphs(self):
        path = Path(__file__).parents[1] / "grafana" / "dashboards" / "airmonitor-print-window.json"
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        positions = {panel["title"]: panel["gridPos"]["y"] for panel in dashboard["panels"]}
        self.assertLess(positions["VOC — 30 Minutes Before Through 30 Minutes After"], positions["Temperature and Humidity"])
        self.assertLess(positions["Particulate Matter"], positions["Temperature and Humidity"])

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
                CREATE TABLE sps30_samples (
                    id INTEGER PRIMARY KEY,
                    sampled_at TEXT,
                    mass_pm1_0 REAL,
                    mass_pm2_5 REAL,
                    mass_pm4_0 REAL,
                    mass_pm10 REAL,
                    number_pm0_5 REAL,
                    number_pm1_0 REAL,
                    number_pm2_5 REAL,
                    number_pm4_0 REAL,
                    number_pm10 REAL,
                    typical_particle_size REAL
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
                compact = self.generator.validation_sql(sql).rstrip(";")
                conn.execute(f"SELECT * FROM ({compact}) LIMIT 1").fetchall()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
