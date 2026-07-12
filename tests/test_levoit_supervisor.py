from __future__ import annotations

import pytest

from airmonitor.filters.levoit.supervisor import DEFAULT_RETRY_DELAYS, parse_retry_delays


def test_default_retry_schedule() -> None:
    assert parse_retry_delays(None) == DEFAULT_RETRY_DELAYS


def test_custom_retry_schedule() -> None:
    assert parse_retry_delays("60, 120,300") == (60, 120, 300)


def test_retry_schedule_rejects_short_delays() -> None:
    with pytest.raises(RuntimeError, match="at least 60 seconds"):
        parse_retry_delays("10,60")


def test_retry_schedule_rejects_non_integer_values() -> None:
    with pytest.raises(RuntimeError, match="comma-separated integers"):
        parse_retry_delays("60,soon")
