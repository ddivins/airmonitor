import unittest

from airmonitor.cli import read_sgx_once
from airmonitor.sensors.sgx_ps1_voc_1000 import (
    CURRENT_COMBINED_READ,
    LEGACY_COMBINED_READ,
    ProtocolError,
    checksum,
    parse_combined_response,
)

from fake_serial import FakeSGXSerial


SAMPLE_RESPONSE = bytes.fromhex(
    "FF 87 00 2A 03 E8 00 20 09 C4 13 88 DC"
)


class SgxProtocolTests(unittest.TestCase):
    def test_current_request_matches_2023_protocol(self):
        self.assertEqual(
            CURRENT_COMBINED_READ,
            bytes.fromhex("FF 01 87 00 00 00 00 00 78"),
        )

    def test_legacy_request_matches_2022_datasheet(self):
        self.assertEqual(
            LEGACY_COMBINED_READ,
            bytes.fromhex("FF 00 87 00 00 00 00 00 79"),
        )

    def test_checksum_uses_twos_complement(self):
        self.assertEqual(checksum(bytes.fromhex("01 87 00 00 00 00 00")), 0x78)

    def test_parses_vendor_sample(self):
        measurement = parse_combined_response(SAMPLE_RESPONSE)

        self.assertEqual(measurement.gas_mass, 4.2)
        self.assertEqual(measurement.gas_ppm, 3.2)
        self.assertEqual(measurement.full_scale, 1000)
        self.assertEqual(measurement.temperature_c, 25.0)
        self.assertEqual(measurement.humidity_rh, 50.0)

    def test_rejects_bad_checksum(self):
        damaged = SAMPLE_RESPONSE[:-1] + b"\x00"
        with self.assertRaisesRegex(ProtocolError, "checksum mismatch"):
            parse_combined_response(damaged)

    def test_rejects_short_frame(self):
        with self.assertRaisesRegex(ProtocolError, "expected 13 bytes"):
            parse_combined_response(SAMPLE_RESPONSE[:-1])


class ReadSgxOnceTests(unittest.TestCase):
    """Exercises the actual read loop (protocol fallback, framing, retries)
    against a simulated serial port instead of the frame helpers directly."""

    def test_reads_current_protocol_on_first_try(self):
        serial_port = FakeSGXSerial(gas_ppm=3.2, temperature_c=25.0, humidity_rh=50.0)
        protocol, measurement, response = read_sgx_once(serial_port, decimal_places=1)
        self.assertEqual(protocol, "2023")
        self.assertEqual(measurement.gas_ppm, 3.2)
        self.assertEqual(len(response), 13)
        self.assertEqual(serial_port.requests, [CURRENT_COMBINED_READ])

    def test_falls_back_to_legacy_protocol_when_current_gets_no_response(self):
        serial_port = FakeSGXSerial(respond_to=("2022-legacy",))
        protocol, measurement, _ = read_sgx_once(serial_port, decimal_places=1)
        self.assertEqual(protocol, "2022-legacy")
        self.assertEqual(serial_port.requests, [CURRENT_COMBINED_READ, LEGACY_COMBINED_READ])

    def test_raises_when_neither_protocol_responds(self):
        serial_port = FakeSGXSerial(respond_to=())
        with self.assertRaisesRegex(RuntimeError, "no response"):
            read_sgx_once(serial_port, decimal_places=1)

    def test_raises_when_response_checksum_is_corrupt(self):
        serial_port = FakeSGXSerial(respond_to=("2023",), corrupt_checksum=True)
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            read_sgx_once(serial_port, decimal_places=1)


if __name__ == "__main__":
    unittest.main()
