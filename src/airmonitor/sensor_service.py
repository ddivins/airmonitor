"""Systemd-friendly sensor logger with hardware resolution and hot-plug recovery."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from airmonitor.hardware import DEFAULT_HARDWARE_ID, DEFAULT_REGISTRY, resolve_device


DEFAULT_RETRY_SECONDS = 5.0
DEFAULT_DEVICE_POLL_SECONDS = 1.0


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _bool_env(name: str, default: bool) -> bool:
    value = _env(name, "true" if default else "false").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def resolve_configured_port() -> str:
    configured = _env("AIRMONITOR_PORT", "auto").strip()
    if configured and configured.lower() != "auto":
        return configured
    hardware_id = _env("AIRMONITOR_HARDWARE_ID", DEFAULT_HARDWARE_ID)
    registry = _env("AIRMONITOR_HARDWARE_REGISTRY", DEFAULT_REGISTRY)
    return resolve_device(hardware_id, registry_path=registry)


def build_log_argv(port: str) -> list[str]:
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


def _airmonitor_executable() -> str:
    candidate = Path(sys.executable).with_name("airmonitor")
    return str(candidate) if candidate.exists() else "airmonitor"


def _stop_child(child: subprocess.Popen[bytes]) -> None:
    if child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGINT)
        child.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def run_forever() -> int:
    retry_seconds = _float_env("AIRMONITOR_HARDWARE_RETRY_SECONDS", DEFAULT_RETRY_SECONDS)
    poll_seconds = _float_env("AIRMONITOR_DEVICE_POLL_SECONDS", DEFAULT_DEVICE_POLL_SECONDS)

    while True:
        try:
            port = resolve_configured_port()
        except Exception as exc:
            print(f"Sensor hardware not available yet: {exc}; retrying in {retry_seconds:g}s", file=sys.stderr, flush=True)
            time.sleep(retry_seconds)
            continue

        if not Path(port).exists():
            print(f"Sensor device not present yet: {port}; retrying in {retry_seconds:g}s", file=sys.stderr, flush=True)
            time.sleep(retry_seconds)
            continue

        argv = [_airmonitor_executable(), *build_log_argv(port)]
        print(f"Resolved AirMonitor sensor port: {port}", flush=True)
        child = subprocess.Popen(argv, start_new_session=True)

        try:
            while child.poll() is None:
                if not Path(port).exists():
                    print(f"Sensor device removed: {port}; stopping logger and waiting for reconnection", file=sys.stderr, flush=True)
                    _stop_child(child)
                    break
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            _stop_child(child)
            return 0

        rc = child.poll()
        if rc not in (None, 0):
            print(f"Sensor logger exited with status {rc}; retrying in {retry_seconds:g}s", file=sys.stderr, flush=True)
        time.sleep(retry_seconds)


def main() -> int:
    return run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
