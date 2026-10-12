"""Typed encode/decode of every frame in PROTOCOL.md sections 2 to 5.

Everything is little-endian. A message is a dataclass with ``TYPE_ID``, ``to_payload()`` and
``from_payload()``. ``encode_frame(msg, seq)`` returns the wire bytes (COBS plus the 0x00 delimiter).
Receivers ignore payload bytes after the fields they know (forward compatibility), so
``from_payload`` never checks for trailing bytes.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, ClassVar, get_args, get_origin, get_type_hints

import numpy as np

from . import cobs
from .crc import crc16_ccitt_false

VER = 0
HEADER_LEN = 4
CRC_LEN = 2
MIN_RAW_LEN = HEADER_LEN + CRC_LEN
MAX_PAYLOAD = 4096
MAX_RAW_LEN = HEADER_LEN + MAX_PAYLOAD + CRC_LEN  # 4102
MAX_ENCODED_LEN = MAX_RAW_LEN + -(-MAX_RAW_LEN // 254)  # 4119, without the delimiter
NAN_F32_BYTES = b"\x00\x00\xc0\x7f"  # quiet NaN 0x7FC00000, "no value"

STREAM_ADC_RAW = 0
STREAM_ADC_DEC = 1
STREAM_ACCEL = 2
STREAM_NAMES = {STREAM_ADC_RAW: "adc_raw", STREAM_ADC_DEC: "adc_dec", STREAM_ACCEL: "accel"}

CLOCK_LTC6903 = 0
CLOCK_ADXL355 = 1
CLOCK_CRYSTAL = 2

UNITS_COUNTS = 0
UNITS_V = 1
UNITS_G = 2

ERR_UNKNOWN_COMMAND = 1
ERR_BAD_PAYLOAD = 2
ERR_UNKNOWN_KEY = 3
ERR_BAD_VALUE = 4
ERR_BUSY = 5
ERR_NOT_AUTHORISED = 6
ERR_SD = 7


class CodecError(ValueError):
    """A payload is shorter than its known fields, or a value cannot be encoded."""


class UnknownTypeError(CodecError):
    """The frame type is not in the table for this direction."""


class FrameError(ValueError):
    """A wire chunk is not a valid frame (COBS, length, CRC or version). Counts as one bad frame."""


# ---------------------------------------------------------------- primitive readers and writers


class _Reader:
    def __init__(self, buf: bytes) -> None:
        self.buf = buf
        self.pos = 0

    def take(self, n: int) -> bytes:
        end = self.pos + n
        if end > len(self.buf):
            raise CodecError(f"payload too short: need {n} bytes at offset {self.pos}, have {len(self.buf)} in total")
        out = self.buf[self.pos : end]
        self.pos = end
        return out

    def unpack(self, fmt: str) -> Any:
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def u8(self) -> int:
        return self.unpack("<B")

    def u16(self) -> int:
        return self.unpack("<H")

    def u32(self) -> int:
        return self.unpack("<I")

    def u64(self) -> int:
        return self.unpack("<Q")

    def i8(self) -> int:
        return self.unpack("<b")

    def i16(self) -> int:
        return self.unpack("<h")

    def i32(self) -> int:
        return self.unpack("<i")

    def f32(self) -> float:
        return self.unpack("<f")

    def str8(self) -> str:
        return self.take(self.u8()).decode("utf-8", errors="replace")

    def str16(self) -> str:
        return self.take(self.u16()).decode("utf-8", errors="replace")

    def blob16(self) -> bytes:
        return self.take(self.u16())


def truncate_utf8(text: str, max_bytes: int) -> bytes:
    """UTF-8 bytes of ``text``, cut to at most ``max_bytes`` on a code point boundary."""
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return data
    cut = max_bytes
    while cut > 0 and (data[cut] & 0xC0) == 0x80:
        cut -= 1
    return data[:cut]


class _Writer:
    def __init__(self) -> None:
        self.buf = bytearray()

    def pack(self, fmt: str, *values: Any) -> _Writer:
        try:
            self.buf += struct.pack(fmt, *values)
        except (struct.error, OverflowError) as exc:
            raise CodecError(f"cannot encode {values!r} as {fmt}: {exc}") from exc
        return self

    def u8(self, v: int) -> _Writer:
        return self.pack("<B", v)

    def u16(self, v: int) -> _Writer:
        return self.pack("<H", v)

    def u32(self, v: int) -> _Writer:
        return self.pack("<I", v)

    def u64(self, v: int) -> _Writer:
        return self.pack("<Q", v)

    def i8(self, v: int) -> _Writer:
        return self.pack("<b", v)

    def i16(self, v: int) -> _Writer:
        return self.pack("<h", v)

    def i32(self, v: int) -> _Writer:
        return self.pack("<i", v)

    def f32(self, v: float) -> _Writer:
        return self.pack("<f", v)

    def str8(self, s: str) -> _Writer:
        data = truncate_utf8(s, 255)
        self.u8(len(data))
        self.buf += data
        return self

    def str16(self, s: str, max_bytes: int = 65535) -> _Writer:
        data = truncate_utf8(s, max_bytes)
        self.u16(len(data))
        self.buf += data
        return self

    def blob16(self, b: bytes) -> _Writer:
        if len(b) > 65535:
            raise CodecError("blob16 longer than 65535 bytes")
        self.u16(len(b))
        self.buf += b
        return self

    def raw(self, b: bytes) -> _Writer:
        self.buf += b
        return self

    def done(self) -> bytes:
        return bytes(self.buf)


# ---------------------------------------------------------------------- node to PC messages


@dataclass
class StreamInfo:
    """One stream in HELLO. ``fir_taps`` and ``fir_delay`` are 0 except for ``adc_dec``."""

    id: int
    n_ch: int
    nominal_hz: int
    bits: int
    clock: int
    fir_taps: int = 0
    fir_delay: int = 0


@dataclass
class HeadInfo:
    port: int
    descriptor: bytes  # minified UTF-8 JSON, at most 900 B


@dataclass
class Hello:
    TYPE_ID: ClassVar[int] = 0x01
    proto: int
    fw_version: str
    node_id: str
    t_dev_us: int
    streams: list[StreamInfo] = field(default_factory=list)
    heads: list[HeadInfo] = field(default_factory=list)

    def to_payload(self) -> bytes:
        w = _Writer().u8(self.proto).str8(self.fw_version).str8(self.node_id).u64(self.t_dev_us)
        w.u8(len(self.streams))
        for s in self.streams:
            w.u8(s.id).u8(s.n_ch).u32(s.nominal_hz).u8(s.bits).u8(s.clock).u16(s.fir_taps).u16(s.fir_delay)
        w.u8(len(self.heads))
        for h in self.heads:
            if len(h.descriptor) > 900:
                raise CodecError("head descriptor longer than 900 B")
            w.u8(h.port).blob16(h.descriptor)
        return w.done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Hello:
        r = _Reader(payload)
        proto, fw, node, t = r.u8(), r.str8(), r.str8(), r.u64()
        streams = [StreamInfo(r.u8(), r.u8(), r.u32(), r.u8(), r.u8(), r.u16(), r.u16()) for _ in range(r.u8())]
        heads = [HeadInfo(r.u8(), r.blob16()) for _ in range(r.u8())]
        return cls(proto, fw, node, t, streams, heads)


@dataclass
class ChannelConfig:
    gain: int
    scale: float  # f32; multiplies a code to get ``units``
    units: int


@dataclass
class StreamConfig:
    id: int
    channels: list[ChannelConfig]


@dataclass
class Config:
    TYPE_ID: ClassVar[int] = 0x09
    streams: list[StreamConfig]
    accel_range_g: int
    status_period_ms: int

    def to_payload(self) -> bytes:
        w = _Writer().u8(len(self.streams))
        for s in self.streams:
            w.u8(s.id).u8(len(s.channels))
            for c in s.channels:
                w.u8(c.gain).f32(c.scale).u8(c.units)
        w.u8(self.accel_range_g).u16(self.status_period_ms)
        return w.done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Config:
        r = _Reader(payload)
        streams = []
        for _ in range(r.u8()):
            sid = r.u8()
            channels = [ChannelConfig(r.u8(), r.f32(), r.u8()) for _ in range(r.u8())]
            streams.append(StreamConfig(sid, channels))
        return cls(streams, r.u8(), r.u16())


@dataclass(eq=False)
class Data:
    """Sample frames of one stream. ``samples`` is (n, n_ch) int32, frame-major."""

    TYPE_ID: ClassVar[int] = 0x02
    stream: int
    first_sample: int
    t_dev_us: int
    samples: np.ndarray

    @property
    def n(self) -> int:
        return int(self.samples.shape[0])

    @property
    def n_ch(self) -> int:
        return int(self.samples.shape[1])

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Data)
            and self.stream == other.stream
            and self.first_sample == other.first_sample
            and self.t_dev_us == other.t_dev_us
            and self.samples.shape == other.samples.shape
            and bool(np.array_equal(self.samples, other.samples))
        )

    def to_payload(self) -> bytes:
        samples = np.asarray(self.samples)
        if samples.ndim != 2 or samples.shape[0] < 1 or samples.shape[1] < 1:
            raise CodecError("DATA needs a (n >= 1, n_ch >= 1) sample array")
        w = _Writer().u8(self.stream).u8(samples.shape[1]).u16(samples.shape[0])
        w.u64(self.first_sample).u64(self.t_dev_us)
        w.raw(np.ascontiguousarray(samples, dtype="<i4").tobytes())
        return w.done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Data:
        r = _Reader(payload)
        stream, n_ch, n = r.u8(), r.u8(), r.u16()
        first, t = r.u64(), r.u64()
        if n < 1 or n_ch < 1:
            raise CodecError("DATA with n = 0 or n_ch = 0")
        body = r.take(4 * n * n_ch)
        samples = np.frombuffer(body, dtype="<i4").astype(np.int32).reshape(n, n_ch)
        return cls(stream, first, t, samples)


@dataclass
class StreamStatus:
    id: int
    running: int
    produced: int
    device_dropped: int
    rate_mhz: int
    clipped: int
    win_first: int
    win_end: int
    win_device: int
    win_link: int


@dataclass
class Status:
    TYPE_ID: ClassVar[int] = 0x03
    t_dev_us: int
    queue_fill: int
    sd_state: int
    sd_free_mb: int
    rssi_dbm: int
    heap_free: int
    temp_c_x10: int
    streams: list[StreamStatus] = field(default_factory=list)

    def to_payload(self) -> bytes:
        w = _Writer().u64(self.t_dev_us).u8(self.queue_fill).u8(self.sd_state).u32(self.sd_free_mb)
        w.i8(self.rssi_dbm).u32(self.heap_free).i16(self.temp_c_x10).u8(len(self.streams))
        for s in self.streams:
            w.u8(s.id).u8(s.running).u64(s.produced).u64(s.device_dropped).u32(s.rate_mhz).u32(s.clipped)
            w.u64(s.win_first).u64(s.win_end).u64(s.win_device).u64(s.win_link)
        return w.done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Status:
        r = _Reader(payload)
        t, qf, sd, free, rssi, heap, temp = r.u64(), r.u8(), r.u8(), r.u32(), r.i8(), r.u32(), r.i16()
        streams = [
            StreamStatus(r.u8(), r.u8(), r.u64(), r.u64(), r.u32(), r.u32(), r.u64(), r.u64(), r.u64(), r.u64())
            for _ in range(r.u8())
        ]
        return cls(t, qf, sd, free, rssi, heap, temp, streams)

    def stream(self, stream_id: int) -> StreamStatus | None:
        for s in self.streams:
            if s.id == stream_id:
                return s
        return None


EVENT_TRIGGER = 0
EVENT_PACK_OUTPUT = 1


@dataclass
class Event:
    TYPE_ID: ClassVar[int] = 0x04
    stream: int
    sample: int
    kind: int
    pack: str
    key: str
    value: float | None  # None is the quiet NaN 0x7FC00000
    label: str

    def to_payload(self) -> bytes:
        w = _Writer().u8(self.stream).u64(self.sample).u8(self.kind).str8(self.pack).str8(self.key)
        if self.value is None or (isinstance(self.value, float) and math.isnan(self.value)):
            w.raw(NAN_F32_BYTES)
        else:
            w.f32(self.value)
        return w.str8(self.label).done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Event:
        r = _Reader(payload)
        stream, sample, kind, pack, key = r.u8(), r.u64(), r.u8(), r.str8(), r.str8()
        value = r.f32()
        return cls(stream, sample, kind, pack, key, None if math.isnan(value) else value, r.str8())


@dataclass
class Log:
    TYPE_ID: ClassVar[int] = 0x05
    level: int
    t_dev_us: int
    tag: str
    msg: str

    def to_payload(self) -> bytes:
        return _Writer().u8(self.level).u64(self.t_dev_us).str8(self.tag).str16(self.msg, 1024).done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Log:
        r = _Reader(payload)
        return cls(r.u8(), r.u64(), r.str8(), r.str16())


@dataclass
class Ack:
    TYPE_ID: ClassVar[int] = 0x06
    cmd_seq: int

    def to_payload(self) -> bytes:
        return _Writer().u16(self.cmd_seq).done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Ack:
        return cls(_Reader(payload).u16())


@dataclass
class Err:
    TYPE_ID: ClassVar[int] = 0x07
    cmd_seq: int
    code: int
    msg: str = ""

    def to_payload(self) -> bytes:
        return _Writer().u16(self.cmd_seq).u16(self.code).str8(self.msg).done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Err:
        r = _Reader(payload)
        return cls(r.u16(), r.u16(), r.str8())


@dataclass
class Pong:
    TYPE_ID: ClassVar[int] = 0x08
    host_t_us: int
    t_dev_us: int

    def to_payload(self) -> bytes:
        return _Writer().u64(self.host_t_us).u64(self.t_dev_us).done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Pong:
        r = _Reader(payload)
        return cls(r.u64(), r.u64())


# ---------------------------------------------------------------------- PC to node messages


@dataclass
class GetInfo:
    TYPE_ID: ClassVar[int] = 0x81

    def to_payload(self) -> bytes:
        return b""

    @classmethod
    def from_payload(cls, payload: bytes) -> GetInfo:
        return cls()


@dataclass
class Start:
    TYPE_ID: ClassVar[int] = 0x82
    stream_mask: int

    def to_payload(self) -> bytes:
        return _Writer().u8(self.stream_mask).done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Start:
        return cls(_Reader(payload).u8())


@dataclass
class Stop:
    TYPE_ID: ClassVar[int] = 0x83
    stream_mask: int

    def to_payload(self) -> bytes:
        return _Writer().u8(self.stream_mask).done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Stop:
        return cls(_Reader(payload).u8())


SET_I32 = 0
SET_F32 = 1
SET_STR8 = 2
SET_BLOB16 = 3
SET_TYPE_NAMES = {SET_I32: "i32", SET_F32: "f32", SET_STR8: "str8", SET_BLOB16: "blob16"}


@dataclass
class Set:
    """SET key = value. The wire type follows the Python type: int i32, float f32, str str8, bytes blob16."""

    TYPE_ID: ClassVar[int] = 0x84
    key: str
    value: int | float | str | bytes

    @property
    def value_type(self) -> int:
        if isinstance(self.value, bytes):
            return SET_BLOB16
        if isinstance(self.value, str):
            return SET_STR8
        if isinstance(self.value, float):
            return SET_F32
        if isinstance(self.value, int) and not isinstance(self.value, bool):
            return SET_I32
        raise CodecError(f"unsupported SET value {self.value!r}")

    def to_payload(self) -> bytes:
        w = _Writer().str8(self.key).u8(self.value_type)
        t = self.value_type
        if t == SET_I32:
            w.i32(self.value)  # type: ignore[arg-type]
        elif t == SET_F32:
            w.f32(self.value)  # type: ignore[arg-type]
        elif t == SET_STR8:
            w.str8(self.value)  # type: ignore[arg-type]
        else:
            w.blob16(self.value)  # type: ignore[arg-type]
        return w.done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Set:
        r = _Reader(payload)
        key, t = r.str8(), r.u8()
        if t == SET_I32:
            return cls(key, r.i32())
        if t == SET_F32:
            return cls(key, r.f32())
        if t == SET_STR8:
            return cls(key, r.str8())
        if t == SET_BLOB16:
            return cls(key, r.blob16())
        raise CodecError(f"unknown SET value type {t}")


@dataclass
class SdRecord:
    TYPE_ID: ClassVar[int] = 0x85
    action: int  # 0 stop, 1 start
    stream_mask: int
    session: str

    def to_payload(self) -> bytes:
        return _Writer().u8(self.action).u8(self.stream_mask).str8(self.session).done()

    @classmethod
    def from_payload(cls, payload: bytes) -> SdRecord:
        r = _Reader(payload)
        return cls(r.u8(), r.u8(), r.str8())


@dataclass
class Ping:
    TYPE_ID: ClassVar[int] = 0x86
    host_t_us: int

    def to_payload(self) -> bytes:
        return _Writer().u64(self.host_t_us).done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Ping:
        return cls(_Reader(payload).u64())


@dataclass
class Reboot:
    TYPE_ID: ClassVar[int] = 0x87

    def to_payload(self) -> bytes:
        return b""

    @classmethod
    def from_payload(cls, payload: bytes) -> Reboot:
        return cls()


@dataclass
class Auth:
    TYPE_ID: ClassVar[int] = 0x88
    key: bytes  # 16 bytes

    def to_payload(self) -> bytes:
        if len(self.key) != 16:
            raise CodecError("AUTH key must be 16 bytes")
        return _Writer().blob16(self.key).done()

    @classmethod
    def from_payload(cls, payload: bytes) -> Auth:
        return cls(_Reader(payload).blob16())


NODE_TO_PC: dict[int, type] = {c.TYPE_ID: c for c in (Hello, Data, Status, Event, Log, Ack, Err, Pong, Config)}
PC_TO_NODE: dict[int, type] = {c.TYPE_ID: c for c in (GetInfo, Start, Stop, Set, SdRecord, Ping, Reboot, Auth)}
ALL_TYPES: dict[int, type] = {**NODE_TO_PC, **PC_TO_NODE}
TYPE_NAMES: dict[int, str] = {
    0x01: "HELLO", 0x02: "DATA", 0x03: "STATUS", 0x04: "EVENT", 0x05: "LOG", 0x06: "ACK", 0x07: "ERR",
    0x08: "PONG", 0x09: "CONFIG", 0x81: "GET_INFO", 0x82: "START", 0x83: "STOP", 0x84: "SET",
    0x85: "SD_RECORD", 0x86: "PING", 0x87: "REBOOT", 0x88: "AUTH",
}  # fmt: skip
TYPE_IDS = {name: tid for tid, name in TYPE_NAMES.items()}


@dataclass
class Frame:
    seq: int
    msg: Any  # one of the message dataclasses above


# ------------------------------------------------------------------------------------ framing


def encode_raw_frame(type_id: int, seq: int, payload: bytes) -> bytes:
    """Header + payload + CRC, before COBS."""
    if len(payload) > MAX_PAYLOAD:
        raise CodecError(f"payload of {len(payload)} B exceeds {MAX_PAYLOAD} B")
    try:
        body = struct.pack("<BBH", VER, type_id, seq) + payload
    except struct.error as exc:
        raise CodecError(f"bad frame header: {exc}") from exc
    return body + struct.pack("<H", crc16_ccitt_false(body))


def to_wire(raw: bytes) -> bytes:
    """COBS-encode a raw frame and append the 0x00 delimiter."""
    return cobs.encode(raw) + b"\x00"


def encode_frame(msg: Any, seq: int) -> bytes:
    """Wire bytes of one frame, including the trailing 0x00."""
    return to_wire(encode_raw_frame(msg.TYPE_ID, seq, msg.to_payload()))


def decode_raw_frame(raw: bytes) -> tuple[int, int, bytes]:
    """Check length, version and CRC of a decoded frame; return (type, seq, payload)."""
    if len(raw) < MIN_RAW_LEN:
        raise FrameError(f"decoded length {len(raw)} is under {MIN_RAW_LEN}")
    if len(raw) > MAX_RAW_LEN:
        raise FrameError(f"decoded length {len(raw)} is over {MAX_RAW_LEN}")
    body, crc_bytes = raw[:-CRC_LEN], raw[-CRC_LEN:]
    if struct.unpack("<H", crc_bytes)[0] != crc16_ccitt_false(body):
        raise FrameError("CRC mismatch")
    ver, type_id, seq = struct.unpack("<BBH", body[:HEADER_LEN])
    if ver != VER:
        raise FrameError(f"unsupported ver {ver}")
    return type_id, seq, body[HEADER_LEN:]


def decode_chunk(chunk: bytes) -> tuple[int, int, bytes]:
    """Decode one chunk between delimiters into (type, seq, payload). Raises :class:`FrameError`."""
    try:
        raw = cobs.decode(chunk)
    except cobs.CobsError as exc:
        raise FrameError(f"COBS: {exc}") from exc
    return decode_raw_frame(raw)


def parse_payload(type_id: int, payload: bytes, table: dict[int, type] | None = None) -> Any:
    """Typed message from a payload. ``table`` limits the accepted types to one direction."""
    cls = (table if table is not None else ALL_TYPES).get(type_id)
    if cls is None:
        raise UnknownTypeError(f"unknown frame type 0x{type_id:02X}")
    return cls.from_payload(payload)


def decode_frame(wire: bytes, table: dict[int, type] | None = None) -> Frame:
    """Decode one complete wire frame (delimiter optional) into a typed :class:`Frame`."""
    chunk = wire[:-1] if wire.endswith(b"\x00") else wire
    type_id, seq, payload = decode_chunk(chunk)
    return Frame(seq, parse_payload(type_id, payload, table))


# ------------------------------------------------------------- JSON form (golden vectors)


def to_jsonable(obj: Any) -> Any:
    """Plain-JSON form of a message: bytes as hex strings, NaN-less floats, arrays as nested lists."""
    if isinstance(obj, Set):
        value = obj.value.hex() if isinstance(obj.value, bytes) else obj.value
        return {"key": obj.key, "type": SET_TYPE_NAMES[obj.value_type], "value": value}
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, list):
        return [to_jsonable(x) for x in obj]
    return obj


def _from_jsonable(tp: Any, value: Any) -> Any:
    origin = get_origin(tp)
    if origin is list:
        (arg,) = get_args(tp)
        return [_from_jsonable(arg, v) for v in value]
    if origin is not None:  # X | None
        args = [a for a in get_args(tp) if a is not type(None)]
        return None if value is None else _from_jsonable(args[0], value)
    if tp is bytes:
        return bytes.fromhex(value)
    if is_dataclass(tp):
        return _dataclass_from_jsonable(tp, value)
    return tp(value)


def _dataclass_from_jsonable(cls: type, d: dict[str, Any]) -> Any:
    hints = get_type_hints(cls)
    return cls(**{f.name: _from_jsonable(hints[f.name], d[f.name]) for f in fields(cls) if f.name in d})


def from_jsonable(type_id: int, d: dict[str, Any]) -> Any:
    """Inverse of :func:`to_jsonable` for the message class of ``type_id``."""
    cls = ALL_TYPES[type_id]
    if cls is Set:
        kind = {v: k for k, v in SET_TYPE_NAMES.items()}[d["type"]]
        value: Any = {SET_I32: int, SET_F32: float, SET_STR8: str, SET_BLOB16: bytes.fromhex}[kind](d["value"])
        return Set(d["key"], value)
    if cls is Data:
        return Data(d["stream"], d["first_sample"], d["t_dev_us"], np.array(d["samples"], dtype=np.int32))
    return _dataclass_from_jsonable(cls, d)
