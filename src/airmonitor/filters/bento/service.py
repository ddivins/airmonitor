#!/usr/bin/env python3
"""Bambu Bento Box filter automation.

This service consumes normalized printer state from a local MQTT broker and
controls a Kasa smart outlet powering a Bento Box filter.

The direct Bambu printer MQTT connection is owned by printer-mqtt-service.
"""

import asyncio
import json
import logging
import os
import signal
import time
from datetime import datetime
from typing import Optional, Set

import paho.mqtt.client as mqtt
from kasa import Discover


APP_NAME = "bambu-bento"
APP_VERSION = "3.2.0"

LOG = logging.getLogger(APP_NAME)


# ----------------------------
# Config helpers
# ----------------------------

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


def getenv_csv_upper(name: str, default: str) -> Set[str]:
    raw = os.environ.get(name, default)
    values = {item.strip().upper() for item in raw.split(",") if item.strip()}
    if not values:
        raise RuntimeError(f"{name} must contain at least one state")
    return values


def getenv_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "yes", "true", "on")


OUTLET_HOST = getenv_required("OUTLET_HOST")
KASA_USERNAME = os.environ.get("KASA_USERNAME") or None
KASA_PASSWORD = os.environ.get("KASA_PASSWORD") or None

OFF_DELAY_SECONDS = getenv_int("OFF_DELAY_SECONDS", 1800, minimum=0)
RECONNECT_DELAY = getenv_int("RECONNECT_DELAY", 15, minimum=1)
MQTT_KEEPALIVE = getenv_int("MQTT_KEEPALIVE", 60, minimum=10)
LOCAL_MQTT_PORT = getenv_int("LOCAL_MQTT_PORT", 1883, minimum=1)
HEARTBEAT_SECONDS = getenv_int("HEARTBEAT_SECONDS", 600, minimum=30)
MQTT_WATCHDOG_SECONDS = getenv_int("MQTT_WATCHDOG_SECONDS", 300, minimum=60)

TURN_OFF_ON_SERVICE_STOP = getenv_bool("TURN_OFF_ON_SERVICE_STOP", False)

ON_STATES = getenv_csv_upper("ON_STATES", "RUNNING,PREPARE,PAUSE")

LOCAL_MQTT_HOST = os.environ.get("LOCAL_MQTT_HOST", "localhost")
LOCAL_MQTT_USERNAME = os.environ.get("LOCAL_MQTT_USERNAME") or None
LOCAL_MQTT_PASSWORD = os.environ.get("LOCAL_MQTT_PASSWORD") or None
LOCAL_MQTT_TOPIC = os.environ.get("LOCAL_MQTT_TOPIC", "printer/state")
LOCAL_MQTT_AVAILABILITY_TOPIC = os.environ.get("LOCAL_MQTT_AVAILABILITY_TOPIC", "printer/available")
LOCAL_MQTT_CLIENT_ID = os.environ.get("LOCAL_MQTT_CLIENT_ID", APP_NAME)

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


# ----------------------------
# Runtime state
# ----------------------------

running = True
force_mqtt_reconnect = False
loop: Optional[asyncio.AbstractEventLoop] = None

outlet_device = None
outlet_is_on: Optional[bool] = None
last_printer_state: Optional[str] = None
last_printer_active: Optional[bool] = None
last_mqtt_seen: Optional[float] = None
last_power_watts: Optional[float] = None
last_printer_available: Optional[str] = None

off_task: Optional[asyncio.Future] = None
off_scheduled_at_epoch: Optional[float] = None
off_due_at_epoch: Optional[float] = None


# ----------------------------
# Formatting helpers
# ----------------------------

def local_dt(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "n/a"

    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)

    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def off_timer_status() -> str:
    if not off_task or off_task.done() or off_due_at_epoch is None:
        return "not_running"

    remaining = off_due_at_epoch - time.time()
    return f"running off_in={fmt_duration(remaining)} due_at={local_dt(off_due_at_epoch)}"


# ----------------------------
# Kasa outlet
# ----------------------------

async def connect_outlet() -> None:
    global outlet_device, outlet_is_on, last_power_watts

    LOG.info("Connecting to Kasa outlet at %s", OUTLET_HOST)

    outlet_device = await Discover.discover_single(
        OUTLET_HOST,
        username=KASA_USERNAME,
        password=KASA_PASSWORD,
    )

    if outlet_device is None:
        raise RuntimeError(f"Could not discover/connect to Kasa outlet {OUTLET_HOST}")

    await outlet_device.update()
    outlet_is_on = bool(outlet_device.is_on)
    last_power_watts = read_power_watts()

    LOG.info(
        "Connected to outlet: alias=%s model=%s state=%s power=%sW",
        getattr(outlet_device, "alias", "unknown"),
        getattr(outlet_device, "model", "unknown"),
        "ON" if outlet_is_on else "OFF",
        last_power_watts if last_power_watts is not None else "unknown",
    )


def read_power_watts() -> Optional[float]:
    if outlet_device is None:
        return None

    try:
        feature = outlet_device.features.get("current_consumption")
        if feature is None or feature.value is None:
            return None
        return float(feature.value)
    except Exception:
        return None


async def refresh_outlet_status() -> None:
    global outlet_device, outlet_is_on, last_power_watts

    if outlet_device is None:
        await connect_outlet()
        return

    try:
        await outlet_device.update()
    except Exception:
        LOG.warning("Outlet refresh failed; reconnecting", exc_info=True)
        outlet_device = None
        await connect_outlet()
        return

    outlet_is_on = bool(outlet_device.is_on)
    last_power_watts = read_power_watts()


async def disconnect_outlet() -> None:
    """Release python-kasa's HTTP session and clear cached outlet state."""
    global outlet_device, outlet_is_on, last_power_watts

    device, outlet_device = outlet_device, None
    outlet_is_on = None
    last_power_watts = None

    if device is None:
        return

    try:
        await device.disconnect()
        LOG.info("Disconnected from Kasa outlet")
    except Exception:
        LOG.warning("Failed to disconnect cleanly from Kasa outlet", exc_info=True)


async def set_outlet(state: bool) -> None:
    global outlet_device, outlet_is_on, last_power_watts

    if outlet_is_on == state:
        LOG.debug("Outlet already %s; duplicate command suppressed", "ON" if state else "OFF")
        return

    if outlet_device is None:
        await connect_outlet()

    LOG.info(
        "Outlet change requested: %s -> %s",
        "unknown" if outlet_is_on is None else ("ON" if outlet_is_on else "OFF"),
        "ON" if state else "OFF",
    )

    try:
        await outlet_device.update()
        if state:
            await outlet_device.turn_on()
        else:
            await outlet_device.turn_off()
        await outlet_device.update()
    except Exception:
        LOG.warning("Outlet command failed; reconnecting and retrying once", exc_info=True)
        outlet_device = None
        await connect_outlet()
        if state:
            await outlet_device.turn_on()
        else:
            await outlet_device.turn_off()
        await outlet_device.update()

    outlet_is_on = bool(outlet_device.is_on)
    last_power_watts = read_power_watts()

    LOG.info(
        "Outlet state now: %s%s",
        "ON" if outlet_is_on else "OFF",
        f" power={last_power_watts}W" if last_power_watts is not None else "",
    )


# ----------------------------
# Timers and printer state
# ----------------------------

async def delayed_off() -> None:
    global off_scheduled_at_epoch, off_due_at_epoch

    LOG.info(
        "Print inactive; outlet OFF scheduled for %s, in %s",
        local_dt(off_due_at_epoch),
        fmt_duration(off_due_at_epoch - time.time()),
    )

    try:
        await asyncio.sleep(OFF_DELAY_SECONDS)
        LOG.info("Delayed OFF timer expired; turning outlet OFF")
        await set_outlet(False)
    except asyncio.CancelledError:
        LOG.info("Delayed OFF timer canceled")
        raise
    finally:
        off_scheduled_at_epoch = None
        off_due_at_epoch = None


def cancel_off_timer() -> None:
    global off_task, off_scheduled_at_epoch, off_due_at_epoch

    if off_task and not off_task.done():
        LOG.info("Canceling pending outlet OFF timer")
        off_task.cancel()

    off_task = None
    off_scheduled_at_epoch = None
    off_due_at_epoch = None


def schedule_off_timer() -> None:
    global off_task, off_scheduled_at_epoch, off_due_at_epoch

    if outlet_is_on is False:
        LOG.debug("Outlet already OFF; delayed OFF timer not needed")
        return

    if off_task and not off_task.done():
        LOG.debug("Delayed OFF timer already running: %s", off_timer_status())
        return

    now = time.time()
    off_scheduled_at_epoch = now
    off_due_at_epoch = now + OFF_DELAY_SECONDS

    LOG.info(
        "Scheduling delayed outlet OFF: now=%s due_at=%s delay=%s",
        local_dt(off_scheduled_at_epoch),
        local_dt(off_due_at_epoch),
        fmt_duration(OFF_DELAY_SECONDS),
    )

    off_task = asyncio.run_coroutine_threadsafe(delayed_off(), loop)


async def handle_printer_state(gcode_state: str, active: Optional[bool] = None) -> None:
    global last_printer_state, last_printer_active, last_mqtt_seen

    last_mqtt_seen = time.time()
    state = gcode_state.strip().upper()
    is_active = bool(active) if active is not None else state in ON_STATES

    if state != last_printer_state or is_active != last_printer_active:
        LOG.info(
            "Printer state transition: state=%s -> %s active=%s -> %s",
            last_printer_state,
            state,
            last_printer_active,
            is_active,
        )
        last_printer_state = state
        last_printer_active = is_active
    else:
        LOG.debug("Duplicate printer state suppressed: %s active=%s", state, is_active)

    if state in ON_STATES:
        cancel_off_timer()
        await set_outlet(True)
    else:
        schedule_off_timer()


# ----------------------------
# Heartbeat and watchdog
# ----------------------------

async def heartbeat_runner() -> None:
    while running:
        await asyncio.sleep(HEARTBEAT_SECONDS)

        try:
            await refresh_outlet_status()
        except Exception:
            LOG.warning("Heartbeat outlet refresh failed", exc_info=True)

        mqtt_age = None
        if last_mqtt_seen is not None:
            mqtt_age = int(time.time() - last_mqtt_seen)

        LOG.info(
            "Heartbeat: version=%s printer_state=%s printer_available=%s outlet=%s power=%sW mqtt_last_seen=%ss off_timer=%s",
            APP_VERSION,
            last_printer_state or "unknown",
            last_printer_available or "unknown",
            "unknown" if outlet_is_on is None else ("ON" if outlet_is_on else "OFF"),
            "unknown" if last_power_watts is None else last_power_watts,
            "never" if mqtt_age is None else mqtt_age,
            off_timer_status(),
        )


async def watchdog_runner() -> None:
    global force_mqtt_reconnect

    while running:
        await asyncio.sleep(10)

        if last_mqtt_seen is None:
            continue

        age = time.time() - last_mqtt_seen
        if age > MQTT_WATCHDOG_SECONDS:
            LOG.warning(
                "MQTT watchdog triggered: no local printer state for %s seconds; forcing reconnect",
                int(age),
            )
            force_mqtt_reconnect = True
            await asyncio.sleep(RECONNECT_DELAY)


# ----------------------------
# MQTT
# ----------------------------

def extract_normalized_state(payload: bytes) -> tuple[Optional[str], Optional[bool]]:
    try:
        data = json.loads(payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        LOG.debug("Received non-JSON local MQTT payload")
        return None, None

    state = data.get("gcode_state")
    active = data.get("active")

    if not isinstance(state, str):
        return None, None

    return state, active if isinstance(active, bool) else None


def on_connect(client, userdata, flags, reason_code, properties=None):
    LOG.info("Connected to local MQTT at %s:%s result=%s", LOCAL_MQTT_HOST, LOCAL_MQTT_PORT, reason_code)
    client.subscribe(LOCAL_MQTT_TOPIC)
    client.subscribe(LOCAL_MQTT_AVAILABILITY_TOPIC)
    LOG.info("Subscribed to local MQTT topics: %s, %s", LOCAL_MQTT_TOPIC, LOCAL_MQTT_AVAILABILITY_TOPIC)


def on_disconnect(client, userdata, *args, **kwargs):
    LOG.warning("Disconnected from local MQTT args=%s kwargs=%s", args, kwargs)


def on_message(client, userdata, msg):
    global last_printer_available, last_mqtt_seen

    if msg.topic == LOCAL_MQTT_AVAILABILITY_TOPIC:
        value = msg.payload.decode("utf-8", errors="replace").strip().lower()
        last_printer_available = value
        LOG.info("Printer MQTT availability: %s", value)
        return

    if msg.topic != LOCAL_MQTT_TOPIC:
        LOG.debug("Ignoring unexpected local MQTT topic: %s", msg.topic)
        return

    state, active = extract_normalized_state(msg.payload)
    if state and loop is not None:
        asyncio.run_coroutine_threadsafe(handle_printer_state(state, active), loop)
    else:
        LOG.debug("Local printer state payload did not include gcode_state")


async def mqtt_runner() -> None:
    global force_mqtt_reconnect

    while running:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{LOCAL_MQTT_CLIENT_ID}-{int(time.time())}",
        )

        if LOCAL_MQTT_USERNAME or LOCAL_MQTT_PASSWORD:
            client.username_pw_set(LOCAL_MQTT_USERNAME, LOCAL_MQTT_PASSWORD)

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message

        try:
            force_mqtt_reconnect = False
            LOG.info("Connecting to local MQTT at %s:%s", LOCAL_MQTT_HOST, LOCAL_MQTT_PORT)
            client.connect(LOCAL_MQTT_HOST, LOCAL_MQTT_PORT, keepalive=MQTT_KEEPALIVE)
            client.loop_start()

            while running and not force_mqtt_reconnect:
                await asyncio.sleep(1)

            client.loop_stop()
            client.disconnect()

            if force_mqtt_reconnect and running:
                LOG.info("MQTT reconnect requested by watchdog")
                await asyncio.sleep(RECONNECT_DELAY)

        except Exception:
            LOG.exception("MQTT connection failed; retrying in %s seconds", RECONNECT_DELAY)
            try:
                client.loop_stop()
            except Exception:
                pass
            await asyncio.sleep(RECONNECT_DELAY)


# ----------------------------
# Shutdown
# ----------------------------

def stop_service(signum, frame):
    global running
    LOG.info("Received signal %s; stopping service", signum)
    running = False


async def shutdown_cleanup(tasks: list[asyncio.Task]) -> None:
    cancel_off_timer()

    for task in tasks:
        task.cancel()

    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass

    try:
        if TURN_OFF_ON_SERVICE_STOP:
            LOG.info("TURN_OFF_ON_SERVICE_STOP enabled; turning outlet OFF")
            await set_outlet(False)
    except Exception:
        LOG.warning("Failed to turn outlet off during shutdown", exc_info=True)
    finally:
        await disconnect_outlet()


# ----------------------------
# Startup
# ----------------------------

def log_startup_config() -> None:
    LOG.info("Starting %s version %s", APP_NAME, APP_VERSION)
    LOG.info("Local MQTT broker: %s:%s", LOCAL_MQTT_HOST, LOCAL_MQTT_PORT)
    LOG.info("Local MQTT state topic: %s", LOCAL_MQTT_TOPIC)
    LOG.info("Local MQTT availability topic: %s", LOCAL_MQTT_AVAILABILITY_TOPIC)
    LOG.info("Outlet host: %s", OUTLET_HOST)
    LOG.info("ON states: %s", sorted(ON_STATES))
    LOG.info("OFF delay: %s seconds", OFF_DELAY_SECONDS)
    LOG.info("Heartbeat: every %s seconds", HEARTBEAT_SECONDS)
    LOG.info("MQTT watchdog: %s seconds", MQTT_WATCHDOG_SECONDS)
    LOG.info("Turn outlet off on service stop: %s", TURN_OFF_ON_SERVICE_STOP)

    if bool(KASA_USERNAME) != bool(KASA_PASSWORD):
        raise RuntimeError("KASA_USERNAME and KASA_PASSWORD must either both be set or both be blank")
    if bool(LOCAL_MQTT_USERNAME) != bool(LOCAL_MQTT_PASSWORD):
        raise RuntimeError("LOCAL_MQTT_USERNAME and LOCAL_MQTT_PASSWORD must either both be set or both be blank")


async def main() -> None:
    global loop

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    loop = asyncio.get_running_loop()

    signal.signal(signal.SIGTERM, stop_service)
    signal.signal(signal.SIGINT, stop_service)

    log_startup_config()

    await connect_outlet()
    background_tasks = [
        asyncio.create_task(heartbeat_runner(), name="heartbeat"),
        asyncio.create_task(watchdog_runner(), name="watchdog"),
    ]

    try:
        await mqtt_runner()
    finally:
        await shutdown_cleanup(background_tasks)
        LOG.info("%s stopped", APP_NAME)


def run() -> None:
    """Run the service from the console entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
