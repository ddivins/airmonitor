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

from airmonitor.database import connect, init_db
from airmonitor.database.repositories import FilterControlRepository
from airmonitor.filters.control import FilterState, resolve_filter_state


APP_NAME = "airmonitor-levoit"
APP_VERSION = "0.1.5"
FILTER_ID = "levoit"
DEFAULT_ENV_FILE = "/etc/airmonitor/levoit.env"
LOG = logging.getLogger(APP_NAME)

running = True
last_printer_state: Optional[dict[str, Any]] = None
last_printer_state_at: Optional[float] = None
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
LEVOIT_POLL_INTERVAL_SECONDS = getenv_int("LEVOIT_POLL_INTERVAL_SECONDS", 120, minimum=30)

LOCAL_MQTT_HOST = os.environ.get("LOCAL_MQTT_HOST", "localhost")
LOCAL_MQTT_PORT = getenv_int("LOCAL_MQTT_PORT", 1883, minimum=1)
LOCAL_MQTT_TOPIC = os.environ.get("LOCAL_MQTT_TOPIC", "printer/state")
LOCAL_MQTT_CLIENT_ID = os.environ.get("LOCAL_MQTT_CLIENT_ID", APP_NAME)
LOCAL_MQTT_USERNAME = os.environ.get("LOCAL_MQTT_USERNAME") or None
LOCAL_MQTT_PASSWORD = os.environ.get("LOCAL_MQTT_PASSWORD") or None
LOCAL_MQTT_KEEPALIVE = getenv_int("LOCAL_MQTT_KEEPALIVE", 60, minimum=10)

AUTO_OFF_DELAY_SECONDS = getenv_int("LEVOIT_AUTO_OFF_DELAY_SECONDS", 1800, minimum=0)
PRINTER_STATE_STALE_SECONDS = getenv_int("PRINTER_STATE_STALE_SECONDS", 300, minimum=30)
TURN_OFF_WHEN_NOT_RECOMMENDED = getenv_bool("LEVOIT_TURN_OFF_WHEN_NOT_RECOMMENDED", False)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
DATABASE_PATH = os.environ.get("AIRMONITOR_DATABASE", "/var/lib/airmonitor/airmonitor.sqlite3")


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


def refresh_device(device: Any) -> bool:
    """Refresh device state once and report whether the cloud request succeeded."""
    try:
        device.update()
        return True
    except Exception:
        LOG.warning("VeSync device update failed", exc_info=True)
        return False


def is_on(device: Any) -> bool | None:
    for attr in ("is_on", "device_status"):
        value = getattr(device, attr, None)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("on", "true")
    return None


def filter_state_value(value: bool | None) -> str:
    if value is None:
        return FilterState.UNKNOWN.value
    return FilterState.ON.value if value else FilterState.OFF.value


def external_override_mode(expected: bool | None, actual: bool | None) -> str | None:
    """Latch external ON, while external OFF releases control back to auto."""
    if expected is None or actual is None or actual == expected:
        return None
    return FilterState.ON.value if actual else "auto"


def record_external_manual_override(actual: bool) -> bool:
    """Persist external ON or release an existing override on external OFF."""
    state = filter_state_value(actual)
    manual_mode = FilterState.ON.value if actual else "auto"
    reason = "external manual change detected: on" if actual else "external off returned control to auto"
    try:
        conn = connect(DATABASE_PATH)
        init_db(conn)
        repo = FilterControlRepository(conn)
        repo.update(
            FILTER_ID,
            manual_mode=manual_mode,
            actual_state=state,
            effective_state=state,
            reason=reason,
        )
        conn.close()
        LOG.info("Detected external purifier state change; control mode is now %s", str(manual_mode).upper())
        return True
    except Exception:
        LOG.warning("Failed to persist external Levoit manual override", exc_info=True)
        return False


def record_filter_state(
    *,
    automation_request: str | None = None,
    actual_state: str | None = None,
    effective_state: str | None = None,
    reason: str | None = None,
) -> None:
    try:
        conn = connect(DATABASE_PATH)
        init_db(conn)
        repo = FilterControlRepository(conn)
        repo.update(
            FILTER_ID,
            automation_request=automation_request,
            actual_state=actual_state,
            effective_state=effective_state,
            reason=reason,
        )
        conn.close()
    except Exception:
        LOG.warning("Failed to record Levoit filter control state", exc_info=True)


def resolve_desired_filter_state(automation_request: str, reason: str, actual_state: str) -> tuple[str, str]:
    try:
        conn = connect(DATABASE_PATH)
        init_db(conn)
        repo = FilterControlRepository(conn)
        record = repo.update(
            FILTER_ID,
            automation_request=automation_request,
            actual_state=actual_state,
            reason=reason,
        )
        decision = resolve_filter_state(
            filter_id=FILTER_ID,
            manual_mode=record.manual_mode,
            automation_request=automation_request,
            automation_reason=reason,
        )
        repo.update(FILTER_ID, effective_state=decision.effective_state.value, reason=decision.reason)
        conn.close()
        return decision.effective_state.value, decision.reason
    except Exception:
        LOG.warning("Failed to resolve Levoit filter control state; using automation request", exc_info=True)
        return automation_request, reason


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


def telemetry_from_device(device: Any, current: bool | None) -> dict[str, Any]:
    """Normalize the fields exposed by different pyvesync purifier classes."""
    details = getattr(device, "details", None)
    details = details if isinstance(details, dict) else {}

    def first_value(*values):
        return next((value for value in values if value is not None), None)

    return {
        "device_name": device_name(device),
        "power_state": filter_state_value(current),
        "mode": first_value(getattr(device, "mode", None), details.get("mode")),
        "fan_level": first_value(
            getattr(device, "fan_speed", None),
            getattr(device, "speed", None),
            details.get("level"),
        ),
        "pm2_5": first_value(
            getattr(device, "pm25", None),
            getattr(device, "air_quality_value", None),
            details.get("air_quality_value"),
        ),
        "air_quality": first_value(getattr(device, "air_quality", None), details.get("air_quality")),
        "filter_life_percent": first_value(getattr(device, "filter_life", None), details.get("filter_life")),
        "raw_json": json.dumps(details, sort_keys=True, default=str),
    }


def record_levoit_telemetry(device: Any, current: bool | None) -> None:
    telemetry = telemetry_from_device(device, current)
    try:
        conn = connect(DATABASE_PATH)
        init_db(conn)
        conn.execute(
            """
            INSERT INTO levoit_samples (
                device_name, power_state, mode, fan_level, pm2_5,
                air_quality, filter_life_percent, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(telemetry[key] for key in (
                "device_name", "power_state", "mode", "fan_level", "pm2_5",
                "air_quality", "filter_life_percent", "raw_json",
            )),
        )
        conn.commit()
        conn.close()
    except Exception:
        LOG.warning("Failed to record Levoit telemetry", exc_info=True)


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


def apply_desired_state(device: Any, desired: DesiredState, current: bool | None) -> bool | None:
    """Apply a state change using the already-refreshed device state.

    No cloud refresh occurs here. The returned value reflects the requested state
    when a command was sent and is verified on the next scheduled poll.
    """
    global last_action_signature
    signature = (desired.should_run, desired.reason, int(desired.delay_off_until or 0))
    if signature != last_action_signature:
        LOG.info("Desired state: should_run=%s reason=%s", desired.should_run, desired.reason)
        last_action_signature = signature

    if desired.should_run and current is not True:
        turn_on(device)
        return True
    if not desired.should_run and current is not False:
        turn_off(device)
        return False
    return current


def on_mqtt_connect(client, userdata, flags, reason_code, properties=None):
    LOG.info("Connected to MQTT at %s:%s result=%s", LOCAL_MQTT_HOST, LOCAL_MQTT_PORT, reason_code)
    client.subscribe(LOCAL_MQTT_TOPIC)
    LOG.info("Subscribed to MQTT topic: %s", LOCAL_MQTT_TOPIC)


def on_mqtt_message(client, userdata, msg):
    global last_printer_state, last_printer_state_at
    try:
        data = json.loads(msg.payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        LOG.debug("Ignoring non-JSON MQTT message on %s", msg.topic)
        return
    if not isinstance(data, dict):
        return
    last_printer_state = data
    last_printer_state_at = time.time()


def printer_state_is_fresh(last_seen_at: Optional[float], *, now: float, stale_after_seconds: float) -> bool:
    """Whether the local MQTT printer-state feed is fresh enough to trust for a new decision.

    A feed that was never received is treated as not-fresh (the pre-existing
    "no printer state" fallback below already handles that safely at startup).
    A feed that *was* received and then went silent must not be silently reread
    as still-current: we hold the last automation decision instead of deriving
    a new one from a stale snapshot.
    """
    if last_seen_at is None:
        return False
    return (now - last_seen_at) <= stale_after_seconds


def build_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=LOCAL_MQTT_CLIENT_ID)
    if LOCAL_MQTT_USERNAME or LOCAL_MQTT_PASSWORD:
        client.username_pw_set(LOCAL_MQTT_USERNAME, LOCAL_MQTT_PASSWORD)
    client.on_connect = on_mqtt_connect
    client.on_message = on_mqtt_message
    return client


def sleep_until_next_poll(seconds: int) -> None:
    """Sleep in short increments so systemd stop requests remain responsive."""
    deadline = time.monotonic() + seconds
    while running and time.monotonic() < deadline:
        time.sleep(min(1.0, deadline - time.monotonic()))


def run_service() -> int:
    setup_logging()
    signal.signal(signal.SIGTERM, stop_service)
    signal.signal(signal.SIGINT, stop_service)

    LOG.info("Starting %s version %s", APP_NAME, APP_VERSION)
    LOG.info("MQTT: %s:%s topic=%s", LOCAL_MQTT_HOST, LOCAL_MQTT_PORT, LOCAL_MQTT_TOPIC)
    LOG.info("Auto off delay: %ss", AUTO_OFF_DELAY_SECONDS)
    LOG.info("VeSync poll interval: %ss", LEVOIT_POLL_INTERVAL_SECONDS)

    manager = login_manager()
    device = find_purifier(manager, LEVOIT_DEVICE_NAME)
    LOG.info("Selected purifier: %s (%s)", device_name(device), type(device).__name__)

    client = build_mqtt_client()
    client.connect(LOCAL_MQTT_HOST, LOCAL_MQTT_PORT, keepalive=LOCAL_MQTT_KEEPALIVE)
    client.loop_start()

    off_deadline: float | None = None
    was_required = False
    expected_device_state: bool | None = None

    try:
        while running:
            state = last_printer_state
            now = time.time()
            state_is_stale = state is not None and not printer_state_is_fresh(
                last_printer_state_at, now=now, stale_after_seconds=PRINTER_STATE_STALE_SECONDS
            )

            if not state_is_stale:
                active_required = bool(state and state.get("active") and state.get("room_filter_recommended"))

                if active_required:
                    off_deadline = None
                    was_required = True
                elif was_required and off_deadline is None:
                    off_deadline = now + AUTO_OFF_DELAY_SECONDS
                    was_required = False
                    LOG.info("Starting purifier cooldown timer: %ss", AUTO_OFF_DELAY_SECONDS)

            # Exactly one VeSync device refresh per service cycle. All decisions,
            # database writes, and possible commands reuse this state.
            refresh_device(device)
            current = is_on(device)
            override_mode = external_override_mode(expected_device_state, current)
            if override_mode is not None:
                record_external_manual_override(bool(current))
            actual_state = filter_state_value(current)

            if state_is_stale:
                # A feed that was fresh and went silent must not be reread as
                # still-current: hold whatever automation_request/effective_state
                # is already persisted instead of deriving a new one from a stale
                # snapshot (see printer_state_is_fresh).
                reason = f"printer state stale (>{PRINTER_STATE_STALE_SECONDS}s); holding last automation request"
                LOG.warning(reason)
                record_filter_state(actual_state=actual_state, reason=reason)
                expected_device_state = current
                record_levoit_telemetry(device, current)
                sleep_until_next_poll(LEVOIT_POLL_INTERVAL_SECONDS)
                continue

            desired = desired_from_printer_state(state, off_deadline)
            if desired.delay_off_until is None and off_deadline is not None and not desired.should_run:
                off_deadline = None

            automation_request = FilterState.ON.value if desired.should_run else FilterState.OFF.value
            effective_state, reason = resolve_desired_filter_state(automation_request, desired.reason, actual_state)
            desired = DesiredState(
                should_run=effective_state == FilterState.ON.value,
                reason=reason,
                delay_off_until=desired.delay_off_until,
            )
            current = apply_desired_state(device, desired, current)
            expected_device_state = current
            record_levoit_telemetry(device, current)
            record_filter_state(
                actual_state=filter_state_value(current),
                effective_state=effective_state,
                reason=reason,
            )
            sleep_until_next_poll(LEVOIT_POLL_INTERVAL_SECONDS)
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
    parser = argparse.ArgumentParser(prog="airmonitor-levoit")
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
