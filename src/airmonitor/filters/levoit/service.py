#!/usr/bin/env python3
"""Control a VeSync/Levoit purifier from normalized printer MQTT state."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any, Optional

import paho.mqtt.client as mqtt
from pyvesync import VeSync


APP_NAME = "levoit-filter"
APP_VERSION = "0.1.1"
DEFAULT_ENV_FILE = "/etc/levoit-filter.env"
LOG = logging.getLogger(APP_NAME)

running = True
last_printer_state: Optional[dict[str, Any]] = None
last_action_signature: Optional[tuple[Any, ...]] = None


def load_env_file(path: str = DEFAULT_ENV_FILE) -> None:
    """Load simple KEY=VALUE entries from an env file if it is readable.

    Systemd reads the same file for the long-running service. This helper makes
    manual CLI commands behave the same way when run as a user that can read the
    env file, or when run with sudo.
    """
    env_path = Path(path)
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except PermissionError:
        return

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(os.environ.get("LEVOIT_FILTER_ENV", DEFAULT_ENV_FILE))


def getenv_required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def getenv_int(name: str, default: int, minimum: Optional[int] = None) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got: {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}, got: {value}")
    return value


def getenv_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "yes", "true", "on")


def getenv_optional_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer or blank, got: {raw!r}") from exc


VESYNC_USERNAME = os.environ.get("VESYNC_USERNAME")
VESYNC_PASSWORD = os.environ.get("VESYNC_PASSWORD")
VESYNC_TIME_ZONE = os.environ.get("VESYNC_TIME_ZONE", "America/New_York")
LEVOIT_DEVICE_NAME = os.environ.get("LEVOIT_DEVICE_NAME") or None
LEVOIT_FAN_SPEED = getenv_optional_int("LEVOIT_FAN_SPEED")

LOCAL_MQTT_HOST = os.environ.get("LOCAL_MQTT_HOST", "localhost")
LOCAL_MQTT_PORT = getenv_int("LOCAL_MQTT_PORT", 1883, minimum=1)
LOCAL_MQTT_TOPIC = os.environ.get("LOCAL_MQTT_TOPIC", "printer/state")
LOCAL_MQTT_CLIENT_ID = os.environ.get("LOCAL_MQTT_CLIENT_ID", APP_NAME)
LOCAL_MQTT_USERNAME = os.environ.get("LOCAL_MQTT_USERNAME") or None
LOCAL_MQTT_PASSWORD = os.environ.get("LOCAL_MQTT_PASSWORD") or None
LOCAL_MQTT_KEEPALIVE = getenv_int("LOCAL_MQTT_KEEPALIVE", 60, minimum=10)

AUTO_OFF_DELAY_SECONDS = getenv_int("LEVOIT_AUTO_OFF_DELAY_SECONDS", 1800, minimum=0)
TURN_OFF_WHEN_NOT_RECOMMENDED = getenv_bool("LEVOIT_TURN_OFF_WHEN_NOT_RECOMMENDED", False)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


@dataclass(frozen=True)
class DesiredState:
    should_run: bool
    reason: str
    delay_off_until: float | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stop_service(signum, frame) -> None:
    global running
    LOG.info("Received signal %s; stopping service", signum)
    running = False


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def login_manager() -> VeSync:
    if not VESYNC_USERNAME or not VESYNC_PASSWORD:
        raise RuntimeError("VESYNC_USERNAME and VESYNC_PASSWORD are required")

    manager = VeSync(VESYNC_USERNAME, VESYNC_PASSWORD, time_zone=VESYNC_TIME_ZONE)
    if not manager.login():
        raise RuntimeError("VeSync login failed")
    manager.update()
    return manager


def all_devices(manager: VeSync) -> list[Any]:
    devices: list[Any] = []
    for attr in ("fans", "outlets", "switches", "bulbs"):
        value = getattr(manager, attr, None)
        if isinstance(value, list):
            devices.extend(value)
    return devices


def device_name(device: Any) -> str:
    return str(getattr(device, "device_name", None) or getattr(device, "name", None) or "")


def find_purifier(manager: VeSync, name: str | None) -> Any:
    devices = all_devices(manager)
    if not devices:
        raise RuntimeError("No VeSync devices found")

    if name:
        for device in devices:
            if device_name(device) == name:
                return device
        names = ", ".join(sorted(device_name(d) or repr(d) for d in devices))
        raise RuntimeError(f"Could not find VeSync device named {name!r}. Found: {names}")

    fans = getattr(manager, "fans", None)
    if isinstance(fans, list) and len(fans) == 1:
        return fans[0]

    if len(devices) == 1:
        return devices[0]

    names = ", ".join(sorted(device_name(d) or repr(d) for d in devices))
    raise RuntimeError(f"Multiple VeSync devices found; set LEVOIT_DEVICE_NAME. Found: {names}")


def refresh_device(device: Any) -> Any:
    try:
        device.update()
    except Exception:
        LOG.debug("Device update failed", exc_info=True)
    return device


def is_on(device: Any) -> bool | None:
    for attr in ("is_on", "device_status"):
        value = getattr(device, attr, None)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("on", "true")
    return None


def turn_on(device: Any) -> None:
    LOG.info("Turning purifier ON")
    if hasattr(device, "turn_on"):
        device.turn_on()
    elif hasattr(device, "on"):
        device.on()
    else:
        raise RuntimeError("Selected VeSync device does not support turn_on/on")

    if LEVOIT_FAN_SPEED is not None:
        set_fan_speed(device, LEVOIT_FAN_SPEED)


def turn_off(device: Any) -> None:
    LOG.info("Turning purifier OFF")
    if hasattr(device, "turn_off"):
        device.turn_off()
    elif hasattr(device, "off"):
        device.off()
    else:
        raise RuntimeError("Selected VeSync device does not support turn_off/off")


def set_fan_speed(device: Any, speed: int) -> None:
    for method_name in ("change_fan_speed", "set_fan_speed", "fan_speed"):
        method = getattr(device, method_name, None)
        if callable(method):
            LOG.info("Setting purifier fan speed: %s", speed)
            method(speed)
            return
    LOG.warning("Selected purifier does not expose a known fan speed method; leaving speed unchanged")


def device_status(device: Any) -> dict[str, Any]:
    refresh_device(device)
    status = {
        "name": device_name(device),
        "type": type(device).__name__,
        "is_on": is_on(device),
    }
    for attr in (
        "mode",
        "fan_speed",
        "air_quality",
        "air_quality_value",
        "pm25",
        "filter_life",
        "details",
    ):
        value = getattr(device, attr, None)
        if value is not None:
            status[attr] = value
    return status


def desired_from_printer_state(state: dict[str, Any] | None, off_deadline: float | None) -> DesiredState:
    if not state:
        return DesiredState(False, "no printer state", off_deadline)

    active = bool(state.get("active"))
    recommended = bool(state.get("room_filter_recommended"))
    filament = state.get("filament_type")
    gcode_state = state.get("gcode_state")

    if active and recommended:
        return DesiredState(True, f"active print requires room filter: state={gcode_state} filament={filament}", None)

    if active and not recommended:
        if TURN_OFF_WHEN_NOT_RECOMMENDED:
            return DesiredState(False, f"active print does not require room filter: filament={filament}", None)
        return DesiredState(False, f"active print does not require room filter: filament={filament}", off_deadline)

    if off_deadline is not None:
        if time.time() < off_deadline:
            remaining = int(off_deadline - time.time())
            return DesiredState(True, f"cooldown delay active: {remaining}s remaining", off_deadline)
        return DesiredState(False, "cooldown delay expired", None)

    return DesiredState(False, f"printer inactive: state={gcode_state}", None)


def apply_desired_state(device: Any, desired: DesiredState) -> None:
    global last_action_signature
    signature = (desired.should_run, desired.reason, int(desired.delay_off_until or 0))
    if signature != last_action_signature:
        LOG.info("Desired state: should_run=%s reason=%s", desired.should_run, desired.reason)
        last_action_signature = signature

    current = is_on(refresh_device(device))
    if desired.should_run and current is not True:
        turn_on(device)
    elif not desired.should_run and current is not False:
        turn_off(device)


def on_mqtt_connect(client, userdata, flags, reason_code, properties=None):
    LOG.info("Connected to MQTT at %s:%s result=%s", LOCAL_MQTT_HOST, LOCAL_MQTT_PORT, reason_code)
    client.subscribe(LOCAL_MQTT_TOPIC)
    LOG.info("Subscribed to MQTT topic: %s", LOCAL_MQTT_TOPIC)


def on_mqtt_message(client, userdata, msg):
    global last_printer_state
    try:
        data = json.loads(msg.payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        LOG.debug("Ignoring non-JSON MQTT message on %s", msg.topic)
        return
    if not isinstance(data, dict):
        return
    last_printer_state = data


def build_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=LOCAL_MQTT_CLIENT_ID)
    if LOCAL_MQTT_USERNAME or LOCAL_MQTT_PASSWORD:
        client.username_pw_set(LOCAL_MQTT_USERNAME, LOCAL_MQTT_PASSWORD)
    client.on_connect = on_mqtt_connect
    client.on_message = on_mqtt_message
    return client


def run_service() -> int:
    setup_logging()
    signal.signal(signal.SIGTERM, stop_service)
    signal.signal(signal.SIGINT, stop_service)

    LOG.info("Starting %s version %s", APP_NAME, APP_VERSION)
    LOG.info("MQTT: %s:%s topic=%s", LOCAL_MQTT_HOST, LOCAL_MQTT_PORT, LOCAL_MQTT_TOPIC)
    LOG.info("Auto off delay: %ss", AUTO_OFF_DELAY_SECONDS)

    manager = login_manager()
    device = find_purifier(manager, LEVOIT_DEVICE_NAME)
    LOG.info("Selected purifier: %s (%s)", device_name(device), type(device).__name__)

    client = build_mqtt_client()
    client.connect(LOCAL_MQTT_HOST, LOCAL_MQTT_PORT, keepalive=LOCAL_MQTT_KEEPALIVE)
    client.loop_start()

    off_deadline: float | None = None
    was_required = False

    try:
        while running:
            state = last_printer_state
            active_required = bool(state and state.get("active") and state.get("room_filter_recommended"))

            if active_required:
                off_deadline = None
                was_required = True
            elif was_required and off_deadline is None:
                off_deadline = time.time() + AUTO_OFF_DELAY_SECONDS
                was_required = False
                LOG.info("Starting purifier cooldown timer: %ss", AUTO_OFF_DELAY_SECONDS)

            desired = desired_from_printer_state(state, off_deadline)
            if desired.delay_off_until is None and off_deadline is not None and not desired.should_run:
                off_deadline = None
            apply_desired_state(device, desired)
            time.sleep(5)
    finally:
        client.loop_stop()
        client.disconnect()
        LOG.info("%s stopped", APP_NAME)

    return 0


def discover() -> int:
    setup_logging()
    manager = login_manager()
    devices = all_devices(manager)
    for device in devices:
        print(json.dumps(device_status(device), sort_keys=True, default=str))
    return 0


def manual(command: str) -> int:
    setup_logging()
    manager = login_manager()
    device = find_purifier(manager, LEVOIT_DEVICE_NAME)
    if command == "status":
        print(json.dumps(device_status(device), indent=2, sort_keys=True, default=str))
    elif command == "on":
        turn_on(device)
        print(json.dumps(device_status(device), indent=2, sort_keys=True, default=str))
    elif command == "off":
        turn_off(device)
        print(json.dumps(device_status(device), indent=2, sort_keys=True, default=str))
    else:
        raise AssertionError(command)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="levoit-filter")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="run the purifier automation service")
    subparsers.add_parser("discover", help="list VeSync devices")
    subparsers.add_parser("status", help="show selected purifier status")
    subparsers.add_parser("on", help="turn selected purifier on")
    subparsers.add_parser("off", help="turn selected purifier off")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return run_service()
    if args.command == "discover":
        return discover()
    if args.command in ("status", "on", "off"):
        return manual(args.command)
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
