"""In-memory stand-ins for pyserial ``Serial`` objects.

Both sensor drivers -- ``airmonitor.cli.read_sgx_once`` and
``airmonitor.sensors.sensirion.sps30.SPS30`` -- only require an object with
``.read``/``.write``/``.flush``/``.reset_input_buffer``; they never construct
``serial.Serial`` themselves. That means the actual protocol-driving code
(request/response framing, checksum validation, protocol fallback, measurement
decoding) can run end to end in tests against these fakes instead of only
exercising the lower-level frame-encode/decode helpers, without any physical
sensor attached.
"""

from __future__ import annotations

import struct

from airmonitor.sensors.sensirion.sps30.driver import (
    FRAME_DELIMITER,
    _escape,
    _unescape,
    checksum as sps30_checksum,
)
from airmonitor.sensors.sgx_ps1_voc_1000 import combined_read_candidates


class FakeSGXSerial:
    """Answers SGX PS1-VOC-1000-MOD combined-read requests with a canned measurement."""

    def __init__(
        self,
        *,
        gas_mass: float = 4.2,
        gas_ppm: float = 3.2,
        full_scale: int = 1000,
        temperature_c: float = 25.0,
        humidity_rh: float = 50.0,
        decimal_places: int = 1,
        respond_to: tuple[str, ...] = ("2023", "2022-legacy"),
        corrupt_checksum: bool = False,
    ) -> None:
        self._measurement = dict(
            gas_mass=gas_mass,
            gas_ppm=gas_ppm,
            full_scale=full_scale,
            temperature_c=temperature_c,
            humidity_rh=humidity_rh,
        )
        self._decimal_places = decimal_places
        self._respond_to = set(respond_to)
        self._corrupt_checksum = corrupt_checksum
        self._buffer = bytearray()
        self.requests: list[bytes] = []

    def reset_input_buffer(self) -> None:
        self._buffer.clear()

    def write(self, data: bytes) -> int:
        self.requests.append(bytes(data))
        for protocol, request in combined_read_candidates():
            if request == bytes(data) and protocol in self._respond_to:
                self._buffer.extend(self._build_response())
                break
        return len(data)

    def flush(self) -> None:
        pass

    def read(self, size: int = 1) -> bytes:
        chunk = bytes(self._buffer[:size])
        del self._buffer[:size]
        return chunk

    def _build_response(self) -> bytes:
        scale = 10**self._decimal_places
        body = bytes((0x87,))
        body += round(self._measurement["gas_mass"] * scale).to_bytes(2, "big")
        body += self._measurement["full_scale"].to_bytes(2, "big")
        body += round(self._measurement["gas_ppm"] * scale).to_bytes(2, "big")
        body += round(self._measurement["temperature_c"] * 100).to_bytes(2, "big", signed=True)
        body += round(self._measurement["humidity_rh"] * 100).to_bytes(2, "big")
        response_checksum = (-sum(body)) & 0xFF
        if self._corrupt_checksum:
            response_checksum ^= 0xFF
        return bytes((0xFF,)) + body + bytes((response_checksum,))


class FakeSPS30Serial:
    """Answers the Sensirion SHDLC commands the ``SPS30`` driver sends.

    ``data_ready_sequence`` lets a test make ``wait_until_ready`` poll more
    than once before the sensor reports data, the same way a slow real unit
    would -- the last entry repeats once the sequence is exhausted.
    """

    def __init__(
        self,
        *,
        product_type: str = "00080000",
        serial_number: str = "SPS30-TEST-0001",
        measurement: tuple[float, ...] | None = None,
        data_ready_sequence: tuple[bool, ...] = (True,),
    ) -> None:
        self.product_type = product_type
        self.serial_number = serial_number
        self.measurement = measurement or (1.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 0.75)
        self._data_ready_sequence = list(data_ready_sequence)
        self.measuring = False
        self._buffer = bytearray()
        self.commands: list[int] = []

    def reset_input_buffer(self) -> None:
        self._buffer.clear()

    def write(self, data: bytes) -> int:
        command, request_data = self._decode(bytes(data))
        self.commands.append(command)
        self._buffer.extend(self._respond(command, request_data))
        return len(data)

    def flush(self) -> None:
        pass

    def read(self, size: int = 1) -> bytes:
        chunk = bytes(self._buffer[:size])
        del self._buffer[:size]
        return chunk

    @staticmethod
    def _decode(frame: bytes) -> tuple[int, bytes]:
        body = _unescape(frame[1:-1])
        command = body[1]
        length = body[2]
        data = body[3 : 3 + length]
        return command, data

    def _respond(self, command: int, request_data: bytes) -> bytes:
        if command == 0xD0:
            text = self.product_type if request_data == b"\x00" else self.serial_number
            data = text.encode("ascii")
        elif command == 0x00:
            self.measuring = True
            data = b""
        elif command == 0x01:
            self.measuring = False
            data = b""
        elif command == 0x02:
            ready = self._data_ready_sequence.pop(0) if len(self._data_ready_sequence) > 1 else self._data_ready_sequence[0]
            data = bytes((1 if ready else 0,))
        elif command == 0x03:
            data = struct.pack(">10f", *self.measurement)
        else:
            data = b""
        return self._build_response(command, data)

    @staticmethod
    def _build_response(command: int, data: bytes) -> bytes:
        body = bytes((0, command, 0, len(data))) + data
        response_checksum = sps30_checksum(body)
        return bytes((FRAME_DELIMITER,)) + _escape(body + bytes((response_checksum,))) + bytes((FRAME_DELIMITER,))
