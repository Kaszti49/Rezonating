"""session.py: the clean-up STOP before START, including the path where its ACK is lost (PROTOCOL.md section 1)."""

import time

import numpy as np
import pytest
from rezonating_lab import session
from rezonating_lab.core.monitor import SessionMonitor
from rezonating_lab.link.client import LinkClient
from rezonating_lab.link.codec import Ack, Data, Frame, Start, Status, StreamStatus, Stop
from rezonating_lab.link.receiver import FROM_PC, Receiver
from rezonating_lab.link.transport_tcp import TcpTransport
from rezonating_lab.link.vectors import HELLO
from rezonating_lab.sim.faults import FaultConfig
from rezonating_lab.sim.node import SimConfig
from rezonating_lab.sim.server import SimThread


class DeafTransport:
    """Accepts writes (and decodes them), never answers: the node's ACK for the clean-up STOP is lost."""

    def __init__(self) -> None:
        self.rx = Receiver(FROM_PC)
        self.sent: list[Frame] = []

    def read(self, timeout_s: float) -> bytes:
        return b""

    def write(self, data: bytes) -> None:
        self.sent += self.rx.feed(data)

    def close(self) -> None:
        pass


def running_status(stream, win_first, win_end):
    streams = [StreamStatus(sid, 0, 0, 0, 0, 0, 0, 0, 0, 0) for sid in (0, 1, 2)]
    streams[stream] = StreamStatus(stream, 1, win_end, 0, 2_000_000, 0, win_first, win_end, 0, 0)
    return Status(1, 0, 1, 0, 0, 0, 0, streams)


def test_lost_clean_up_stop_ack_forces_the_start_and_does_not_hide_the_stale_window():
    t = DeafTransport()
    client = LinkClient(t)
    mon = SessionMonitor()
    mon.on_frame(Frame(0, HELLO))
    # a left-over window of a killed PC: the monitor believes stream 0 runs; its STATUS is not accounted (the gate
    # was closed by the HELLO itself)
    mon.on_frame(Frame(1, Data(0, 0, 0, np.zeros((500, 2), np.int32))))
    mon.on_frame(Frame(2, running_status(0, 0, 600)))
    assert mon.streams[0].running and mon.streams[0].loss() is None

    start_seq = session.begin_recording(client, mon, 0b001, lambda frames: None, stop_timeout_s=0.05)

    assert [type(f.msg) for f in t.sent] == [Stop, Start]  # clean-up STOP first, then START (opening 0x00 aside)
    assert t.sent[0].msg.stream_mask == 0b111 and t.sent[1].msg.stream_mask == 0b001
    assert t.sent[1].seq == start_seq
    sm = mon.streams[0]
    # force=True: the stream looked running but is reset anyway, and STATUS windows are gated until the START ack
    assert sm.awaiting_start and sm.status is None and sm.loss() is None and sm.samples == 0
    assert not sm.stop_acked  # the lost ACK is not assumed
    # a STATUS of the old window before the START ack is ignored, not counted as loss
    mon.on_frame(Frame(3, running_status(0, 0, 9000)))
    assert sm.loss() is None
    # only the START's own ack arms the accounting
    mon.on_frame(Frame(4, Ack(start_seq)))
    assert not sm.awaiting_start
    mon.on_frame(Frame(5, Data(0, 0, 0, np.zeros((100, 2), np.int32))))
    mon.on_frame(Frame(6, running_status(0, 0, 300)))
    rep = sm.loss()
    assert (rep.received, rep.missing, rep.pending) == (100, 200, 200)


def test_acked_clean_up_stop_does_not_force():
    t = DeafTransport()
    client = LinkClient(t)
    mon = SessionMonitor()
    mon.on_frame(Frame(0, HELLO))
    sent_stop: list[int] = []

    def handle(_frames) -> None:
        # answer the STOP the moment it was sent
        if t.sent and not sent_stop and isinstance(t.sent[0].msg, Stop):
            sent_stop.append(t.sent[0].seq)
            mon.on_frame(Frame(1, Ack(t.sent[0].seq)))

    session.begin_recording(client, mon, 0b001, handle, stop_timeout_s=1.0)
    assert sent_stop
    assert mon.streams[0].stop_acked is True and mon.streams[0].awaiting_start


def test_lost_clean_up_stop_ack_end_to_end_gives_no_host_gap():
    """The sim executes the STOP but its ACK is corrupted on the wire; the START still arms, the numbers are exact."""
    state = {"drop_next_ack": False}

    def fault(msg) -> bool:
        if isinstance(msg, Ack) and state["drop_next_ack"]:
            state["drop_next_ack"] = False
            return True
        return False

    cfg = SimConfig(speed=10.0, control_fault=fault, faults=FaultConfig())
    with SimThread(cfg) as sim:
        client = LinkClient(TcpTransport("127.0.0.1", sim.port))
        mon = SessionMonitor()
        frames_seen: list[Frame] = []

        def handle(frames) -> None:
            frames_seen.extend(frames)
            for fr in frames:
                mon.on_frame(fr)

        session.open_session(client, mon, None, handle)
        state["drop_next_ack"] = True
        session.begin_recording(client, mon, 0b111, handle, stop_timeout_s=0.3)
        assert client.rx.bad_frames >= 1  # the corrupted ACK
        assert not any(sm.stop_acked for sm in mon.streams.values())
        for fr in client.drain(1.0):
            handle([fr])
        # armed by the START's ack
        assert all(not sm.awaiting_start for sm in mon.streams.values())
        stop_seq = client.send(Stop(0b111))
        mon.expect_stop_ack(stop_seq, 0b111)
        session.wait_for_reply(client, stop_seq, handle, time.perf_counter, 3.0)
        for sm in mon.streams.values():
            rep = sm.loss()
            assert sm.finalized and rep.host_gap == 0 and rep.received > 0 and rep.win_first == 0
        client.close()


def test_begin_recording_needs_hello():
    client = LinkClient(DeafTransport())
    with pytest.raises(session.SessionError):
        session.begin_recording(client, SessionMonitor(), 1, lambda f: None)
