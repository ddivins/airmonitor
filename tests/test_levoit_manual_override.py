from __future__ import annotations

from airmonitor.filters.levoit.service import (
    external_override_mode,
    printer_state_is_fresh,
    telemetry_from_device,
)


def test_external_on_change_becomes_manual_on() -> None:
    assert external_override_mode(False, True) == "on"


def test_external_off_change_releases_control_to_auto() -> None:
    assert external_override_mode(True, False) == "auto"


def test_unchanged_and_unknown_states_do_not_create_override() -> None:
    assert external_override_mode(False, False) is None
    assert external_override_mode(True, True) is None
    assert external_override_mode(None, True) is None
    assert external_override_mode(False, None) is None


def test_normalizes_400s_telemetry_fields() -> None:
    device = type("Purifier", (), {
        "device_name": "400S",
        "mode": "manual",
        "speed": 2,
        "details": {"air_quality_value": 4, "air_quality": 1, "filter_life": 93},
    })()

    telemetry = telemetry_from_device(device, True)

    assert telemetry["power_state"] == "on"
    assert telemetry["fan_level"] == 2
    assert telemetry["pm2_5"] == 4
    assert telemetry["filter_life_percent"] == 93


def test_printer_state_never_received_is_not_fresh() -> None:
    assert printer_state_is_fresh(None, now=1000.0, stale_after_seconds=300) is False


def test_printer_state_within_window_is_fresh() -> None:
    assert printer_state_is_fresh(1000.0, now=1200.0, stale_after_seconds=300) is True


def test_printer_state_past_window_is_not_fresh() -> None:
    assert printer_state_is_fresh(1000.0, now=1301.0, stale_after_seconds=300) is False
