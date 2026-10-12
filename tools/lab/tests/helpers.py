"""Shared helpers for the lab tests."""

from __future__ import annotations

from rezonating_lab.link import codec
from rezonating_lab.link.codec import Frame
from rezonating_lab.link.receiver import FROM_NODE, Receiver
from rezonating_lab.sim.node import Connection, SimConfig, SimNode


class FakeClock:
    """Wall clock that only moves when the test says so."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class Pc:
    """A PC talking to a SimNode without any transport: sends frames, collects what the node writes."""

    def __init__(self, node: SimNode, leading_zero: bool = True) -> None:
        self.node = node
        self.out = bytearray()
        self.closed = False
        self.conn: Connection = node.connect(self.out.extend, close=self._on_close)
        self.rx = Receiver(FROM_NODE)
        self.tx_seq = 0
        self.raw = bytearray()  # every byte the node wrote, kept for byte-exact checks
        self.all: list[Frame] = []  # every frame decoded so far
        if leading_zero:
            self.conn.feed(b"\x00")

    def _on_close(self) -> None:
        self.closed = True

    def send(self, msg) -> int:
        seq = self.tx_seq
        self.tx_seq += 1
        self.conn.feed(codec.encode_frame(msg, seq))
        return seq

    def take_bytes(self) -> bytes:
        data = bytes(self.out)
        self.out.clear()
        self.raw += data
        return data

    def frames(self) -> list[Frame]:
        """Frames the node wrote since the last call."""
        new = self.rx.feed(self.take_bytes())
        self.all += new
        return new


def make_node(clock: FakeClock | None = None, **kw) -> tuple[SimNode, FakeClock]:
    clock = clock or FakeClock()
    return SimNode(SimConfig(**kw), clock), clock


def run(node: SimNode, clock: FakeClock, wall_s: float, step_s: float = 0.01) -> None:
    """Advance wall time in small steps, ticking the node each step."""
    n = round(wall_s / step_s)
    for _ in range(n):
        clock.advance(step_s)
        node.tick()


def of_type(frames, cls):
    return [f for f in frames if isinstance(f.msg, cls)]


def datas(frames, stream: int):
    return [f.msg for f in frames if isinstance(f.msg, codec.Data) and f.msg.stream == stream]
