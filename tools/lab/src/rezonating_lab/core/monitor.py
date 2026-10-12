"""What the PC knows about a session: per-stream accounting and rate fit, fed by decoded frames.

No I/O here; ``tail`` today and the Live page later both feed frames in and read numbers out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..link import codec
from ..link.codec import Ack, Config, Data, Err, Frame, Hello, Log, Pong, Status, StreamInfo, StreamStatus
from .accounting import LossReport, StreamAccounting
from .timing import RESIDUAL_LIMIT_ACCEL_PERIODS, RESIDUAL_LIMIT_ADC_PERIODS, RateFit


def offset_pct(rate_hz: float | None, nominal_hz: float) -> float | None:
    """Rate error against nominal, in percent."""
    if rate_hz is None or nominal_hz <= 0:
        return None
    return (rate_hz / nominal_hz - 1.0) * 100.0


class StreamMonitor:
    def __init__(self, info: StreamInfo) -> None:
        self.info = info
        self.name = codec.STREAM_NAMES.get(info.id, f"stream{info.id}")
        self.acct = StreamAccounting()
        self.fit = RateFit()
        self.status: StreamStatus | None = None
        self.finalized = False  # STOP was acknowledged and its final STATUS (running = 0) was received
        # STATUS gate: after a START is sent, STATUS frames may still describe an older window (a left-over
        # session). Until the START is acknowledged they only update ``status``; they do not feed accounting.
        self.awaiting_start = False
        self.stop_acked = False  # a STOP covering this stream was acknowledged: the stream is idle on the node
        self._stop_sent = False
        self._final_status = False  # a STATUS with running = 0 arrived after STOP was sent
        self.timing_flags = 0
        self.max_residual_periods = 0.0
        self.packets = 0
        self.samples = 0
        self._limit = RESIDUAL_LIMIT_ACCEL_PERIODS if info.clock == codec.CLOCK_ADXL355 else RESIDUAL_LIMIT_ADC_PERIODS

    @property
    def running(self) -> bool:
        """The node is sending this stream (last STATUS says so and no STOP was acknowledged since)."""
        return bool(self.status and self.status.running and not self.stop_acked)

    def begin_window(self) -> None:
        """Call when a START is sent for a stream that is not running: indices may restart at 0."""
        self.acct.reset()
        self.fit = RateFit()
        self.status = None
        self.finalized = False
        self.awaiting_start = False
        self._stop_sent = False
        self._final_status = False
        self.timing_flags = 0
        self.max_residual_periods = 0.0
        self.packets = 0
        self.samples = 0

    def on_data(self, d: Data) -> None:
        self.packets += 1
        self.samples += d.n
        self.acct.on_data(d.first_sample, d.n)
        residual = self.fit.add(d.first_sample, d.t_dev_us)
        period = self.fit.period_us()
        if residual is not None and period:
            periods = abs(residual) / period
            self.max_residual_periods = max(self.max_residual_periods, periods)
            if periods > self._limit:
                self.timing_flags += 1

    def mark_start_sent(self) -> None:
        """A START for this (idle) stream was sent: ignore STATUS windows until it is acknowledged."""
        self.awaiting_start = True

    def arm(self) -> None:
        """The START was acknowledged (or a running STATUS proved it took effect): STATUS windows are ours."""
        self.awaiting_start = False
        self.stop_acked = False

    def mark_stop_sent(self) -> None:
        self._stop_sent = True
        self._final_status = False
        self.finalized = False

    def on_stop_ack(self) -> None:
        """The STOP was acknowledged. The window is final only if its final STATUS (running = 0) arrived."""
        self.stop_acked = True
        self.finalized = self._final_status

    def on_status(self, s: StreamStatus) -> None:
        self.status = s
        if self.awaiting_start:
            if s.running and self.stop_acked:
                # The START ack was lost, but this stream was idle (a STOP was acknowledged) and now runs:
                # the STATUS describes our window.
                self.arm()
            else:
                return  # possibly an older window: not used for accounting
        self.acct.on_status(s.win_first, s.win_end, s.win_device, s.win_link)
        if self._stop_sent and not s.running:
            self._final_status = True

    @property
    def rate_status_hz(self) -> float | None:
        return None if self.status is None or self.status.rate_mhz == 0 else self.status.rate_mhz / 1000.0

    @property
    def rate_fit_hz(self) -> float | None:
        return self.fit.rate_hz()

    def loss(self, session_alive: bool = True) -> LossReport | None:
        """Live numbers while recording, final numbers after STOP's final STATUS, 'incomplete' after a lost session."""
        if self.finalized:
            return self.acct.report("final")
        return self.acct.report("live" if session_alive else "incomplete")


@dataclass
class SessionMonitor:
    hello: Hello | None = None
    config: Config | None = None
    last_status: Status | None = None
    streams: dict[int, StreamMonitor] = field(default_factory=dict)
    errors: list[Err] = field(default_factory=list)
    logs: list[Log] = field(default_factory=list)
    rtt_us: float | None = None
    clock_offset_us: float | None = None  # node clock minus host clock, from the latest PONG
    _stop_acks: dict[int, int] = field(default_factory=dict)  # cmd_seq of a STOP -> stream mask
    _start_acks: dict[int, int] = field(default_factory=dict)  # cmd_seq of a START -> stream mask

    def expect_stop_ack(self, cmd_seq: int, stream_mask: int) -> None:
        """Call right after sending a STOP. Only a STATUS with running = 0 that arrives after this call, then
        the ACK, makes the stream's window final (PROTOCOL.md section 6)."""
        self._stop_acks[cmd_seq] = stream_mask
        for sid, mon in self.streams.items():
            if stream_mask & (1 << sid):
                mon.mark_stop_sent()

    def begin_window(self, stream_mask: int) -> None:
        """Reset the accounting of every idle stream in the mask (a running stream keeps its window)."""
        for sid, mon in self.streams.items():
            if stream_mask & (1 << sid) and not mon.running:
                mon.begin_window()

    def start_sent(self, cmd_seq: int, stream_mask: int, force: bool = False) -> None:
        """Call right after sending a START: reset idle streams and ignore STATUS windows until the ACK.
        ``force`` also resets streams that look running (the PC does not know the node's state).

        Frames arrive in order, so every STATUS before the START's ACK was made before the node handled the
        START and may still describe an older window (left-over USB session, PROTOCOL.md section 1)."""
        for sid, mon in self.streams.items():
            if stream_mask & (1 << sid) and (force or not mon.running):
                mon.begin_window()
                mon.mark_start_sent()
        self._start_acks[cmd_seq] = stream_mask

    def on_frame(self, frame: Frame, host_now_us: int | None = None) -> None:
        msg = frame.msg
        if isinstance(msg, Hello):
            self.hello = msg
            self.streams = {s.id: self.streams.get(s.id) or StreamMonitor(s) for s in msg.streams}
            for mon in self.streams.values():
                mon.stop_acked = False  # the node's state is unknown again after a HELLO
        elif isinstance(msg, Config):
            self.config = msg
        elif isinstance(msg, Data):
            mon = self.streams.get(msg.stream)
            if mon is not None:
                mon.on_data(msg)
        elif isinstance(msg, Status):
            self.last_status = msg
            for ss in msg.streams:
                mon = self.streams.get(ss.id)
                if mon is not None:
                    mon.on_status(ss)
        elif isinstance(msg, Ack):
            mask = self._stop_acks.pop(msg.cmd_seq, None)
            if mask is not None:
                for sid, mon in self.streams.items():
                    if mask & (1 << sid):
                        mon.on_stop_ack()
            mask = self._start_acks.pop(msg.cmd_seq, None)
            if mask is not None:
                for sid, mon in self.streams.items():
                    if mask & (1 << sid) and mon.awaiting_start:
                        mon.arm()
        elif isinstance(msg, Err):
            self.errors.append(msg)
            self._stop_acks.pop(msg.cmd_seq, None)
            self._start_acks.pop(msg.cmd_seq, None)
        elif isinstance(msg, Log):
            self.logs.append(msg)
        elif isinstance(msg, Pong) and host_now_us is not None:
            self.rtt_us = float(host_now_us - msg.host_t_us)
            self.clock_offset_us = msg.t_dev_us - (msg.host_t_us + self.rtt_us / 2)
