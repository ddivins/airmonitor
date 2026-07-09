"""Command-line interface for Air Monitor."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
import sys
import time
from typing import Any

from airmonitor.database import (
    connect,
    end_sensor_session,
    init_db,
    insert_sgx_voc_sample,
    start_sensor_session,
    upsert_sensor,
)
from airmonitor.filament_policy import FilamentPolicy
from airmonitor.print_tracker import PrintTracker
from airmonitor.printer_mqtt import PrinterStateCache
from airmonitor.sensors.sgx_ps1_voc_1000 import (
    BAUD_RATE,
    COMBINED_RESPONSE_LENGTH,
    ProtocolError,
    combined_read_candidates,
    parse_combined_response,
)


APP_VERSION = "0.4.0"
SENSOR_MANUFACTURER = "SGX Sensortech"
SENSOR_PRODUCT = "PS1-VOC-1000-MOD"
SENSOR_MODEL = "SGX PS1-VOC-1000-MOD"
LOG = logging.getLogger("airmonitor")


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
            measurement = parse_combined_response(
                response, decimal_places=decimal_places
            )
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
    if args.protocol == "all":
        requests = list(combined_read_candidates())
    else:
        requests = [(args.protocol, candidates[args.protocol])]

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
                            measurement = parse_combined_response(
                                response, decimal_places=args.decimal_places
                            )
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
        software_version=APP_VERSION,
        sensor_protocol=None,
        sensor_port=args.port,
    )
    print_tracker = PrintTracker(
        conn,
        post_print_context_seconds=args.post_print_context_seconds,
    )
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
        APP_VERSION,
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
                    printer_state = enrich_with_filament_policy(printer_state, policy)
                    printer_available = printer_cache.availability() if printer_cache else None
                    print_id = print_tracker.update(
                        printer_state=printer_state,
                        printer_available=printer_available,
                    )
                    insert_sgx_voc_sample(
                        conn,
                        sensor_id=args.sensor_id,
                        session_id=session_id,
                        print_id=print_id,
                        sensor_protocol=protocol,
                        sensor_port=args.port,
                        measurement=measurement,
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


def enrich_with_filament_policy(
    printer_state: dict[str, Any] | None, policy: FilamentPolicy
) -> dict[str, Any] | None:
    if not printer_state:
        return printer_state
    state = dict(printer_state)
    decision = policy.classify(state.get("filament_type"))
    state.update(decision.as_printer_state_fields())
    return state


def _dict_get(value: dict[str, Any] | None, key: str) -> Any:
    if not value:
        return None
    return value.get(key)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="airmonitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe_parser = subparsers.add_parser(
        "probe", help="perform one read-only SGX sensor query"
    )
    probe_parser.add_argument("--port", default="/dev/serial0")
    probe_parser.add_argument("--timeout", type=float, default=1.0)
    probe_parser.add_argument("--decimal-places", type=int, default=1)

    raw_parser = subparsers.add_parser(
        "raw", help="stream raw SGX serial request/response frames as JSON lines"
    )
    raw_parser.add_argument("--port", default="/dev/serial0")
    raw_parser.add_argument("--timeout", type=float, default=1.0)
    raw_parser.add_argument("--decimal-places", type=int, default=1)
    raw_parser.add_argument("--interval", type=float, default=1.0)
    raw_parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="number of frames to read; 0 means run until Ctrl-C",
    )
    raw_parser.add_argument(
        "--protocol",
        choices=["2023", "2022-legacy", "all"],
        default="2023",
        help="which combined-read request to send",
    )

    log_parser = subparsers.add_parser(
        "log", help="continuously log SGX samples to SQLite"
    )
    log_parser.add_argument("--port", default="/dev/serial0")
    log_parser.add_argument("--timeout", type=float, default=1.0)
    log_parser.add_argument("--decimal-places", type=int, default=1)
    log_parser.add_argument("--sensor-id", default="sgx-voc-01")
    log_parser.add_argument("--sensor-transport", default="gpio-uart")
    log_parser.add_argument("--sensor-serial", default=None)
    log_parser.add_argument("--sensor-location", default=None)
    log_parser.add_argument("--database", default="/var/lib/airmonitor/airmonitor.sqlite3")
    log_parser.add_argument("--filament-policy", default="/etc/airmonitor-filament-policy.yaml")
    log_parser.add_argument("--interval", type=float, default=10.0)
    log_parser.add_argument("--post-print-context-seconds", type=int, default=1800)
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
    if args.command == "log":
        return log_samples(args)
    raise AssertionError(f"unhandled command: {args.command}")
