"""Simulator over a real TCP socket, in-process, sped up: client codec + monitor against the node.

The loss rule of PROTOCOL.md section 6 is checked against what the simulator itself injected:
missing = device + link + host_gap, host_gap > 0 only when frames were corrupted on the wire.
"""

import io
import re
import time

import pytest
from rezonating_lab import session
from rezonating_lab.core.monitor import SessionMonitor
from rezonating_lab.link import codec
from rezonating_lab.link.client import LinkClient
from rezonating_lab.link.codec import GetInfo, Ping, Start, Status, Stop
from rezonating_lab.link.transport_tcp import TcpTransport
from rezonating_lab.sim.faults import FaultConfig
from rezonating_lab.sim.node import SimConfig
from rezonating_lab.sim.server import SimThread
from rezonating_lab.tail import run_tail

SPEED = 25.0
DEVICE_SECONDS = 8.0


def record(cfg: SimConfig, device_s: float = DEVICE_SECONDS, mask: int = 0b111):
    """Run one START ... STOP recording against a sim thread; return the PC-side monitor and the node."""
    with SimThread(cfg) as sim:
        client = LinkClient(TcpTransport("127.0.0.1", sim.port))
        mon = SessionMonitor()
        client.open_session(GetInfo())
        deadline = time.monotonic() + 5
        while (mon.hello is None or mon.config is None) and time.monotonic() < deadline:
            for fr in client.poll(0.05):
                mon.on_frame(fr, int(time.perf_counter() * 1e6))
        assert mon.hello and mon.config, "no HELLO and CONFIG"
        session.begin_recording(
            client, mon, mask, lambda fs: [mon.on_frame(f, int(time.perf_counter() * 1e6)) for f in fs]
        )
        end = time.monotonic() + device_s / cfg.speed
        next_ping = 0.0
        while time.monotonic() < end:
            for fr in client.poll(0.02):
                mon.on_frame(fr, int(time.perf_counter() * 1e6))
            if time.monotonic() >= next_ping:
                client.send(Ping(int(time.perf_counter() * 1e6)))
                next_ping = time.monotonic() + 1.0
        seq = client.send(Stop(mask))
        mon.expect_stop_ack(seq, mask)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not all(mon.streams[s].finalized for s in range(3) if mask & (1 << s)):
            for fr in client.poll(0.02):
                mon.on_frame(fr, int(time.perf_counter() * 1e6))
        rx = client.rx
        client.close()
    return mon, rx, sim.node


def injected_set(ranges):
    return {i for a, b in ranges for i in range(a, b)}


def received_set(sm):
    return {i for a, b in sm.acct.received.intervals() for i in range(a, b)}


@pytest.mark.parametrize(
    "corrupt_rate, device_rate, link_rate",
    [(0.0, 0.0, 0.0), (0.0, 0.003, 0.08), (0.06, 0.0, 0.0), (0.06, 0.003, 0.08)],
)
def test_loss_accounting_matches_what_the_simulator_injected(corrupt_rate, device_rate, link_rate):
    cfg = SimConfig(
        seed=11,
        speed=SPEED,
        record_injections=True,
        faults=FaultConfig(device_drop_rate=device_rate, link_drop_rate=link_rate, corrupt_rate=corrupt_rate),
    )
    mon, rx, node = record(cfg)
    total_corrupt = 0
    for sid in (0, 1, 2):
        sm, inj = mon.streams[sid], node.streams[sid].injected
        assert sm.finalized, f"stream {sid}: no final STATUS"
        rep = sm.loss()
        assert rep and not rep.incomplete and not rep.protocol_bug
        assert rep.window > 8.0 * 1900 * (0.5 if sid == 1 else 1.0)  # about 8 device seconds were recorded
        # the three counters equal what the node dropped, and the sum rule holds
        assert rep.device == len(injected_set(inj.device)) == inj.device_total
        assert rep.link == inj.link_total
        assert rep.host_gap == inj.corrupt_total
        assert rep.missing == rep.device + rep.link + rep.host_gap
        # not only the counts: the very indices that never arrived are the injected ones
        window = set(range(rep.win_first, rep.win_end))
        lost = window - received_set(sm)
        assert lost == injected_set(inj.device) | injected_set(inj.link) | injected_set(inj.corrupt)
        if corrupt_rate == 0.0:
            assert rep.host_gap == 0  # host gaps appear only when the wire corrupts frames
        total_corrupt += inj.corrupt_packets
    if corrupt_rate > 0.0:
        assert total_corrupt > 0 and any(mon.streams[s].loss().host_gap > 0 for s in (0, 1, 2))
        assert rx.bad_frames == total_corrupt  # each corrupted frame costs exactly one bad frame
        assert rx.lost_frames == total_corrupt  # and one seq jump (link drops spend no seq)
    else:
        assert rx.bad_frames == 0 and rx.lost_frames == 0


def test_measured_rates_show_the_clock_error():
    mon, rx, _ = record(SimConfig(seed=2, speed=SPEED))
    expect = {0: 2016.0, 1: 1008.0, 2: 1996.0}  # +0.8 % on the ADC, -0.2 % on the accelerometer
    for sid, hz in expect.items():
        sm = mon.streams[sid]
        assert abs(sm.rate_fit_hz - hz) < 0.5, (sid, sm.rate_fit_hz)
        assert abs(sm.rate_status_hz - hz) < 1.0, (sid, sm.rate_status_hz)
        assert sm.timing_flags == 0  # timestamps stay within 0.5 (ADC) and 1.5 (accel) sample periods
    assert mon.rtt_us is not None and mon.rtt_us > 0
    assert rx.bad_frames == 0 and rx.lost_frames == 0 and rx.unknown_types == 0


def test_clock_error_option_end_to_end():
    mon, _, _ = record(SimConfig(seed=2, speed=SPEED, faults=FaultConfig(clock_error=-0.005)), mask=0b001)
    assert abs(mon.streams[0].rate_fit_hz - 1990.0) < 0.5


def test_a_second_client_is_refused_with_err_5_while_a_session_is_live():
    with SimThread(SimConfig(speed=SPEED)) as sim:
        a = LinkClient(TcpTransport("127.0.0.1", sim.port))
        a.open_session(GetInfo())
        mon_a = SessionMonitor()
        deadline = time.monotonic() + 3
        while mon_a.config is None and time.monotonic() < deadline:
            for fr in a.poll(0.05):
                mon_a.on_frame(fr)
        b = LinkClient(TcpTransport("127.0.0.1", sim.port))
        cmd = b.open_session(GetInfo())
        mon_b = SessionMonitor()
        deadline = time.monotonic() + 3
        while not mon_b.errors and time.monotonic() < deadline:
            for fr in b.poll(0.05):
                mon_b.on_frame(fr)
        assert [(e.cmd_seq, e.code) for e in mon_b.errors] == [(cmd, codec.ERR_BUSY)]
        a.close()
        b.close()


def test_auth_mode_end_to_end():
    key = bytes(range(16))
    with SimThread(SimConfig(speed=SPEED, auth=True, key=key, auth_timeout_s=0.3)) as sim:
        out = io.StringIO()
        rc = run_tail(TcpTransport("127.0.0.1", sim.port), key=key, duration_s=1.0, out=out)
        assert rc == 0 and "final loss summary" in out.getvalue()
        out = io.StringIO()  # no AUTH: the node sends ERR 6 after its timeout and closes
        rc = run_tail(TcpTransport("127.0.0.1", sim.port), key=None, duration_s=1.0, out=out)
        assert rc == 1 and "ERR 6" in out.getvalue()
        out = io.StringIO()
        rc = run_tail(TcpTransport("127.0.0.1", sim.port), key=b"\x01" * 16, duration_s=1.0, out=out)
        assert rc == 1 and "ERR 6" in out.getvalue()


def test_session_lost_without_final_status_is_reported_incomplete():
    with SimThread(SimConfig(speed=SPEED)) as sim:
        client = LinkClient(TcpTransport("127.0.0.1", sim.port))
        mon = SessionMonitor()
        client.open_session(GetInfo())
        deadline = time.monotonic() + 3
        while mon.config is None and time.monotonic() < deadline:
            for fr in client.poll(0.05):
                mon.on_frame(fr, int(time.perf_counter() * 1e6))
        mon.start_sent(client.send(Start(0b001)), 0b001)
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            for fr in client.poll(0.02):
                mon.on_frame(fr, int(time.perf_counter() * 1e6))
        client.close()  # vanish: no STOP, no final STATUS
    sm = mon.streams[0]
    assert not sm.finalized
    rep = sm.loss(session_alive=False)
    assert rep.incomplete and rep.win_end > 0
    assert rep.missing == rep.device + rep.link + rep.host_gap  # whatever is not attributed is host_gap
    assert sm.loss(session_alive=True).incomplete is False


# ---------------------------------------------------- USB: a killed PC leaves the session running (finding 2)


def _handler(mon):
    return lambda frames: [mon.on_frame(f, int(time.perf_counter() * 1e6)) for f in frames]


def test_tail_killed_without_stop_then_restarted_within_5_s_reports_a_clean_window():
    with SimThread(SimConfig(speed=10.0)) as sim:
        # a first PC starts every stream and dies: no STOP, and the node cannot see the port close
        client = LinkClient(TcpTransport("127.0.0.1", sim.port))
        mon = SessionMonitor()
        handle = _handler(mon)
        session.open_session(client, mon, None, handle)
        session.begin_recording(client, mon, 0b111, handle)
        end = time.monotonic() + 0.5
        while time.monotonic() < end:
            handle(client.poll(0.02))
        client.close()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not (sim.node.active is not None and sim.node.active.detached):
            time.sleep(0.01)
        assert sim.node.active is not None and sim.node.active.detached  # the session lives on
        assert all(st.sending for st in sim.node.streams.values())  # streams still running, old window

        out = io.StringIO()  # a second PC within 5 s: lands in the old session
        rc = run_tail(TcpTransport("127.0.0.1", sim.port), duration_s=1.2, out=out)
    assert rc == 0
    summary = out.getvalue().split("final loss summary")[1]
    assert "(loss incomplete" not in summary and "PROTOCOL BUG" not in summary
    for name, rate in (("adc_raw", 2016), ("adc_dec", 1008), ("accel", 1996)):
        m = re.search(
            rf"{name}\s+window \[(\d+), (\d+)\)\s+received (\d+)\s+missing (\d+)\s+device (\d+)\s+link (\d+)\s+host_gap (\d+)",
            summary,
        )
        assert m, summary
        first, end_, received, missing, device, link, gap = map(int, m.groups())
        # the old window is gone: STOP idled the node, so the new window restarts at 0 and is about 12 s long
        assert first == 0 and received == end_ and missing == device == link == gap == 0, m.group(0)
        assert 0.7 * 12 * rate < end_ < 1.3 * 12 * rate, (name, end_)
    assert "bad_frames 0" in summary and "lost_frames 0" in summary


def test_the_old_window_would_show_up_as_host_gap_if_the_client_did_not_stop_first():
    # what the clean-up STOP prevents: a START on the left-over running streams is a no-op, the node's window
    # still begins at the first PC's START and everything the first PC read is missing here
    with SimThread(SimConfig(speed=10.0)) as sim:
        client = LinkClient(TcpTransport("127.0.0.1", sim.port))
        mon = SessionMonitor()
        handle = _handler(mon)
        session.open_session(client, mon, None, handle)
        client.send(Start(0b001))
        time.sleep(0.4)
        client.close()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not (sim.node.active is not None and sim.node.active.detached):
            time.sleep(0.01)
        client = LinkClient(TcpTransport("127.0.0.1", sim.port))
        mon = SessionMonitor()
        handle = _handler(mon)
        session.open_session(client, mon, None, handle)
        seq = client.send(Start(0b001))  # the naive start, without the STOP
        mon.start_sent(seq, 0b001)
        end = time.monotonic() + 0.4
        while time.monotonic() < end:
            handle(client.poll(0.02))
        stop = client.send(Stop(0b001))
        mon.expect_stop_ack(stop, 0b001)
        session.wait_for_reply(client, stop, handle, time.perf_counter, 3.0)
        client.close()
    rep = mon.streams[0].loss()
    assert rep.host_gap > 1000  # the failure the fix avoids


# ------------------------------------------------------------------ a final STATUS lost on the wire (finding 1)


def test_tail_reports_loss_incomplete_when_the_final_status_is_corrupted():
    def drop_final(msg):
        return isinstance(msg, Status) and not any(s.running for s in msg.streams)

    with SimThread(SimConfig(speed=10.0, control_fault=drop_final)) as sim:
        out = io.StringIO()
        rc = run_tail(TcpTransport("127.0.0.1", sim.port), duration_s=1.2, out=out)
    assert rc == 0
    summary = out.getvalue().split("final loss summary")[1]
    for name in ("adc_raw", "adc_dec", "accel"):
        line = next(ln for ln in summary.splitlines() if ln.strip().startswith(name))
        assert "(loss incomplete: no final STATUS)" in line, line
    assert "bad_frames" in summary and "bad_frames 0" not in summary  # the corrupted frame was counted
