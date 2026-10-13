"""Streaming receiver: bytes in, typed frames out, with the counters PROTOCOL.md section 2 asks for.

The receiver splits the byte stream on 0x00, ignores empty chunks and counts, never raises:

* ``bad_frames``: a chunk that is not a valid frame (COBS, length, CRC, ver), a known type whose payload
  is too short, or more than 4119 bytes without a 0x00;
* ``lost_frames``: sum of forward ``seq`` jumps (modulo 65536). The expected ``seq`` restarts at every HELLO
  (node to PC direction);
* ``resyncs``: ``seq`` jumps that mean "the numbering restarted", not loss (see ``_track_seq``);
* ``unknown_types``: valid frames whose type is not in this direction's table (still counted for ``seq``).

Payload bytes after the known fields are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import codec
from .codec import CodecError, Frame, FrameError, UnknownTypeError

FROM_NODE = "from_node"
FROM_PC = "from_pc"


@dataclass
class Unhandled:
    """A valid frame the receiver could not turn into a message: unknown type or a payload too short.

    Delivered in order (instead of being dropped) only when ``deliver_unhandled=True``; the node simulator
    uses it to answer ``ERR 1`` and ``ERR 2``.
    """

    type_id: int
    payload: bytes
    malformed: bool  # True: known type with a short payload; False: unknown type


class Receiver:
    def __init__(
        self,
        direction: str = FROM_NODE,
        deliver_unhandled: bool = False,
    ) -> None:
        if direction not in (FROM_NODE, FROM_PC):
            raise ValueError(f"direction must be {FROM_NODE!r} or {FROM_PC!r}")
        self.direction = direction
        self._table = codec.NODE_TO_PC if direction == FROM_NODE else codec.PC_TO_NODE
        self.deliver_unhandled = deliver_unhandled
        self.bad_frames = 0
        self.lost_frames = 0
        self.resyncs = 0
        self.unknown_types = 0
        self.frames_ok = 0
        self.bytes_in = 0
        self._buf = bytearray()
        self._discarding = False  # inside an oversize chunk: swallow bytes up to the next 0x00
        self._expected_seq: int | None = None

    def reset_counters(self) -> None:
        self.bad_frames = self.lost_frames = self.resyncs = self.unknown_types = self.frames_ok = 0

    def feed(self, data: bytes) -> list[Frame]:
        """Consume bytes; return the frames that completed, in order."""
        self.bytes_in += len(data)
        out: list[Frame] = []
        pos = 0
        n = len(data)
        while pos < n:
            end = data.find(0, pos)
            if end < 0:
                self._append_partial(data[pos:])
                break
            chunk = data[pos:end]
            pos = end + 1
            if self._discarding:
                self._discarding = False  # the rest of an oversize chunk, already counted
                self._buf.clear()
                continue
            if self._buf:
                chunk = bytes(self._buf) + chunk
                self._buf.clear()
            if not chunk:
                continue  # empty chunk: extra delimiter
            if len(chunk) > codec.MAX_ENCODED_LEN:
                self.bad_frames += 1
                continue
            frame = self._handle_chunk(chunk)
            if frame is not None:
                out.append(frame)
        return out

    def _append_partial(self, part: bytes) -> None:
        if self._discarding:
            return
        self._buf += part
        if len(self._buf) > codec.MAX_ENCODED_LEN:
            self.bad_frames += 1
            self._buf.clear()
            self._discarding = True

    def _track_seq(self, seq: int) -> None:
        """Count lost frames from the ``seq`` jump, or a resync when the jump means "numbering restarted".

        Rule (PROTOCOL.md section 2): with ``jump = (seq - expected) mod 65536``,

        * ``jump == 0``: in order;
        * ``jump > 32768`` (the new ``seq`` is *behind* the expected one), or ``seq < 16`` with
          ``jump > 1024`` (the numbering fell back to its start): the sender restarted its numbering, for
          example because a HELLO was lost and CONFIG (seq 1) arrived. Count one resync and no lost frames;
        * otherwise ``jump`` frames were lost.

        A real loss of more than 1024 frames in a row (about 14 s of DATA at 75 frames/s) cannot happen
        inside the 5 s liveness limit, so the rule does not hide real loss.
        """
        expected = self._expected_seq
        self._expected_seq = (seq + 1) & 0xFFFF
        if expected is None or seq == expected:
            return
        jump = (seq - expected) & 0xFFFF
        if jump > 32768 or (seq < 16 and jump > 1024):
            self.resyncs += 1
        else:
            self.lost_frames += jump

    def _handle_chunk(self, chunk: bytes) -> Frame | None:
        try:
            type_id, seq, payload = codec.decode_chunk(chunk)
        except FrameError:
            self.bad_frames += 1
            return None
        if self.direction == FROM_NODE and type_id == codec.Hello.TYPE_ID:
            self._expected_seq = None  # the node restarts its seq at HELLO
        self._track_seq(seq)
        try:
            msg = codec.parse_payload(type_id, payload, self._table)
        except UnknownTypeError:
            self.unknown_types += 1
            return Frame(seq, Unhandled(type_id, payload, False)) if self.deliver_unhandled else None
        except CodecError:
            self.bad_frames += 1
            return Frame(seq, Unhandled(type_id, payload, True)) if self.deliver_unhandled else None
        self.frames_ok += 1
        return Frame(seq, msg)
