from pathlib import Path

import pytest
import yaml

from airmonitor.hardware import SerialDevice, load_registry, resolve_device, save_registry


def test_resolve_usb_eeprom_identity(tmp_path: Path):
    registry_path = tmp_path / "hardware.yaml"
    save_registry(
        {
            "version": 1,
            "devices": {
                "sgx-voc-01": {
                    "driver": "airmonitor.sensors.sgx.ps1_voc",
                    "transport": "usb-uart",
                    "match": {
                        "vendor": "DSD",
                        "product": "AirMonitor",
                        "serial": "SGX-VOC-1000-01",
                    },
                }
            },
        },
        registry_path,
    )
    discovered = [
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
    assert resolve_device("sgx-voc-01", registry_path=registry_path, discovered=discovered).endswith("port0")


def test_resolve_manual_true_uart(tmp_path: Path):
    device = tmp_path / "serial0"
    device.touch()
    registry_path = tmp_path / "hardware.yaml"
    save_registry(
        {
            "version": 1,
            "devices": {
                "sgx-voc-gpio": {
                    "driver": "airmonitor.sensors.sgx.ps1_voc",
                    "transport": "gpio-uart",
                    "device": str(device),
                }
            },
        },
        registry_path,
    )
    assert resolve_device("sgx-voc-gpio", registry_path=registry_path) == str(device)


def test_explicit_device_missing_is_clear_error(tmp_path: Path):
    registry_path = tmp_path / "hardware.yaml"
    save_registry(
        {"version": 1, "devices": {"missing": {"device": str(tmp_path / "none")}}},
        registry_path,
    )
    with pytest.raises(FileNotFoundError, match="configured device does not exist"):
        resolve_device("missing", registry_path=registry_path)


def test_registry_round_trip(tmp_path: Path):
    path = tmp_path / "hardware.yaml"
    original = {"version": 1, "devices": {"uart": {"device": "/dev/serial0"}}}
    save_registry(original, path)
    assert load_registry(path) == original
