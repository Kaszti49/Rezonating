import io
import re

import pytest
import serial
from rezonating_lab import cli
from rezonating_lab.link import transport_serial
from rezonating_lab.link.transport_serial import SerialTransport, open_serial
from rezonating_lab.link.transport_tcp import TcpTransport, parse_host_port
from rezonating_lab.sim.faults import FaultConfig
from rezonating_lab.sim.node import SimConfig
from rezonating_lab.sim.server import SimThread
from rezonating_lab.tail import run_tail, stream_mask


class InterruptAfter:
    """Transport wrapper that raises Ctrl+C after n reads."""

    def __init__(self, inner, n):
        self.inner, self.n = inner, n

    def read(self, timeout_s):
        self.n -= 1
        if self.n == -1:  # once: the STOP that follows must be able to finish
            raise KeyboardInterrupt
        return self.inner.read(timeout_s)

    def write(self, data):
        self.inner.write(data)

    def close(self):
        self.inner.close()


def test_tail_prints_one_line_per_second_per_stream_and_a_summary():
    with SimThread(SimConfig(speed=10.0, faults=FaultConfig(device_drop_rate=0.002))) as sim:
        out = io.StringIO()
        rc = run_tail(TcpTransport("127.0.0.1", sim.port), duration_s=3.2, out=out)
    text = out.getvalue()
    assert rc == 0
    assert "node rzn-sim001" in text
    for name in ("adc_raw", "adc_dec", "accel"):
        lines = [ln for ln in text.splitlines() if re.match(r"\[\s*\d+\.\d+s\] " + name, ln)]
        assert len(lines) == 3, text  # one per second
        last = lines[-1]
        # measured rate from STATUS and from the t_dev fit, each with the percent offset, then the counters
        assert re.search(r"status\s+[\d.]+ Hz\s+[+-][\d.]+%", last)
        assert re.search(r"fit\s+[\d.]+ Hz\s+[+-][\d.]+%", last)
        for field in ("rx", "dev", "link", "gap", "bad", "lost"):
            assert re.search(rf"\b{field}\s+\d+", last), (field, last)
    assert "+0.8" in text  # the default clock error shows up as a percent offset
    summary = text.split("final loss summary")[1]
    assert "(loss incomplete" not in summary
    assert re.search(
        r"adc_raw\s+window \[0, \d+\)\s+received \d+\s+missing \d+\s+device \d+\s+link 0\s+host_gap 0", summary
    )
    assert "bad_frames 0" in summary and "lost_frames 0" in summary


def test_ctrl_c_sends_stop_and_prints_the_final_summary():
    with SimThread(SimConfig(speed=10.0)) as sim:
        out = io.StringIO()
        transport = InterruptAfter(TcpTransport("127.0.0.1", sim.port), n=60)
        rc = run_tail(transport, out=out)
        assert rc == 0
        assert "Ctrl+C" in out.getvalue() and "final loss summary" in out.getvalue()
        assert "(loss incomplete" not in out.getvalue()  # STOP was sent and its final STATUS arrived
        assert not any(st.sending for st in sim.node.streams.values())  # the node saw the STOP


def test_tail_reports_a_missing_node():
    out = io.StringIO()

    class Silent:
        def read(self, timeout_s):
            import time

            time.sleep(timeout_s)
            return b""

        def write(self, data):
            pass

        def close(self):
            pass

    import rezonating_lab.tail as tail

    old = tail.HANDSHAKE_TIMEOUT_S
    tail.HANDSHAKE_TIMEOUT_S = 0.3
    try:
        assert run_tail(Silent(), out=out) == 1
    finally:
        tail.HANDSHAKE_TIMEOUT_S = old
    assert "no HELLO" in out.getvalue()


def test_stream_mask():
    assert stream_mask(None) == 0b111
    assert stream_mask(["accel", "adc_raw"]) == 0b101
    with pytest.raises(Exception, match="unknown stream"):
        stream_mask(["nope"])


def test_parse_host_port():
    assert parse_host_port("10.0.0.5:7351") == ("10.0.0.5", 7351)
    assert parse_host_port("10.0.0.5") == ("10.0.0.5", 7350)
    assert parse_host_port(":9000") == ("127.0.0.1", 9000)


def test_cli_tail_over_a_pyserial_socket_url(capsys):
    with SimThread(SimConfig(speed=10.0)) as sim:
        rc = cli.main(
            ["tail", "--serial", f"socket://127.0.0.1:{sim.port}", "--duration", "1.2", "--streams", "adc_raw"]
        )
    out = capsys.readouterr().out
    assert (
        rc == 0
        and "adc_raw" in out
        and "accel" not in out.split("final loss summary")[0].split("node ")[1].split("\n", 1)[1]
    )


def test_cli_tail_tcp_refused_gives_exit_1(capsys):
    assert cli.main(["tail", "--tcp", "127.0.0.1:1"]) == 1
    assert "cannot connect" in capsys.readouterr().err


def test_cli_parser_defaults_and_sim_flags():
    ap = cli.build_parser()
    a = ap.parse_args(["sim"])
    assert (a.host, a.port, a.auth, a.speed, a.clock_error) == ("127.0.0.1", 7350, False, 1.0, 0.8)
    a = ap.parse_args(
        ["sim", "--auth", "--clock-error", "-1.5", "--device-drop-rate", "0.01", "--link-drop-rate", "0.02",
         "--corrupt-rate", "0.03", "--speed", "3"]
    )  # fmt: skip
    assert (
        a.auth
        and a.clock_error == -1.5
        and (a.device_drop_rate, a.link_drop_rate, a.corrupt_rate) == (0.01, 0.02, 0.03)
    )
    assert a.speed == 3
    with pytest.raises(SystemExit):
        ap.parse_args(["sim", "--corrupt-rate", "2"])
    with pytest.raises(SystemExit):
        ap.parse_args(["tail", "--tcp", "a:1", "--serial", "COM1"])  # mutually exclusive


# --------------------------------------------------------------------------------- serial port opening


class FakePort:
    """Records the order of attribute writes relative to open()."""

    def __init__(self):
        object.__setattr__(self, "is_open", False)
        object.__setattr__(self, "events", [])

    def __setattr__(self, name, value):
        self.events.append((name, value, self.is_open))
        object.__setattr__(self, name, value)

    def open(self):
        self.events.append(("open", None, self.is_open))
        object.__setattr__(self, "is_open", True)


def test_serial_opens_with_dtr_and_rts_deasserted_before_open(monkeypatch):
    fake = FakePort()
    calls = {}

    def fake_for_url(url, **kw):
        calls.update(url=url, **kw)
        return fake

    monkeypatch.setattr(transport_serial.serial, "serial_for_url", fake_for_url)
    port = open_serial("COM7")
    assert port is fake and calls["do_not_open"] is True
    names = [e[0] for e in fake.events]
    assert names.index("dtr") < names.index("open") and names.index("rts") < names.index("open")
    assert ("dtr", False, False) in fake.events and ("rts", False, False) in fake.events  # False, port still closed


def test_serial_loop_port_has_lines_deasserted():
    port = open_serial("loop://")
    try:
        assert port.dtr is False and port.rts is False and port.is_open
    finally:
        port.close()


def test_serial_transport_reads_and_writes_through_socket_url():
    with SimThread(SimConfig(speed=10.0)) as sim:
        t = SerialTransport(f"socket://127.0.0.1:{sim.port}")
        from rezonating_lab.link.client import LinkClient
        from rezonating_lab.link.codec import GetInfo, Hello

        client = LinkClient(t)
        client.open_session(GetInfo())
        frames = []
        for _ in range(40):
            frames += client.poll(0.05)
            if len(frames) >= 2:
                break
        assert isinstance(frames[0].msg, Hello) and [f.seq for f in frames[:2]] == [0, 1]
        client.close()
    with pytest.raises(serial.SerialException):
        serial.serial_for_url("socket://127.0.0.1:1")


def test_live_line_marks_a_lower_bound_gap_with_a_plus_and_exact_ones_without():
    import numpy as np
    from rezonating_lab.core.monitor import SessionMonitor
    from rezonating_lab.link.codec import Ack, Data, Frame, Status, StreamStatus
    from rezonating_lab.link.vectors import HELLO
    from rezonating_lab.tail import format_stream_line

    def line(device):
        mon = SessionMonitor()
        mon.on_frame(Frame(0, HELLO))
        mon.start_sent(1, 0b001)
        mon.on_frame(Frame(1, Ack(1)))
        for first, n in ((0, 400), (420, 500)):  # a 20-sample hole, then 80 samples still in flight
            mon.on_frame(Frame(2, Data(0, first, 0, np.zeros((n, 2), np.int32))))
        streams = [StreamStatus(0, 1, 1000, device, 2_016_000, 0, 0, 1000, device, 0)]
        streams += [StreamStatus(sid, 0, 0, 0, 0, 0, 0, 0, 0, 0) for sid in (1, 2)]
        mon.on_frame(Frame(3, Status(1, 0, 1, 0, 0, 0, 0, streams)))
        return format_stream_line(1.0, mon.streams[0], 0, 0)

    assert re.search(r"\bgap\s+15\+\s", line(5)), line(5)  # 5 device losses may sit in the tail: at least 15
    assert re.search(r"\bgap\s+20\s", line(0)), line(0)  # nothing to attribute: exact
    assert "+" not in line(0).split("gap")[1].split("pend")[0]


def test_final_summary_shows_resyncs():
    out = io.StringIO()
    with SimThread(SimConfig(speed=10.0)) as sim:
        run_tail(TcpTransport("127.0.0.1", sim.port), duration_s=1.2, out=out)
    assert "resyncs 0" in out.getvalue()
