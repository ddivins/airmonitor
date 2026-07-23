from __future__ import annotations

import struct

from airmonitor.sensors.sensirion.sps30 import SPS30, SPS30Error, SPS30Measurement, build_frame, parse_response

from fake_serial import FakeSPS30Serial


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


# The tests below exercise the actual SPS30 command/response cycle (framing,
# escaping, checksum) against a simulated serial port, instead of only the
# frame encode/decode helpers above.


def test_product_type_round_trips_through_the_command_cycle() -> None:
    sensor = SPS30(FakeSPS30Serial(product_type="00080000"))
    assert sensor.product_type() == "00080000"


def test_serial_number_round_trips_through_the_command_cycle() -> None:
    sensor = SPS30(FakeSPS30Serial(serial_number="SPS30-ABC-123"))
    assert sensor.serial_number() == "SPS30-ABC-123"


def test_start_and_stop_measurement_toggle_sensor_state() -> None:
    serial_port = FakeSPS30Serial()
    sensor = SPS30(serial_port)
    sensor.start_measurement()
    assert serial_port.measuring is True
    sensor.stop_measurement()
    assert serial_port.measuring is False


def test_read_measurement_decodes_all_ten_fields() -> None:
    expected = (1.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 0.75)
    sensor = SPS30(FakeSPS30Serial(measurement=expected))
    measurement = sensor.read_measurement()
    assert measurement == SPS30Measurement(*expected)


def test_data_ready_reflects_simulated_sensor_state() -> None:
    assert SPS30(FakeSPS30Serial(data_ready_sequence=(False,))).data_ready() is False
    assert SPS30(FakeSPS30Serial(data_ready_sequence=(True,))).data_ready() is True


def test_wait_until_ready_polls_until_a_later_response_is_ready() -> None:
    sensor = SPS30(FakeSPS30Serial(data_ready_sequence=(False, False, True)))
    sensor.wait_until_ready(timeout=1.0, interval=0.01)  # does not raise


def test_wait_until_ready_times_out_if_never_ready() -> None:
    sensor = SPS30(FakeSPS30Serial(data_ready_sequence=(False,)))
    try:
        sensor.wait_until_ready(timeout=0.05, interval=0.01)
    except SPS30Error as exc:
        assert "not ready" in str(exc)
    else:
        raise AssertionError("expected SPS30Error")
