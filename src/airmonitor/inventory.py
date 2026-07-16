"""AirMonitor appliance inventory reporting."""

from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

from airmonitor.hardware import DEFAULT_REGISTRY, load_registry, resolve_device
from airmonitor.health import run_checks


def package_version() -> str:
    try:
        return version("airmonitor")
    except PackageNotFoundError:
        return "development"


def _service_state(service: str) -> str:
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", service],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {exc}"
    return (proc.stdout or proc.stderr).strip() or f"exit={proc.returncode}"


def hardware_inventory(registry_path: str | Path = DEFAULT_REGISTRY) -> list[dict[str, Any]]:
    registry = load_registry(registry_path)
    items: list[dict[str, Any]] = []
    for hardware_id, entry in registry["devices"].items():
        item: dict[str, Any] = {"hardware_id": hardware_id, **entry}
        try:
            item["resolved_device"] = resolve_device(hardware_id, registry_path=registry_path)
            item["connected"] = True
        except Exception as exc:
            item["resolved_device"] = None
            item["connected"] = False
            item["detail"] = str(exc)
        items.append(item)
    return sorted(items, key=lambda value: value["hardware_id"])


def collect_inventory(
    *,
    registry_path: str | Path = DEFAULT_REGISTRY,
    database: str = "/var/lib/airmonitor/airmonitor.sqlite3",
    serial_device: str = "/dev/serial0",
    include_systemd: bool = True,
) -> dict[str, Any]:
    health = run_checks(
        database=database,
        serial_device=serial_device,
        include_systemd=include_systemd,
    )
    services = {
        name: _service_state(name)
        for name in (
            "airmonitor-printer-mqtt.service",
            "airmonitor.target",
            "airmonitor-voc.service",
            "airmonitor-bento.service",
            "airmonitor-levoit.service",
            "airmonitor-status.service",
            "airmonitor-export.service",
            "grafana-server.service",
            "mosquitto.service",
        )
    } if include_systemd else {}
    return {
        "airmonitor_version": package_version(),
        "hardware_registry": str(registry_path),
        "hardware": hardware_inventory(registry_path),
        "services": services,
        "health": health,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airmonitor-inventory",
        description="Report installed AirMonitor hardware and appliance services",
    )
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--database", default="/var/lib/airmonitor/airmonitor.sqlite3")
    parser.add_argument("--serial-device", default="/dev/serial0")
    parser.add_argument("--systemd", action=argparse.BooleanOptionalAction, default=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    report = collect_inventory(
        registry_path=args.registry,
        database=args.database,
        serial_device=args.serial_device,
        include_systemd=args.systemd,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["health"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
