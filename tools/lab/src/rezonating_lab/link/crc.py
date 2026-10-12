"""CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, not reflected, xorout 0. Check value 0x29B1."""

from __future__ import annotations

import binascii

CHECK_INPUT = b"123456789"
CHECK_VALUE = 0x29B1


def crc16_ccitt_false(data: bytes) -> int:
    """CRC of ``data`` (header + payload of a frame). ``binascii.crc_hqx`` is poly 0x1021, not reflected."""
    return binascii.crc_hqx(data, 0xFFFF)


def crc16_bitwise(data: bytes) -> int:
    """Slow reference implementation, the one a firmware author can port line by line."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc
