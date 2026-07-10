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
        ORDER BY sampled_at
    """,
    "temperature": """
        SELECT CAST(strftime('%s', sampled_at) AS INTEGER) AS time,
               temperature_c
        FROM sgx_voc_samples
        ORDER BY sampled_at
    """,
    "humidity": """
        SELECT CAST(strftime('%s', sampled_at) AS INTEGER) AS time,
               humidity_rh
        FROM sgx_voc_samples
        ORDER BY sampled_at
    """,
    "temperature_humidity": """
        SELECT CAST(strftime('%s', sampled_at) AS INTEGER) AS time,
               temperature_c,
               humidity_rh
        FROM sgx_voc_samples
        ORDER BY sampled_at
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


def build() -> dict[str, Any]:
    panels = [
        timeseries(1, "VOC History", 0, 0, 24, 8, "voc", "ppm", 5),
        timeseries(2, "Temperature", 0, 8, 12, 8, "temperature", "celsius"),
        timeseries(3, "Humidity", 12, 8, 12, 8, "humidity", "humidity"),
        timeseries(4, "Temperature / Humidity", 0, 16, 24, 8, "temperature_humidity"),
        table(5, "Latest Sample", 0, 24, 24, 4, "latest_sample"),
        table(6, "Filter Control", 0, 28, 24, 5, "filters"),
        table(7, "Recent Prints", 0, 33, 24, 7, "recent_prints"),
        table(8, "Latest Samples", 0, 40, 24, 7, "latest_samples"),
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
        "editable": True,
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
            conn.execute(f"SELECT * FROM ({compact_sql(sql).rstrip(';')}) LIMIT 1").fetchall()
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
