#!/usr/bin/env python3
"""Generate the file-provisioned AirMonitor Grafana dashboard."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


DS = {"type": "frser-sqlite-datasource", "uid": "airmonitor-sqlite"}


SQL = {
    "voc": """
        SELECT CAST(strftime('%s', sampled_at) AS INTEGER) AS time,
               gas_ppm AS voc_ppm
        FROM sgx_voc_samples
        WHERE CAST(strftime('%s', sampled_at) AS INTEGER) >= $__from / 1000
          AND CAST(strftime('%s', sampled_at) AS INTEGER) < $__to / 1000
        ORDER BY sampled_at
    """,
    "temperature": """
        SELECT CAST(strftime('%s', sampled_at) AS INTEGER) AS time,
               temperature_c
        FROM sgx_voc_samples
        WHERE CAST(strftime('%s', sampled_at) AS INTEGER) >= $__from / 1000
          AND CAST(strftime('%s', sampled_at) AS INTEGER) < $__to / 1000
        ORDER BY sampled_at
    """,
    "humidity": """
        SELECT CAST(strftime('%s', sampled_at) AS INTEGER) AS time,
               humidity_rh
        FROM sgx_voc_samples
        WHERE CAST(strftime('%s', sampled_at) AS INTEGER) >= $__from / 1000
          AND CAST(strftime('%s', sampled_at) AS INTEGER) < $__to / 1000
        ORDER BY sampled_at
    """,
    "temperature_humidity": """
        SELECT CAST(strftime('%s', sampled_at) AS INTEGER) AS time,
               temperature_c,
               humidity_rh
        FROM sgx_voc_samples
        WHERE CAST(strftime('%s', sampled_at) AS INTEGER) >= $__from / 1000
          AND CAST(strftime('%s', sampled_at) AS INTEGER) < $__to / 1000
        ORDER BY sampled_at
    """,
    "sps30_mass": """
        SELECT CAST(strftime('%s', sampled_at) AS INTEGER) AS time,
               mass_pm1_0,
               mass_pm2_5,
               mass_pm4_0,
               mass_pm10
        FROM sps30_samples
        WHERE CAST(strftime('%s', sampled_at) AS INTEGER) >= $__from / 1000
          AND CAST(strftime('%s', sampled_at) AS INTEGER) < $__to / 1000
        ORDER BY sampled_at
    """,
    "sps30_counts": """
        SELECT CAST(strftime('%s', sampled_at) AS INTEGER) AS time,
               number_pm0_5,
               number_pm1_0,
               number_pm2_5,
               number_pm4_0,
               number_pm10
        FROM sps30_samples
        WHERE CAST(strftime('%s', sampled_at) AS INTEGER) >= $__from / 1000
          AND CAST(strftime('%s', sampled_at) AS INTEGER) < $__to / 1000
        ORDER BY sampled_at
    """,
    "sps30_particle_size": """
        SELECT CAST(strftime('%s', sampled_at) AS INTEGER) AS time,
               typical_particle_size
        FROM sps30_samples
        WHERE CAST(strftime('%s', sampled_at) AS INTEGER) >= $__from / 1000
          AND CAST(strftime('%s', sampled_at) AS INTEGER) < $__to / 1000
        ORDER BY sampled_at
    """,
    "latest_sps30_sample": """
        SELECT sampled_at,
               printf('%.2f', mass_pm1_0) AS pm1_0_ug_m3,
               printf('%.2f', mass_pm2_5) AS pm2_5_ug_m3,
               printf('%.2f', mass_pm4_0) AS pm4_0_ug_m3,
               printf('%.2f', mass_pm10) AS pm10_ug_m3,
               printf('%.3f', typical_particle_size) AS typical_size_um
        FROM sps30_samples
        ORDER BY id DESC
        LIMIT 1
    """,
    "latest_sps30_samples": """
        SELECT sampled_at,
               mass_pm1_0,
               mass_pm2_5,
               mass_pm4_0,
               mass_pm10,
               number_pm0_5,
               number_pm1_0,
               number_pm2_5,
               number_pm4_0,
               number_pm10,
               typical_particle_size
        FROM sps30_samples
        ORDER BY id DESC
        LIMIT 20
    """,
    "latest_sample": """
        SELECT sampled_at,
               printf('%.2f', gas_ppm) AS voc_ppm,
               printf('%.1f C', temperature_c) AS temperature,
               printf('%.1f %%', humidity_rh) AS humidity
        FROM sgx_voc_samples
        ORDER BY id DESC
        LIMIT 1
    """,
    "latest_samples": """
        SELECT s.sampled_at,
               s.gas_ppm,
               s.temperature_c,
               s.humidity_rh,
               p.last_gcode_state AS printer_state,
               p.filament_type,
               p.subtask_name
        FROM sgx_voc_samples s
        LEFT JOIN prints p ON p.id = s.print_id
        ORDER BY s.id DESC
        LIMIT 20
    """,
    "recent_prints": """
        SELECT started_at,
               COALESCE(ended_at, '') AS ended_at,
               COALESCE(last_gcode_state, ended_gcode_state, started_gcode_state, '') AS state,
               COALESCE(subtask_name, '') AS file,
               COALESCE(filament_type, '') AS filament,
               COALESCE(filament_emission_class, '') AS emissions,
               CASE room_filter_recommended
                   WHEN 1 THEN 'yes'
                   WHEN 0 THEN 'no'
                   ELSE ''
               END AS room_filter
        FROM prints
        ORDER BY COALESCE(last_seen_at, started_at) DESC
        LIMIT 20
    """,
    "filters": """
        SELECT filter_id,
               manual_mode,
               automation_request,
               actual_state,
               effective_state,
               COALESCE(reason, '') AS reason,
               updated_at
        FROM filter_control_state
        ORDER BY filter_id
    """,
}


def compact_sql(sql: str) -> str:
    return " ".join(line.strip() for line in sql.strip().splitlines())


def validation_sql(sql: str) -> str:
    return compact_sql(sql).replace("$__from / 1000", "0").replace("$__to / 1000", "9999999999")


def target(sql_key: str, ref_id: str = "A", query_type: str = "table") -> dict[str, Any]:
    query_text = compact_sql(SQL[sql_key])
    time_columns = ["time"] if query_type == "time series" else []
    return {
        "refId": ref_id,
        "datasource": DS,
        "queryText": query_text,
        "rawQueryText": query_text,
        "queryType": query_type,
        "timeColumns": time_columns,
        "format": "table",
    }


def stat(
    panel_id: int,
    title: str,
    x: int,
    y: int,
    w: int,
    sql_key: str,
    field: str,
    unit: str | None = None,
    decimals: int | None = None,
) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "mappings": [],
        "thresholds": {
            "mode": "absolute",
            "steps": [
                {"color": "green", "value": None},
                {"color": "yellow", "value": 1},
                {"color": "orange", "value": 3},
                {"color": "red", "value": 10},
            ],
        },
    }
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "id": panel_id,
        "type": "stat",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": 4, "w": w, "x": x, "y": y},
        "targets": [target(sql_key)],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"values": False, "fields": field, "calcs": ["lastNotNull"]},
            "orientation": "auto",
            "textMode": "auto",
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
        },
    }


def table(panel_id: int, title: str, x: int, y: int, w: int, h: int, sql_key: str) -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "table",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(sql_key)],
        "fieldConfig": {
            "defaults": {
                "custom": {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False},
                "mappings": [],
            },
            "overrides": [],
        },
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
    }


def timeseries(
    panel_id: int,
    title: str,
    x: int,
    y: int,
    w: int,
    h: int,
    sql_key: str,
    unit: str | None = None,
    soft_max: int | None = None,
) -> dict[str, Any]:
    custom: dict[str, Any] = {
        "drawStyle": "line",
        "lineWidth": 2,
        "fillOpacity": 10,
        "gradientMode": "opacity",
        "showPoints": "never",
        "lineInterpolation": "smooth",
        "axisSoftMin": 0,
    }
    if soft_max is not None:
        custom["axisSoftMax"] = soft_max
    defaults: dict[str, Any] = {"custom": custom, "mappings": []}
    if unit:
        defaults["unit"] = unit
    return {
        "id": panel_id,
        "type": "timeseries",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(sql_key, query_type="time series")],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "legend": {
                "showLegend": True,
                "placement": "bottom",
                "displayMode": "list",
                "calcs": ["lastNotNull", "max"],
            },
            "tooltip": {"mode": "multi", "sort": "none"},
        },
    }


def brand_panel(panel_id: int) -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "text",
        "title": "",
        "datasource": DS,
        "gridPos": {"h": 6, "w": 24, "x": 0, "y": 0},
        "targets": [],
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {
            "mode": "markdown",
            "content": "![AirMonitor — Monitor. Understand. Don't Die.](/public/img/airmonitor-brand-300.png)",
        },
        "transparent": True,
    }


def build() -> dict[str, Any]:
    panels = [
        brand_panel(12),
        timeseries(1, "SGX VOC History", 0, 6, 12, 8, "voc", "ppm", 5),
        timeseries(2, "SGX Temperature / Humidity", 12, 6, 12, 8, "temperature_humidity"),
        timeseries(3, "SPS30 PM Mass", 0, 14, 24, 8, "sps30_mass", "ug/m3"),
        timeseries(4, "SPS30 Particle Count", 0, 22, 12, 8, "sps30_counts", "#/cm3"),
        timeseries(5, "SPS30 Typical Particle Size", 12, 22, 12, 8, "sps30_particle_size", "um"),
        table(6, "Latest SGX Sample", 0, 30, 24, 4, "latest_sample"),
        table(7, "Latest SGX Samples", 0, 34, 24, 7, "latest_samples"),
        table(8, "Latest SPS30 Sample", 0, 41, 24, 4, "latest_sps30_sample"),
        table(9, "Latest SPS30 Samples", 0, 45, 24, 7, "latest_sps30_samples"),
        table(10, "Filter Control", 0, 52, 24, 5, "filters"),
        table(11, "Recent Prints", 0, 57, 24, 7, "recent_prints"),
    ]
    return {
        "uid": "airmonitor-live",
        "title": "AirMonitor Live",
        "style": "light",
        "tags": ["airmonitor", "environment"],
        "timezone": "browser",
        "refresh": "10s",
        "schemaVersion": 39,
        "version": 1,
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {"refresh_intervals": ["10s", "30s", "1m", "5m"]},
        "editable": False,
        "graphTooltip": 1,
        "annotations": {"list": []},
        "templating": {"list": []},
        "links": [],
        "panels": panels,
    }


def validate_sql(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        for name, sql in SQL.items():
            conn.execute(f"SELECT * FROM ({validation_sql(sql).rstrip(';')}) LIMIT 1").fetchall()
            print(f"ok {name}")
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "--validate-db":
        validate_sql(Path(argv[2]))
        return 0

    text = json.dumps(build(), indent=2) + "\n"
    if len(argv) > 1:
        Path(argv[1]).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
