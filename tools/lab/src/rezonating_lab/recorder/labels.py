"""Live label marks: stamped by the server on arrival, resolved to sample indices when the recording ends.

A mark is two *edges* (start, end). Each edge is a host-clock stamp (microseconds on the Lab server's clock, the same
clock the PING frames use) plus where it came from:

* ``key``: the browser only reports that Space was pressed. The server stamps the arrival; the browser clock is never
  used. Uncertainty: half the round trip of the PING/PONG pairs that map the host clock to the node clock, plus
  ``KEY_ALLOWANCE_MS`` for the loopback request and the event loop (an assumption, not a measurement).
* ``phone``: the phone page measured its round trip to the server; the server subtracts half of it from the arrival
  stamp. Uncertainty: that half round trip (the most the correction can be off when all latency sits on one side),
  plus the node clock term and ``PHONE_ALLOWANCE_MS``.

The index of an edge in a stream is found at the end of the recording, with every PING/PONG pair and every DATA
packet of the session (a line through the packets nearest in time), so early marks profit from the later fit.
A mark's ``unc_ms`` is the larger of its two edges.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..core.timing import ClockMap, index_at_time

KEY_ALLOWANCE_MS = 12.0
PHONE_ALLOWANCE_MS = 10.0


@dataclass
class Edge:
    src: str  # "key" | "phone"
    host_us: float  # corrected stamp on the server clock: arrival, minus half the phone's round trip
    arrival_us: float
    rtt_ms: float | None  # phone page's round trip; None for the keyboard
    allowance_ms: float  # uncertainty that is not the node clock map

    def to_dict(self) -> dict:
        return {"src": self.src, "host_us": self.host_us, "rtt_ms": self.rtt_ms}


@dataclass
class Mark:
    id: int
    label: str
    person: str | None
    pace: str | None
    shoes: bool | None
    start: Edge
    end: Edge | None = None
    clamped: bool = False  # an edge fell outside a file and was moved to its end

    @property
    def is_open(self) -> bool:
        return self.end is None


@dataclass
class StreamTimebase:
    """What one stream's WAV needs to place a mark."""

    base: int  # node sample index of the WAV's first frame
    frames: int  # frames in the WAV
    first_samples: np.ndarray  # DATA packets: first_sample, sorted
    t_dev_us: np.ndarray  # and their device timestamps
    rate_hz: float  # sample_rate written in the sidecar (the WAV header rate)


@dataclass
class ResolvedLabel:
    t0: float
    t1: float
    i0: int
    i1: int
    src: str
    unc_ms: float
    clamped: bool


class LabelBook:
    """The marks of one recording. Thread-safe; ids count up and are never reused."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._marks: list[Mark] = []
        self._next_id = 1

    def open_mark(self) -> Mark | None:
        with self._lock:
            return next((m for m in self._marks if m.is_open), None)

    def start(self, edge: Edge, label: str, person: str | None, pace: str | None, shoes: bool | None) -> Mark:
        with self._lock:
            if any(m.is_open for m in self._marks):
                raise ValueError("a mark is already open")
            m = Mark(self._next_id, label, person, pace, shoes, edge)
            self._next_id += 1
            self._marks.append(m)
            return m

    def end(self, edge: Edge) -> Mark:
        with self._lock:
            m = next((x for x in self._marks if x.is_open), None)
            if m is None:
                raise ValueError("no mark is open")
            if edge.host_us < m.start.host_us:  # a phone correction can reorder a very short mark
                edge = Edge(edge.src, m.start.host_us, edge.arrival_us, edge.rtt_ms, edge.allowance_ms)
            m.end = edge
            return m

    def delete(self, mark_id: int) -> Mark | None:
        with self._lock:
            for i, m in enumerate(self._marks):
                if m.id == mark_id:
                    return self._marks.pop(i)
        return None

    def all(self) -> list[Mark]:
        with self._lock:
            return list(self._marks)

    def __len__(self) -> int:
        return len(self._marks)


def edge_unc_ms(edge: Edge, clock_unc_us: float, sample_rate_hz: float) -> float:
    rtt_term = (edge.rtt_ms / 2.0) if edge.rtt_ms is not None else 0.0
    quantisation_ms = 0.5 * 1000.0 / sample_rate_hz  # the index is a whole sample
    return clock_unc_us / 1000.0 + rtt_term + edge.allowance_ms + quantisation_ms


def resolve(mark: Mark, clock: ClockMap, tb: StreamTimebase) -> ResolvedLabel | None:
    """Place a closed mark in one stream's WAV. None when the clock or the packets do not allow it."""
    if mark.end is None:
        return None
    idx: list[int] = []
    unc: list[float] = []
    clamped = mark.clamped
    for edge in (mark.start, mark.end):
        off = clock.offset_at(edge.host_us)
        if off is None:
            return None
        t_dev = edge.host_us + off.offset_us
        i_abs = index_at_time(tb.first_samples, tb.t_dev_us, t_dev)
        if i_abs is None:
            return None
        i_rel = int(round(i_abs)) - tb.base
        if i_rel < 0 or i_rel > tb.frames:
            clamped = True
            i_rel = min(max(i_rel, 0), tb.frames)
        idx.append(i_rel)
        unc.append(edge_unc_ms(edge, off.unc_us, tb.rate_hz))
    i0, i1 = idx[0], max(idx[0], idx[1])
    return ResolvedLabel(
        t0=i0 / tb.rate_hz,
        t1=i1 / tb.rate_hz,
        i0=i0,
        i1=i1,
        src=mark.start.src,
        unc_ms=round(max(unc), 1),
        clamped=clamped,
    )


def label_entry(mark: Mark, r: ResolvedLabel) -> dict[str, Any]:
    """A ``labels[]`` item of the sidecar (schema v1)."""
    out: dict[str, Any] = {
        "t0": r.t0,
        "t1": r.t1,
        "i0": r.i0,
        "i1": r.i1,
        "src": r.src,
        "unc_ms": r.unc_ms,
        "label": mark.label,
    }
    if mark.person is not None:
        out["person"] = mark.person
    if mark.shoes is not None:
        out["shoes"] = mark.shoes
    if mark.pace is not None:
        out["pace"] = mark.pace
    return out
