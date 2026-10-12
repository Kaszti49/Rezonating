"""Golden vectors for link protocol v0 (PROTOCOL.md section 8).

``python -m rezonating_lab.link.vectors --write`` regenerates ``tests/vectors/link-v0.json``;
``--check`` fails when the file differs from what this script produces. The JSON is the contract the
firmware's host-side test reads, so the output is deterministic and stable: no randomness, no dates.

Case kinds:

* ``cobs``:   ``raw_hex`` encodes to ``encoded_hex`` (no delimiter);
* ``frame``:  one frame. ``fields`` are the decoded message, ``raw_hex`` is header + payload + CRC,
              ``wire_hex`` is COBS plus the 0x00 delimiter;
* ``stream``: bytes fed to a receiver, with the frames and counters it must produce.
              A receiver must give the same result when the bytes arrive in pieces of any size.

Bytes are lowercase hex strings. Floats are IEEE binary32 values written as exact decimal doubles.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from . import cobs, codec
from .codec import (
    Ack,
    Auth,
    ChannelConfig,
    Config,
    Data,
    Err,
    Event,
    GetInfo,
    HeadInfo,
    Hello,
    Log,
    Ping,
    Pong,
    Reboot,
    SdRecord,
    Set,
    Start,
    Status,
    Stop,
    StreamConfig,
    StreamInfo,
    StreamStatus,
)
from .crc import CHECK_INPUT, CHECK_VALUE
from .receiver import Receiver

VECTORS_RELPATH = Path("tests") / "vectors" / "link-v0.json"


def default_vectors_path() -> Path:
    """tools/lab/tests/vectors/link-v0.json, found from this file (src layout)."""
    return Path(__file__).resolve().parents[3] / VECTORS_RELPATH


def f32(x: float) -> float:
    return float(np.float32(x))


def nonzero_runs(raw: bytes) -> list[int]:
    """Lengths of the maximal runs of non-zero bytes in ``raw``."""
    runs, cur = [], 0
    for b in raw:
        if b:
            cur += 1
        else:
            runs.append(cur)
            cur = 0
    runs.append(cur)
    return runs


# ---------------------------------------------------------------------------------- sample messages


def _head_json(**kw: Any) -> bytes:
    return json.dumps(kw, separators=(",", ":")).encode()


HEADS = [
    HeadInfo(
        1,
        _head_json(
            schema=0,
            type="geophone",
            model="sm24",
            serial="G-0001",
            interface="analog",
            channels=[{"axis": "z", "quantity": "velocity", "units": "m/s", "sensitivity": 28.8}],
            recommended_gain=8,
            mount="spike",
        ),
    ),
    HeadInfo(
        2,
        _head_json(
            schema=0,
            type="piezo",
            model="disc35",
            serial="PZ-0001",
            interface="analog",
            channels=[{"quantity": "strain", "units": "V", "sensitivity": 1.0}],
            recommended_gain=1,
        ),
    ),
    HeadInfo(
        3,
        _head_json(
            schema=0,
            type="accelerometer",
            model="adxl355",
            serial="A-0001",
            interface="i2c",
            i2c_address=29,
            channels=[
                {"axis": a, "quantity": "acceleration", "units": "g", "sensitivity": 256000} for a in ("x", "y", "z")
            ],
        ),
    ),
]

HELLO = Hello(
    proto=0,
    fw_version="0.1.0",
    node_id="rzn-a1b2c3",
    t_dev_us=5_123_456,
    streams=[
        StreamInfo(0, 2, 2000, 24, codec.CLOCK_LTC6903, 0, 0),
        StreamInfo(1, 2, 1000, 24, codec.CLOCK_LTC6903, 63, 31),
        StreamInfo(2, 3, 2000, 20, codec.CLOCK_ADXL355, 0, 0),
    ],
    heads=HEADS,
)

ADC_SCALE_GAIN8 = f32(1.2 / 8 / 2**23)
ACCEL_SCALE_2G = f32(1 / 256000)
CONFIG = Config(
    streams=[
        StreamConfig(0, [ChannelConfig(8, ADC_SCALE_GAIN8, codec.UNITS_V)] * 2),
        StreamConfig(1, [ChannelConfig(8, ADC_SCALE_GAIN8, codec.UNITS_V)] * 2),
        StreamConfig(2, [ChannelConfig(1, ACCEL_SCALE_2G, codec.UNITS_G)] * 3),
    ],
    accel_range_g=2,
    status_period_ms=1000,
)

STATUS = Status(
    t_dev_us=15_250_000,
    queue_fill=3,
    sd_state=1,
    sd_free_mb=14000,
    rssi_dbm=-61,
    heap_free=181_204,
    temp_c_x10=412,
    streams=[
        StreamStatus(0, 1, 20_000, 0, 2_016_000, 0, 4_000, 20_000, 0, 0),
        StreamStatus(1, 1, 10_000, 2, 1_008_000, 0, 2_000, 10_000, 2, 0),
        StreamStatus(2, 0, 4_294_967_296 + 5, 7, 1_999_500, 1, 0, 0, 0, 0),
    ],
)


def _fill_nonzero(length: int, start: int = 0) -> bytes:
    return bytes((i + start) % 255 + 1 for i in range(length))


# ------------------------------------------------------------------------------------------- builders


def _frame_case(name: str, description: str, msg: Any, seq: int) -> dict[str, Any]:
    payload = msg.to_payload()
    raw = codec.encode_raw_frame(msg.TYPE_ID, seq, payload)
    return {
        "name": name,
        "kind": "frame",
        "description": description,
        "frame_type": codec.TYPE_NAMES[msg.TYPE_ID],
        "type_id": msg.TYPE_ID,
        "seq": seq,
        "fields": codec.to_jsonable(msg),
        "raw_hex": raw.hex(),
        "wire_hex": codec.to_wire(raw).hex(),
    }


def _expect_frame(msg: Any, seq: int) -> dict[str, Any]:
    return {"seq": seq, "frame_type": codec.TYPE_NAMES[msg.TYPE_ID], "fields": codec.to_jsonable(msg)}


def _stream_case(
    name: str,
    description: str,
    wire: bytes,
    frames: list[tuple[Any, int]],
    bad_frames: int = 0,
    lost_frames: int = 0,
    unknown_types: int = 0,
) -> dict[str, Any]:
    """A byte stream and what a receiver must make of it. The generator checks its own claim."""
    rx = Receiver()
    got = rx.feed(wire)
    assert [(f.msg, f.seq) for f in got] == frames, f"{name}: receiver gave {got}"
    assert (rx.bad_frames, rx.lost_frames, rx.unknown_types) == (bad_frames, lost_frames, unknown_types), (
        f"{name}: counters {(rx.bad_frames, rx.lost_frames, rx.unknown_types)}"
    )
    return {
        "name": name,
        "kind": "stream",
        "description": description,
        "wire_hex": wire.hex(),
        "expect": {
            "frames": [_expect_frame(m, s) for m, s in frames],
            "bad_frames": bad_frames,
            "lost_frames": lost_frames,
            "unknown_types": unknown_types,
        },
    }


def _cobs_case(name: str, description: str, raw: bytes) -> dict[str, Any]:
    enc = cobs.encode(raw)
    assert cobs.decode(enc) == raw
    return {"name": name, "kind": "cobs", "description": description, "raw_hex": raw.hex(), "encoded_hex": enc.hex()}


def _log_with_end_run(run: int) -> Log:
    """A LOG frame whose raw bytes end in a run of exactly ``run`` non-zero bytes (msg + 2 CRC bytes)."""
    msg_len = run - 2
    assert 0 < msg_len < 256  # the u16 length then has a 0x00 high byte, which starts the run
    seq = 0x0101
    for tweak in range(26):
        msg = Log(3, 0x0102030405060708, "t", "A" * (msg_len - 1) + chr(ord("A") + tweak))
        raw = codec.encode_raw_frame(msg.TYPE_ID, seq, msg.to_payload())
        if raw[-1] and raw[-2] and nonzero_runs(raw)[-1] == run:
            return msg
    raise AssertionError("no LOG frame with the wanted end run")


def _event_with_mid_run(run: int) -> Event:
    """An EVENT frame whose first non-zero run (after the leading ver byte) is ``run`` bytes, then 0x00."""
    # run = type 1 + seq 2 + stream 1 + sample 8 + kind 1 + two str8 length bytes 2 + pack P + key K = 15 + P + K
    pack_len = 100
    key_len = run - 15 - pack_len
    msg = Event(1, 0x0102030405060708, 1, "p" * pack_len, "k" * key_len, None, "")
    raw = codec.encode_raw_frame(msg.TYPE_ID, 0x0101, msg.to_payload())
    assert nonzero_runs(raw)[1] == run and raw[1 + run] == 0, nonzero_runs(raw)[:3]
    return msg


def _ping_ending_in_zero() -> tuple[Ping, int]:
    for host_t in range(1, 100000):
        msg = Ping(0x0A0B0C0D0E0F + host_t)
        raw = codec.encode_raw_frame(msg.TYPE_ID, 0x0101, msg.to_payload())
        if raw[-1] == 0 and raw[-2] != 0:
            return msg, 0x0101
    raise AssertionError("no PING whose CRC ends in 0x00")


def _largest_set() -> Set:
    """Largest legal frame: payload 4096 B, raw 4102 B, no zero except the ver byte -> 4119 B encoded."""
    key = "pair.key"
    blob_len = 4096 - (1 + len(key)) - 1 - 2
    for tweak in range(255):
        msg = Set(key, _fill_nonzero(blob_len, tweak))
        raw = codec.encode_raw_frame(msg.TYPE_ID, 0x0101, msg.to_payload())
        if raw[-1] and raw[-2]:
            assert len(raw) == codec.MAX_RAW_LEN and len(cobs.encode(raw)) == codec.MAX_ENCODED_LEN
            return msg
    raise AssertionError("no largest SET frame without a zero CRC byte")


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    # COBS on its own -------------------------------------------------------------------------------
    cases += [
        _cobs_case("cobs_single_zero", "one 0x00 byte", b"\x00"),
        _cobs_case("cobs_ends_in_zero", "ends in 0x00: final empty block written as 01", b"\x01\x00"),
        _cobs_case("cobs_zero_in_middle", "a zero between two non-zero runs", b"\x11\x22\x00\x33"),
        _cobs_case("cobs_leading_zero", "frames always start with the ver byte 0x00", b"\x00\x05\x01\x01"),
        _cobs_case("cobs_run_253", "253 non-zero bytes", b"\x01" * 253),
        _cobs_case("cobs_run_254_end", "254 non-zero bytes: no extra code byte after the final full block", b"\x01" * 254),
        _cobs_case("cobs_run_255", "255 non-zero bytes: one full block and a block of 1", b"\x01" * 255),
        _cobs_case("cobs_run_254_zero", "254 non-zero bytes then 0x00: FF block, then an empty block", b"\x01" * 254 + b"\x00"),
        _cobs_case("cobs_run_254_zero_more", "254 non-zero bytes, 0x00, one more byte", b"\x01" * 254 + b"\x00\x02"),
        _cobs_case("cobs_run_508", "two full blocks", b"\x01" * 508),
        _cobs_case("cobs_run_509", "two full blocks and a block of 1", b"\x01" * 509),
        _cobs_case("cobs_worst_case", "4102 bytes: ver byte, then 4101 non-zero -> 4119 bytes", b"\x00" + b"\x01" * 4101),
    ]  # fmt: skip

    # Every frame type ------------------------------------------------------------------------------
    cases += [
        _frame_case("hello", "HELLO with three streams and three heads", HELLO, 0),
        _frame_case("config", "CONFIG: gain 8 on both ADC channels, accel +-2 g", CONFIG, 1),
        _frame_case(
            "data_adc_raw",
            "DATA adc_raw: 4 frames x 2 channels, negative codes, index above 2^32",
            Data(0, 4_294_967_300, 5_100_000, np.array([[0, -1], [8388607, -8388608], [1000, -1000], [0, 0]], np.int32)),
            2,
        ),
        _frame_case(
            "data_adc_dec",
            "DATA adc_dec: 3 frames x 2 channels",
            Data(1, 2000, 5_100_500, np.array([[12, -12], [1 << 20, -(1 << 20)], [0, 7]], np.int32)),
            3,
        ),
        _frame_case(
            "data_accel",
            "DATA accel: 3 frames x 3 channels, 20-bit values around 1 g on z",
            Data(2, 7, 5_100_250, np.array([[5, -3, 256000], [6, -2, 255990], [-524288, 524287, 256010]], np.int32)),
            4,
        ),
        _frame_case("status", "STATUS with three streams, one above 2^32 indices", STATUS, 5),
        _frame_case(
            "event_trigger",
            "EVENT: bare trigger, no value (quiet NaN on the wire)",
            Event(0, 123456, codec.EVENT_TRIGGER, "", "", None, ""),
            6,
        ),
        _frame_case(
            "event_pack_output",
            "EVENT: pack output with a score and a label",
            Event(1, 123456, codec.EVENT_PACK_OUTPUT, "footstep-id", "person", 0.8125, "P2"),
            7,
        ),
        _frame_case("log", "LOG info line", Log(3, 5_200_000, "link", "session started"), 8),
        _frame_case("ack", "ACK of command seq 300", Ack(300), 9),
        _frame_case("err", "ERR busy", Err(301, codec.ERR_BUSY, "acquisition running"), 10),
        _frame_case("pong", "PONG echoing host_t_us", Pong(1_700_000_000_123_456, 5_300_000), 11),
        _frame_case("get_info", "GET_INFO, empty payload", GetInfo(), 0),
        _frame_case("start", "START all three streams", Start(0b111), 1),
        _frame_case("stop", "STOP adc_raw and adc_dec", Stop(0b011), 2),
        _frame_case("set_i32", "SET adc.gain.0 = 8 (i32)", Set("adc.gain.0", 8), 3),
        _frame_case("set_f32", "SET with an f32 value", Set("test.float", 0.25), 4),
        _frame_case("set_str8", "SET wifi.ssid (str8)", Set("wifi.ssid", "lab-net"), 5),
        _frame_case("set_blob16", "SET pair.key (blob16, 16 bytes)", Set("pair.key", bytes(range(16))), 6),
        _frame_case("sd_record", "SD_RECORD start for adc_raw and accel", SdRecord(1, 0b101, "s-2026-10-13-a"), 7),
        _frame_case("ping", "PING with a host clock value", Ping(1_700_000_000_123_456), 8),
        _frame_case("reboot", "REBOOT, empty payload", Reboot(), 9),
        _frame_case("auth", "AUTH: blob16 of length 16 (wire 10 00 + key)", Auth(bytes(range(0xA0, 0xB0))), 0),
    ]  # fmt: skip

    # COBS edge cases at frame level ------------------------------------------------------------------
    for run in (253, 254, 255):
        msg = _log_with_end_run(run)
        note = " (the 254-byte run that ends exactly at the end of the frame)" if run == 254 else ""
        cases.append(
            _frame_case(
                f"cobs_frame_end_run_{run}",
                f"LOG frame whose raw bytes end in a run of exactly {run} non-zero bytes{note}",
                msg,
                0x0101,
            )
        )
    for run in (253, 254, 255):
        msg = _event_with_mid_run(run)
        note = " (a 254-byte run followed by 0x00)" if run == 254 else ""
        cases.append(
            _frame_case(
                f"cobs_frame_mid_run_{run}",
                f"EVENT frame with a run of exactly {run} non-zero bytes after the ver byte, then 0x00{note}",
                msg,
                0x0101,
            )
        )
    ping0, seq0 = _ping_ending_in_zero()
    cases.append(
        _frame_case("cobs_frame_last_byte_zero", "PING whose CRC high byte, the last raw byte, is 0x00", ping0, seq0)
    )
    cases.append(
        _frame_case(
            "frame_largest",
            "largest legal frame: payload 4096 B, raw 4102 B, 4119 B encoded plus the delimiter",
            _largest_set(),
            0x0101,
        )
    )
    cases.append(
        _frame_case("payload_with_zero_bytes", "DATA payload full of 0x00 bytes", Data(0, 0, 0, np.zeros((2, 2), np.int32)), 0)
    )  # fmt: skip

    # Streams ----------------------------------------------------------------------------------------
    hello_wire = codec.encode_frame(HELLO, 0)
    config_wire = codec.encode_frame(CONFIG, 1)
    cases.append(
        _stream_case(
            "session_start",
            "what the node writes at session start: 00, HELLO seq 0, CONFIG seq 1",
            b"\x00" + hello_wire + config_wire,
            [(HELLO, 0), (CONFIG, 1)],
        )
    )
    boot = (
        b"ESP-ROM:esp32s3-20210327\r\nBuild:Mar 27 2021\r\n"
        b"rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\nSPIWP:0xee\r\n"
    )
    cases.append(
        _stream_case(
            "boot_text_then_hello",
            "boot text, the session-start 0x00, then HELLO: the text costs one bad frame",
            boot + b"\x00" + hello_wire,
            [(HELLO, 0)],
            bad_frames=1,
        )
    )
    ping_raw = codec.encode_raw_frame(Ping.TYPE_ID, 0, Ping(42).to_payload())
    bad_crc_raw = ping_raw[:-1] + bytes([ping_raw[-1] ^ 0x01])
    cases.append(
        _stream_case(
            "corrupted_crc",
            "a frame with one CRC bit flipped is dropped and counted",
            codec.to_wire(bad_crc_raw),
            [],
            bad_frames=1,
        )
    )
    ack0, ack1, ack2 = Ack(10), Ack(11), Ack(12)
    cases.append(
        _stream_case(
            "resync_after_garbage",
            "garbage between two frames costs one bad frame, the next frame is decoded",
            codec.encode_frame(ack0, 0) + b"\x12\x34\x56\x00" + codec.encode_frame(ack1, 1),
            [(ack0, 0), (ack1, 1)],
            bad_frames=1,
        )
    )
    cases.append(
        _stream_case(
            "extra_delimiters",
            "extra 0x00 bytes between frames are ignored",
            b"\x00\x00" + codec.encode_frame(ack0, 0) + b"\x00\x00\x00" + codec.encode_frame(ack1, 1) + b"\x00",
            [(ack0, 0), (ack1, 1)],
        )
    )
    cases.append(
        _stream_case(
            "seq_jump",
            "seq 0, 1, 5: three frames were lost",
            codec.encode_frame(ack0, 0) + codec.encode_frame(ack1, 1) + codec.encode_frame(ack2, 5),
            [(ack0, 0), (ack1, 1), (ack2, 5)],
            lost_frames=3,
        )
    )
    cases.append(
        _stream_case(
            "seq_wraps",
            "seq 65534, 65535, 0 is no loss",
            codec.encode_frame(ack0, 65534) + codec.encode_frame(ack1, 65535) + codec.encode_frame(ack2, 0),
            [(ack0, 65534), (ack1, 65535), (ack2, 0)],
        )
    )
    cases.append(
        _stream_case(
            "hello_resets_seq",
            "HELLO restarts the expected seq: ACK 7, ACK 8, HELLO 0, CONFIG 1 is no loss",
            codec.encode_frame(ack0, 7) + codec.encode_frame(ack1, 8) + hello_wire + config_wire,
            [(ack0, 7), (ack1, 8), (HELLO, 0), (CONFIG, 1)],
        )
    )
    unknown_raw = codec.encode_raw_frame(0x55, 1, b"abc")
    cases.append(
        _stream_case(
            "unknown_type",
            "a valid frame of an unknown node-to-PC type is counted, not delivered; its seq still counts",
            codec.encode_frame(ack0, 0) + codec.to_wire(unknown_raw) + codec.encode_frame(ack2, 2),
            [(ack0, 0), (ack2, 2)],
            unknown_types=1,
        )
    )
    trailing_raw = codec.encode_raw_frame(Ack.TYPE_ID, 0, Ack(77).to_payload() + b"\xde\xad\xbe")
    cases.append(
        _stream_case(
            "trailing_payload_bytes",
            "bytes after the known fields are ignored (forward compatibility)",
            codec.to_wire(trailing_raw),
            [(Ack(77), 0)],
        )
    )
    cases.append(
        _stream_case(
            "oversize_without_delimiter",
            "4120 bytes without a 0x00 are discarded as one bad frame; the next frame is decoded",
            b"A" * 4120 + b"\x00" + codec.encode_frame(ack0, 0),
            [(ack0, 0)],
            bad_frames=1,
        )
    )
    cases.append(
        _stream_case(
            "oversize_4121_without_delimiter",
            "4121 bytes without a 0x00: still one bad frame; everything up to and including the next 0x00 is swallowed",
            b"A" * 4121 + b"\x00" + codec.encode_frame(ack0, 0),
            [(ack0, 0)],
            bad_frames=1,
        )
    )
    return cases


def build_document() -> dict[str, Any]:
    return {
        "protocol": "rezonating-link",
        "version": 0,
        "about": "Golden vectors for tools/lab/PROTOCOL.md. Generated by 'python -m rezonating_lab.link.vectors "
        "--write'; do not edit by hand. See the module docstring for the case kinds.",
        "crc16": {"input_ascii": CHECK_INPUT.decode(), "crc_hex": f"{CHECK_VALUE:04x}"},
        "limits": {
            "max_payload": codec.MAX_PAYLOAD,
            "max_raw_frame": codec.MAX_RAW_LEN,
            "max_encoded_frame": codec.MAX_ENCODED_LEN,
        },
        "cases": build_cases(),
    }


# -------------------------------------------------------------------------------------- JSON output


def _is_scalar(x: Any) -> bool:
    return x is None or isinstance(x, (bool, int, float, str))


def _inline(x: Any) -> bool:
    return isinstance(x, list) and all(
        _is_scalar(e) or (isinstance(e, list) and all(_is_scalar(s) for s in e)) for e in x
    )


def dumps(obj: Any, indent: int = 0) -> str:
    """Stable, readable JSON: objects one key per line, arrays of numbers on one line."""
    pad = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items = [f"{pad}  {json.dumps(k)}: {dumps(v, indent + 1)}" for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(obj, list):
        if not obj:
            return "[]"
        if _inline(obj):
            return json.dumps(obj, separators=(", ", ": "), ensure_ascii=False)
        items = [f"{pad}  {dumps(v, indent + 1)}" for v in obj]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(obj, ensure_ascii=False)


def render() -> str:
    return dumps(build_document()) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rezonating_lab.link.vectors", description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help="write the vectors file")
    ap.add_argument("--check", action="store_true", help="exit 1 if the file differs from the generated vectors")
    ap.add_argument(
        "--out", type=Path, default=None, help="vectors file (default tools/lab/tests/vectors/link-v0.json)"
    )
    args = ap.parse_args(argv)
    path = args.out or default_vectors_path()
    text = render()
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path} ({len(text)} bytes, {len(json.loads(text)['cases'])} cases)")
        return 0
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print(f"{path} is out of date: run with --write", file=sys.stderr)
            return 1
        print(f"{path} is up to date")
        return 0
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
