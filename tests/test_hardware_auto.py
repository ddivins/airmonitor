from __future__ import annotations

from pathlib import Path

from airmonitor.hardware import SerialDevice
from airmonitor.hardware_auto import choose_device, registry_entry, update_env_file


def test_choose_device_by_usb_identity() -> None:
    devices = [
        SerialDevice(
            device="/dev/serial/by-id/usb-DSD_AirMonitor_SGX-VOC-1000-01-if00-port0",
            real_device="/dev/ttyUSB0",
            vendor="DSD",
            product="AirMonitor",
            serial="SGX-VOC-1000-01",
            vendor_id="0403",
            product_id="6001",
        )
    ]
    selected = choose_device(
        devices,
        vendor="DSD",
        product="AirMonitor",
        serial="SGX-VOC-1000-01",
        device=None,
    )
    assert selected.serial == "SGX-VOC-1000-01"


def test_registry_entry_prefers_usb_identity() -> None:
    device = SerialDevice(
        device="/dev/serial/by-id/usb-DSD_AirMonitor_SGX-VOC-1000-01-if00-port0",
        real_device="/dev/ttyUSB0",
        vendor="DSD",
        product="AirMonitor",
        serial="SGX-VOC-1000-01",
    )
    entry = registry_entry(device, driver="driver", transport="usb-uart")
    assert entry["match"] == {
        "vendor": "DSD",
        "product": "AirMonitor",
        "serial": "SGX-VOC-1000-01",
    }
    assert entry["fallback_device"] == device.device


def test_registry_entry_uses_explicit_path_without_identity() -> None:
    device = SerialDevice(device="/dev/serial0", real_device="/dev/ttyAMA0")
    entry = registry_entry(device, driver="driver", transport="gpio-uart")
    assert entry["device"] == "/dev/serial0"
    assert "match" not in entry


def test_update_env_file_replaces_and_adds_values(tmp_path: Path) -> None:
    env_file = tmp_path / "sgx-voc.env"
    env_file.write_text("AIRMONITOR_PORT=/dev/serial0\nAIRMONITOR_SENSOR_TRANSPORT=gpio-uart\nOTHER=value\n")
    update_env_file(
        env_file,
        hardware_id="sgx-voc-01",
        registry="/etc/airmonitor/hardware.yaml",
        transport="usb-uart",
        sensor_serial="SGX-VOC-1000-01",
    )
    text = env_file.read_text()
    assert "AIRMONITOR_PORT=auto" in text
    assert "AIRMONITOR_HARDWARE_ID=sgx-voc-01" in text
    assert "AIRMONITOR_HARDWARE_REGISTRY=/etc/airmonitor/hardware.yaml" in text
    assert "AIRMONITOR_SENSOR_TRANSPORT=usb-uart" in text
    assert "AIRMONITOR_SENSOR_SERIAL=SGX-VOC-1000-01" in text
    assert "OTHER=value" in text
