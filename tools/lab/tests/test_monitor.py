"""SessionMonitor: which STATUS counts as final, and which STATUS windows are ignored (PROTOCOL.md sections 1, 6)."""

import numpy as np
from rezonating_lab.core.monitor import SessionMonitor
from rezonating_lab.link.codec import Ack, Data, Err, Frame, Status, StreamStatus
from rezonating_lab.link.vectors import HELLO


def frame(msg, seq=0):
    return Frame(seq, msg)


def status(running, win_first, win_end, win_device=0, win_link=0, stream=0):
    streams = [StreamStatus(sid, 0, 0, 0, 0, 0, 0, 0, 0, 0) for sid in (0, 1, 2)]
    streams[stream] = StreamStatus(stream, running, win_end, 0, 2_000_000, 0, win_first, win_end, win_device, win_link)
    return Status(1, 0, 1, 0, 0, 0, 0, streams)


def data(first, n, stream=0):
    return Data(stream, first, 0, np.zeros((n, 2), np.int32))


def new_monitor():
    mon = SessionMonitor()
    mon.on_frame(frame(HELLO))
    return mon


def feed(mon, *msgs):
    for m in msgs:
        mon.on_frame(frame(m))


def test_a_lost_final_status_is_never_reported_complete():
    mon = new_monitor()
    mon.start_sent(1, 0b001)
    feed(mon, Ack(1))
    for first in range(0, 2500, 500):
        feed(mon, data(first, 500))
    feed(mon, status(1, 0, 1000))  # a periodic STATUS
    mon.expect_stop_ack(2, 0b001)
    feed(mon, Ack(2))  # the final STATUS (running = 0) was corrupted on the wire
    sm = mon.streams[0]
    assert not sm.finalized
    rep = sm.loss(session_alive=False)
    assert rep.incomplete and (rep.win_first, rep.win_end) == (0, 1000)  # the last STATUS that did arrive


def test_a_final_status_before_the_ack_makes_the_window_final():
    mon = new_monitor()
    mon.start_sent(1, 0b001)
    feed(mon, Ack(1), data(0, 1000))
    mon.expect_stop_ack(2, 0b001)
    feed(mon, status(0, 0, 1000), Ack(2))
    sm = mon.streams[0]
    assert sm.finalized
    rep = sm.loss()
    assert not rep.incomplete and (rep.missing, rep.host_gap) == (0, 0)


def test_a_running_status_after_stop_is_not_final():
    # a periodic STATUS made before the node handled STOP still says running = 1
    mon = new_monitor()
    mon.start_sent(1, 0b001)
    feed(mon, Ack(1), data(0, 1000))
    mon.expect_stop_ack(2, 0b001)
    feed(mon, status(1, 0, 1000), Ack(2))
    assert not mon.streams[0].finalized


def test_a_status_from_before_stop_was_sent_is_not_final():
    mon = new_monitor()
    mon.start_sent(1, 0b001)
    feed(mon, Ack(1), data(0, 1000), status(0, 0, 1000))  # running = 0, but before our STOP
    mon.expect_stop_ack(2, 0b001)
    feed(mon, Ack(2))
    assert not mon.streams[0].finalized


def test_stop_err_does_not_finalize():
    mon = new_monitor()
    mon.start_sent(1, 0b001)
    feed(mon, Ack(1), data(0, 1000))
    mon.expect_stop_ack(2, 0b001)
    feed(mon, status(0, 0, 1000), Err(2, 4, "bad stream mask"))
    assert not mon.streams[0].finalized


def test_status_windows_before_the_start_ack_are_ignored():
    # a left-over session: STATUS frames of an old window [5000, 9000) arrive before our START is acknowledged
    mon = new_monitor()
    mon.start_sent(7, 0b001)
    feed(mon, status(1, 5000, 9000, win_device=3))
    sm = mon.streams[0]
    assert sm.status is not None and sm.loss() is None  # shown as the last status, not used for accounting
    feed(mon, Ack(7), data(0, 500), status(1, 0, 600))
    rep = sm.loss()
    assert (rep.win_first, rep.win_end, rep.device) == (0, 600, 0)


def test_a_lost_start_ack_is_recovered_by_a_running_status_after_an_acknowledged_stop():
    mon = new_monitor()
    mon.expect_stop_ack(1, 0b111)  # the clean-up STOP before START
    feed(mon, status(0, 5000, 9000), Ack(1))
    mon.start_sent(2, 0b001)
    feed(mon, status(0, 5000, 9000))  # still the old, idle window
    assert mon.streams[0].loss() is None
    feed(mon, data(0, 500), status(1, 0, 600))  # the START ack never came; the node is running our window
    assert mon.streams[0].loss().win_end == 600


def test_without_an_acknowledged_stop_only_the_start_ack_arms():
    mon = new_monitor()
    mon.start_sent(2, 0b001, force=True)
    feed(mon, status(1, 5000, 9000))  # could be the left-over window: ignored
    assert mon.streams[0].loss() is None


def test_start_of_a_running_stream_keeps_its_window():
    mon = new_monitor()
    mon.start_sent(1, 0b001)
    feed(mon, Ack(1), data(0, 500), status(1, 0, 600))
    mon.start_sent(2, 0b001)  # no-op on the node: ACK, no index reset
    feed(mon, Ack(2), data(500, 500), status(1, 0, 1100))
    assert mon.streams[0].loss().received == 1000
