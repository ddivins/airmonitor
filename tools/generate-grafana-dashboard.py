#!/usr/bin/env python3
import json
import sys
from pathlib import Path

DS = {"type": "frser-sqlite-datasource", "uid": "airmonitor-sqlite"}


def target(sql):
    return {"refId": "A", "datasource": DS, "queryText": sql}


def stat(pid, title, x, y, w, sql, field, unit=None, decimals=None):
    defaults = {
        "mappings": [],
        "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
    }
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "id": pid,
        "type": "stat",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": 4, "w": w, "x": x, "y": y},
        "targets": [target(sql)],
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


def table(pid, title, x, y, w, h, sql):
    return {
        "id": pid,
        "type": "table",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(sql)],
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False}, "mappings": []}, "overrides": []},
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
    }


def timeseries(pid, title, x, y, w, h, sql, unit=None, soft_max=None):
    custom = {
        "drawStyle": "line",
        "lineWidth": 3,
        "fillOpacity": 12,
        "gradientMode": "opacity",
        "showPoints": "never",
        "lineInterpolation": "smooth",
        "axisSoftMin": 0,
    }
    if soft_max is not None:
        custom["axisSoftMax"] = soft_max
    defaults = {"custom": custom, "mappings": []}
    if unit:
        defaults["unit"] = unit
    return {
        "id": pid,
        "type": "timeseries",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(sql)],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"legend": {"showLegend": True, "placement": "bottom", "displayMode": "list", "calcs": ["lastNotNull", "max"]}, "tooltip": {"mode": "multi", "sort": "none"}},
    }


def build():
    # The SQLite plugin converts ISO-8601 text fields named time into Grafana time fields.
    voc = "SELECT sampled_at AS time, gas_ppm AS voc_ppm FROM sgx_voc_samples ORDER BY sampled_at;"
    temp = "SELECT sampled_at AS time, temperature_c FROM sgx_voc_samples ORDER BY sampled_at;"
    hum = "SELECT sampled_at AS time, humidity_rh FROM sgx_voc_samples ORDER BY sampled_at;"
    temp_hum = "SELECT sampled_at AS time, temperature_c, humidity_rh FROM sgx_voc_samples ORDER BY sampled_at;"
    panels = [
        stat(1, "Current VOC", 0, 0, 6, voc, "voc_ppm", "ppm", 2),
        stat(2, "Temperature", 6, 0, 6, temp, "temperature_c", "celsius", 1),
        stat(3, "Humidity", 12, 0, 6, hum, "humidity_rh", "humidity", 1),
        table(4, "Printer", 18, 0, 6, 4, "SELECT COALESCE(last_gcode_state, ended_gcode_state, started_gcode_state) AS state, filament_type AS filament, subtask_name AS file FROM prints ORDER BY COALESCE(last_seen_at, started_at) DESC LIMIT 1;"),
        timeseries(5, "VOC History", 0, 4, 24, 9, voc, "ppm", 5),
        timeseries(6, "Temperature / Humidity", 0, 13, 24, 8, temp_hum),
        table(7, "Latest Samples", 0, 21, 24, 7, "SELECT s.sampled_at, s.gas_ppm, s.temperature_c, s.humidity_rh, p.last_gcode_state AS printer_state, p.filament_type, p.subtask_name FROM sgx_voc_samples s LEFT JOIN prints p ON p.id = s.print_id ORDER BY s.sampled_at DESC LIMIT 10;"),
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


if __name__ == "__main__":
    text = json.dumps(build(), indent=2) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text)
    else:
        print(text, end="")
