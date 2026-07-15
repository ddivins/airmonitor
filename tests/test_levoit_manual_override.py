from __future__ import annotations

from airmonitor.filters.levoit.service import external_override_mode


def test_external_on_change_becomes_manual_on() -> None:
    assert external_override_mode(False, True) == "on"


def test_external_off_change_becomes_manual_off() -> None:
    assert external_override_mode(True, False) == "off"


def test_unchanged_and_unknown_states_do_not_create_override() -> None:
    assert external_override_mode(False, False) is None
    assert external_override_mode(True, True) is None
    assert external_override_mode(None, True) is None
    assert external_override_mode(False, None) is None
