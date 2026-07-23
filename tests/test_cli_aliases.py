from __future__ import annotations

from pathlib import Path
from unittest import mock

from airmonitor.cli import main


def test_inventory_alias_forwards_passthrough_args() -> None:
    with mock.patch("airmonitor.inventory.main") as inventory_main:
        inventory_main.return_value = 0
        exit_code = main(["inventory", "--no-systemd", "--database", "/tmp/x.sqlite3"])
    assert exit_code == 0
    inventory_main.assert_called_once_with(["--no-systemd", "--database", "/tmp/x.sqlite3"])


def test_hardware_alias_forwards_passthrough_args_even_with_leading_flag() -> None:
    """A flag before the hardware subcommand word (`--registry X list`) is
    exactly the shape that breaks a naive argparse REMAINDER positional."""

    with mock.patch("airmonitor.hardware.main") as hardware_main:
        hardware_main.return_value = 0
        exit_code = main(["hardware", "--registry", "/tmp/hw.yaml", "list"])
    assert exit_code == 0
    hardware_main.assert_called_once_with(["--registry", "/tmp/hw.yaml", "list"])


def test_hardware_alias_runs_the_real_module_end_to_end(tmp_path: Path) -> None:
    registry = tmp_path / "hardware.yaml"
    exit_code = main(["hardware", "--registry", str(registry), "list"])
    assert exit_code == 0
