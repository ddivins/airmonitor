from __future__ import annotations

import struct

from airmonitor.sensors.sensirion.sps30 import SPS30Measurement, build_frame, parse_response


def _response(command: int, data: bytes = b"", state: int = 0) -> bytes:
    body = bytes((0, command, state, len(data))) + data
    checksum = (~sum(body)) & 0xFF
    escaped = bytearray()
    mapping = {0x7E: 0x5E, 0x7D: 0x5D, 0x11: 0x31, 0x13: 0x33}
    for value in body + bytes((checksum,)):
        if value in mapping:
            escaped.extend((0x7D, mapping[value]))
        else:
            escaped.append(value)
    return b"\x7e" + bytes(escaped) + b"\x7e"


def test_product_type_command_matches_verified_hardware_frame() -> None:
    assert build_frame(0xD0, b"\x00") == bytes.fromhex("7e 00 d0 01 00 2e 7e")
    command, data = parse_response(bytes.fromhex("7e 00 d0 00 09 30 30 30 38 30 30 30 30 00 9e 7e"), 0xD0)
    assert command == 0xD0
    assert data.rstrip(b"\x00") == b"00080000"


def test_measurement_payload_decodes_ten_big_endian_floats() -> None:
    expected = (1.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 0.75)
    _, data = parse_response(_response(0x03, struct.pack(">10f", *expected)), 0x03)
    measurement = SPS30Measurement(*struct.unpack(">10f", data))
    assert measurement.mass_pm2_5 == 2.5
    assert measurement.typical_particle_size == 0.75


def test_frame_escaping_round_trip() -> None:
    data = bytes((0x7E, 0x7D, 0x11, 0x13))
    frame = _response(0x03, data)
    _, decoded = parse_response(frame, 0x03)
    assert decoded == data
