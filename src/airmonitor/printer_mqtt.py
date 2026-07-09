"""Local MQTT consumer for normalized printer state."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt


LOG = logging.getLogger(__name__)


class PrinterStateCache:
    """Subscribe to normalized printer state and keep the latest payload."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        state_topic: str,
        availability_topic: str,
        client_id: str,
        username: str | None = None,
        password: str | None = None,
        keepalive: int = 60,
    ) -> None:
        self.host = host
        self.port = port
        self.state_topic = state_topic
        self.availability_topic = availability_topic
        self.keepalive = keepalive
        self._lock = threading.Lock()
        self._state: dict[str, Any] | None = None
        self._availability: str | None = None
        self._last_seen: float | None = None
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if username or password:
            self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    def start(self) -> None:
        LOG.info("Connecting to local MQTT broker at %s:%s", self.host, self.port)
        self._client.connect(self.host, self.port, keepalive=self.keepalive)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def latest_state(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._state) if self._state else None

    def availability(self) -> str | None:
        with self._lock:
            return self._availability

    def last_seen_age(self) -> float | None:
        with self._lock:
            if self._last_seen is None:
                return None
            return time.time() - self._last_seen

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        LOG.info("Connected to local MQTT result=%s", reason_code)
        client.subscribe(self.state_topic)
        client.subscribe(self.availability_topic)
        LOG.info("Subscribed to local MQTT topics: %s, %s", self.state_topic, self.availability_topic)

    def _on_disconnect(self, client, userdata, *args, **kwargs):
        LOG.warning("Disconnected from local MQTT args=%s kwargs=%s", args, kwargs)

    def _on_message(self, client, userdata, msg):
        if msg.topic == self.availability_topic:
            value = msg.payload.decode("utf-8", errors="replace").strip().lower()
            with self._lock:
                self._availability = value
            LOG.info("Printer availability: %s", value)
            return

        if msg.topic != self.state_topic:
            LOG.debug("Ignoring unexpected MQTT topic: %s", msg.topic)
            return

        try:
            state = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            LOG.debug("Ignoring non-JSON printer state payload")
            return

        if not isinstance(state, dict):
            LOG.debug("Ignoring non-object printer state payload")
            return

        state = add_best_effort_filament_fields(state)
        with self._lock:
            self._state = state
            self._last_seen = time.time()


def add_best_effort_filament_fields(state: dict[str, Any]) -> dict[str, Any]:
    """Add convenient filament fields from a Bambu AMS payload when possible.

    Bambu AMS payloads vary across model and firmware versions. AirMonitor stores
    the full printer JSON regardless, but these fields make common queries easy
    when the expected values are present.
    """
    if state.get("filament_type") or state.get("filament_color"):
        return state

    ams = state.get("ams")
    if not isinstance(ams, dict):
        return state

    tray_candidates: list[dict[str, Any]] = []
    for key in ("tray", "tray_info", "ams", "ams_info"):
        value = ams.get(key)
        if isinstance(value, list):
            tray_candidates.extend(item for item in value if isinstance(item, dict))

    for tray in tray_candidates:
        filament_type = tray.get("tray_type") or tray.get("filament_type") or tray.get("type")
        filament_color = tray.get("tray_color") or tray.get("filament_color") or tray.get("color")
        if filament_type or filament_color:
            updated = dict(state)
            if filament_type:
                updated["filament_type"] = str(filament_type)
            if filament_color:
                updated["filament_color"] = str(filament_color)
            return updated

    return state
