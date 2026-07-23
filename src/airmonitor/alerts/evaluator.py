"""Pure alert-evaluation logic: given current readings/state, decide alert transitions.

Kept free of database and network I/O so the threshold/staleness/mismatch
rules can be tested directly without a real sensor, database, or webhook.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from airmonitor.alerts.thresholds import MetricThreshold
from airmonitor.state_freshness import assess_timestamp
from airmonitor.status import SENSOR_OFFLINE_SECONDS, SENSOR_STALE_SECONDS

FILTER_MISMATCH_ESCALATION_SECONDS = 600.0


@dataclass(frozen=True)
class AlertCandidate:
    key: str
    level: str  # "warning" | "critical"
    title: str
    body: str
    value: float | None = None
    threshold: float | None = None


def evaluate_metric(
    key: str,
    value: float | None,
    threshold: MetricThreshold,
    *,
    label: str,
) -> AlertCandidate | None:
    if value is None:
        return None
    if threshold.critical is not None and value >= threshold.critical:
        return AlertCandidate(
            key, "critical", f"{label} critical",
            f"{label} at {value:g} (>= {threshold.critical:g})", value, threshold.critical,
        )
    if threshold.warning is not None and value >= threshold.warning:
        return AlertCandidate(
            key, "warning", f"{label} warning",
            f"{label} at {value:g} (>= {threshold.warning:g})", value, threshold.warning,
        )
    return None


def evaluate_sensor_freshness(
    key: str,
    label: str,
    sampled_at: str | None,
    *,
    now: datetime | None = None,
) -> AlertCandidate | None:
    if sampled_at is None:
        return AlertCandidate(key, "critical", f"{label} offline", f"{label} has no recorded samples")
    result = assess_timestamp(sampled_at, max_age_seconds=SENSOR_STALE_SECONDS, now=now)
    if result.fresh:
        return None
    offline = result.age_seconds is not None and result.age_seconds > SENSOR_OFFLINE_SECONDS
    level = "critical" if offline else "warning"
    title = f"{label} {'offline' if offline else 'stale'}"
    threshold_seconds = SENSOR_OFFLINE_SECONDS if offline else SENSOR_STALE_SECONDS
    return AlertCandidate(key, level, title, result.reason, result.age_seconds, float(threshold_seconds))


def evaluate_filter_mismatch(
    key: str,
    label: str,
    actual_state: str | None,
    effective_state: str | None,
    reason: str | None,
    *,
    open_since: str | None = None,
    now: datetime | None = None,
    escalate_after_seconds: float = FILTER_MISMATCH_ESCALATION_SECONDS,
) -> AlertCandidate | None:
    """Flag a filter whose actual state disagrees with its commanded state.

    ``open_since`` is the ``fired_at`` of the currently-open alert for this
    key, if any (the caller reads it from ``alert_events`` before this
    mismatch is re-evaluated). A mismatch starts as a warning -- commands can
    take a moment to take effect -- and escalates to critical once it has
    stayed open past ``escalate_after_seconds``, the same warning-then-critical
    shape sensor-freshness alerts already use for a condition that gets worse
    the longer it's ignored.
    """

    if not actual_state or not effective_state:
        return None
    if actual_state == "unknown" or effective_state == "unknown":
        return None
    if actual_state == effective_state:
        return None
    detail = f"{label} commanded {effective_state} but reports {actual_state}"
    if reason:
        detail = f"{detail} ({reason})"

    level = "warning"
    if open_since is not None:
        elapsed = assess_timestamp(open_since, max_age_seconds=escalate_after_seconds, now=now)
        if not elapsed.fresh:
            level = "critical"
            detail = f"{detail}; unresolved for over {escalate_after_seconds:g}s"

    return AlertCandidate(key, level, f"{label} not responding", detail)


def diff_alerts(
    candidates: Mapping[str, AlertCandidate],
    open_levels: Mapping[str, str],
) -> tuple[list[AlertCandidate], list[str]]:
    """Return (alerts to open or escalate, alert keys to resolve).

    An alert is only (re)opened when it's new or its level changed, so a
    condition that keeps triggering doesn't re-notify on every poll.
    """

    to_open = [candidate for key, candidate in candidates.items() if open_levels.get(key) != candidate.level]
    to_resolve = [key for key in open_levels if key not in candidates]
    return to_open, to_resolve
