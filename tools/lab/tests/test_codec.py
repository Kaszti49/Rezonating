import math
import struct

import numpy as np
import pytest
from rezonating_lab.link import codec
from rezonating_lab.link.codec import (
    Ack,
    Auth,
    CodecError,
    Data,
    Err,
    Event,
    FrameError,
    GetInfo,
    Log,
    Ping,
    Pong,
    Reboot,
    SdRecord,
    Set,
    Start,
    Stop,
)
from rezonating_lab.link.vectors import CONFIG, HELLO, STATUS


def _samples(n, n_ch, seed=0):
    return np.random.default_rng(seed).integers(-(2**23), 2**23, size=(n, n_ch), dtype=np.int32)


ONE_OF_EACH = [
    HELLO,
    CONFIG,
    Data(0, 2**33, 99, _samples(5, 2)),
    Data(1, 0, 0, _samples(1, 2)),
    Data(2, 7, 8, _samples(9, 3)),
    STATUS,
    Event(1, 5, codec.EVENT_PACK_OUTPUT, "footstep-id", "person", 0.5, "P1"),
    Event(0, 5, codec.EVENT_TRIGGER, "", "", None, ""),
    Log(4, 123, "tag", "hello"),
    Ack(65535),
    Err(3, codec.ERR_BUSY, "busy"),
    Pong(2**63, 2**40),
    GetInfo(),
    Start(7),
    Stop(3),
    Set("adc.gain.0", -4),
    Set("x", 0.5),
    Set("wifi.ssid", "net"),
    Set("pair.key", bytes(range(16))),
    SdRecord(1, 5, "session-1"),
    Ping(2**64 - 1),
    Reboot(),
    Auth(bytes(16)),
]


@pytest.mark.parametrize("msg", ONE_OF_EACH, ids=lambda m: type(m).__name__)
def test_round_trip_every_frame_type(msg):
    wire = codec.encode_frame(msg, 0x1234)
    assert wire.endswith(b"\x00") and b"\x00" not in wire[:-1]
    frame = codec.decode_frame(wire)
    assert frame.seq == 0x1234
    assert frame.msg == msg


def test_every_type_in_the_spec_is_covered():
    covered = {m.TYPE_ID for m in ONE_OF_EACH}
    assert covered == set(codec.TYPE_NAMES) == set(codec.ALL_TYPES)


def test_header_layout_and_crc_are_little_endian():
    raw = codec.encode_raw_frame(0x86, 0x0102, struct.pack("<Q", 5))
    assert raw[:4] == bytes([0, 0x86, 0x02, 0x01])
    body, crc = raw[:-2], struct.unpack("<H", raw[-2:])[0]
    assert crc == codec.crc16_ccitt_false(body)


def test_auth_wire_is_length_prefixed_blob():
    key = bytes(range(16))
    assert Auth(key).to_payload() == b"\x10\x00" + key
    with pytest.raises(CodecError):
        Auth(b"short").to_payload()


def test_data_layout():
    msg = Data(2, 0x1122334455667788, 0x0102030405060708, np.array([[1, -2, 3], [4, 5, 6]], np.int32))
    p = msg.to_payload()
    assert p[:4] == bytes([2, 3, 2, 0])  # stream, n_ch, n (u16)
    assert struct.unpack("<QQ", p[4:20]) == (0x1122334455667788, 0x0102030405060708)
    assert struct.unpack("<6i", p[20:]) == (1, -2, 3, 4, 5, 6)  # frame-major


def test_data_with_zero_frames_is_rejected():
    payload = bytes([0, 2, 0, 0]) + bytes(16)
    with pytest.raises(CodecError):
        Data.from_payload(payload)
    with pytest.raises(CodecError):
        Data(0, 0, 0, np.zeros((0, 2), np.int32)).to_payload()


def test_receivers_ignore_trailing_payload_bytes():
    for msg in ONE_OF_EACH:
        payload = msg.to_payload() + b"\xaa\xbb\xcc"
        assert type(msg).from_payload(payload) == msg


def test_short_payload_raises_codec_error():
    for msg in ONE_OF_EACH:
        payload = msg.to_payload()
        if len(payload) == 0:
            continue
        with pytest.raises(CodecError):
            type(msg).from_payload(payload[:-1])


def test_event_none_value_is_the_quiet_nan():
    p = Event(0, 1, 0, "", "", None, "").to_payload()
    assert codec.NAN_F32_BYTES in p
    assert struct.unpack("<I", codec.NAN_F32_BYTES)[0] == 0x7FC00000
    assert Event.from_payload(p).value is None
    assert Event(0, 1, 0, "", "", math.nan, "").to_payload() == p


def test_strings_are_cut_on_a_code_point_boundary():
    text = "é" * 200  # 400 bytes in UTF-8
    cut = Log(3, 0, "t", text).to_payload()
    # str8 limit 255 applies to the tag only; msg is limited to 1024 B
    assert Log.from_payload(cut).msg == text
    long_tag = Log(3, 0, "é" * 200, "m")
    tag = Log.from_payload(long_tag.to_payload()).tag
    assert tag == "é" * 127 and len(tag.encode()) == 254
    big = Log(3, 0, "t", "é" * 1000)
    assert len(Log.from_payload(big.to_payload()).msg.encode()) == 1024


def test_set_value_types():
    assert Set("a", 5).value_type == codec.SET_I32
    assert Set("a", 0.5).value_type == codec.SET_F32
    assert Set("a", "s").value_type == codec.SET_STR8
    assert Set("a", b"b").value_type == codec.SET_BLOB16
    with pytest.raises(CodecError):
        Set("a", None).to_payload()  # type: ignore[arg-type]


def test_payload_over_4096_bytes_is_refused():
    with pytest.raises(CodecError):
        codec.encode_raw_frame(0x01, 0, bytes(4097))
    codec.encode_raw_frame(0x01, 0, bytes(4096))


def test_unknown_type_and_direction_tables():
    raw = codec.encode_raw_frame(0x55, 0, b"")
    t, seq, payload = codec.decode_raw_frame(raw)
    with pytest.raises(codec.UnknownTypeError):
        codec.parse_payload(t, payload)
    with pytest.raises(codec.UnknownTypeError):
        codec.parse_payload(Ping.TYPE_ID, Ping(1).to_payload(), codec.NODE_TO_PC)
    assert codec.parse_payload(Ping.TYPE_ID, Ping(1).to_payload(), codec.PC_TO_NODE) == Ping(1)


def test_frame_checks():
    good = codec.encode_raw_frame(Ack.TYPE_ID, 1, Ack(2).to_payload())
    codec.decode_raw_frame(good)
    with pytest.raises(FrameError):
        codec.decode_raw_frame(good[:5])  # under 6 bytes
    with pytest.raises(FrameError):
        codec.decode_raw_frame(bytes(4103))  # over 4102
    with pytest.raises(FrameError):
        codec.decode_raw_frame(good[:-1] + bytes([good[-1] ^ 1]))  # CRC
    body = bytes([1, Ack.TYPE_ID, 1, 0]) + Ack(2).to_payload()  # ver 1
    with pytest.raises(FrameError):
        codec.decode_raw_frame(body + struct.pack("<H", codec.crc16_ccitt_false(body)))


def test_json_round_trip_of_every_message():
    for msg in ONE_OF_EACH:
        d = codec.to_jsonable(msg)
        assert codec.from_jsonable(msg.TYPE_ID, d) == msg
