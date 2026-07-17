"""AirMonitor appliance health checks.

This module intentionally avoids printing secret values. It can be used from
systemd, cron, support scripts, or directly as ``airmonitor-doctor``.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
from typing import Iterable

from airmonitor.database import SCHEMA_VERSION, connect, init_db
from airmonitor.hardware import DEFAULT_HARDWARE_ID, DEFAULT_REGISTRY, resolve_device

DEFAULT_DATABASE = "/var/lib/airmonitor/airmonitor.sqlite3"
DEFAULT_SERIAL = "auto"
DEFAULT_GRAFANA_HOST = "127.0.0.1"
DEFAULT_GRAFANA_PORT = 3000
DEFAULT_MQTT_HOST = "127.0.0.1"
DEFAULT_MQTT_PORT = 1883
ENV_FILES = (
    "/etc/airmonitor/sgx-voc.env",
    "/etc/airmonitor/sps30.env",
    "/etc/airmonitor/printer-mqtt.env",
    "/etc/airmonitor/bento.env",
    "/etc/airmonitor/levoit.env",
)
SERVICES = (
    "airmonitor-printer-mqtt.service",
    "airmonitor.target",
    "airmonitor-voc.service",
    "airmonitor-sps30.service",
    "airmonitor-bento.service",
    "airmonitor-levoit.service",
    "airmonitor-status.service",
    "airmonitor-export.service",
)


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    required: bool = True

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _package_version() -> str:
    try:
        return version("airmonitor")
    except PackageNotFoundError:
        return "development"


def check_path(path: str, *, required: bool, readable: bool = True, writable: bool = False, name: str | None = None) -> Check:
    item = Path(path)
    check_name = name or path
    if not item.exists():
        return Check(check_name, "fail" if required else "warn", f"missing: {path}", required)
    problems: list[str] = []
    if readable and not os.access(item, os.R_OK):
        problems.append("not readable")
    if writable and not os.access(item, os.W_OK):
        problems.append("not writable")
    if problems:
        return Check(check_name, "fail" if required else "warn", f"{path}: {', '.join(problems)}", required)
    return Check(check_name, "ok", path, required)


def check_sensor_hardware(serial_device: str, hardware_id: str, registry: str) -> Check:
    try:
        resolved = serial_device if serial_device.lower() != "auto" else resolve_device(hardware_id, registry_path=registry)
    except Exception as exc:
        return Check("sensor_hardware", "fail", str(exc), True)
    result = check_path(resolved, required=True, readable=True, writable=True, name="sensor_hardware")
    if result.ok:
        return Check("sensor_hardware", "ok", f"{hardware_id} -> {resolved}", True)
    return result


def check_tcp(name: str, host: str, port: int, *, required: bool = False, timeout: float = 1.0) -> Check:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return Check(name, "fail" if required else "warn", f"{host}:{port}: {exc}", required)
    return Check(name, "ok", f"{host}:{port}", required)


def check_database(path: str) -> list[Check]:
    checks: list[Check] = []
    try:
        conn = connect(path)
        init_db(conn)
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        schema_rows = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        installed_schema = int(schema_rows[0]) if schema_rows else 0
        writable = conn.execute("PRAGMA query_only").fetchone()[0] == 0
        conn.close()
    except (OSError, sqlite3.Error) as exc:
        return [Check("database", "fail", str(exc), True)]

    checks.append(Check("database", "ok" if result == "ok" else "fail", f"integrity={result}", True))
    checks.append(
        Check(
            "database_schema",
            "ok" if installed_schema >= SCHEMA_VERSION else "fail",
            f"installed={installed_schema} expected={SCHEMA_VERSION}",
            True,
        )
    )
    checks.append(Check("database_writable", "ok" if writable else "fail", str(writable).lower(), True))
    return checks


def check_systemd_service(service: str) -> Check:
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", service],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return Check(service, "warn", str(exc), False)
    state = (proc.stdout or proc.stderr).strip() or f"exit={proc.returncode}"
    return Check(service, "ok" if proc.returncode == 0 else "warn", state, False)


def run_checks(
    *,
    database: str = DEFAULT_DATABASE,
    serial_device: str = DEFAULT_SERIAL,
    hardware_id: str = DEFAULT_HARDWARE_ID,
    hardware_registry: str = DEFAULT_REGISTRY,
    mqtt_host: str = DEFAULT_MQTT_HOST,
    mqtt_port: int = DEFAULT_MQTT_PORT,
    grafana_host: str = DEFAULT_GRAFANA_HOST,
    grafana_port: int = DEFAULT_GRAFANA_PORT,
    include_systemd: bool = True,
) -> dict[str, object]:
    checks: list[Check] = [
        Check("python", "ok", sys.version.split()[0], True),
        Check("airmonitor_version", "ok", _package_version(), True),
        check_sensor_hardware(serial_device, hardware_id, hardware_registry),
    ]
    checks.extend(check_path(path, required=False, readable=True) for path in ENV_FILES)
    checks.extend(check_database(database))
    checks.append(check_tcp("mqtt", mqtt_host, mqtt_port, required=False))
    checks.append(check_tcp("grafana", grafana_host, grafana_port, required=False))
    if include_systemd:
        checks.extend(check_systemd_service(service) for service in SERVICES)

    required_failures = [check for check in checks if check.required and not check.ok]
    warnings = [check for check in checks if check.status == "warn"]
    return {
        "ok": not required_failures,
        "summary": {
            "checks": len(checks),
            "required_failures": len(required_failures),
            "warnings": len(warnings),
        },
        "checks": [asdict(check) for check in checks],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="airmonitor-doctor", description="Run AirMonitor appliance health checks")
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--serial-device", default=DEFAULT_SERIAL, help="explicit serial path or 'auto' for hardware registry resolution")
    parser.add_argument("--hardware-id", default=DEFAULT_HARDWARE_ID)
    parser.add_argument("--hardware-registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--mqtt-host", default=DEFAULT_MQTT_HOST)
    parser.add_argument("--mqtt-port", type=int, default=DEFAULT_MQTT_PORT)
    parser.add_argument("--grafana-host", default=DEFAULT_GRAFANA_HOST)
    parser.add_argument("--grafana-port", type=int, default=DEFAULT_GRAFANA_PORT)
    parser.add_argument("--systemd", action=argparse.BooleanOptionalAction, default=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    report = run_checks(
        database=args.database,
        serial_device=args.serial_device,
        hardware_id=args.hardware_id,
        hardware_registry=args.hardware_registry,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        grafana_host=args.grafana_host,
        grafana_port=args.grafana_port,
        include_systemd=args.systemd,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
