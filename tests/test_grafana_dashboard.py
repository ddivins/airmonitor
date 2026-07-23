from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
from pathlib import Path
import unittest
from unittest import mock


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
        self.assertEqual(dashboard["links"][0]["url"], "/")
        self.assertEqual(
            dashboard["links"][1]["url"],
            "/grafana/d/airmonitor-print-window/airmonitor-print-window",
        )
        for panel in dashboard["panels"]:
            self.assertEqual(panel["datasource"]["uid"], "airmonitor-sqlite")

        brand = dashboard["panels"][0]
        self.assertEqual(brand["type"], "text")
        self.assertIn("airmonitor-brand-300.png", brand["options"]["content"])

        environment = next(panel for panel in dashboard["panels"] if panel["id"] == 2)
        self.assertEqual(environment["title"], "Ambient Temperature / Humidity / Chamber")
        self.assertIn("chamber_temperature_c", environment["targets"][0]["queryText"])

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
        environment = "Temperature, Humidity, and Chamber"
        self.assertLess(positions["VOC — 30 Minutes Before Through 30 Minutes After"], positions[environment])
        self.assertLess(positions["Particulate Matter"], positions[environment])

        panel = next(panel for panel in dashboard["panels"] if panel["title"] == environment)
        self.assertIn("chamber_temperature_c", panel["targets"][0]["queryText"])

    def test_print_dashboard_links_selected_print_to_public_export_page(self):
        path = Path(__file__).parents[1] / "grafana" / "dashboards" / "airmonitor-print-window.json"
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        export_link = next(link for link in dashboard["links"] if link["title"] == "Export Selected Print")
        self.assertEqual(
            export_link["url"],
            "/exports/print?print_id=${print_id}",
        )

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
                    chamber_temperature_c REAL,
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


class StatusPageUrlTests(unittest.TestCase):
    """Grafana rewrites a relative dashboard link to be relative to its own
    sub-path (serve_from_sub_path = true), so a root-relative "/" would land
    back on Grafana instead of the status page. These confirm the link is
    generated as a fully-qualified absolute URL whenever a real domain is
    available, and only falls back to "/" when it isn't."""

    @classmethod
    def setUpClass(cls):
        cls.generator = load_generator()

    def test_uses_relative_url_without_a_configured_domain(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GRAFANA_DOMAIN", None)
            self.assertEqual(self.generator.status_page_url(), "/")

    def test_uses_relative_url_for_localhost(self):
        with mock.patch.dict(os.environ, {"GRAFANA_DOMAIN": "localhost"}):
            self.assertEqual(self.generator.status_page_url(), "/")

    def test_uses_absolute_https_url_for_a_configured_domain(self):
        with mock.patch.dict(os.environ, {"GRAFANA_DOMAIN": "airmonitor.example.com"}):
            self.assertEqual(self.generator.status_page_url(), "https://airmonitor.example.com/")

    def test_build_wires_the_status_link_to_status_page_url(self):
        with mock.patch.dict(os.environ, {"GRAFANA_DOMAIN": "airmonitor.example.com"}):
            dashboard = self.generator.build()
        status_link = next(link for link in dashboard["links"] if link["title"] == "AirMonitor Status")
        self.assertEqual(status_link["url"], "https://airmonitor.example.com/")


if __name__ == "__main__":
    unittest.main()
