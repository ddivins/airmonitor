"""Sensirion SPS30 SHDLC UART driver."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import struct
import time
from typing import Any

BAUD_RATE = 115200
FRAME_DELIMITER = 0x7E
ESCAPE = 0x7D
ESCAPED_BYTES = {0x7E: 0x5E, 0x7D: 0x5D, 0x11: 0x31, 0x13: 0x33}
UNESCAPED_BYTES = {value: key for key, value in ESCAPED_BYTES.items()}


class SPS30Error(RuntimeError):
    pass


@dataclass(frozen=True)
class SPS30Measurement:
    mass_pm1_0: float
    mass_pm2_5: float
    mass_pm4_0: float
    mass_pm10: float
    number_pm0_5: float
    number_pm1_0: float
    number_pm2_5: float
    number_pm4_0: float
    number_pm10: float
    typical_particle_size: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def checksum(payload: bytes) -> int:
    return (~sum(payload)) & 0xFF


def _escape(payload: bytes) -> bytes:
    result = bytearray()
    for value in payload:
        if value in ESCAPED_BYTES:
            result.extend((ESCAPE, ESCAPED_BYTES[value]))
        else:
            result.append(value)
    return bytes(result)


def _unescape(payload: bytes) -> bytes:
    result = bytearray()
    escaped = False
    for value in payload:
        if escaped:
            if value not in UNESCAPED_BYTES:
                raise SPS30Error(f"invalid escaped byte 0x{value:02x}")
            result.append(UNESCAPED_BYTES[value])
            escaped = False
        elif value == ESCAPE:
            escaped = True
        else:
            result.append(value)
    if escaped:
        raise SPS30Error("truncated escape sequence")
    return bytes(result)


def build_frame(command: int, data: bytes = b"", address: int = 0) -> bytes:
    body = bytes((address, command, len(data))) + data
    return bytes((FRAME_DELIMITER,)) + _escape(body + bytes((checksum(body),))) + bytes((FRAME_DELIMITER,))


def parse_response(frame: bytes, expected_command: int | None = None) -> tuple[int, bytes]:
    if len(frame) < 2 or frame[0] != FRAME_DELIMITER or frame[-1] != FRAME_DELIMITER:
        raise SPS30Error(f"invalid frame delimiters: {frame.hex(' ')}")
    body = _unescape(frame[1:-1])
    if len(body) < 5:
        raise SPS30Error(f"short response: {body.hex(' ')}")
    address, command, state, length = body[:4]
    data = body[4:-1]
    received_checksum = body[-1]
    if address != 0:
        raise SPS30Error(f"unexpected address {address}")
    if expected_command is not None and command != expected_command:
        raise SPS30Error(f"expected command 0x{expected_command:02x}, got 0x{command:02x}")
    if length != len(data):
        raise SPS30Error(f"response length field {length} does not match {len(data)} bytes")
    if checksum(body[:-1]) != received_checksum:
        raise SPS30Error("response checksum mismatch")
    if state != 0:
        raise SPS30Error(f"sensor returned state 0x{state:02x} for command 0x{command:02x}")
    return command, data


def read_frame(serial_port) -> bytes:
    while True:
        first = serial_port.read(1)
        if not first:
            raise SPS30Error("no response")
        if first[0] == FRAME_DELIMITER:
            break
    result = bytearray(first)
    while True:
        value = serial_port.read(1)
        if not value:
            raise SPS30Error("incomplete response")
        result.extend(value)
        if value[0] == FRAME_DELIMITER:
            return bytes(result)


class SPS30:
    def __init__(self, serial_port):
        self.serial = serial_port

    def command(self, command: int, data: bytes = b"") -> bytes:
        self.serial.reset_input_buffer()
        self.serial.write(build_frame(command, data))
        self.serial.flush()
        _, response = parse_response(read_frame(self.serial), command)
        return response

    def product_type(self) -> str:
        return self.command(0xD0, b"\x00").rstrip(b"\x00").decode("ascii", errors="replace")

    def serial_number(self) -> str:
        return self.command(0xD0, b"\x03").rstrip(b"\x00").decode("ascii", errors="replace")

    def start_measurement(self) -> None:
        # 0x01 = IEEE754 float output, 0x03 = mass + number concentration.
        self.command(0x00, b"\x01\x03")

    def stop_measurement(self) -> None:
        self.command(0x01)

    def data_ready(self) -> bool:
        data = self.command(0x02)
        return bool(data and data[-1])

    def read_measurement(self) -> SPS30Measurement:
        data = self.command(0x03)
        if len(data) != 40:
            raise SPS30Error(f"expected 40 measurement bytes, received {len(data)}")
        return SPS30Measurement(*struct.unpack(">10f", data))

    def wait_until_ready(self, timeout: float = 10.0, interval: float = 0.25) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.data_ready():
                return
            time.sleep(interval)
        raise SPS30Error(f"measurement not ready after {timeout:g}s")
