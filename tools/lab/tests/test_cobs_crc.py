import random

import pytest
from rezonating_lab.link import cobs
from rezonating_lab.link.crc import CHECK_INPUT, CHECK_VALUE, crc16_bitwise, crc16_ccitt_false


def test_crc_check_value():
    assert crc16_ccitt_false(CHECK_INPUT) == CHECK_VALUE == 0x29B1
    assert crc16_bitwise(CHECK_INPUT) == 0x29B1


def test_crc_fast_matches_bitwise_reference():
    rng = random.Random(1)
    for n in (0, 1, 2, 17, 255, 1000):
        data = bytes(rng.randrange(256) for _ in range(n))
        assert crc16_ccitt_false(data) == crc16_bitwise(data)


@pytest.mark.parametrize(
    "raw, encoded",
    [
        (b"\x00", "0101"),
        (b"\x01\x00", "020101"),  # PROTOCOL.md: a frame ending in 0x00 gets a final empty block
        (b"\x11\x22\x00\x33", "03112202" + "33"),
        (b"\x00\x05\x01\x01", "01" + "04050101"),
    ],
)
def test_cobs_known_encodings(raw, encoded):
    assert cobs.encode(raw).hex() == encoded
    assert cobs.decode(bytes.fromhex(encoded)) == raw


def test_254_run_has_no_extra_code_byte():
    raw = b"\x01" * 254
    enc = cobs.encode(raw)
    assert len(enc) == 255 and enc[0] == 0xFF and enc[1:] == raw


def test_254_run_followed_by_zero_ends_with_empty_block():
    raw = b"\x01" * 254 + b"\x00"
    enc = cobs.encode(raw)
    assert enc == b"\xff" + b"\x01" * 254 + b"\x01\x01"
    assert cobs.decode(enc) == raw


@pytest.mark.parametrize("n, size", [(253, 254), (254, 255), (255, 257), (508, 510), (509, 512)])
def test_run_lengths(n, size):
    raw = b"\x07" * n
    enc = cobs.encode(raw)
    assert len(enc) == size
    assert cobs.decode(enc) == raw


def test_worst_case_is_4119_bytes():
    raw = b"\x00" + b"\x01" * 4101  # 4102 bytes
    assert len(cobs.encode(raw)) == 4119


def test_random_round_trip_has_no_zero_bytes():
    rng = random.Random(7)
    for n in list(range(1, 600)) + [1000, 4102]:
        for _ in range(3):
            raw = bytes(rng.choice((0, 1, 255, rng.randrange(256))) for _ in range(n))
            enc = cobs.encode(raw)
            assert 0 not in enc
            assert cobs.decode(enc) == raw


@pytest.mark.parametrize("bad", [b"", b"\x00", b"\x05\x01\x02", b"\x03\x01\x00"])
def test_decode_rejects_malformed(bad):
    with pytest.raises(cobs.CobsError):
        cobs.decode(bad)


def test_empty_raw_frame_is_refused():
    with pytest.raises(ValueError):
        cobs.encode(b"")
