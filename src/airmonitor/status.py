"""Read-only appliance status assembled from service-owned state."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Callable


DEFAULT_DATABASE = "/var/lib/airmonitor/airmonitor.sqlite3"
SENSOR_STALE_SECONDS = 90
SENSOR_OFFLINE_SECONDS = 300
SERVICES = (
    "airmonitor.service",
    "airmonitor-sps30.service",
    "airmonitor-printer-mqtt.service",
    "airmonitor-bento.service",
    "airmonitor-levoit.service",
    "airmonitor-status.service",
    "grafana-server.service",
    "mosquitto.service",
)


def _iso_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc)


def _age_seconds(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds())


def _row(conn: sqlite3.Connection, sql: str) -> dict[str, Any] | None:
    result = conn.execute(sql).fetchone()
    return dict(result) if result else None


def _service_state(service: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"
    return (result.stdout or result.stderr).strip() or "unknown"


def _host_metrics(database: str, disk_path: str = "/var/lib/airmonitor") -> dict[str, Any]:
    stat = os.statvfs(disk_path)
    total = stat.f_blocks * stat.f_frsize
    available = stat.f_bavail * stat.f_frsize
    used = total - available
    try:
        uptime_seconds = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        uptime_seconds = None
    cpu_temp_c = None
    for path in (Path("/sys/class/thermal/thermal_zone0/temp"), Path("/sys/devices/virtual/thermal/thermal_zone0/temp")):
        try:
            cpu_temp_c = float(path.read_text(encoding="utf-8").strip()) / 1000
            break
        except (OSError, ValueError):
            continue
    try:
        database_size = Path(database).stat().st_size
    except OSError:
        database_size = None
    return {
        "disk_total_bytes": total,
        "disk_used_bytes": used,
        "disk_used_percent": round((used / total) * 100, 1) if total else None,
        "database_size_bytes": database_size,
        "uptime_seconds": uptime_seconds,
        "cpu_temperature_c": cpu_temp_c,
    }


def collect_status(
    database: str = DEFAULT_DATABASE,
    *,
    now: datetime | None = None,
    service_reader: Callable[[str], str] = _service_state,
    host_reader: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Collect status without talking to sensor hardware or control integrations."""
    checked_at = _iso_now(now)
    database_error = None
    sgx = sps30 = printer = levoit = None
    filters: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        sgx = _row(conn, """
            SELECT sampled_at, gas_ppm, temperature_c, humidity_rh
            FROM sgx_voc_samples ORDER BY id DESC LIMIT 1
        """)
        sps30 = _row(conn, """
            SELECT sampled_at, mass_pm1_0, mass_pm2_5, mass_pm4_0, mass_pm10
            FROM sps30_samples ORDER BY id DESC LIMIT 1
        """)
        printer = _row(conn, """
            SELECT last_seen_at, printer_available, printer_connected, printer_active,
                   last_gcode_state, filament_type, filament_name, subtask_name
            FROM prints ORDER BY COALESCE(last_seen_at, started_at) DESC LIMIT 1
        """)
        filters = [dict(row) for row in conn.execute("""
            SELECT filter_id, manual_mode, automation_request, actual_state,
                   effective_state, reason, updated_at
            FROM filter_control_state ORDER BY filter_id
        """)]
        levoit = _row(conn, """
            SELECT sampled_at, device_name, power_state, mode, fan_level,
                   pm2_5, air_quality, filter_life_percent
            FROM levoit_samples ORDER BY id DESC LIMIT 1
        """)
        conn.close()
    except (OSError, sqlite3.Error) as exc:
        database_error = str(exc)

    sensor_freshness = {
        "sgx": {
            "sampled_at": sgx.get("sampled_at") if sgx else None,
            "age_seconds": _age_seconds(sgx.get("sampled_at"), checked_at) if sgx else None,
        },
        "sps30": {
            "sampled_at": sps30.get("sampled_at") if sps30 else None,
            "age_seconds": _age_seconds(sps30.get("sampled_at"), checked_at) if sps30 else None,
        },
    }
    services = {name: service_reader(name) for name in SERVICES}
    host = (host_reader or (lambda path: _host_metrics(path)))(database)

    ages = [item["age_seconds"] for item in sensor_freshness.values()]
    both_offline = all(age is None or age > SENSOR_OFFLINE_SECONDS for age in ages)
    core_inactive = [name for name, state in services.items() if state != "active"]
    warnings: list[str] = []
    if database_error:
        warnings.append("Database unavailable")
    if any(age is None or age > SENSOR_STALE_SECONDS for age in ages):
        warnings.append("One or more sensor streams are stale")
    if core_inactive:
        warnings.append("One or more services are inactive")
    if (host.get("disk_used_percent") or 0) >= 85:
        warnings.append("Disk usage is high")
    if (host.get("cpu_temperature_c") or 0) >= 75:
        warnings.append("CPU temperature is high")

    if database_error or both_offline or all(services.get(name) != "active" for name in ("airmonitor.service", "airmonitor-sps30.service")):
        overall = "offline"
    elif warnings:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "overall": overall,
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "warnings": warnings,
        "readings": {"sgx": sgx, "sps30": sps30},
        "freshness": sensor_freshness,
        "printer": printer,
        "filters": filters,
        "levoit": levoit,
        "services": services,
        "host": host,
        "database_error": database_error,
    }
