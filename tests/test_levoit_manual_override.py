from __future__ import annotations

from airmonitor.filters.levoit.service import external_override_mode, telemetry_from_device


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
