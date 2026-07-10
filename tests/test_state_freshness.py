from __future__ import annotations

from datetime import datetime, timedelta, timezone

from airmonitor.state_freshness import assess_state, assess_timestamp, safe_automation_request


def test_fresh_timestamp_is_accepted() -> None:
    now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    result = assess_timestamp(
        (now - timedelta(seconds=20)).isoformat(),
        max_age_seconds=60,
        now=now,
    )
    assert result.fresh is True
    assert result.age_seconds == 20


def test_stale_state_cannot_be_treated_as_confident_off() -> None:
    now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    freshness = assess_state(
        {"updated_at": (now - timedelta(minutes=30)).isoformat(), "gcode_state": "IDLE"},
        max_age_seconds=120,
        now=now,
    )
    request, reason = safe_automation_request("off", freshness)
    assert freshness.fresh is False
    assert request == "unknown"
    assert "stale" in reason


def test_missing_state_is_unknown() -> None:
    freshness = assess_state(None, max_age_seconds=60)
    request, _ = safe_automation_request("off", freshness)
    assert request == "unknown"
