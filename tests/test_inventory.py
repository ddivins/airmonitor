from __future__ import annotations

from pathlib import Path

import yaml

from airmonitor.inventory import hardware_inventory


def test_hardware_inventory_reports_explicit_device(tmp_path: Path) -> None:
    device = tmp_path / "ttyUSB0"
    device.touch()
    registry = tmp_path / "hardware.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "devices": {
                    "sgx-voc-01": {
                        "driver": "airmonitor.sensors.sgx.ps1_voc",
                        "transport": "usb-uart",
                        "device": str(device),
                    }
                },
            },
            sort_keys=False,
        )
    )

    items = hardware_inventory(registry)

    assert items == [
        {
            "hardware_id": "sgx-voc-01",
            "driver": "airmonitor.sensors.sgx.ps1_voc",
            "transport": "usb-uart",
            "device": str(device),
            "resolved_device": str(device),
            "connected": True,
        }
    ]


def test_hardware_inventory_reports_missing_device(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    registry = tmp_path / "hardware.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "devices": {
                    "sgx-voc-01": {
                        "driver": "airmonitor.sensors.sgx.ps1_voc",
                        "transport": "gpio-uart",
                        "device": str(missing),
                    }
                },
            },
            sort_keys=False,
        )
    )

    item = hardware_inventory(registry)[0]

    assert item["connected"] is False
    assert item["resolved_device"] is None
    assert "does not exist" in item["detail"]
