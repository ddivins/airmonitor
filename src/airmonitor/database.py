"""SQLite storage for Air Monitor samples."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1


DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS air_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sampled_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    sensor_id TEXT NOT NULL,
    sensor_model TEXT NOT NULL,
    sensor_protocol TEXT,
    sensor_port TEXT,

    gas_ppm REAL,
    gas_mass REAL,
    full_scale INTEGER,
    temperature_c REAL,
    humidity_rh REAL,
    frame_hex TEXT,

    printer_available TEXT,
    printer_connected INTEGER,
    printer_active INTEGER,
    printer_gcode_state TEXT,
    printer_progress_percent INTEGER,
    printer_layer_num INTEGER,
    printer_total_layer_num INTEGER,
    printer_subtask_name TEXT,
    printer_print_error INTEGER,
    printer_filament_type TEXT,
    printer_filament_color TEXT,
    printer_state_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_air_samples_sampled_at ON air_samples(sampled_at);
CREATE INDEX IF NOT EXISTS idx_air_samples_sensor_time ON air_samples(sensor_id, sampled_at);
CREATE INDEX IF NOT EXISTS idx_air_samples_printer_state ON air_samples(printer_gcode_state, sampled_at);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version(version) VALUES (?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _json_default(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def insert_air_sample(
    conn: sqlite3.Connection,
    *,
    sensor_id: str,
    sensor_model: str,
    sensor_protocol: str | None,
    sensor_port: str | None,
    measurement: Any,
    frame_hex: str | None,
    printer_state: Mapping[str, Any] | None,
    printer_available: str | None,
) -> None:
    printer_state = printer_state or {}
    conn.execute(
        """
        INSERT INTO air_samples (
            sensor_id, sensor_model, sensor_protocol, sensor_port,
            gas_ppm, gas_mass, full_scale, temperature_c, humidity_rh, frame_hex,
            printer_available, printer_connected, printer_active, printer_gcode_state,
            printer_progress_percent, printer_layer_num, printer_total_layer_num,
            printer_subtask_name, printer_print_error, printer_filament_type,
            printer_filament_color, printer_state_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sensor_id,
            sensor_model,
            sensor_protocol,
            sensor_port,
            _value(measurement, "gas_ppm"),
            _value(measurement, "gas_mass"),
            _value(measurement, "full_scale"),
            _value(measurement, "temperature_c"),
            _value(measurement, "humidity_rh"),
            frame_hex,
            printer_available,
            _bool_to_int(printer_state.get("connected")),
            _bool_to_int(printer_state.get("active")),
            printer_state.get("gcode_state"),
            printer_state.get("progress_percent"),
            printer_state.get("layer_num"),
            printer_state.get("total_layer_num"),
            printer_state.get("subtask_name"),
            printer_state.get("print_error"),
            printer_state.get("filament_type"),
            printer_state.get("filament_color"),
            json.dumps(printer_state, sort_keys=True, default=_json_default) if printer_state else None,
        ),
    )
    conn.commit()


def _bool_to_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0
