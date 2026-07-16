"""Bounded, read-only SQLite access for one print export."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import sqlite3
import subprocess
from typing import Any

from airmonitor.exports.metrics import calculate_metric
from airmonitor.exports.model import PrintExport


MAX_SAMPLES_PER_STREAM = 200_000

PRINT_COLUMNS = (
    "id", "started_at", "ended_at", "last_seen_at", "printer_available",
    "printer_connected", "printer_active", "started_gcode_state",
    "last_gcode_state", "ended_gcode_state", "progress_percent", "layer_num",
    "total_layer_num", "subtask_name", "print_error", "print_type",
    "filament_tray_id", "filament_ams_slot", "filament_type", "filament_color",
    "filament_profile", "filament_sub_brand", "filament_vendor", "filament_name",
    "policy_version", "filament_policy_material", "filament_emission_class",
    "filament_odor_class", "filament_particle_class", "bento_recommended",
    "room_filter_recommended", "nozzle_diameter", "nozzle_type",
    "nozzle_target_temperature_c", "bed_target_temperature_c",
)
SGX_COLUMNS = (
    "id", "sampled_at", "sensor_id", "session_id", "print_id",
    "sensor_protocol", "sensor_port", "gas_ppm", "gas_mass", "full_scale",
    "temperature_c", "humidity_rh",
)
SPS30_COLUMNS = (
    "id", "sampled_at", "sensor_id", "session_id", "sensor_port",
    "mass_pm1_0", "mass_pm2_5", "mass_pm4_0", "mass_pm10",
    "number_pm0_5", "number_pm1_0", "number_pm2_5", "number_pm4_0",
    "number_pm10", "typical_particle_size",
)
LEVOIT_COLUMNS = (
    "id", "sampled_at", "device_name", "power_state", "mode", "fan_level",
    "pm2_5", "air_quality", "filter_life_percent",
)
FILTER_COLUMNS = (
    "filter_id", "manual_mode", "automation_request", "actual_state",
    "effective_state", "reason", "updated_at",
)


class ExportNotFound(LookupError):
    """The selected print does not exist."""


class ExportTooLarge(RuntimeError):
    """The selected window exceeds the safety limit."""


class ExportRepository:
    def __init__(self, database: str, *, max_samples: int = MAX_SAMPLES_PER_STREAM) -> None:
        self.database = database
        self.max_samples = max_samples

    def load(self, print_id: int, *, now: datetime | None = None) -> PrintExport:
        generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        conn = sqlite3.connect(f"file:{self.database}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            record = conn.execute(
                f"SELECT {', '.join(PRINT_COLUMNS)} FROM prints WHERE id = ?",
                (print_id,),
            ).fetchone()
            if record is None:
                raise ExportNotFound(f"Print {print_id} was not found")
            print_record = dict(record)
            started_at = parse_timestamp(record["started_at"])
            source_end = parse_timestamp(record["ended_at"] or record["last_seen_at"])
            active = record["ended_at"] is None
            # Freeze active reports at the persisted last-seen endpoint so every
            # artifact uses the same bounds as the provisioned Grafana dashboard.
            ended_at = source_end
            window_start = started_at - timedelta(minutes=30)
            window_end = ended_at + timedelta(minutes=30)
            sgx = self._samples(conn, "sgx_voc_samples", SGX_COLUMNS, window_start, window_end)
            sps = self._samples(conn, "sps30_samples", SPS30_COLUMNS, window_start, window_end)
            levoit = self._samples(conn, "levoit_samples", LEVOIT_COLUMNS, window_start, window_end)
            filters = self._filter_state(conn)
        finally:
            conn.close()

        warnings: list[str] = []
        if not sgx:
            warnings.append("SGX data was unavailable in the selected export window.")
        if not sps:
            warnings.append("SPS30 data was unavailable in the selected export window.")
        if active:
            warnings.append("This report was generated while the print was active; results are preliminary.")
        metrics = {
            "voc": calculate_metric("VOC", "ppm", sgx, "gas_ppm", print_start=started_at, print_end=ended_at),
            "pm2_5": calculate_metric("PM2.5", "µg/m³", sps, "mass_pm2_5", print_start=started_at, print_end=ended_at),
        }
        return PrintExport(
            print_id=print_id,
            print_record=print_record,
            started_at=started_at,
            ended_at=ended_at,
            window_start=window_start,
            window_end=window_end,
            generated_at=generated_at,
            active=active,
            sgx_samples=tuple(sgx),
            sps30_samples=tuple(sps),
            levoit_samples=tuple(levoit),
            filter_state=tuple(filters),
            metrics=metrics,
            warnings=tuple(warnings),
            project_version=project_version(),
            git_commit=git_commit(),
        )

    def _samples(
        self,
        conn: sqlite3.Connection,
        table: str,
        columns: tuple[str, ...],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        if not _table_exists(conn, table):
            return []
        rows = conn.execute(
            f"""
            SELECT {', '.join(columns)}
            FROM {table}
            WHERE datetime(sampled_at) BETWEEN datetime(?) AND datetime(?)
            ORDER BY sampled_at
            LIMIT ?
            """,
            (sqlite_timestamp(start), sqlite_timestamp(end), self.max_samples + 1),
        ).fetchall()
        if len(rows) > self.max_samples:
            raise ExportTooLarge(
                f"{table} exceeds the {self.max_samples:,} sample export limit"
            )
        values = [dict(row) for row in rows]
        for value in values:
            value["sampled_at"] = parse_timestamp(value["sampled_at"])
        return values

    @staticmethod
    def _filter_state(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        if not _table_exists(conn, "filter_control_state"):
            return []
        rows = conn.execute(
            f"SELECT {', '.join(FILTER_COLUMNS)} FROM filter_control_state ORDER BY filter_id"
        ).fetchall()
        values = [dict(row) for row in rows]
        for value in values:
            if value.get("updated_at"):
                value["updated_at"] = parse_timestamp(value["updated_at"])
        return values


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sqlite_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def project_version() -> str:
    try:
        return version("airmonitor")
    except PackageNotFoundError:
        return "development"


def git_commit() -> str:
    configured = os.environ.get("AIRMONITOR_GIT_COMMIT")
    if configured:
        return configured
    state_file = Path("/var/lib/airmonitor/update-state/installed-commit")
    try:
        return state_file.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        pass
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
