"""Outbound alert delivery: a generic JSON webhook and/or ntfy push.

Uses stdlib urllib rather than adding a requests dependency, matching the
rest of the appliance's preference for stdlib HTTP (see status_web.py).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from urllib import error, request

LOG = logging.getLogger("airmonitor.alerts.notifier")

_NTFY_PRIORITY = {"critical": "urgent", "warning": "high", "resolved": "default"}
_NTFY_TAGS = {"critical": "rotating_light", "warning": "warning", "resolved": "white_check_mark"}


@dataclass(frozen=True)
class NotifierConfig:
    webhook_url: str | None = None
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str | None = None
    timeout: float = 5.0


@dataclass(frozen=True)
class AlertMessage:
    alert_key: str
    level: str  # "warning" | "critical" | "resolved"
    title: str
    body: str
    value: float | None = None
    threshold: float | None = None


def send(config: NotifierConfig, message: AlertMessage) -> None:
    if config.webhook_url:
        _send_webhook(config, message)
    if config.ntfy_topic:
        _send_ntfy(config, message)


def _send_webhook(config: NotifierConfig, message: AlertMessage) -> None:
    payload = json.dumps(
        {
            "alert_key": message.alert_key,
            "level": message.level,
            "title": message.title,
            "message": message.body,
            "value": message.value,
            "threshold": message.threshold,
        }
    ).encode("utf-8")
    req = request.Request(
        config.webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=config.timeout):
            pass
    except (error.URLError, OSError) as exc:
        LOG.warning("webhook delivery failed for %s: %s", message.alert_key, exc)


def _send_ntfy(config: NotifierConfig, message: AlertMessage) -> None:
    url = f"{config.ntfy_server.rstrip('/')}/{config.ntfy_topic}"
    req = request.Request(
        url,
        data=message.body.encode("utf-8"),
        headers={
            "Title": message.title,
            "Priority": _NTFY_PRIORITY.get(message.level, "default"),
            "Tags": _NTFY_TAGS.get(message.level, "information_source"),
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=config.timeout):
            pass
    except (error.URLError, OSError) as exc:
        LOG.warning("ntfy delivery failed for %s: %s", message.alert_key, exc)
