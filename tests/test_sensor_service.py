from __future__ import annotations

from pathlib import Path

from airmonitor import sensor_service


def test_explicit_port_bypasses_registry(monkeypatch, tmp_path: Path) -> None:
    device = tmp_path / "ttyUSB-test"
    device.touch()
    monkeypatch.setenv("AIRMONITOR_PORT", str(device))
    monkeypatch.setenv("AIRMONITOR_HARDWARE_REGISTRY", str(tmp_path / "missing.yaml"))

    assert sensor_service.resolve_configured_port() == str(device)


def test_log_arguments_use_resolved_port(monkeypatch) -> None:
    monkeypatch.setenv("AIRMONITOR_SENSOR_ID", "sgx-voc-01")
    monkeypatch.setenv("AIRMONITOR_SENSOR_TRANSPORT", "usb-uart")
    monkeypatch.setenv("AIRMONITOR_SENSOR_SERIAL", "SGX-VOC-1000-01")

    argv = sensor_service.build_log_argv("/dev/airmonitor-sgx")

    assert argv[:3] == ["log", "--port", "/dev/airmonitor-sgx"]
    assert argv[argv.index("--sensor-id") + 1] == "sgx-voc-01"
    assert argv[argv.index("--sensor-transport") + 1] == "usb-uart"
    assert argv[argv.index("--sensor-serial") + 1] == "SGX-VOC-1000-01"


def test_retry_values_fall_back_when_invalid(monkeypatch) -> None:
    monkeypatch.setenv("AIRMONITOR_HARDWARE_RETRY_SECONDS", "not-a-number")

    assert sensor_service._float_env(
        "AIRMONITOR_HARDWARE_RETRY_SECONDS",
        sensor_service.DEFAULT_RETRY_SECONDS,
    ) == sensor_service.DEFAULT_RETRY_SECONDS
