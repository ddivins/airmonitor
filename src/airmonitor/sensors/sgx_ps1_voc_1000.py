"""Protocol support for the SGX PS1-VOC-1000-MOD.

The February 2022 datasheet and July 2023 protocol note differ in byte 1 of
the combined-read request. The response format is identical, so callers can
try the current request first and fall back to the legacy request.
"""

from __future__ import annotations

from dataclasses import dataclass


BAUD_RATE = 9600
COMBINED_RESPONSE_LENGTH = 13


class ProtocolError(ValueError):
    """Raised when a sensor frame is malformed or fails its checksum."""


@dataclass(frozen=True)
class Measurement:
    gas_mass: float
    gas_ppm: float
    full_scale: int
    temperature_c: float
    humidity_rh: float


def checksum(data: bytes) -> int:
    """Return the protocol's 8-bit two's-complement checksum."""

    return (-sum(data)) & 0xFF


def build_combined_read(retain: int) -> bytes:
    """Build a combined VOC, temperature, and humidity read request."""

    if retain not in (0x00, 0x01):
        raise ValueError("retain must be 0x00 or 0x01")

    body = bytes((retain, 0x87, 0x00, 0x00, 0x00, 0x00, 0x00))
    return bytes((0xFF,)) + body + bytes((checksum(body),))


CURRENT_COMBINED_READ = build_combined_read(0x01)
LEGACY_COMBINED_READ = build_combined_read(0x00)


def combined_read_candidates() -> tuple[tuple[str, bytes], ...]:
    """Return read-only requests in preferred compatibility order."""

    return (
        ("2023", CURRENT_COMBINED_READ),
        ("2022-legacy", LEGACY_COMBINED_READ),
    )


def parse_combined_response(frame: bytes, *, decimal_places: int = 1) -> Measurement:
    """Parse a 13-byte combined response.

    Concentration scaling is configurable because the module-information frame
    defines it and the vendor's examples are generic rather than specific to
    every sensor range. The PS1-VOC-1000-MOD's documented resolution is 0.1 ppm.
    """

    if len(frame) != COMBINED_RESPONSE_LENGTH:
        raise ProtocolError(
            f"expected {COMBINED_RESPONSE_LENGTH} bytes, received {len(frame)}"
        )
    if frame[0] != 0xFF:
        raise ProtocolError(f"unexpected start byte: 0x{frame[0]:02X}")
    if frame[1] != 0x87:
        raise ProtocolError(f"unexpected response command: 0x{frame[1]:02X}")
    if sum(frame[1:]) & 0xFF:
        raise ProtocolError("checksum mismatch")
    if decimal_places not in range(4):
        raise ValueError("decimal_places must be between 0 and 3")

    scale = 10**decimal_places
    gas_mass_raw = int.from_bytes(frame[2:4], "big")
    full_scale = int.from_bytes(frame[4:6], "big")
    gas_ppm_raw = int.from_bytes(frame[6:8], "big")
    temperature_raw = int.from_bytes(frame[8:10], "big", signed=True)
    humidity_raw = int.from_bytes(frame[10:12], "big")

    return Measurement(
        gas_mass=gas_mass_raw / scale,
        gas_ppm=gas_ppm_raw / scale,
        full_scale=full_scale,
        temperature_c=temperature_raw / 100,
        humidity_rh=humidity_raw / 100,
    )
