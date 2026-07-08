import unittest

from airmonitor.sensors.sgx_ps1_voc_1000 import (
    CURRENT_COMBINED_READ,
    LEGACY_COMBINED_READ,
    ProtocolError,
    checksum,
    parse_combined_response,
)


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


if __name__ == "__main__":
    unittest.main()
