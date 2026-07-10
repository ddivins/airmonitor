"""Helpers for deciding whether external state is fresh enough to trust."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(frozen=True)
class FreshnessResult:
    fresh: bool
    age_seconds: float | None
    reason: str


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assess_timestamp(
    value: str | None,
    *,
    max_age_seconds: float,
    now: datetime | None = None,
) -> FreshnessResult:
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return FreshnessResult(False, None, "missing or invalid timestamp")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = max(0.0, (current - timestamp).total_seconds())
    if age > max_age_seconds:
        return FreshnessResult(False, age, f"state is stale ({age:.1f}s > {max_age_seconds:.1f}s)")
    return FreshnessResult(True, age, "fresh")


def assess_state(
    state: Mapping[str, Any] | None,
    *,
    max_age_seconds: float,
    timestamp_keys: tuple[str, ...] = ("observed_at", "updated_at", "timestamp", "received_at"),
    now: datetime | None = None,
) -> FreshnessResult:
    if not state:
        return FreshnessResult(False, None, "state is missing")
    for key in timestamp_keys:
        if key in state:
            return assess_timestamp(str(state.get(key) or ""), max_age_seconds=max_age_seconds, now=now)
    return FreshnessResult(False, None, "state has no freshness timestamp")


def safe_automation_request(
    requested_state: str,
    freshness: FreshnessResult,
    *,
    stale_fallback: str = "unknown",
) -> tuple[str, str]:
    """Return a trusted automation request and an auditable reason.

    A stale printer state must not be silently interpreted as a confident idle/off
    signal.  Callers may choose a conservative fallback such as ``on`` for a
    safety-first policy, but ``unknown`` is the default.
    """

    if freshness.fresh:
        return requested_state, "automation state is fresh"
    return stale_fallback, f"automation state ignored: {freshness.reason}"
