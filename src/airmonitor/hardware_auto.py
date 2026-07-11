"""One-command AirMonitor serial hardware enrollment.

This command is intentionally conservative: it requires exactly one matching
serial device, optionally probes it as an SGX sensor, records its USB identity
(or explicit path), updates the service environment, restarts the sensor
service, and runs the appliance doctor.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable

from airmonitor.hardware import (
    DEFAULT_HARDWARE_ID,
    DEFAULT_REGISTRY,
    SerialDevice,
    discover_serial_devices,
    load_registry,
    save_registry,
)

DEFAULT_ENV_FILE = "/etc/airmonitor/airmonitor.env"
DEFAULT_SERVICE = "airmonitor.service"
DEFAULT_DRIVER = "airmonitor.sensors.sgx.ps1_voc"


def _matching_devices(
    devices: Iterable[SerialDevice],
    *,
    vendor: str | None,
    product: str | None,
    serial: str | None,
) -> list[SerialDevice]:
    def same(expected: str | None, actual: str | None) -> bool:
        return expected is None or expected.casefold() == (actual or "").casefold()

    return [
        item
        for item in devices
        if same(vendor, item.vendor)
        and same(product, item.product)
        and same(serial, item.serial)
    ]


def choose_device(
    devices: Iterable[SerialDevice],
    *,
    vendor: str | None,
    product: str | None,
    serial: str | None,
    device: str | None,
) -> SerialDevice:
    items = list(devices)
    if device:
        requested = os.path.realpath(device)
        matches = [item for item in items if item.device == device or item.real_device == requested]
    else:
        matches = _matching_devices(items, vendor=vendor, product=product, serial=serial)

    if not matches:
        raise LookupError("no connected serial device matches the requested identity")
    if len(matches) > 1:
        paths = ", ".join(item.device for item in matches)
        raise LookupError(f"multiple serial devices match; specify --device or --usb-serial: {paths}")
    return matches[0]


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True)


def _service_active(service: str) -> bool:
    proc = _run(["systemctl", "is-active", "--quiet", service], check=False)
    return proc.returncode == 0


def probe_device(device: str, *, timeout: float = 2.0) -> None:
    executable = str(Path(sys.executable).with_name("airmonitor"))
    if not Path(executable).exists():
        executable = "airmonitor"
    proc = _run([executable, "probe", "--port", device, "--timeout", str(timeout)], check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"SGX probe failed on {device}: {detail}")


def registry_entry(device: SerialDevice, *, driver: str, transport: str) -> dict[str, object]:
    entry: dict[str, object] = {"driver": driver, "transport": transport}
    if device.serial and device.vendor and device.product:
        entry["match"] = {
            "vendor": device.vendor,
            "product": device.product,
            "serial": device.serial,
        }
        entry["fallback_device"] = device.device
    else:
        entry["device"] = device.device
    return entry


def update_env_file(
    path: str | Path,
    *,
    hardware_id: str,
    registry: str,
    transport: str,
    sensor_serial: str | None,
) -> None:
    env_path = Path(path)
    current = env_path.read_text().splitlines() if env_path.exists() else []
    replacements = {
        "AIRMONITOR_PORT": "auto",
        "AIRMONITOR_HARDWARE_ID": hardware_id,
        "AIRMONITOR_HARDWARE_REGISTRY": registry,
        "AIRMONITOR_SENSOR_TRANSPORT": transport,
        "AIRMONITOR_SENSOR_SERIAL": sensor_serial or "",
    }
    found: set[str] = set()
    updated: list[str] = []
    for line in current:
        key, sep, _ = line.partition("=")
        if sep and key in replacements:
            updated.append(f"{key}={replacements[key]}")
            found.add(key)
        else:
            updated.append(line)
    if updated and updated[-1] != "":
        updated.append("")
    for key, value in replacements.items():
        if key not in found:
            updated.append(f"{key}={value}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = env_path.with_suffix(env_path.suffix + ".tmp")
    temporary.write_text("\n".join(updated).rstrip() + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, env_path)


def enroll(args: argparse.Namespace) -> int:
    device = choose_device(
        discover_serial_devices(),
        vendor=args.usb_vendor,
        product=args.usb_product,
        serial=args.usb_serial,
        device=args.device,
    )

    service_was_active = False
    service_stopped_for_probe = False

    try:
        if args.probe and args.manage_service:
            service_was_active = _service_active(args.service)
            if service_was_active:
                _run(["systemctl", "stop", args.service])
                service_stopped_for_probe = True

        if args.probe:
            probe_device(device.device, timeout=args.probe_timeout)

        registry = load_registry(args.registry)
        if args.hardware_id in registry["devices"] and not args.force:
            raise RuntimeError(f"hardware id already exists: {args.hardware_id}; use --force to replace it")
        entry = registry_entry(device, driver=args.driver, transport=args.transport)
        registry["devices"][args.hardware_id] = entry
        save_registry(registry, args.registry)

        if args.configure_service:
            update_env_file(
                args.env_file,
                hardware_id=args.hardware_id,
                registry=args.registry,
                transport=args.transport,
                sensor_serial=device.serial,
            )

        if args.restart_service:
            _run(["systemctl", "restart", args.service])
            service_stopped_for_probe = False

        doctor_result: int | None = None
        if args.doctor:
            doctor = str(Path(sys.executable).with_name("airmonitor-doctor"))
            if not Path(doctor).exists():
                doctor = "airmonitor-doctor"
            proc = subprocess.run([doctor], check=False)
            doctor_result = proc.returncode

        print(json.dumps({
            "hardware_id": args.hardware_id,
            "device": device.as_dict(),
            "registry_entry": entry,
            "env_file": args.env_file if args.configure_service else None,
            "service_restarted": args.restart_service,
            "doctor_exit_code": doctor_result,
        }, indent=2, sort_keys=True))
        return 0 if doctor_result in (None, 0) else doctor_result
    finally:
        if service_stopped_for_probe and service_was_active:
            _run(["systemctl", "start", args.service], check=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airmonitor-hardware-auto",
        description="Discover, probe, register, configure, and activate one AirMonitor serial sensor",
    )
    parser.add_argument("hardware_id", nargs="?", default=DEFAULT_HARDWARE_ID)
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    parser.add_argument("--driver", default=DEFAULT_DRIVER)
    parser.add_argument("--transport", default="usb-uart")
    parser.add_argument("--device", help="explicit device path for a true UART or generic USB adapter")
    parser.add_argument("--usb-vendor", default="DSD")
    parser.add_argument("--usb-product", default="AirMonitor")
    parser.add_argument("--usb-serial", help="specific USB EEPROM serial; strongly recommended when several adapters exist")
    parser.add_argument("--probe", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--probe-timeout", type=float, default=2.0)
    parser.add_argument("--manage-service", action=argparse.BooleanOptionalAction, default=True, help="stop the sensor service before probing so the serial port is not locked")
    parser.add_argument("--configure-service", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--restart-service", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--doctor", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return enroll(args)
    except (LookupError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
