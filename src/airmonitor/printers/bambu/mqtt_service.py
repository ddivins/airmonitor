#!/usr/bin/env python3
"""Bambu printer MQTT normalization service.

This service owns the direct Bambu local MQTT connection and republishes a
small normalized state object to a local MQTT broker for consumers such as
bambu-bento and AirMonitor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import os
import signal
import ssl
import time
from typing import Any, Optional

import paho.mqtt.client as mqtt


APP_NAME = "printer-mqtt-service"
APP_VERSION = "0.2.0"
LOG = logging.getLogger(APP_NAME)

running = True
last_bambu_seen: Optional[float] = None
last_state: Optional["PrinterState"] = None
last_log_signature: Optional[tuple[Any, ...]] = None
local_client: Optional[mqtt.Client] = None


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


PRINTER_HOST = getenv_required("PRINTER_HOST")
PRINTER_SERIAL = getenv_required("PRINTER_SERIAL")
PRINTER_ACCESS_CODE = getenv_required("PRINTER_ACCESS_CODE")
PRINTER_MQTT_PORT = getenv_int("PRINTER_MQTT_PORT", 8883, minimum=1)
PRINTER_MQTT_USERNAME = os.environ.get("PRINTER_MQTT_USERNAME", "bblp")
PRINTER_MQTT_KEEPALIVE = getenv_int("PRINTER_MQTT_KEEPALIVE", 60, minimum=10)
PRINTER_MQTT_TOPIC = os.environ.get("PRINTER_MQTT_TOPIC") or f"device/{PRINTER_SERIAL}/report"

LOCAL_MQTT_HOST = os.environ.get("LOCAL_MQTT_HOST", "localhost")
LOCAL_MQTT_PORT = getenv_int("LOCAL_MQTT_PORT", 1883, minimum=1)
LOCAL_MQTT_USERNAME = os.environ.get("LOCAL_MQTT_USERNAME") or None
LOCAL_MQTT_PASSWORD = os.environ.get("LOCAL_MQTT_PASSWORD") or None
LOCAL_MQTT_TOPIC_PREFIX = os.environ.get("LOCAL_MQTT_TOPIC_PREFIX", "printer").strip("/")
LOCAL_MQTT_CLIENT_ID = os.environ.get("LOCAL_MQTT_CLIENT_ID", APP_NAME)

RECONNECT_DELAY = getenv_int("RECONNECT_DELAY", 15, minimum=1)
WATCHDOG_SECONDS = getenv_int("WATCHDOG_SECONDS", 300, minimum=60)
HEARTBEAT_SECONDS = getenv_int("HEARTBEAT_SECONDS", 600, minimum=30)
PUBLISH_RAW = getenv_bool("PUBLISH_RAW", False)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

ACTIVE_STATES = {"RUNNING", "PREPARE", "PAUSE"}


@dataclass(frozen=True)
class PrinterState:
    connected: bool
    active: bool
    gcode_state: Optional[str]
    print_error: Optional[int]
    progress_percent: Optional[int]
    layer_num: Optional[int]
    total_layer_num: Optional[int]
    subtask_name: Optional[str]
    nozzle_temperature_c: Optional[float]
    bed_temperature_c: Optional[float]
    chamber_temperature_c: Optional[float]
    nozzle_target_temperature_c: Optional[float]
    bed_target_temperature_c: Optional[float]
    nozzle_diameter_mm: Optional[float]
    nozzle_type: Optional[str]
    print_type: Optional[str]
    remaining_time_min: Optional[int]
    ams: dict[str, Any]
    ams_tray_id: Optional[int]
    ams_slot: Optional[int]
    filament_type: Optional[str]
    filament_color: Optional[str]
    filament_profile: Optional[str]
    filament_sub_brand: Optional[str]
    filament_name: Optional[str]
    filament: dict[str, Any]
    received_at: str
    source: str = "bambu"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_state(payload: bytes) -> Optional[PrinterState]:
    try:
        data = json.loads(payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        LOG.debug("Received non-JSON Bambu MQTT payload")
        return None

    print_block = data.get("print")
    if not isinstance(print_block, dict):
        return None

    raw_state = print_block.get("gcode_state")
    gcode_state = raw_state.strip().upper() if isinstance(raw_state, str) else None
    ams = print_block.get("ams") if isinstance(print_block.get("ams"), dict) else {}
    filament = extract_filament(print_block)

    state = PrinterState(
        connected=True,
        active=bool(gcode_state in ACTIVE_STATES),
        gcode_state=gcode_state,
        print_error=as_int(print_block.get("print_error")),
        progress_percent=as_int(print_block.get("mc_percent")),
        layer_num=as_int(print_block.get("layer_num")),
        total_layer_num=as_int(print_block.get("total_layer_num")),
        subtask_name=print_block.get("subtask_name") if isinstance(print_block.get("subtask_name"), str) else None,
        nozzle_temperature_c=as_float(print_block.get("nozzle_temper")),
        bed_temperature_c=as_float(print_block.get("bed_temper")),
        chamber_temperature_c=as_float(print_block.get("chamber_temper") or _nested(print_block, "info", "temp")),
        nozzle_target_temperature_c=as_float(print_block.get("nozzle_target_temper")),
        bed_target_temperature_c=as_float(print_block.get("bed_target_temper")),
        nozzle_diameter_mm=as_float(print_block.get("nozzle_diameter")),
        nozzle_type=print_block.get("nozzle_type") if isinstance(print_block.get("nozzle_type"), str) else None,
        print_type=print_block.get("print_type") if isinstance(print_block.get("print_type"), str) else None,
        remaining_time_min=as_int(print_block.get("mc_remaining_time") or print_block.get("remain_time")),
        ams=ams,
        ams_tray_id=filament.get("ams_tray_id"),
        ams_slot=filament.get("ams_slot"),
        filament_type=filament.get("type"),
        filament_color=filament.get("color"),
        filament_profile=filament.get("profile"),
        filament_sub_brand=filament.get("sub_brand"),
        filament_name=filament.get("name"),
        filament=filament,
        received_at=utc_now(),
    )
    return state


def _nested(obj: dict[str, Any], *keys: str) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def extract_filament(print_block: dict[str, Any]) -> dict[str, Any]:
    ams = print_block.get("ams")
    tray_id = None
    if isinstance(ams, dict):
        tray_id = _valid_tray_id(ams.get("tray_now"))
        if tray_id is None:
            tray_id = _valid_tray_id(ams.get("tray_tar"))
        if tray_id is None:
            tray_id = _valid_tray_id(ams.get("tray_pre"))

    if tray_id is None:
        mapping = print_block.get("mapping")
        if isinstance(mapping, list):
            for item in reversed(mapping):
                candidate = _valid_tray_id(item)
                if candidate is not None:
                    tray_id = candidate
                    break

    tray = _find_ams_tray(print_block, tray_id) if tray_id is not None else None
    if tray is None:
        tray = print_block.get("vt_tray") if isinstance(print_block.get("vt_tray"), dict) else None

    if not isinstance(tray, dict):
        return {}

    actual_tray_id = _valid_tray_id(tray.get("id"))
    if actual_tray_id is None:
        actual_tray_id = tray_id

    result: dict[str, Any] = {}
    if actual_tray_id is not None:
        result["ams_tray_id"] = actual_tray_id
        result["ams_slot"] = actual_tray_id + 1
    _copy_str(result, "type", tray.get("tray_type"))
    _copy_str(result, "color", tray.get("tray_color"))
    _copy_str(result, "profile", tray.get("tray_info_idx"))
    _copy_str(result, "sub_brand", tray.get("tray_sub_brands"))
    _copy_str(result, "name", tray.get("tray_id_name"))
    _copy_str(result, "diameter", tray.get("tray_diameter"))
    _copy_str(result, "tag_uid", tray.get("tag_uid"))
    return result


def _valid_tray_id(value: Any) -> Optional[int]:
    tray_id = as_int(value)
    if tray_id is None or tray_id < 0 or tray_id == 255 or tray_id == 65535:
        return None
    return tray_id


def _find_ams_tray(print_block: dict[str, Any], tray_id: int) -> Optional[dict[str, Any]]:
    ams = print_block.get("ams")
    if not isinstance(ams, dict):
        return None
    for ams_unit in ams.get("ams", []):
        if not isinstance(ams_unit, dict):
            continue
        for tray in ams_unit.get("tray", []):
            if isinstance(tray, dict) and _valid_tray_id(tray.get("id")) == tray_id:
                return tray
    return None


def _copy_str(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    text = str(value)
    if text:
        target[key] = text


def state_log_signature(state: PrinterState) -> tuple[Any, ...]:
    return (
        state.connected,
        state.active,
        state.gcode_state,
        state.print_error,
        state.progress_percent,
        state.layer_num,
        state.total_layer_num,
        state.subtask_name,
        state.ams_tray_id,
        state.filament_type,
        state.filament_color,
    )


def topic(name: str) -> str:
    return f"{LOCAL_MQTT_TOPIC_PREFIX}/{name}"


def publish(topic_name: str, payload: str, *, retain: bool) -> None:
    if local_client is None:
        raise RuntimeError("local MQTT client is not connected")
    info = local_client.publish(topic(topic_name), payload=payload, qos=0, retain=retain)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        LOG.warning("Local MQTT publish failed topic=%s rc=%s", topic(topic_name), info.rc)


def publish_available(value: str) -> None:
    publish("available", value, retain=True)


def publish_state(state: PrinterState) -> None:
    publish("state", json.dumps(asdict(state), sort_keys=True, separators=(",", ":")), retain=True)


def on_bambu_connect(client, userdata, flags, reason_code, properties=None):
    LOG.info("Connected to Bambu MQTT at %s:%s result=%s", PRINTER_HOST, PRINTER_MQTT_PORT, reason_code)
    client.subscribe(PRINTER_MQTT_TOPIC)
    LOG.info("Subscribed to Bambu MQTT topic: %s", PRINTER_MQTT_TOPIC)
    publish_available("online")


def on_bambu_disconnect(client, userdata, *args, **kwargs):
    LOG.warning("Disconnected from Bambu MQTT args=%s kwargs=%s", args, kwargs)
    try:
        publish_available("offline")
    except Exception:
        LOG.debug("Could not publish offline state", exc_info=True)


def on_bambu_message(client, userdata, msg):
    global last_bambu_seen, last_state, last_log_signature

    last_bambu_seen = time.time()
    state = normalize_state(msg.payload)

    if PUBLISH_RAW:
        try:
            publish("raw", msg.payload.decode("utf-8", errors="replace"), retain=False)
        except Exception:
            LOG.warning("Failed to publish raw payload", exc_info=True)

    if state is None:
        return

    signature = state_log_signature(state)
    if signature != last_log_signature:
        LOG.info(
            "Printer state: gcode_state=%s active=%s progress=%s layer=%s/%s file=%s error=%s filament=%s slot=%s",
            state.gcode_state,
            state.active,
            state.progress_percent,
            state.layer_num,
            state.total_layer_num,
            state.subtask_name,
            state.print_error,
            state.filament_type,
            state.ams_slot,
        )
        last_log_signature = signature
    else:
        LOG.debug("Duplicate normalized printer state suppressed")

    last_state = state
    publish_state(state)


def connect_local_mqtt() -> mqtt.Client:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=LOCAL_MQTT_CLIENT_ID,
    )
    if LOCAL_MQTT_USERNAME or LOCAL_MQTT_PASSWORD:
        client.username_pw_set(LOCAL_MQTT_USERNAME, LOCAL_MQTT_PASSWORD)
    LOG.info("Connecting to local MQTT broker at %s:%s", LOCAL_MQTT_HOST, LOCAL_MQTT_PORT)
    client.connect(LOCAL_MQTT_HOST, LOCAL_MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


def build_bambu_client() -> mqtt.Client:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{APP_NAME}-{int(time.time())}",
    )
    client.username_pw_set(PRINTER_MQTT_USERNAME, PRINTER_ACCESS_CODE)
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.on_connect = on_bambu_connect
    client.on_disconnect = on_bambu_disconnect
    client.on_message = on_bambu_message
    return client


def stop_service(signum, frame) -> None:
    global running
    LOG.info("Received signal %s; stopping service", signum)
    running = False


def log_startup_config() -> None:
    LOG.info("Starting %s version %s", APP_NAME, APP_VERSION)
    LOG.info("Printer host: %s", PRINTER_HOST)
    LOG.info("Printer serial: %s", PRINTER_SERIAL)
    LOG.info("Bambu MQTT topic: %s", PRINTER_MQTT_TOPIC)
    LOG.info("Local MQTT broker: %s:%s", LOCAL_MQTT_HOST, LOCAL_MQTT_PORT)
    LOG.info("Local topic prefix: %s", LOCAL_MQTT_TOPIC_PREFIX)
    LOG.info("Publish raw payloads: %s", PUBLISH_RAW)
    if bool(LOCAL_MQTT_USERNAME) != bool(LOCAL_MQTT_PASSWORD):
        raise RuntimeError("LOCAL_MQTT_USERNAME and LOCAL_MQTT_PASSWORD must either both be set or both be blank")


def run() -> None:
    global local_client, last_bambu_seen

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    signal.signal(signal.SIGTERM, stop_service)
    signal.signal(signal.SIGINT, stop_service)
    log_startup_config()

    local_client = connect_local_mqtt()
    publish_available("offline")

    try:
        while running:
            client = build_bambu_client()
            try:
                last_bambu_seen = None
                LOG.info("Connecting to Bambu MQTT at %s:%s", PRINTER_HOST, PRINTER_MQTT_PORT)
                client.connect(PRINTER_HOST, PRINTER_MQTT_PORT, keepalive=PRINTER_MQTT_KEEPALIVE)
                client.loop_start()

                last_heartbeat = time.time()
                while running:
                    now = time.time()
                    if last_bambu_seen and now - last_bambu_seen > WATCHDOG_SECONDS:
                        LOG.warning(
                            "Bambu MQTT watchdog triggered: no report for %s seconds; reconnecting",
                            int(now - last_bambu_seen),
                        )
                        break
                    if now - last_heartbeat > HEARTBEAT_SECONDS:
                        age = "never" if last_bambu_seen is None else int(now - last_bambu_seen)
                        LOG.info("Heartbeat: last_bambu_seen=%s state=%s", age, last_state)
                        last_heartbeat = now
                    time.sleep(1)

            except Exception:
                LOG.exception("Bambu MQTT connection failed; retrying in %s seconds", RECONNECT_DELAY)
            finally:
                try:
                    client.loop_stop()
                    client.disconnect()
                except Exception:
                    LOG.debug("Bambu MQTT disconnect cleanup failed", exc_info=True)
                try:
                    publish_available("offline")
                except Exception:
                    LOG.debug("Could not publish offline state", exc_info=True)

            if running:
                time.sleep(RECONNECT_DELAY)

    finally:
        if local_client is not None:
            try:
                publish_available("offline")
                local_client.loop_stop()
                local_client.disconnect()
            except Exception:
                LOG.debug("Local MQTT cleanup failed", exc_info=True)
        LOG.info("%s stopped", APP_NAME)


if __name__ == "__main__":
    run()
