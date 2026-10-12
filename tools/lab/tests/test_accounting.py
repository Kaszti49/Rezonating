import random
import time

from rezonating_lab.core.accounting import IntervalSet, StreamAccounting


def test_interval_set_matches_a_python_set():
    rng = random.Random(11)
    iv, ref = IntervalSet(), set()
    for _ in range(400):
        a = rng.randrange(0, 300)
        b = a + rng.randrange(0, 12)
        new = iv.add(a, b)
        before = len(ref)
        ref |= set(range(a, b))
        assert new == len(ref) - before
        assert len(iv) == len(ref)
    for lo, hi in ((0, 50), (17, 17), (100, 250), (0, 400), (290, 305)):
        assert iv.count_in(lo, hi) == len([x for x in ref if lo <= x < hi])
    # intervals are disjoint, sorted and not touching
    spans = iv.intervals()
    assert all(a < b for a, b in spans)
    assert all(spans[i][1] < spans[i + 1][0] for i in range(len(spans) - 1))


def test_interval_set_last_below():
    iv = IntervalSet()
    iv.add(10, 20)
    iv.add(30, 40)
    assert iv.last_below(5) is None
    assert iv.last_below(15) == 14
    assert iv.last_below(25) == 19
    assert iv.last_below(100) == 39


def test_hours_at_2ksps_stay_one_interval():
    iv = IntervalSet()
    n = 80
    t0 = time.perf_counter()
    for k in range(90_000):  # 1 hour of 80-frame packets at 2 kSPS = 7.2 M samples
        iv.add(k * n, (k + 1) * n)
    assert iv.n_intervals == 1 and len(iv) == 90_000 * n
    assert time.perf_counter() - t0 < 2.0
    assert iv.count_in(1_000, 7_200_000) == 7_200_000 - 1_000


def _acct(received, win, device=0, link=0):
    acc = StreamAccounting()
    for a, b in received:
        acc.on_data(a, b - a)
    acc.on_status(win[0], win[1], device, link)
    return acc


def test_no_loss():
    rep = _acct([(100, 1100)], (100, 1100)).report("final")
    assert (rep.missing, rep.device, rep.link, rep.host_gap) == (0, 0, 0, 0)
    assert not rep.protocol_bug and not rep.incomplete


def test_three_kinds_of_loss_add_up():
    # window 1000 samples; 30 lost on the device, 20 never handed to the transport, 50 sent but not received
    received = [(0, 100), (130, 400), (420, 600), (650, 1000)]  # holes: 30 + 20 + 50
    rep = _acct(received, (0, 1000), device=30, link=20).report("final")
    assert rep.missing == 100
    assert rep.host_gap == 50
    assert rep.missing == rep.device + rep.link + rep.host_gap


def test_samples_outside_the_window_do_not_count():
    rep = _acct([(0, 500), (500, 2000)], (500, 1500)).report("final")
    assert rep.received == 1000 and rep.missing == 0


def test_duplicates_are_not_double_counted():
    acc = StreamAccounting()
    acc.on_data(0, 100)
    acc.on_data(50, 100)
    assert acc.duplicates == 50
    acc.on_status(0, 150, 0, 0)
    assert acc.report("final").missing == 0


def test_negative_host_gap_is_a_protocol_bug():
    rep = _acct([(0, 1000)], (0, 1000), device=5).report("final")
    assert rep.host_gap == -5 and rep.protocol_bug


def test_live_view_shows_the_tail_as_pending_not_lost():
    # STATUS says the window ends at 1000, DATA has only arrived up to 920
    rep = _acct([(0, 920)], (0, 1000)).report("live")
    assert rep.pending == 80
    assert rep.host_gap == 0 and not rep.protocol_bug
    # a hole before the last received index is a real gap even in the live view
    rep = _acct([(0, 400), (420, 920)], (0, 1000)).report("live")
    assert rep.pending == 80 and rep.host_gap == 20


def test_live_view_with_nothing_received_yet():
    rep = _acct([], (0, 1000)).report("live")
    assert rep.pending == 1000 and rep.host_gap == 0


def test_session_lost_without_final_status_is_loss_incomplete():
    # last STATUS: window [0, 1000); data stops at 900: the missing tail is host_gap, and the report says so
    rep = _acct([(0, 900)], (0, 1000), device=0, link=0).report("incomplete")
    assert rep.incomplete and rep.pending == 0
    assert rep.missing == 100 and rep.host_gap == 100


def test_no_window_yet():
    assert StreamAccounting().report() is None
    assert _acct([(0, 10)], (0, 0)).report("final").missing == 0


def test_reset_forgets_everything():
    acc = _acct([(0, 100)], (0, 100))
    acc.reset()
    assert len(acc.received) == 0 and acc.report() is None


def test_incomplete_report_carries_the_sidecar_note():
    from rezonating_lab.core.accounting import LOSS_INCOMPLETE_NOTE

    assert LOSS_INCOMPLETE_NOTE == "rzlab: loss=incomplete"
    assert _acct([(0, 900)], (0, 1000)).report("incomplete").sidecar_note == LOSS_INCOMPLETE_NOTE
    assert _acct([(0, 1000)], (0, 1000)).report("final").sidecar_note is None


def test_live_host_gap_is_a_lower_bound_when_device_losses_may_sit_in_the_tail():
    # window [0, 1000), received up to 920 with a 20-sample hole, tail of 80 still in flight.
    # The node says 5 samples were lost on the device: they may be in the hole or in the tail.
    rep = _acct([(0, 400), (420, 920)], (0, 1000), device=5).report("live")
    assert rep.pending == 80
    assert rep.host_gap == 15  # assumes all 5 are in the hole: the smallest possible
    assert rep.host_gap_max == 20  # all 5 in the tail: the whole hole is host loss
    assert not rep.host_gap_exact
    # same with link losses
    rep = _acct([(0, 400), (420, 920)], (0, 1000), link=5).report("live")
    assert (rep.host_gap, rep.host_gap_max, rep.host_gap_exact) == (15, 20, False)


def test_live_host_gap_is_exact_without_device_or_link_loss_or_without_a_tail():
    rep = _acct([(0, 400), (420, 920)], (0, 1000)).report("live")
    assert (rep.host_gap, rep.host_gap_max, rep.host_gap_exact) == (20, 20, True)
    rep = _acct([(0, 400), (420, 1000)], (0, 1000), device=5).report("live")  # nothing pending
    assert (rep.host_gap, rep.host_gap_max, rep.host_gap_exact) == (15, 15, True)


def test_final_and_incomplete_reports_are_always_exact():
    for mode in ("final", "incomplete"):
        rep = _acct([(0, 400), (420, 920)], (0, 1000), device=5, link=5).report(mode)
        assert rep.host_gap_exact and rep.host_gap == rep.host_gap_max == 90
