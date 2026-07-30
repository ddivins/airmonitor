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
        # The logo is a normal navigation element, not decoration: clicking it
        # goes back to the status page, same as the status_static pages' header.
        self.assertEqual(brand["options"]["content"], "[![AirMonitor — Monitor. Understand. Don't Die.](/public/img/airmonitor-brand-300.png)](/)")

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

    def test_print_dashboard_has_a_clickable_logo_banner(self):
        """Previously this dashboard had no logo/banner at all -- the only way
        back to status was the small "AirMonitor Status" link button. Its
        banner panel should match airmonitor-live's in shape (full-width,
        first panel, same clickable-logo markdown) for a consistent
        navigation experience across dashboards."""

        path = Path(__file__).parents[1] / "grafana" / "dashboards" / "airmonitor-print-window.json"
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        brand = dashboard["panels"][0]
        self.assertEqual(brand["type"], "text")
        self.assertEqual(brand["gridPos"], {"h": 6, "w": 24, "x": 0, "y": 0})
        self.assertEqual(
            brand["options"]["content"],
            "[![AirMonitor — Monitor. Understand. Don't Die.](/public/img/airmonitor-brand-300.png)](__AIRMONITOR_STATUS_URL__)",
        )

        # No two panels should overlap now that the banner pushed everything else down.
        spans = sorted((p["gridPos"]["y"], p["gridPos"]["y"] + p["gridPos"]["h"]) for p in dashboard["panels"])
        for (_, end), (next_start, _) in zip(spans, spans[1:]):
            self.assertLessEqual(end, next_start)

    def test_print_dashboard_status_link_is_a_placeholder_for_install_time_substitution(self):
        """This dashboard is a static committed file, not python-generated like
        airmonitor-live.json, so its "AirMonitor Status" link can't call
        status_page_url() directly -- tools/install-grafana.sh substitutes this
        placeholder for the real domain (or "/") when it installs the file.
        Guards against someone reverting it to a bare "/" that install-grafana.sh
        would then have nothing to substitute."""

        path = Path(__file__).parents[1] / "grafana" / "dashboards" / "airmonitor-print-window.json"
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        status_link = next(link for link in dashboard["links"] if link["title"] == "AirMonitor Status")
        self.assertEqual(status_link["url"], "__AIRMONITOR_STATUS_URL__")

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

    def test_build_wires_the_logo_banner_to_status_page_url(self):
        with mock.patch.dict(os.environ, {"GRAFANA_DOMAIN": "airmonitor.example.com"}):
            dashboard = self.generator.build()
        brand = dashboard["panels"][0]
        self.assertIn("](https://airmonitor.example.com/)", brand["options"]["content"])

    def test_build_links_to_compare_prints_dashboard(self):
        dashboard = self.generator.build()
        link = next(link for link in dashboard["links"] if link["title"] == "Compare Prints")
        self.assertEqual(link["url"], "/grafana/d/airmonitor-compare-prints/airmonitor-compare-prints")


def _interpolate_grafana_variables(query: str) -> str:
    """Stand in literal values for Grafana template-variable syntax so a raw
    sqlite3 connection can execute a dashboard's own query text directly,
    the same trick test_all_panel_queries_match_schema uses for the SQL dict."""

    for letter, print_id in zip("abcd", (1, 2, 3, 4)):
        query = query.replace(f"${{print_{letter}:text}}", f"Slot {letter.upper()}")
        query = query.replace(f"$print_{letter}", str(print_id))
    query = query.replace("$window_minutes", "30")
    return query


class ComparePrintsDashboardTests(unittest.TestCase):
    """airmonitor-compare-prints.json is a static committed file (like
    airmonitor-print-window.json), not python-generated -- these validate its
    structure and, since its queries are new and more involved than the
    existing dashboards' (UNION ALL branches, conditional-aggregation pivots
    for multi-print overlay series), that they actually execute cleanly
    against a schema shaped like the real database."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parents[1] / "grafana" / "dashboards" / "airmonitor-compare-prints.json"
        cls.dashboard = json.loads(path.read_text(encoding="utf-8"))

    def test_has_four_independent_print_select_variables_and_a_window_control(self):
        names = [variable["name"] for variable in self.dashboard["templating"]["list"]]
        self.assertEqual(names, ["print_a", "print_b", "print_c", "print_d", "window_minutes"])
        for variable in self.dashboard["templating"]["list"]:
            self.assertFalse(variable["multi"])

    def test_pre_post_window_is_adjustable_and_defaults_to_30_minutes(self):
        """The pre/post window around each print used to be hardcoded to 30
        minutes in every query; it's now a dashboard variable so a user can
        widen it (e.g. to see a longer post-print recovery tail) without
        editing the dashboard."""

        variables = {v["name"]: v for v in self.dashboard["templating"]["list"]}
        window = variables["window_minutes"]
        self.assertEqual(window["current"]["value"], "30")
        self.assertEqual({opt["value"] for opt in window["options"]}, {"15", "30", "60", "90", "120"})

        for panel in self.dashboard["panels"]:
            for target in panel.get("targets", []):
                query = target["queryText"]
                self.assertIn("$window_minutes", query)
                self.assertNotIn("30 minutes'", query)

    def test_has_a_clickable_logo_banner_and_cross_links(self):
        brand = self.dashboard["panels"][0]
        self.assertEqual(brand["type"], "text")
        self.assertEqual(brand["gridPos"], {"h": 6, "w": 24, "x": 0, "y": 0})
        self.assertIn("__AIRMONITOR_STATUS_URL__", brand["options"]["content"])

        link_titles = {link["title"] for link in self.dashboard["links"]}
        self.assertEqual(link_titles, {"AirMonitor Status", "AirMonitor Live", "Print Window"})

    def test_no_panels_overlap(self):
        spans = sorted((p["gridPos"]["y"], p["gridPos"]["y"] + p["gridPos"]["h"]) for p in self.dashboard["panels"])
        for (_, end), (next_start, _) in zip(spans, spans[1:]):
            self.assertLessEqual(end, next_start)

    def test_overlay_charts_do_not_mark_time_as_a_time_column(self):
        """Regression test: the "time" column here is elapsed minutes since
        each print's own start, not epoch seconds. Listing it in
        timeColumns tells the plugin to convert it as epoch seconds, which
        silently collapses many distinct elapsed-minute values onto the same
        instant (observed live as Grafana's "Values must be in ascending
        order" error on the VOC panel). airmonitor-print-window.json's own
        trend panels use an empty timeColumns for the same reason."""

        trend_panels = [p for p in self.dashboard["panels"] if p["type"] == "trend"]
        self.assertEqual(len(trend_panels), 3)
        for panel in trend_panels:
            self.assertEqual(panel["targets"][0]["timeColumns"], [])

    def test_summary_table_and_overlay_queries_execute_against_real_schema(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(
                """
                CREATE TABLE sgx_voc_samples (
                    id INTEGER PRIMARY KEY,
                    sampled_at TEXT,
                    gas_ppm REAL,
                    temperature_c REAL,
                    print_id INTEGER
                );
                CREATE TABLE sps30_samples (
                    id INTEGER PRIMARY KEY,
                    sampled_at TEXT,
                    mass_pm2_5 REAL
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
                """
            )
            conn.executemany(
                "INSERT INTO prints (id, started_at, ended_at, last_seen_at) VALUES (?, ?, ?, ?)",
                [
                    (i, f"2026-01-0{i}T00:00:00Z", f"2026-01-0{i}T01:00:00Z", f"2026-01-0{i}T01:00:00Z")
                    for i in (1, 2, 3, 4)
                ],
            )
            for panel in self.dashboard["panels"]:
                for target in panel["targets"]:
                    query = _interpolate_grafana_variables(target["queryText"]).rstrip(";")
                    conn.execute(f"SELECT * FROM ({query}) LIMIT 1").fetchall()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
