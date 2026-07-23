"""SQLite storage for AirMonitor."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import platform
import sqlite3
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 8


DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS sensors (
    sensor_id TEXT PRIMARY KEY,
    manufacturer TEXT,
    product TEXT,
    model TEXT,
    transport TEXT,
    port TEXT,
    serial TEXT,
    location TEXT,
    installed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    removed_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS sensor_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id TEXT NOT NULL REFERENCES sensors(sensor_id),
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ended_at TEXT,
    software_version TEXT,
    hostname TEXT,
    sensor_protocol TEXT,
    sensor_port TEXT
);

CREATE TABLE IF NOT EXISTS prints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ended_at TEXT,
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    printer_available TEXT,
    printer_connected INTEGER,
    printer_active INTEGER,
    started_gcode_state TEXT,
    last_gcode_state TEXT,
    ended_gcode_state TEXT,

    progress_percent INTEGER,
    layer_num INTEGER,
    total_layer_num INTEGER,
    subtask_name TEXT,
    print_error INTEGER,
    print_type TEXT,

    filament_tray_id INTEGER,
    filament_ams_slot INTEGER,
    filament_type TEXT,
    filament_color TEXT,
    filament_profile TEXT,
    filament_sub_brand TEXT,
    filament_vendor TEXT,
    filament_name TEXT,

    policy_version TEXT,
    filament_policy_material TEXT,
    filament_emission_class TEXT,
    filament_odor_class TEXT,
    filament_particle_class TEXT,
    bento_recommended INTEGER,
    room_filter_recommended INTEGER,

    nozzle_diameter REAL,
    nozzle_type TEXT,
    nozzle_target_temperature_c REAL,
    bed_target_temperature_c REAL,
    chamber_temperature_c REAL,

    printer_state_json TEXT
);

CREATE TABLE IF NOT EXISTS sgx_voc_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sampled_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    sensor_id TEXT NOT NULL REFERENCES sensors(sensor_id),
    session_id INTEGER REFERENCES sensor_sessions(id),
    print_id INTEGER REFERENCES prints(id),

    sensor_protocol TEXT,
    sensor_port TEXT,
    gas_ppm REAL,
    gas_mass REAL,
    full_scale INTEGER,
    temperature_c REAL,
    humidity_rh REAL,
    chamber_temperature_c REAL,
    frame_hex TEXT
);

CREATE TABLE IF NOT EXISTS filter_control_state (
    filter_id TEXT PRIMARY KEY,
    manual_mode TEXT NOT NULL DEFAULT 'auto',
    automation_request TEXT NOT NULL DEFAULT 'unknown',
    actual_state TEXT NOT NULL DEFAULT 'unknown',
    effective_state TEXT NOT NULL DEFAULT 'unknown',
    reason TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_key TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    value REAL,
    threshold REAL,
    fired_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS levoit_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sampled_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    device_name TEXT,
    power_state TEXT NOT NULL,
    mode TEXT,
    fan_level INTEGER,
    pm2_5 REAL,
    air_quality INTEGER,
    filter_life_percent INTEGER,
    raw_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_sensor_sessions_sensor_time ON sensor_sessions(sensor_id, started_at);
CREATE INDEX IF NOT EXISTS idx_prints_started_at ON prints(started_at);
CREATE INDEX IF NOT EXISTS idx_prints_last_state ON prints(last_gcode_state, started_at);
CREATE INDEX IF NOT EXISTS idx_sgx_samples_sampled_at ON sgx_voc_samples(sampled_at);
CREATE INDEX IF NOT EXISTS idx_sgx_samples_sensor_time ON sgx_voc_samples(sensor_id, sampled_at);
CREATE INDEX IF NOT EXISTS idx_sgx_samples_print_time ON sgx_voc_samples(print_id, sampled_at);
CREATE INDEX IF NOT EXISTS idx_levoit_samples_sampled_at ON levoit_samples(sampled_at);
CREATE INDEX IF NOT EXISTS idx_alert_events_key ON alert_events(alert_key);
CREATE INDEX IF NOT EXISTS idx_alert_events_open ON alert_events(alert_key, resolved_at);

-- Legacy v1 table retained for existing installations. New code writes to the
-- normalized tables above.
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
"""

PRINT_COLUMN_MIGRATIONS = {
    "print_type": "TEXT",
    "filament_tray_id": "INTEGER",
    "filament_ams_slot": "INTEGER",
    "filament_profile": "TEXT",
    "filament_sub_brand": "TEXT",
    "policy_version": "TEXT",
    "filament_policy_material": "TEXT",
    "filament_emission_class": "TEXT",
    "filament_odor_class": "TEXT",
    "filament_particle_class": "TEXT",
    "bento_recommended": "INTEGER",
    "room_filter_recommended": "INTEGER",
    "nozzle_diameter": "REAL",
    "nozzle_type": "TEXT",
    "nozzle_target_temperature_c": "REAL",
    "bed_target_temperature_c": "REAL",
    "chamber_temperature_c": "REAL",
}

SGX_SAMPLE_COLUMN_MIGRATIONS = {
    "chamber_temperature_c": "REAL",
}

POST_MIGRATION_DDL = """
CREATE INDEX IF NOT EXISTS idx_prints_policy
ON prints(filament_emission_class, room_filter_recommended, started_at);
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
    ensure_columns(conn, "prints", PRINT_COLUMN_MIGRATIONS)
    ensure_columns(conn, "sgx_voc_samples", SGX_SAMPLE_COLUMN_MIGRATIONS)
    conn.executescript(POST_MIGRATION_DDL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version(version) VALUES (?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()


def ensure_columns(conn: sqlite3.Connection, table: str, migrations: Mapping[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for column, column_type in migrations.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def upsert_sensor(
    conn: sqlite3.Connection,
    *,
    sensor_id: str,
    manufacturer: str,
    product: str,
    model: str,
    transport: str,
    port: str | None,
    serial: str | None = None,
    location: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO sensors (
            sensor_id, manufacturer, product, model, transport, port, serial, location
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sensor_id) DO UPDATE SET
            manufacturer=excluded.manufacturer,
            product=excluded.product,
            model=excluded.model,
            transport=excluded.transport,
            port=excluded.port,
            serial=COALESCE(excluded.serial, sensors.serial),
            location=COALESCE(excluded.location, sensors.location)
        """,
        (sensor_id, manufacturer, product, model, transport, port, serial, location),
    )
    conn.commit()


def start_sensor_session(
    conn: sqlite3.Connection,
    *,
    sensor_id: str,
    software_version: str,
    sensor_protocol: str | None,
    sensor_port: str | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO sensor_sessions (
            sensor_id, software_version, hostname, sensor_protocol, sensor_port
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (sensor_id, software_version, platform.node(), sensor_protocol, sensor_port),
    )
    conn.commit()
    return int(cur.lastrowid)


def end_sensor_session(conn: sqlite3.Connection, *, session_id: int) -> None:
    conn.execute(
        """
        UPDATE sensor_sessions
        SET ended_at = COALESCE(ended_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        WHERE id = ?
        """,
        (session_id,),
    )
    conn.commit()


def start_or_update_print(
    conn: sqlite3.Connection,
    *,
    print_id: int | None,
    printer_state: Mapping[str, Any],
    printer_available: str | None,
    started_state: str | None,
) -> int:
    if print_id is None:
        cur = conn.execute(
            """
            INSERT INTO prints (
                printer_available, printer_connected, printer_active,
                started_gcode_state, last_gcode_state, progress_percent,
                layer_num, total_layer_num, subtask_name, print_error, print_type,
                filament_tray_id, filament_ams_slot, filament_type, filament_color,
                filament_profile, filament_sub_brand, filament_vendor, filament_name,
                policy_version, filament_policy_material, filament_emission_class,
                filament_odor_class, filament_particle_class, bento_recommended,
                room_filter_recommended, nozzle_diameter, nozzle_type,
                nozzle_target_temperature_c, bed_target_temperature_c,
                chamber_temperature_c, printer_state_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _print_values(printer_state, printer_available, started_state, started_state),
        )
        conn.commit()
        return int(cur.lastrowid)

    conn.execute(
        """
        UPDATE prints
        SET last_seen_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            printer_available = ?,
            printer_connected = ?,
            printer_active = ?,
            last_gcode_state = ?,
            progress_percent = ?,
            layer_num = ?,
            total_layer_num = ?,
            subtask_name = COALESCE(?, subtask_name),
            print_error = ?,
            print_type = COALESCE(?, print_type),
            filament_tray_id = COALESCE(?, filament_tray_id),
            filament_ams_slot = COALESCE(?, filament_ams_slot),
            filament_type = COALESCE(?, filament_type),
            filament_color = COALESCE(?, filament_color),
            filament_profile = COALESCE(?, filament_profile),
            filament_sub_brand = COALESCE(?, filament_sub_brand),
            filament_vendor = COALESCE(?, filament_vendor),
            filament_name = COALESCE(?, filament_name),
            policy_version = COALESCE(?, policy_version),
            filament_policy_material = COALESCE(?, filament_policy_material),
            filament_emission_class = COALESCE(?, filament_emission_class),
            filament_odor_class = COALESCE(?, filament_odor_class),
            filament_particle_class = COALESCE(?, filament_particle_class),
            bento_recommended = COALESCE(?, bento_recommended),
            room_filter_recommended = COALESCE(?, room_filter_recommended),
            nozzle_diameter = COALESCE(?, nozzle_diameter),
            nozzle_type = COALESCE(?, nozzle_type),
            nozzle_target_temperature_c = COALESCE(?, nozzle_target_temperature_c),
            bed_target_temperature_c = COALESCE(?, bed_target_temperature_c),
            chamber_temperature_c = COALESCE(?, chamber_temperature_c),
            printer_state_json = ?
        WHERE id = ?
        """,
        _print_update_values(printer_state, printer_available) + (print_id,),
    )
    conn.commit()
    return print_id


def finish_print(
    conn: sqlite3.Connection,
    *,
    print_id: int,
    printer_state: Mapping[str, Any],
    printer_available: str | None,
    ended_state: str | None,
) -> None:
    conn.execute(
        """
        UPDATE prints
        SET ended_at = COALESCE(ended_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            last_seen_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            printer_available = ?,
            printer_connected = ?,
            printer_active = ?,
            last_gcode_state = ?,
            ended_gcode_state = ?,
            progress_percent = ?,
            layer_num = ?,
            total_layer_num = ?,
            subtask_name = COALESCE(?, subtask_name),
            print_error = ?,
            print_type = COALESCE(?, print_type),
            filament_tray_id = COALESCE(?, filament_tray_id),
            filament_ams_slot = COALESCE(?, filament_ams_slot),
            filament_type = COALESCE(?, filament_type),
            filament_color = COALESCE(?, filament_color),
            filament_profile = COALESCE(?, filament_profile),
            filament_sub_brand = COALESCE(?, filament_sub_brand),
            filament_vendor = COALESCE(?, filament_vendor),
            filament_name = COALESCE(?, filament_name),
            policy_version = COALESCE(?, policy_version),
            filament_policy_material = COALESCE(?, filament_policy_material),
            filament_emission_class = COALESCE(?, filament_emission_class),
            filament_odor_class = COALESCE(?, filament_odor_class),
            filament_particle_class = COALESCE(?, filament_particle_class),
            bento_recommended = COALESCE(?, bento_recommended),
            room_filter_recommended = COALESCE(?, room_filter_recommended),
            nozzle_diameter = COALESCE(?, nozzle_diameter),
            nozzle_type = COALESCE(?, nozzle_type),
            nozzle_target_temperature_c = COALESCE(?, nozzle_target_temperature_c),
            bed_target_temperature_c = COALESCE(?, bed_target_temperature_c),
            chamber_temperature_c = COALESCE(?, chamber_temperature_c),
            printer_state_json = ?
        WHERE id = ?
        """,
        _print_finish_values(printer_state, printer_available, ended_state) + (print_id,),
    )
    conn.commit()


def insert_sgx_voc_sample(
    conn: sqlite3.Connection,
    *,
    sensor_id: str,
    session_id: int | None,
    print_id: int | None,
    sensor_protocol: str | None,
    sensor_port: str | None,
    measurement: Any,
    printer_state: Mapping[str, Any] | None,
    frame_hex: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO sgx_voc_samples (
            sensor_id, session_id, print_id, sensor_protocol, sensor_port,
            gas_ppm, gas_mass, full_scale, temperature_c, humidity_rh,
            chamber_temperature_c, frame_hex
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sensor_id,
            session_id,
            print_id,
            sensor_protocol,
            sensor_port,
            _value(measurement, "gas_ppm"),
            _value(measurement, "gas_mass"),
            _value(measurement, "full_scale"),
            _value(measurement, "temperature_c"),
            _value(measurement, "humidity_rh"),
            _value(printer_state, "chamber_temperature_c"),
            frame_hex,
        ),
    )
    conn.commit()


def get_filter_control_state(conn: sqlite3.Connection, *, filter_id: str) -> sqlite3.Row:
    """Return persisted filter state, creating an auto/unknown row if needed."""

    conn.execute(
        """
        INSERT OR IGNORE INTO filter_control_state (
            filter_id, manual_mode, automation_request, actual_state, effective_state, reason
        ) VALUES (?, 'auto', 'unknown', 'unknown', 'unknown', 'initialized')
        """,
        (filter_id,),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM filter_control_state WHERE filter_id = ?",
        (filter_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"filter state missing after initialization: {filter_id}")
    return row


def set_filter_manual_mode(conn: sqlite3.Connection, *, filter_id: str, manual_mode: str) -> sqlite3.Row:
    """Persist a user-selected filter mode."""

    if manual_mode not in {"auto", "on", "off"}:
        raise ValueError("manual_mode must be auto, on, or off")
    get_filter_control_state(conn, filter_id=filter_id)
    conn.execute(
        """
        UPDATE filter_control_state
        SET manual_mode = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE filter_id = ?
        """,
        (manual_mode, filter_id),
    )
    conn.commit()
    return get_filter_control_state(conn, filter_id=filter_id)


def update_filter_control_state(
    conn: sqlite3.Connection,
    *,
    filter_id: str,
    manual_mode: str | None = None,
    automation_request: str | None = None,
    actual_state: str | None = None,
    effective_state: str | None = None,
    reason: str | None = None,
) -> sqlite3.Row:
    """Update observed or resolved filter state while preserving unspecified fields."""

    get_filter_control_state(conn, filter_id=filter_id)
    conn.execute(
        """
        UPDATE filter_control_state
        SET manual_mode = COALESCE(?, manual_mode),
            automation_request = COALESCE(?, automation_request),
            actual_state = COALESCE(?, actual_state),
            effective_state = COALESCE(?, effective_state),
            reason = COALESCE(?, reason),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE filter_id = ?
        """,
        (manual_mode, automation_request, actual_state, effective_state, reason, filter_id),
    )
    conn.commit()
    return get_filter_control_state(conn, filter_id=filter_id)


def list_open_alert_events(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """Return currently open alerts keyed by alert_key."""

    rows = conn.execute("SELECT * FROM alert_events WHERE resolved_at IS NULL").fetchall()
    return {row["alert_key"]: row for row in rows}


def open_alert_event(
    conn: sqlite3.Connection,
    *,
    alert_key: str,
    level: str,
    message: str,
    value: float | None = None,
    threshold: float | None = None,
) -> sqlite3.Row:
    """Close any existing open alert for this key and record a new one.

    Closing and reopening (rather than updating in place) preserves an
    auditable history when a condition escalates, e.g. warning to critical.
    """

    conn.execute(
        "UPDATE alert_events SET resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE alert_key = ? AND resolved_at IS NULL",
        (alert_key,),
    )
    conn.execute(
        """
        INSERT INTO alert_events (alert_key, level, message, value, threshold)
        VALUES (?, ?, ?, ?, ?)
        """,
        (alert_key, level, message, value, threshold),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM alert_events WHERE alert_key = ? ORDER BY id DESC LIMIT 1",
        (alert_key,),
    ).fetchone()


def resolve_alert_event(conn: sqlite3.Connection, *, alert_key: str) -> None:
    conn.execute(
        "UPDATE alert_events SET resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE alert_key = ? AND resolved_at IS NULL",
        (alert_key,),
    )
    conn.commit()


def _print_values(
    printer_state: Mapping[str, Any],
    printer_available: str | None,
    started_state: str | None,
    last_state: str | None,
) -> tuple[Any, ...]:
    return (
        printer_available,
        _bool_to_int(printer_state.get("connected")),
        _bool_to_int(printer_state.get("active")),
        started_state,
        last_state,
        printer_state.get("progress_percent"),
        printer_state.get("layer_num"),
        printer_state.get("total_layer_num"),
        printer_state.get("subtask_name"),
        printer_state.get("print_error"),
        printer_state.get("print_type"),
        _state_first(printer_state, "filament_tray_id", "ams_tray_id"),
        _state_first(printer_state, "filament_ams_slot", "ams_slot"),
        printer_state.get("filament_type"),
        printer_state.get("filament_color"),
        printer_state.get("filament_profile"),
        printer_state.get("filament_sub_brand"),
        printer_state.get("filament_vendor"),
        printer_state.get("filament_name"),
        printer_state.get("policy_version"),
        printer_state.get("filament_policy_material"),
        printer_state.get("filament_emission_class"),
        printer_state.get("filament_odor_class"),
        printer_state.get("filament_particle_class"),
        _bool_to_int(printer_state.get("bento_recommended")),
        _bool_to_int(printer_state.get("room_filter_recommended")),
        _state_first(printer_state, "nozzle_diameter", "nozzle_diameter_mm"),
        printer_state.get("nozzle_type"),
        printer_state.get("nozzle_target_temperature_c"),
        printer_state.get("bed_target_temperature_c"),
        printer_state.get("chamber_temperature_c"),
        _state_json(printer_state),
    )


def _print_update_values(
    printer_state: Mapping[str, Any], printer_available: str | None
) -> tuple[Any, ...]:
    return (
        printer_available,
        _bool_to_int(printer_state.get("connected")),
        _bool_to_int(printer_state.get("active")),
        printer_state.get("gcode_state"),
        printer_state.get("progress_percent"),
        printer_state.get("layer_num"),
        printer_state.get("total_layer_num"),
        printer_state.get("subtask_name"),
        printer_state.get("print_error"),
        printer_state.get("print_type"),
        _state_first(printer_state, "filament_tray_id", "ams_tray_id"),
        _state_first(printer_state, "filament_ams_slot", "ams_slot"),
        printer_state.get("filament_type"),
        printer_state.get("filament_color"),
        printer_state.get("filament_profile"),
        printer_state.get("filament_sub_brand"),
        printer_state.get("filament_vendor"),
        printer_state.get("filament_name"),
        printer_state.get("policy_version"),
        printer_state.get("filament_policy_material"),
        printer_state.get("filament_emission_class"),
        printer_state.get("filament_odor_class"),
        printer_state.get("filament_particle_class"),
        _bool_to_int(printer_state.get("bento_recommended")),
        _bool_to_int(printer_state.get("room_filter_recommended")),
        _state_first(printer_state, "nozzle_diameter", "nozzle_diameter_mm"),
        printer_state.get("nozzle_type"),
        printer_state.get("nozzle_target_temperature_c"),
        printer_state.get("bed_target_temperature_c"),
        printer_state.get("chamber_temperature_c"),
        _state_json(printer_state),
    )


def _print_finish_values(
    printer_state: Mapping[str, Any],
    printer_available: str | None,
    ended_state: str | None,
) -> tuple[Any, ...]:
    return (
        printer_available,
        _bool_to_int(printer_state.get("connected")),
        _bool_to_int(printer_state.get("active")),
        printer_state.get("gcode_state"),
        ended_state,
        printer_state.get("progress_percent"),
        printer_state.get("layer_num"),
        printer_state.get("total_layer_num"),
        printer_state.get("subtask_name"),
        printer_state.get("print_error"),
        printer_state.get("print_type"),
        _state_first(printer_state, "filament_tray_id", "ams_tray_id"),
        _state_first(printer_state, "filament_ams_slot", "ams_slot"),
        printer_state.get("filament_type"),
        printer_state.get("filament_color"),
        printer_state.get("filament_profile"),
        printer_state.get("filament_sub_brand"),
        printer_state.get("filament_vendor"),
        printer_state.get("filament_name"),
        printer_state.get("policy_version"),
        printer_state.get("filament_policy_material"),
        printer_state.get("filament_emission_class"),
        printer_state.get("filament_odor_class"),
        printer_state.get("filament_particle_class"),
        _bool_to_int(printer_state.get("bento_recommended")),
        _bool_to_int(printer_state.get("room_filter_recommended")),
        _state_first(printer_state, "nozzle_diameter", "nozzle_diameter_mm"),
        printer_state.get("nozzle_type"),
        printer_state.get("nozzle_target_temperature_c"),
        printer_state.get("bed_target_temperature_c"),
        printer_state.get("chamber_temperature_c"),
        _state_json(printer_state),
    )


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _state_first(state: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = state.get(key)
        if value is not None:
            return value
    return None


def _state_json(state: Mapping[str, Any] | None) -> str | None:
    if not state:
        return None
    return json.dumps(state, sort_keys=True, default=_json_default)


def _json_default(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _bool_to_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0
