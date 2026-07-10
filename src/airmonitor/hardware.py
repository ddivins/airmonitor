"""AirMonitor serial hardware discovery and persistent device registry.

USB devices can be matched by EEPROM-provided manufacturer, product, and serial
strings.  Devices without writable EEPROMs, and true UART devices, can be added
with an explicit device path instead.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import glob
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable

import yaml

DEFAULT_REGISTRY = "/etc/airmonitor/hardware.yaml"
DEFAULT_HARDWARE_ID = "sgx-voc-01"


@dataclass(frozen=True)
class SerialDevice:
    device: str
    real_device: str
    vendor: str | None = None
    product: str | None = None
    serial: str | None = None
    vendor_id: str | None = None
    product_id: str | None = None
    by_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _udev_properties(device: str) -> dict[str, str]:
    try:
        proc = subprocess.run(
            ["udevadm", "info", "-q", "property", "-n", device],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0:
        return {}
    result: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            result[key] = value
    return result


def discover_serial_devices() -> list[SerialDevice]:
    """Return unique serial devices with their udev USB identity, when present."""

    candidates: list[str] = []
    candidates.extend(sorted(glob.glob("/dev/serial/by-id/*")))
    candidates.extend(sorted(glob.glob("/dev/ttyUSB*")))
    candidates.extend(sorted(glob.glob("/dev/ttyACM*")))
    if Path("/dev/serial0").exists():
        candidates.append("/dev/serial0")

    by_real: dict[str, SerialDevice] = {}
    for candidate in candidates:
        try:
            real = os.path.realpath(candidate)
        except OSError:
            continue
        if not Path(real).exists():
            continue
        props = _udev_properties(candidate)
        previous = by_real.get(real)
        by_id = candidate if candidate.startswith("/dev/serial/by-id/") else (previous.by_id if previous else None)
        by_real[real] = SerialDevice(
            device=by_id or candidate,
            real_device=real,
            vendor=props.get("ID_VENDOR"),
            product=props.get("ID_MODEL"),
            serial=props.get("ID_SERIAL_SHORT"),
            vendor_id=props.get("ID_VENDOR_ID"),
            product_id=props.get("ID_MODEL_ID"),
            by_id=by_id,
        )
    return sorted(by_real.values(), key=lambda item: item.device)


def load_registry(path: str | Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    registry_path = Path(path)
    if not registry_path.exists():
        return {"version": 1, "devices": {}}
    loaded = yaml.safe_load(registry_path.read_text()) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"hardware registry must contain a mapping: {registry_path}")
    loaded.setdefault("version", 1)
    loaded.setdefault("devices", {})
    if not isinstance(loaded["devices"], dict):
        raise ValueError(f"hardware registry devices must be a mapping: {registry_path}")
    return loaded


def save_registry(registry: dict[str, Any], path: str | Path = DEFAULT_REGISTRY) -> None:
    registry_path = Path(path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = registry_path.with_suffix(registry_path.suffix + ".tmp")
    temporary.write_text(yaml.safe_dump(registry, sort_keys=False))
    os.replace(temporary, registry_path)


def _normalized(value: object) -> str:
    return str(value or "").strip().casefold()


def _matches(device: SerialDevice, match: dict[str, Any]) -> bool:
    comparisons = {
        "vendor": device.vendor,
        "product": device.product,
        "serial": device.serial,
        "vendor_id": device.vendor_id,
        "product_id": device.product_id,
    }
    specified = False
    for key, actual in comparisons.items():
        expected = match.get(key)
        if expected in (None, ""):
            continue
        specified = True
        if _normalized(expected) != _normalized(actual):
            return False
    return specified


def resolve_device(
    hardware_id: str,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY,
    discovered: Iterable[SerialDevice] | None = None,
) -> str:
    """Resolve a configured hardware identity to a usable serial device path."""

    registry = load_registry(registry_path)
    try:
        entry = registry["devices"][hardware_id]
    except KeyError as exc:
        raise LookupError(f"hardware id is not configured: {hardware_id}") from exc
    if not isinstance(entry, dict):
        raise ValueError(f"hardware entry must be a mapping: {hardware_id}")

    explicit = entry.get("device")
    if explicit:
        if Path(str(explicit)).exists():
            return str(explicit)
        raise FileNotFoundError(f"configured device does not exist for {hardware_id}: {explicit}")

    match = entry.get("match") or {}
    if match:
        matches = [item for item in (list(discovered) if discovered is not None else discover_serial_devices()) if _matches(item, match)]
        if len(matches) == 1:
            return matches[0].device
        if len(matches) > 1:
            paths = ", ".join(item.device for item in matches)
            raise LookupError(f"multiple serial devices match {hardware_id}: {paths}")

    fallback = entry.get("fallback_device")
    if fallback and Path(str(fallback)).exists():
        return str(fallback)

    raise FileNotFoundError(f"no connected serial device matches hardware id: {hardware_id}")


def _device_entry(args: argparse.Namespace) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "driver": args.driver,
        "transport": args.transport,
    }
    if args.device:
        entry["device"] = args.device
    else:
        match = {
            key: value
            for key, value in {
                "vendor": args.usb_vendor,
                "product": args.usb_product,
                "serial": args.usb_serial,
                "vendor_id": args.usb_vendor_id,
                "product_id": args.usb_product_id,
            }.items()
            if value
        }
        if not match:
            raise SystemExit("add requires --device or at least one USB match option")
        entry["match"] = match
        if args.fallback_device:
            entry["fallback_device"] = args.fallback_device
    return entry


def command_discover(args: argparse.Namespace) -> int:
    devices = [item.as_dict() for item in discover_serial_devices()]
    print(json.dumps(devices, indent=2, sort_keys=True))
    return 0


def command_list(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    output = []
    for hardware_id, entry in registry["devices"].items():
        item = {"hardware_id": hardware_id, **entry}
        try:
            item["resolved_device"] = resolve_device(hardware_id, registry_path=args.registry)
            item["status"] = "connected"
        except Exception as exc:
            item["resolved_device"] = None
            item["status"] = str(exc)
        output.append(item)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def command_resolve(args: argparse.Namespace) -> int:
    print(resolve_device(args.hardware_id, registry_path=args.registry))
    return 0


def command_add(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    if args.hardware_id in registry["devices"] and not args.force:
        raise SystemExit(f"hardware id already exists: {args.hardware_id}; use --force to replace it")
    registry["devices"][args.hardware_id] = _device_entry(args)
    save_registry(registry, args.registry)
    print(json.dumps({"hardware_id": args.hardware_id, **registry["devices"][args.hardware_id]}, indent=2, sort_keys=True))
    return 0


def command_remove(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    if registry["devices"].pop(args.hardware_id, None) is None:
        raise SystemExit(f"hardware id is not configured: {args.hardware_id}")
    save_registry(registry, args.registry)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="airmonitor-hardware", description="Discover and register AirMonitor serial hardware")
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover", help="show connected serial devices and USB EEPROM identity")
    discover.set_defaults(func=command_discover)

    list_parser = subparsers.add_parser("list", help="show configured hardware and resolution status")
    list_parser.set_defaults(func=command_list)

    resolve = subparsers.add_parser("resolve", help="print the serial device path for a hardware id")
    resolve.add_argument("hardware_id")
    resolve.set_defaults(func=command_resolve)

    add = subparsers.add_parser("add", help="add a USB-matched or explicit-path serial device")
    add.add_argument("hardware_id")
    add.add_argument("--driver", default="airmonitor.sensors.sgx.ps1_voc")
    add.add_argument("--transport", default="usb-uart")
    add.add_argument("--device", help="manual device path, for true UARTs or devices without a useful EEPROM")
    add.add_argument("--usb-vendor")
    add.add_argument("--usb-product")
    add.add_argument("--usb-serial")
    add.add_argument("--usb-vendor-id")
    add.add_argument("--usb-product-id")
    add.add_argument("--fallback-device")
    add.add_argument("--force", action="store_true")
    add.set_defaults(func=command_add)

    remove = subparsers.add_parser("remove", help="remove a hardware registry entry")
    remove.add_argument("hardware_id")
    remove.set_defaults(func=command_remove)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except (FileNotFoundError, LookupError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
