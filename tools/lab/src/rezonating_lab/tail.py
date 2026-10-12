"""``rzlab tail``: start a session, STOP anything left over, START the streams, PING every second, print one line
per second per stream. A gap value with a ``+`` (``gap 12+``) is a lower bound: device or link losses may sit in
the part of the window that is still in flight."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import TextIO

from .core.monitor import SessionMonitor, StreamMonitor, offset_pct
from . import session
from .link import codec
from .link.client import LinkClient, Transport
from .link.codec import Err, Log, Ping, Stop
from .link.transport_tcp import TransportClosed
from .session import SessionError

HANDSHAKE_TIMEOUT_S = 3.0
STOP_TIMEOUT_S = 3.0
PRINT_PERIOD_S = 1.0
PING_PERIOD_S = 1.0

TailError = SessionError


def _fmt_rate(rate_hz: float | None, nominal_hz: float) -> str:
    if rate_hz is None:
        return "    --        "
    pct = offset_pct(rate_hz, nominal_hz)
    return f"{rate_hz:9.2f} Hz {pct:+6.2f}%"


def format_stream_line(t_s: float, sm: StreamMonitor, bad_frames: int, lost_frames: int) -> str:
    """One status line for a stream: measured rate (STATUS and own t_dev fit), received and the loss counters."""
    nominal = float(sm.info.nominal_hz)
    loss = sm.loss()
    if loss is None:
        counts = f"rx {sm.samples:9d}  (no STATUS yet)"
    else:
        gap = f"{loss.host_gap}{'' if loss.host_gap_exact else '+'}"  # "12+" = at least 12 while in flight
        counts = (
            f"rx {loss.received:9d}  dev {loss.device:5d}  link {loss.link:5d}  gap {gap:>6}  pend {loss.pending:5d}"
        )
    flags = f"  tflag {sm.timing_flags}" if sm.timing_flags else ""
    return (
        f"[{t_s:6.1f}s] {sm.name:<7} status {_fmt_rate(sm.rate_status_hz, nominal)}  "
        f"fit {_fmt_rate(sm.rate_fit_hz, nominal)}  {counts}  bad {bad_frames}  lost {lost_frames}{flags}"
    )


def format_summary(mon: SessionMonitor, client: LinkClient, session_alive: bool, streams: list[int]) -> list[str]:
    rx = client.rx
    lines = ["", "final loss summary"]
    for sid in streams:
        sm = mon.streams.get(sid)
        if sm is None:
            continue
        loss = sm.loss(session_alive)
        if loss is None:
            lines.append(f"  {sm.name:<7} no STATUS received, nothing to report (rx {sm.samples} samples)")
            continue
        note = " (loss incomplete: no final STATUS)" if loss.incomplete else ""
        lines.append(
            f"  {sm.name:<7} window [{loss.win_first}, {loss.win_end})  received {loss.received}  "
            f"missing {loss.missing}  device {loss.device}  link {loss.link}  host_gap {loss.host_gap}{note}"
        )
        if loss.protocol_bug:
            lines.append(f"  {sm.name:<7} PROTOCOL BUG: host_gap is negative ({loss.host_gap})")
        if sm.timing_flags:
            lines.append(
                f"  {sm.name:<7} {sm.timing_flags} packets off the t_dev fit "
                f"(worst {sm.max_residual_periods:.2f} sample periods)"
            )
    lines.append(
        f"  link: frames ok {rx.frames_ok}  bad_frames {rx.bad_frames}  lost_frames {rx.lost_frames}  "
        f"resyncs {rx.resyncs}  unknown_types {rx.unknown_types}"
    )
    return lines


def stream_mask(names: list[str] | None) -> int:
    if not names:
        return 0b111
    by_name = {v: k for k, v in codec.STREAM_NAMES.items()}
    mask = 0
    for name in names:
        if name not in by_name:
            raise TailError(f"unknown stream {name!r}; choose from {', '.join(by_name)}")
        mask |= 1 << by_name[name]
    return mask


def run_tail(
    transport: Transport,
    key: bytes | None = None,
    mask: int = 0b111,
    duration_s: float | None = None,
    out: TextIO | None = None,
    wall: Callable[[], float] = time.perf_counter,
) -> int:
    """Run until ``duration_s`` (or Ctrl+C). Returns 0 when the session ran, 1 when it failed."""
    out = out or sys.stdout
    client = LinkClient(transport)
    mon = SessionMonitor()
    stream_ids = [sid for sid in codec.STREAM_NAMES if mask & (1 << sid)]
    session_alive = True

    def host_us() -> int:
        return int(wall() * 1e6)

    def handle(frames) -> None:
        for fr in frames:
            mon.on_frame(fr, host_us())
            if isinstance(fr.msg, Err):
                print(f"  ! ERR {fr.msg.code} for command seq {fr.msg.cmd_seq}: {fr.msg.msg}", file=out)
            elif isinstance(fr.msg, Log):
                print(f"  log[{fr.msg.level}] {fr.msg.tag}: {fr.msg.msg}", file=out)

    try:
        session.open_session(client, mon, key, handle, wall, HANDSHAKE_TIMEOUT_S)
        hello = mon.hello
        assert hello is not None
        names = ", ".join(f"{codec.STREAM_NAMES.get(s.id, s.id)} {s.n_ch}ch {s.nominal_hz}Hz" for s in hello.streams)
        print(f"node {hello.node_id}  fw {hello.fw_version}  proto {hello.proto}  streams: {names}", file=out)
        print(
            "  (a gap value like 12+ is a lower bound while samples are in flight; the final summary is exact)",
            file=out,
        )
        absent = [sid for sid in stream_ids if sid not in mon.streams]
        if absent:
            raise TailError(f"the node has no stream {absent}")

        # STOP anything a killed PC left running, then START (PROTOCOL.md section 1)
        session.begin_recording(client, mon, mask, handle, wall)
        t0 = wall()
        next_ping, next_print = t0, t0 + PRINT_PERIOD_S
        try:
            while True:
                handle(client.poll(0.05))
                t = wall()
                if t >= next_ping:
                    client.send(Ping(host_us()))
                    next_ping += PING_PERIOD_S
                if t >= next_print:
                    for sid in stream_ids:
                        print(
                            format_stream_line(t - t0, mon.streams[sid], client.rx.bad_frames, client.rx.lost_frames),
                            file=out,
                        )
                    out.flush()
                    next_print += PRINT_PERIOD_S
                if duration_s is not None and t - t0 >= duration_s:
                    break
        except KeyboardInterrupt:
            print("\nCtrl+C: stopping", file=out)
        # STOP: the node drains, sends the final STATUS and then the ACK.
        stop_seq = client.send(Stop(mask))
        mon.expect_stop_ack(stop_seq, mask)
        session.wait_for_reply(client, stop_seq, handle, wall, STOP_TIMEOUT_S)
        if not all(mon.streams[s].finalized for s in stream_ids):
            session_alive = False  # no ACK, or no final STATUS before it: report "loss incomplete"
    except TransportClosed as exc:
        session_alive = False
        print(f"connection lost: {exc}", file=out)
    except TailError as exc:
        print(f"rzlab tail: {exc}", file=out)
        client.close()
        return 1
    except KeyboardInterrupt:
        session_alive = False
    for line in format_summary(mon, client, session_alive, stream_ids):
        print(line, file=out)
    client.close()
    return 0
