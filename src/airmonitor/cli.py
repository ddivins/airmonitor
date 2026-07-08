"""Command-line interface for Air Monitor."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from airmonitor.sensors.sgx_ps1_voc_1000 import (
    BAUD_RATE,
    COMBINED_RESPONSE_LENGTH,
    ProtocolError,
    combined_read_candidates,
    parse_combined_response,
)


def _read_frame(serial_port) -> bytes:
    """Synchronize on 0xFF and read one combined response."""

    while True:
        first = serial_port.read(1)
        if not first:
            return b""
        if first == b"\xFF":
            return first + serial_port.read(COMBINED_RESPONSE_LENGTH - 1)


def probe(port: str, timeout: float, decimal_places: int) -> int:
    try:
        import serial
    except ImportError:
        print("pyserial is required; install the project with `pip install -e .`", file=sys.stderr)
        return 2

    errors: list[str] = []
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

            output = asdict(measurement)
            output.update(protocol=protocol, frame_hex=response.hex(" "))
            print(json.dumps(output, indent=2, sort_keys=True))
            return 0

    print("Unable to read the sensor:", file=sys.stderr)
    for error in errors:
        print(f"  {error}", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="airmonitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe_parser = subparsers.add_parser(
        "probe", help="perform one read-only SGX sensor query"
    )
    probe_parser.add_argument("--port", default="/dev/serial0")
    probe_parser.add_argument("--timeout", type=float, default=1.0)
    probe_parser.add_argument("--decimal-places", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "probe":
        return probe(args.port, args.timeout, args.decimal_places)
    raise AssertionError(f"unhandled command: {args.command}")
