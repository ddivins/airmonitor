"""Systemd-friendly sensor logger entry point with hardware resolution."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from airmonitor.cli import main as cli_main
from airmonitor.hardware import DEFAULT_HARDWARE_ID, DEFAULT_REGISTRY, resolve_device


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _bool_env(name: str, default: bool) -> bool:
    value = _env(name, "true" if default else "false").strip().lower()
    return value not in {"0", "false", "no", "off"}


def resolve_configured_port() -> str:
    configured = _env("AIRMONITOR_PORT", "auto").strip()
    if configured and configured.lower() != "auto":
        return configured
    hardware_id = _env("AIRMONITOR_HARDWARE_ID", DEFAULT_HARDWARE_ID)
    registry = _env("AIRMONITOR_HARDWARE_REGISTRY", DEFAULT_REGISTRY)
    return resolve_device(hardware_id, registry_path=registry)


def build_log_argv() -> list[str]:
    port = resolve_configured_port()
    argv = [
        "log",
        "--port", port,
        "--sensor-id", _env("AIRMONITOR_SENSOR_ID", DEFAULT_HARDWARE_ID),
        "--sensor-transport", _env("AIRMONITOR_SENSOR_TRANSPORT", "usb-uart"),
        "--database", _env("AIRMONITOR_DATABASE", "/var/lib/airmonitor/airmonitor.sqlite3"),
        "--interval", _env("AIRMONITOR_INTERVAL", "10"),
        "--post-print-context-seconds", _env("AIRMONITOR_POST_PRINT_CONTEXT_SECONDS", "1800"),
        "--filament-policy", _env("AIRMONITOR_FILAMENT_POLICY", "/etc/airmonitor/filament-policy.yaml"),
        "--local-mqtt-host", _env("AIRMONITOR_LOCAL_MQTT_HOST", "localhost"),
        "--local-mqtt-port", _env("AIRMONITOR_LOCAL_MQTT_PORT", "1883"),
        "--local-mqtt-topic", _env("AIRMONITOR_LOCAL_MQTT_TOPIC", "printer/state"),
        "--local-mqtt-availability-topic", _env("AIRMONITOR_LOCAL_MQTT_AVAILABILITY_TOPIC", "printer/available"),
        "--local-mqtt-client-id", _env("AIRMONITOR_LOCAL_MQTT_CLIENT_ID", "airmonitor"),
        "--log-level", _env("AIRMONITOR_LOG_LEVEL", "INFO"),
    ]
    optional = {
        "--sensor-serial": _env("AIRMONITOR_SENSOR_SERIAL"),
        "--sensor-location": _env("AIRMONITOR_SENSOR_LOCATION"),
        "--local-mqtt-username": _env("AIRMONITOR_LOCAL_MQTT_USERNAME"),
        "--local-mqtt-password": _env("AIRMONITOR_LOCAL_MQTT_PASSWORD"),
    }
    for option, value in optional.items():
        if value:
            argv.extend([option, value])
    argv.append("--printer-mqtt" if _bool_env("AIRMONITOR_PRINTER_MQTT", True) else "--no-printer-mqtt")
    return argv


def main() -> int:
    try:
        argv = build_log_argv()
    except Exception as exc:
        print(f"Unable to resolve AirMonitor sensor hardware: {exc}", file=sys.stderr)
        return 1
    print(f"Resolved AirMonitor sensor port: {argv[argv.index('--port') + 1]}", flush=True)
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
