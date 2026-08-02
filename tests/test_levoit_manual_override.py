from __future__ import annotations

import threading
import time
from unittest import mock

from airmonitor.filters.levoit import service
from airmonitor.filters.levoit.service import (
    DesiredState,
    apply_desired_state,
    external_override_mode,
    printer_state_is_fresh,
    sleep_until_next_poll,
    stop_service,
    telemetry_from_device,
    wake_now,
)


class FakePurifier:
    """Minimal pyvesync-shaped fake: turn_on/turn_off flip is_on, but only
    after `succeed_after` prior calls to the same method -- simulating
    VeSync's cloud occasionally accepting a command without the device
    actually toggling on the first attempt."""

    def __init__(self, succeed_after: int = 0):
        self.is_on = False
        self.update_calls = 0
        self.command_calls = 0
        self._succeed_after = succeed_after

    def update(self):
        self.update_calls += 1

    def turn_on(self):
        self.command_calls += 1
        if self.command_calls > self._succeed_after:
            self.is_on = True

    def turn_off(self):
        self.command_calls += 1
        if self.command_calls > self._succeed_after:
            self.is_on = False
        else:
            self.is_on = True


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


def test_apply_desired_state_does_nothing_when_already_matching() -> None:
    device = FakePurifier()
    device.is_on = True

    result = apply_desired_state(device, DesiredState(True, "already on"), current=True)

    assert result is True
    assert device.command_calls == 0


def test_apply_desired_state_succeeds_on_first_command() -> None:
    device = FakePurifier(succeed_after=0)

    with mock.patch("airmonitor.filters.levoit.service.time.sleep") as sleep:
        result = apply_desired_state(device, DesiredState(True, "print active"), current=False)

    assert result is True
    assert device.command_calls == 1
    sleep.assert_not_called()


def test_apply_desired_state_retries_once_when_cloud_command_silently_fails() -> None:
    """Regression test: VeSync's cloud API occasionally accepts a command
    without the device actually toggling. Previously this went unnoticed
    until the next scheduled poll (up to LEVOIT_POLL_INTERVAL_SECONDS later),
    which read to an operator as needing to "tell it twice." One immediate,
    verified retry closes that gap within the same automation cycle."""

    device = FakePurifier(succeed_after=1)

    with mock.patch("airmonitor.filters.levoit.service.time.sleep") as sleep:
        result = apply_desired_state(device, DesiredState(True, "print active"), current=False)

    assert result is True
    assert device.command_calls == 2
    sleep.assert_called_once_with(2)


def test_apply_desired_state_gives_up_after_one_retry() -> None:
    device = FakePurifier(succeed_after=99)

    with mock.patch("airmonitor.filters.levoit.service.time.sleep"):
        result = apply_desired_state(device, DesiredState(True, "print active"), current=False)

    assert result is False
    assert device.command_calls == 2


def test_apply_desired_state_verifies_turn_off_too() -> None:
    device = FakePurifier(succeed_after=1)
    device.is_on = True

    with mock.patch("airmonitor.filters.levoit.service.time.sleep"):
        result = apply_desired_state(device, DesiredState(False, "print finished"), current=True)

    assert result is False
    assert device.command_calls == 2


def test_sleep_until_next_poll_waits_out_the_interval_when_not_woken() -> None:
    service.wake_event.clear()
    started = time.monotonic()

    sleep_until_next_poll(1)

    assert time.monotonic() - started >= 0.9


def test_sleep_until_next_poll_wakes_immediately_on_signal() -> None:
    """Regression test: a manual on/auto/off change from the status page
    sends SIGUSR1 so the purifier responds right away instead of waiting out
    the full LEVOIT_POLL_INTERVAL_SECONDS -- the poll interval itself stays
    untouched (VeSync rate-limits more frequent polling), only a deliberate,
    one-off button click gets this early wake."""

    service.wake_event.clear()

    def fire() -> None:
        time.sleep(0.05)
        wake_now(0, None)

    threading.Thread(target=fire, daemon=True).start()
    started = time.monotonic()

    sleep_until_next_poll(5)

    assert time.monotonic() - started < 1.0


def test_stop_service_also_wakes_the_sleep_immediately() -> None:
    """SIGTERM/SIGINT must keep waking the loop immediately (systemd stop
    responsiveness), not just SIGUSR1 -- both share the same wake_event."""

    service.wake_event.clear()
    service.running = True
    try:

        def fire() -> None:
            time.sleep(0.05)
            stop_service(0, None)

        threading.Thread(target=fire, daemon=True).start()
        started = time.monotonic()

        sleep_until_next_poll(5)

        assert time.monotonic() - started < 1.0
        assert service.running is False
    finally:
        service.running = True
