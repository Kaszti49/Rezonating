"""PC side of a link session: sequence numbers, the opening 0x00, a receiver, and a blocking poll loop."""

from __future__ import annotations

import time
from typing import Any, Protocol

from . import codec
from .codec import Frame
from .receiver import FROM_NODE, Receiver


class Transport(Protocol):
    def read(self, timeout_s: float) -> bytes: ...
    def write(self, data: bytes) -> None: ...
    def close(self) -> None: ...


class LinkClient:
    """Sends PC to node frames (own ``seq`` counter) and turns incoming bytes into frames."""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self.rx = Receiver(FROM_NODE)
        self._tx_seq = 0
        self._opened = False
        self.frames_sent = 0

    @property
    def next_seq(self) -> int:
        return self._tx_seq

    def open_session(self, start_msg: Any) -> int:
        """Write the flushing 0x00, then the session-start frame (GET_INFO on USB, AUTH on TCP)."""
        self.transport.write(b"\x00")
        self._opened = True
        return self.send(start_msg)

    def send(self, msg: Any) -> int:
        """Send one frame; return the seq it was sent with (the node's ACK/ERR carries it as cmd_seq)."""
        if not self._opened:
            self.transport.write(b"\x00")
            self._opened = True
        seq = self._tx_seq
        self.transport.write(codec.encode_frame(msg, seq))
        self._tx_seq = (seq + 1) & 0xFFFF
        self.frames_sent += 1
        return seq

    def poll(self, timeout_s: float = 0.05) -> list[Frame]:
        """Wait up to ``timeout_s`` for bytes and return the frames that completed. Raises TransportClosed."""
        data = self.transport.read(timeout_s)
        return self.rx.feed(data) if data else []

    def drain(self, duration_s: float) -> list[Frame]:
        """Poll for ``duration_s`` and return everything received."""
        end = time.monotonic() + duration_s
        out: list[Frame] = []
        while time.monotonic() < end:
            out += self.poll(min(0.05, max(0.0, end - time.monotonic())))
        return out

    def close(self) -> None:
        self.transport.close()
