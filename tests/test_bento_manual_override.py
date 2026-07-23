from __future__ import annotations

import os

os.environ.setdefault("OUTLET_HOST", "192.0.2.20")

from airmonitor.filters.bento.service import external_override_mode, printer_state_is_stale


def test_external_on_change_becomes_manual_on() -> None:
    assert external_override_mode(False, True) == "on"


def test_external_off_change_releases_control_to_auto() -> None:
    assert external_override_mode(True, False) == "auto"


def test_unchanged_and_unknown_states_do_not_create_override() -> None:
    assert external_override_mode(False, False) is None
    assert external_override_mode(True, True) is None
    assert external_override_mode(None, True) is None
    assert external_override_mode(False, None) is None


def test_printer_state_unknown_age_is_not_stale() -> None:
    assert printer_state_is_stale(None, threshold_seconds=300) is False


def test_printer_state_within_threshold_is_not_stale() -> None:
    assert printer_state_is_stale(299.0, threshold_seconds=300) is False


def test_printer_state_past_threshold_is_stale() -> None:
    assert printer_state_is_stale(301.0, threshold_seconds=300) is True
