"""Command-line interface for Air Monitor."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any

from airmonitor.backup import (
    DEFAULT_BACKUP_DIR,
    DEFAULT_RETENTION,
    create_backup,
    restore_backup,
)
from airmonitor.database import (
    connect,
    end_sensor_session,
    init_db,
    insert_sgx_voc_sample,
    start_sensor_session,
    upsert_sensor,
)
from airmonitor.database.repositories import FilterControlRepository
from airmonitor.filters.control import FilterState, resolve_filter_state
from airmonitor.filament_policy import FilamentPolicy
from airmonitor.health import _package_version
from airmonitor.print_tracker import PrintTracker
from airmonitor.printer_mqtt import PrinterStateCache
from airmonitor.sensors.sgx_ps1_voc_1000 import (
    BAUD_RATE,
    COMBINED_RESPONSE_LENGTH,
    ProtocolError,
    combined_read_candidates,
    parse_combined_response,
)


SENSOR_MANUFACTURER = "SGX Sensortech"
SENSOR_PRODUCT = "PS1-VOC-1000-MOD"
SENSOR_MODEL = "SGX PS1-VOC-1000-MOD"
LOG = logging.getLogger("airmonitor")
FILTER_IDS = ("bento", "levoit")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_frame(serial_port) -> bytes:
    """Synchronize on 0xFF and read one combined response."""

    while True:
        first = serial_port.read(1)
        if not first:
            return b""
        if first == b"\xFF":
            return first + serial_port.read(COMBINED_RESPONSE_LENGTH - 1)


def read_sgx_once(serial_port, decimal_places: int) -> tuple[str, Any, bytes]:
    errors: list[str] = []
    for protocol, request in combined_read_candidates():
        serial_port.reset_input_buffer()
        serial_port.write(request)
        serial_port.flush()
        response = _read_frame(serial_port)
        if not response:
            errors.append(f"{protocol}: no response")
            continue

        try:
            measurement = parse_combined_response(response, decimal_places=decimal_places)
        except ProtocolError as exc:
            errors.append(f"{protocol}: {exc}; raw={response.hex(' ')}")
            continue

        return protocol, measurement, response

    raise RuntimeError("; ".join(errors) if errors else "no sensor response")


def probe(port: str, timeout: float, decimal_places: int) -> int:
    try:
        import serial
    except ImportError:
        print("pyserial is required; install the project with `pip install -e .`", file=sys.stderr)
        return 2

    try:
        with serial.Serial(
            port=port,
            baudrate=BAUD_RATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=timeout,
            exclusive=True,
        ) as serial_port:
            protocol, measurement, response = read_sgx_once(serial_port, decimal_places)
    except RuntimeError as exc:
        print("Unable to read the sensor:", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1

    output = asdict(measurement)
    output.update(protocol=protocol, frame_hex=response.hex(" "))
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def raw_serial(args: argparse.Namespace) -> int:
    """Print raw SGX UART request/response frames as JSON lines."""
    try:
        import serial
    except ImportError:
        print("pyserial is required; install the project with `pip install -e .`", file=sys.stderr)
        return 2

    candidates = dict(combined_read_candidates())
    requests = list(combined_read_candidates()) if args.protocol == "all" else [(args.protocol, candidates[args.protocol])]

    try:
        with serial.Serial(
            port=args.port,
            baudrate=BAUD_RATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=args.timeout,
            write_timeout=args.timeout,
            exclusive=True,
        ) as serial_port:
            count = 0
            while args.count == 0 or count < args.count:
                for protocol, request in requests:
                    serial_port.reset_input_buffer()
                    serial_port.write(request)
                    serial_port.flush()
                    response = _read_frame(serial_port)

                    event: dict[str, Any] = {
                        "timestamp": utc_now(),
                        "port": args.port,
                        "baud": BAUD_RATE,
                        "protocol": protocol,
                        "tx_hex": request.hex(" "),
                        "rx_hex": response.hex(" ") if response else None,
                        "rx_len": len(response),
                    }

                    if response:
                        try:
                            measurement = parse_combined_response(response, decimal_places=args.decimal_places)
                            event["parsed"] = asdict(measurement)
                            event["parse_ok"] = True
                        except Exception as exc:
                            event["parse_ok"] = False
                            event["parse_error"] = str(exc)
                    else:
                        event["parse_ok"] = False
                        event["parse_error"] = "no response"

                    print(json.dumps(event, sort_keys=True), flush=True)
                    count += 1
                    if args.count and count >= args.count:
                        break

                if args.count == 0 or count < args.count:
                    time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0

    return 0


def show_policy(args: argparse.Namespace) -> int:
    policy = FilamentPolicy.load(args.filament_policy)
    for material in args.materials:
        decision = policy.classify(material)
        print(json.dumps(asdict(decision), sort_keys=True))
    return 0


def filter_control(args: argparse.Namespace) -> int:
    filter_id, filter_command = parse_filter_args(args.filter_args)
    conn = connect(args.database)
    init_db(conn)
    repo = FilterControlRepository(conn)
    filter_ids = FILTER_IDS if filter_id == "all" else (filter_id,)

    try:
        if filter_command == "status":
            records = [repo.get(filter_id).as_dict() for filter_id in filter_ids]
            print(json.dumps(records[0] if len(records) == 1 else records, indent=2, sort_keys=True))
            return 0

        updated = []
        for filter_id in filter_ids:
            record = repo.set_manual_mode(filter_id, filter_command)
            decision = resolve_filter_state(
                filter_id=filter_id,
                manual_mode=record.manual_mode,
                automation_request=record.automation_request
                if record.automation_request in {"on", "off", "unknown"}
                else FilterState.UNKNOWN,
                automation_reason="automation",
            )
            record = repo.update(
                filter_id,
                effective_state=decision.effective_state.value,
                reason=decision.reason,
            )
            updated.append(record.as_dict())
        print(json.dumps(updated[0] if len(updated) == 1 else updated, indent=2, sort_keys=True))
        return 0
    finally:
        conn.close()


def parse_filter_args(values: list[str]) -> tuple[str, str]:
    if values == ["status"]:
        return "all", "status"
    if len(values) != 2:
        raise SystemExit("usage: airmonitor filter status | airmonitor filter {bento,levoit,all} {status,auto,on,off}")
    filter_id, command = values
    if filter_id not in {*FILTER_IDS, "all"}:
        raise SystemExit(f"unknown filter: {filter_id}")
    if command not in {"status", "auto", "on", "off"}:
        raise SystemExit(f"unknown filter command: {command}")
    return filter_id, command


def backup_database(args: argparse.Namespace) -> int:
    result = create_backup(database=args.database, backup_dir=args.backup_dir, retention=args.retention)
    print(json.dumps({
        "path": str(result.path),
        "size_bytes": result.size_bytes,
        "removed": [str(path) for path in result.removed],
    }, indent=2, sort_keys=True))
    return 0


def restore_database(args: argparse.Namespace) -> int:
    if not args.yes:
        print(
            "Refusing to restore without --yes: this overwrites the live database at "
            f"{args.database} (a pre-restore copy is still kept alongside it). "
            "Stop AirMonitor services writing to it first.",
            file=sys.stderr,
        )
        return 1
    try:
        pre_restore_copy = restore_backup(args.backup_file, database=args.database)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "restored_from": args.backup_file,
        "database": args.database,
        "pre_restore_copy": str(pre_restore_copy) if pre_restore_copy else None,
    }, indent=2, sort_keys=True))
    return 0


def doctor(args: argparse.Namespace) -> int:
    checks = {
        "python": sys.version.split()[0],
        "database_path": args.database,
        "policy_path": default_policy_path(),
    }
    conn = connect(args.database)
    try:
        init_db(conn)
        checks["database"] = "ok"
    finally:
        conn.close()
    print(json.dumps(checks, indent=2, sort_keys=True))
    return 0


def install(args: argparse.Namespace) -> int:
    print("AirMonitor install plan")
    print(f"  prefix: {args.prefix}")
    print("  preserve:")
    for env_file in preserved_env_files():
        print(f"    {env_file}")
    print("  services:")
    for service_name in service_names():
        print(f"    {service_name}")
    if args.dry_run:
        return 0
    print("Install actions are intentionally generated by tools/update.sh for now; run with sudo on the host.")
    return 0


def update(args: argparse.Namespace) -> int:
    print("AirMonitor update plan")
    print("  pull latest repository")
    print("  install package into the configured virtualenv")
    print("  preserve " + ", ".join(preserved_env_files()))
    print("  reload/restart generated systemd services")
    return 0


def preserved_env_files() -> tuple[str, ...]:
    return (
        "/etc/airmonitor/sgx-voc.env",
        "/etc/airmonitor/sps30.env",
        "/etc/airmonitor/bento.env",
        "/etc/airmonitor/levoit.env",
        "/etc/airmonitor/printer-mqtt.env",
    )


def service_names() -> tuple[str, ...]:
    return (
        "airmonitor.target",
        "airmonitor-printer-mqtt.service",
        "airmonitor-voc.service",
        "airmonitor-sps30.service",
        "airmonitor-bento.service",
        "airmonitor-levoit.service",
    )


def run_printer_mqtt_service() -> int:
    from airmonitor.printers.bambu import mqtt_service

    mqtt_service.run()
    return 0


def run_bento_service() -> int:
    from airmonitor.filters.bento import service

    service.run()
    return 0


def run_levoit_service(argv: list[str] | None = None) -> int:
    from airmonitor.filters.levoit import service

    return service.main(argv)


def log_samples(args: argparse.Namespace) -> int:
    try:
        import serial
    except ImportError:
        print("pyserial is required; install the project with `pip install -e .`", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    policy = None
    if args.filament_policy:
        policy = FilamentPolicy.load(args.filament_policy)
        LOG.info("Loaded filament policy: path=%s version=%s", args.filament_policy, policy.version)

    conn = connect(args.database)
    init_db(conn)
    upsert_sensor(
        conn,
        sensor_id=args.sensor_id,
        manufacturer=SENSOR_MANUFACTURER,
        product=SENSOR_PRODUCT,
        model=SENSOR_MODEL,
        transport=args.sensor_transport,
        port=args.port,
        serial=args.sensor_serial,
        location=args.sensor_location,
    )

    session_id = start_sensor_session(
        conn,
        sensor_id=args.sensor_id,
        software_version=_package_version(),
        sensor_protocol=None,
        sensor_port=args.port,
    )
    print_tracker = PrintTracker(conn, post_print_context_seconds=args.post_print_context_seconds)
    printer_cache = None

    if args.printer_mqtt:
        printer_cache = PrinterStateCache(
            host=args.local_mqtt_host,
            port=args.local_mqtt_port,
            state_topic=args.local_mqtt_topic,
            availability_topic=args.local_mqtt_availability_topic,
            client_id=args.local_mqtt_client_id,
            username=args.local_mqtt_username,
            password=args.local_mqtt_password,
            keepalive=args.local_mqtt_keepalive,
        )
        printer_cache.start()

    LOG.info(
        "Starting sensor logger: version=%s sensor_id=%s port=%s database=%s interval=%ss printer_mqtt=%s session_id=%s",
        _package_version(),
        args.sensor_id,
        args.port,
        args.database,
        args.interval,
        args.printer_mqtt,
        session_id,
    )

    try:
        with serial.Serial(
            port=args.port,
            baudrate=BAUD_RATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=args.timeout,
            write_timeout=args.timeout,
            exclusive=True,
        ) as serial_port:
            while True:
                try:
                    protocol, measurement, response = read_sgx_once(serial_port, args.decimal_places)
                    printer_state = printer_cache.latest_state() if printer_cache else None
                    printer_state = enrich_printer_state_with_policy(printer_state, policy)
                    printer_available = printer_cache.availability() if printer_cache else None
                    print_id = print_tracker.update(printer_state=printer_state, printer_available=printer_available)
                    insert_sgx_voc_sample(
                        conn,
                        sensor_id=args.sensor_id,
                        session_id=session_id,
                        print_id=print_id,
                        sensor_protocol=protocol,
                        sensor_port=args.port,
                        measurement=measurement,
                        printer_state=printer_state,
                        frame_hex=response.hex(" "),
                    )
                    LOG.info(
                        "Logged sample: voc=%s ppm temp=%sC rh=%s%% print_id=%s printer_state=%s active=%s file=%s filament=%s emission=%s room_filter=%s",
                        measurement.gas_ppm,
                        measurement.temperature_c,
                        measurement.humidity_rh,
                        print_id,
                        _dict_get(printer_state, "gcode_state"),
                        _dict_get(printer_state, "active"),
                        _dict_get(printer_state, "subtask_name"),
                        _dict_get(printer_state, "filament_type"),
                        _dict_get(printer_state, "filament_emission_class"),
                        _dict_get(printer_state, "room_filter_recommended"),
                    )
                except Exception:
                    LOG.warning("Sample failed", exc_info=True)

                time.sleep(args.interval)
    except KeyboardInterrupt:
        LOG.info("Stopping sensor logger")
        return 0
    finally:
        end_sensor_session(conn, session_id=session_id)
        if printer_cache:
            printer_cache.stop()
        conn.close()


def enrich_printer_state_with_policy(printer_state: dict[str, Any] | None, policy: FilamentPolicy | None) -> dict[str, Any] | None:
    if printer_state is None or policy is None:
        return printer_state
    enriched = dict(printer_state)
    decision = policy.classify(enriched.get("filament_type"))
    enriched.update(decision.as_printer_state_fields())
    return enriched


def _dict_get(value: dict[str, Any] | None, key: str) -> Any:
    if not value:
        return None
    return value.get(key)


def default_policy_path() -> str:
    candidates = [
        Path("/etc/airmonitor/filament-policy.yaml"),
        Path("/etc/airmonitor-filament-policy.yaml"),
        Path(__file__).resolve().parents[2] / "config" / "filament-policy.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="airmonitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe_parser = subparsers.add_parser("probe", help="perform one read-only SGX sensor query")
    probe_parser.add_argument("--port", default="/dev/serial0")
    probe_parser.add_argument("--timeout", type=float, default=1.0)
    probe_parser.add_argument("--decimal-places", type=int, default=1)

    raw_parser = subparsers.add_parser("raw", help="stream raw SGX serial request/response frames as JSON lines")
    raw_parser.add_argument("--port", default="/dev/serial0")
    raw_parser.add_argument("--timeout", type=float, default=1.0)
    raw_parser.add_argument("--decimal-places", type=int, default=1)
    raw_parser.add_argument("--interval", type=float, default=1.0)
    raw_parser.add_argument("--count", type=int, default=0, help="number of frames to read; 0 means run until Ctrl-C")
    raw_parser.add_argument("--protocol", choices=["2023", "2022-legacy", "all"], default="2023")

    policy_parser = subparsers.add_parser("policy", help="classify filament materials using the configured policy")
    policy_parser.add_argument("materials", nargs="+", help="filament material names to classify")
    policy_parser.add_argument("--filament-policy", default=default_policy_path())

    filter_parser = subparsers.add_parser("filter", help="inspect or set filter manual override mode")
    filter_parser.add_argument("filter_args", nargs="+", metavar="ARG")
    filter_parser.add_argument("--database", default="/var/lib/airmonitor/airmonitor.sqlite3")

    doctor_parser = subparsers.add_parser("doctor", help="run local AirMonitor sanity checks")
    doctor_parser.add_argument("--database", default="/var/lib/airmonitor/airmonitor.sqlite3")

    backup_parser = subparsers.add_parser("backup", help="create a compressed database backup and prune old ones")
    backup_parser.add_argument("--database", default="/var/lib/airmonitor/airmonitor.sqlite3")
    backup_parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    backup_parser.add_argument("--retention", type=int, default=DEFAULT_RETENTION, help="number of backups to keep")

    restore_parser = subparsers.add_parser("restore", help="restore the database from a backup file")
    restore_parser.add_argument("backup_file", help="path to a .sqlite3 or .sqlite3.gz backup file")
    restore_parser.add_argument("--database", default="/var/lib/airmonitor/airmonitor.sqlite3")
    restore_parser.add_argument("--yes", action="store_true", help="confirm overwriting the live database")

    install_parser = subparsers.add_parser("install", help="show or execute the AirMonitor install plan")
    install_parser.add_argument("--prefix", default="/opt/airmonitor")
    install_parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)

    subparsers.add_parser("update", help="show the AirMonitor update plan")

    subparsers.add_parser("printer-mqtt", help="run the Bambu printer MQTT normalization service")
    subparsers.add_parser("bento-service", help="run the Bento filter service")
    levoit_parser = subparsers.add_parser("levoit-service", help="run Levoit filter service commands")
    levoit_parser.add_argument("levoit_args", nargs=argparse.REMAINDER)

    log_parser = subparsers.add_parser("log", help="continuously log SGX samples to SQLite")
    log_parser.add_argument("--port", default="/dev/serial0")
    log_parser.add_argument("--timeout", type=float, default=1.0)
    log_parser.add_argument("--decimal-places", type=int, default=1)
    log_parser.add_argument("--sensor-id", default="sgx-voc-01")
    log_parser.add_argument("--sensor-transport", default="gpio-uart")
    log_parser.add_argument("--sensor-serial", default=None)
    log_parser.add_argument("--sensor-location", default=None)
    log_parser.add_argument("--database", default="/var/lib/airmonitor/airmonitor.sqlite3")
    log_parser.add_argument("--interval", type=float, default=10.0)
    log_parser.add_argument("--post-print-context-seconds", type=int, default=1800)
    log_parser.add_argument("--filament-policy", default=default_policy_path())
    log_parser.add_argument("--printer-mqtt", action=argparse.BooleanOptionalAction, default=True)
    log_parser.add_argument("--local-mqtt-host", default="localhost")
    log_parser.add_argument("--local-mqtt-port", type=int, default=1883)
    log_parser.add_argument("--local-mqtt-topic", default="printer/state")
    log_parser.add_argument("--local-mqtt-availability-topic", default="printer/available")
    log_parser.add_argument("--local-mqtt-client-id", default="airmonitor")
    log_parser.add_argument("--local-mqtt-username", default=None)
    log_parser.add_argument("--local-mqtt-password", default=None)
    log_parser.add_argument("--local-mqtt-keepalive", type=int, default=60)
    log_parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "probe":
        return probe(args.port, args.timeout, args.decimal_places)
    if args.command == "raw":
        return raw_serial(args)
    if args.command == "policy":
        return show_policy(args)
    if args.command == "filter":
        return filter_control(args)
    if args.command == "doctor":
        return doctor(args)
    if args.command == "backup":
        return backup_database(args)
    if args.command == "restore":
        return restore_database(args)
    if args.command == "install":
        return install(args)
    if args.command == "update":
        return update(args)
    if args.command == "printer-mqtt":
        return run_printer_mqtt_service()
    if args.command == "bento-service":
        return run_bento_service()
    if args.command == "levoit-service":
        return run_levoit_service(args.levoit_args or None)
    if args.command == "log":
        return log_samples(args)
    raise AssertionError(f"unhandled command: {args.command}")
