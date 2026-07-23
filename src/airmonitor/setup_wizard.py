"""Interactive `airmonitor setup` flow for printer, sensor, filter, and MQTT config.

Fills in the per-integration credentials that `tools/install.sh` leaves as
blank templates (it already prints "ACTION REQUIRED: configure ..." for
exactly these files) rather than duplicating install.sh's own system-level
prompts (mode, domain, cert email) — those still belong to `airmonitor
install`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import getpass
import os
from pathlib import Path
import sys
from typing import Callable

DEFAULT_CONFIG_DIR = "/etc/airmonitor"

# (env filename, host key, port key) for the local MQTT broker connection
# shared by the printer/filter services. Key names aren't uniform across
# files (sgx-voc.env uses an AIRMONITOR_-prefixed form), so this is an
# explicit mapping rather than an assumed-shared constant.
MQTT_KEY_NAMES: dict[str, tuple[str, str]] = {
    "printer-mqtt.env": ("LOCAL_MQTT_HOST", "LOCAL_MQTT_PORT"),
    "bento.env": ("LOCAL_MQTT_HOST", "LOCAL_MQTT_PORT"),
    "levoit.env": ("LOCAL_MQTT_HOST", "LOCAL_MQTT_PORT"),
    "sgx-voc.env": ("AIRMONITOR_LOCAL_MQTT_HOST", "AIRMONITOR_LOCAL_MQTT_PORT"),
}


@dataclass
class Prompter:
    """Wraps input/secret-input/output so the flow is testable without a real TTY."""

    ask: Callable[[str], str] = input
    ask_secret: Callable[[str], str] = getpass.getpass
    out: Callable[[str], None] = print

    def value(self, question: str, current: str | None, *, secret: bool = False) -> str:
        shown = "(unchanged)" if secret and current else (current or "")
        suffix = f" [{shown}]" if shown else ""
        asker = self.ask_secret if secret else self.ask
        entered = asker(f"{question}{suffix}: ").strip()
        return entered if entered else (current or "")


def read_env_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def get_env_value(lines: list[str], key: str) -> str | None:
    prefix = f"{key}="
    for line in lines:
        if line.strip().startswith(prefix):
            return line.strip()[len(prefix):]
    return None


def set_env_values(lines: list[str], values: dict[str, str]) -> tuple[list[str], set[str]]:
    """Return updated lines and the set of keys whose value actually changed."""

    remaining = dict(values)
    changed: set[str] = set()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        matched_key = next((key for key in remaining if stripped.startswith(f"{key}=")), None)
        if matched_key is None:
            result.append(line)
            continue
        new_line = f"{matched_key}={remaining.pop(matched_key)}"
        if new_line != line:
            changed.add(matched_key)
        result.append(new_line)
    for key, value in remaining.items():
        result.append(f"{key}={value}")
        changed.add(key)
    return result, changed


def write_env_file(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


@dataclass
class SetupSection:
    title: str
    env_filename: str
    fields: list[tuple[str, str, bool]] = field(default_factory=list)  # key, question, secret


SECTIONS: list[SetupSection] = [
    SetupSection(
        "Printer (Bambu local MQTT)",
        "printer-mqtt.env",
        [
            ("PRINTER_HOST", "Printer LAN IP or hostname", False),
            ("PRINTER_SERIAL", "Printer serial number", False),
            ("PRINTER_ACCESS_CODE", "Printer local access code", True),
        ],
    ),
    SetupSection(
        "Sensors (SGX VOC)",
        "sgx-voc.env",
        [("AIRMONITOR_SENSOR_LOCATION", "SGX VOC sensor location label", False)],
    ),
    SetupSection(
        "Sensors (SPS30)",
        "sps30.env",
        [("AIRMONITOR_SPS30_SENSOR_LOCATION", "SPS30 sensor location label", False)],
    ),
    SetupSection(
        "Bento Box filter (Kasa outlet)",
        "bento.env",
        [
            ("OUTLET_HOST", "Kasa outlet IP or hostname", False),
            ("KASA_USERNAME", "Kasa account email (blank for local-only outlets)", False),
            ("KASA_PASSWORD", "Kasa account password", True),
        ],
    ),
    SetupSection(
        "Room filter (Levoit/VeSync)",
        "levoit.env",
        [
            ("VESYNC_USERNAME", "VeSync account email", False),
            ("VESYNC_PASSWORD", "VeSync account password", True),
            ("LEVOIT_DEVICE_NAME", "Purifier device name (blank to auto-select if only one)", False),
        ],
    ),
]


def run_section(config_dir: Path, section: SetupSection, prompter: Prompter) -> set[str]:
    env_path = config_dir / section.env_filename
    prompter.out(f"\n-- {section.title} ({env_path}) --")
    lines = read_env_lines(env_path)
    values: dict[str, str] = {}
    for key, question, secret in section.fields:
        current = get_env_value(lines, key)
        values[key] = prompter.value(question, current, secret=secret)
    updated_lines, changed = set_env_values(lines, values)
    if changed:
        write_env_file(env_path, updated_lines)
        prompter.out(f"Updated: {', '.join(sorted(changed))}")
    else:
        prompter.out("No changes.")
    return changed


def run_mqtt_section(config_dir: Path, prompter: Prompter) -> set[str]:
    prompter.out("\n-- Local MQTT broker (shared by printer/filter/sensor services) --")
    reference_lines = read_env_lines(config_dir / "printer-mqtt.env")
    current_host = get_env_value(reference_lines, "LOCAL_MQTT_HOST") or "localhost"
    current_port = get_env_value(reference_lines, "LOCAL_MQTT_PORT") or "1883"
    host = prompter.value("Local MQTT broker host", current_host)
    port = prompter.value("Local MQTT broker port", current_port)

    changed_files: set[str] = set()
    for filename, (host_key, port_key) in MQTT_KEY_NAMES.items():
        path = config_dir / filename
        lines = read_env_lines(path)
        if get_env_value(lines, host_key) is None:
            continue  # this file doesn't define a local broker connection
        updated_lines, changed = set_env_values(lines, {host_key: host, port_key: port})
        if changed:
            write_env_file(path, updated_lines)
            changed_files.add(filename)
    prompter.out(f"Updated: {', '.join(sorted(changed_files))}" if changed_files else "No changes.")
    return changed_files


def report_grafana_status(config_dir: Path, prompter: Prompter) -> None:
    install_conf = config_dir / "install.conf"
    if not install_conf.exists():
        return
    lines = read_env_lines(install_conf)
    mode = get_env_value(lines, "MODE") or "core"
    domain = get_env_value(lines, "DOMAIN") or ""
    prompter.out(f"\n-- Grafana --\nCurrent mode: {mode}" + (f", domain: {domain}" if domain else ""))
    if mode != "full":
        prompter.out("Grafana isn't installed. Run `airmonitor install --full --no-dry-run` to add it.")


def run_setup(
    *,
    config_dir: str | Path = DEFAULT_CONFIG_DIR,
    prompter: Prompter | None = None,
    require_tty: bool = True,
    require_root: bool = True,
) -> int:
    if require_tty and not sys.stdin.isatty():
        print("airmonitor setup is interactive; run it directly from a terminal, not via a script.", file=sys.stderr)
        return 1

    config_dir = Path(config_dir)
    if require_root and os.geteuid() != 0:
        print(
            f"airmonitor setup writes to {config_dir}, which is root-owned; run it with sudo.",
            file=sys.stderr,
        )
        return 1

    prompter = prompter or Prompter()
    prompter.out("AirMonitor setup: press Enter to keep the current value shown in [brackets].")

    all_changed: set[str] = set()
    for section in SECTIONS:
        all_changed |= run_section(config_dir, section, prompter)
    all_changed |= run_mqtt_section(config_dir, prompter)
    report_grafana_status(config_dir, prompter)

    if all_changed:
        prompter.out("\nRestart affected services to apply changes, e.g.:\n  sudo systemctl restart airmonitor.target")
    else:
        prompter.out("\nNo configuration changed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airmonitor-setup",
        description="Interactively configure printer/sensor/filter/MQTT connection details",
    )
    parser.add_argument("--config-dir", default=DEFAULT_CONFIG_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_setup(config_dir=args.config_dir)


if __name__ == "__main__":
    raise SystemExit(main())
