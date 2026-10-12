"""The golden vectors: the codec must reproduce every byte and decode back to the same fields.

The same JSON is what the firmware's host-side test reads, so this file also pins the file's shape.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from rezonating_lab.link import cobs, codec, vectors
from rezonating_lab.link.crc import crc16_ccitt_false
from rezonating_lab.link.receiver import FROM_NODE, FROM_PC, Receiver

VECTORS = Path(__file__).parent / "vectors" / "link-v0.json"
DOC = json.loads(VECTORS.read_text(encoding="utf-8"))
CASES = DOC["cases"]


def by_kind(kind):
    return [c for c in CASES if c["kind"] == kind]


def test_file_is_what_the_generator_produces():
    assert VECTORS.read_text(encoding="utf-8").replace("\r\n", "\n") == vectors.render(), (
        "tests/vectors/link-v0.json is stale: run python -m rezonating_lab.link.vectors --write"
    )


def test_header_of_the_file():
    assert DOC["protocol"] == "rezonating-link" and DOC["version"] == 0
    assert DOC["crc16"] == {"input_ascii": "123456789", "crc_hex": "29b1"}
    assert crc16_ccitt_false(b"123456789") == 0x29B1
    assert DOC["limits"] == {"max_payload": 4096, "max_raw_frame": 4102, "max_encoded_frame": 4119}
    names = [c["name"] for c in CASES]
    assert len(names) == len(set(names))


def test_every_frame_type_is_present():
    seen = {c["type_id"] for c in by_kind("frame")}
    assert seen >= set(codec.TYPE_NAMES)
    # a DATA frame for each stream
    streams = {c["fields"]["stream"] for c in by_kind("frame") if c["frame_type"] == "DATA"}
    assert streams == {0, 1, 2}


def test_section_8_cases_exist():
    names = {c["name"] for c in CASES}
    assert {
        "payload_with_zero_bytes",
        "cobs_frame_end_run_253",
        "cobs_frame_end_run_254",
        "cobs_frame_end_run_255",
        "cobs_frame_mid_run_253",
        "cobs_frame_mid_run_254",
        "cobs_frame_mid_run_255",
        "cobs_frame_last_byte_zero",
        "session_start",
        "frame_largest",
        "corrupted_crc",
        "boot_text_then_hello",
        "oversize_without_delimiter",
        "oversize_4121_without_delimiter",
    } <= names
    for name in ("oversize_without_delimiter", "oversize_4121_without_delimiter"):
        case = next(c for c in CASES if c["name"] == name)
        wire = bytes.fromhex(case["wire_hex"])
        assert wire.index(0) in (4120, 4121) and case["expect"]["bad_frames"] == 1  # one bad frame each


@pytest.mark.parametrize("case", by_kind("cobs"), ids=lambda c: c["name"])
def test_cobs_cases(case):
    raw, enc = bytes.fromhex(case["raw_hex"]), bytes.fromhex(case["encoded_hex"])
    assert cobs.encode(raw) == enc
    assert cobs.decode(enc) == raw


@pytest.mark.parametrize("case", by_kind("frame"), ids=lambda c: c["name"])
def test_frame_cases_reproduce_every_byte(case):
    msg = codec.from_jsonable(case["type_id"], case["fields"])
    assert codec.TYPE_NAMES[case["type_id"]] == case["frame_type"]
    wire = codec.encode_frame(msg, case["seq"])
    assert wire.hex() == case["wire_hex"]
    assert codec.encode_raw_frame(case["type_id"], case["seq"], msg.to_payload()).hex() == case["raw_hex"]


@pytest.mark.parametrize("case", by_kind("frame"), ids=lambda c: c["name"])
def test_frame_cases_decode_back_to_the_same_fields(case):
    frame = codec.decode_frame(bytes.fromhex(case["wire_hex"]))
    assert frame.seq == case["seq"]
    assert frame.msg.TYPE_ID == case["type_id"]
    assert codec.to_jsonable(frame.msg) == case["fields"]
    # and through the streaming receiver, in one piece and byte by byte
    for piece in (None, 1):
        rx = Receiver(FROM_PC if case["type_id"] >= 0x80 else FROM_NODE)
        wire = bytes.fromhex(case["wire_hex"])
        frames = rx.feed(wire) if piece is None else [f for b in range(len(wire)) for f in rx.feed(wire[b : b + 1])]
        assert len(frames) == 1 and rx.bad_frames == 0
        assert codec.to_jsonable(frames[0].msg) == case["fields"]


@pytest.mark.parametrize("case", by_kind("stream"), ids=lambda c: c["name"])
def test_stream_cases(case):
    wire = bytes.fromhex(case["wire_hex"])
    expect = case["expect"]
    for piece in (len(wire), 1, 13):
        rx = Receiver()
        frames = []
        for i in range(0, len(wire), piece):
            frames += rx.feed(wire[i : i + piece])
        assert [(f.seq, codec.TYPE_NAMES[f.msg.TYPE_ID], codec.to_jsonable(f.msg)) for f in frames] == [
            (e["seq"], e["frame_type"], e["fields"]) for e in expect["frames"]
        ]
        assert rx.bad_frames == expect["bad_frames"]
        assert rx.lost_frames == expect["lost_frames"]
        assert rx.unknown_types == expect["unknown_types"]


def test_session_start_is_zero_hello_config():
    case = next(c for c in CASES if c["name"] == "session_start")
    wire = bytes.fromhex(case["wire_hex"])
    assert wire[0] == 0
    assert wire[1:] == codec.encode_frame(vectors.HELLO, 0) + codec.encode_frame(vectors.CONFIG, 1)


def test_cobs_edge_frames_have_the_promised_structure():
    def raw(name):
        return bytes.fromhex(next(c for c in CASES if c["name"] == name)["raw_hex"])

    for run in (253, 254, 255):
        end = raw(f"cobs_frame_end_run_{run}")
        assert vectors.nonzero_runs(end)[-1] == run and end[-1] != 0
        mid = raw(f"cobs_frame_mid_run_{run}")
        assert vectors.nonzero_runs(mid)[1] == run and mid[run + 1] == 0
    assert raw("cobs_frame_last_byte_zero")[-1] == 0
    largest = raw("frame_largest")
    assert len(largest) == 4102 and len(cobs.encode(largest)) == 4119
    zeros = raw("payload_with_zero_bytes")
    assert zeros.count(0) > 20


def test_samples_survive_the_json_form():
    case = next(c for c in CASES if c["name"] == "data_adc_raw")
    msg = codec.from_jsonable(case["type_id"], case["fields"])
    assert msg.samples.dtype == np.int32 and msg.samples.shape == (4, 2)
    assert msg.first_sample == 4_294_967_300
