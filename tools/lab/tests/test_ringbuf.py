"""SampleRing: samples sit at their index, gaps stay gaps, nothing shifts."""

import numpy as np
from rezonating_lab.core.ringbuf import SampleRing


def block(first, n, n_ch=2):
    """Samples whose value encodes the index, so a shift is visible: ch0 = index, ch1 = -index."""
    idx = np.arange(first, first + n, dtype=np.int32)
    return np.stack([idx, -idx][:n_ch], axis=1)


def test_in_order_write_and_read_back():
    ring = SampleRing(2, 1000)
    ring.write(0, block(0, 300))
    ring.write(300, block(300, 200))
    lo, data, valid = ring.read(0, 500)
    assert lo == 0 and valid.all()
    assert np.array_equal(data, block(0, 500))
    assert ring.head == 500 and ring.base == 0 and ring.written == 500


def test_a_hole_stays_a_gap_and_later_samples_do_not_shift():
    ring = SampleRing(2, 1000)
    ring.write(0, block(0, 100))
    ring.write(160, block(160, 40))  # indices 100..159 never arrived
    lo, data, valid = ring.read(0, 200)
    assert valid[:100].all() and not valid[100:160].any() and valid[160:].all()
    assert np.array_equal(data[160:], block(160, 40))  # still at their own index
    assert not data[100:160].any()  # a gap reads as zeros with valid False


def test_late_samples_fill_the_gap():
    ring = SampleRing(2, 1000)
    ring.write(0, block(0, 100))
    ring.write(150, block(150, 50))
    ring.write(100, block(100, 50))
    lo, data, valid = ring.read(0, 200)
    assert valid.all() and np.array_equal(data, block(0, 200))


def test_wraps_around_and_keeps_only_capacity():
    ring = SampleRing(2, 100)
    for first in range(0, 450, 30):
        ring.write(first, block(first, 30))
    assert ring.head == 450
    assert ring.oldest() == 350
    lo, data, valid = ring.read(0, 450)
    assert lo == 350 and valid.all() and np.array_equal(data, block(350, 100))


def test_a_gap_across_the_wrap_clears_old_data():
    ring = SampleRing(1, 100)
    ring.write(0, block(0, 100, 1))
    ring.write(150, block(150, 20, 1))  # 100..149 lost; their ring positions still hold data of 0..49
    lo, data, valid = ring.read(0, 170)
    assert lo == 70  # the ring holds 70..169
    assert {lo + i for i in np.flatnonzero(valid)} == set(range(70, 100)) | set(range(150, 170))
    assert np.array_equal(data[:30], block(70, 30, 1))


def test_a_huge_jump_invalidates_everything_older():
    ring = SampleRing(1, 100)
    ring.write(0, block(0, 100, 1))
    ring.write(10_000, block(10_000, 10, 1))
    lo, data, valid = ring.read(0, 10_010)
    assert {lo + i for i in np.flatnonzero(valid)} == set(range(10_000, 10_010))


def test_too_old_samples_are_counted_not_stored():
    ring = SampleRing(1, 100)
    ring.write(1000, block(1000, 100, 1))
    ring.write(0, block(0, 50, 1))
    assert ring.late_dropped == 50 and ring.head == 1100


def test_reset_starts_a_new_epoch_with_restarted_indices():
    ring = SampleRing(2, 1000)
    ring.write(5000, block(5000, 100))
    assert ring.epoch == 0
    assert ring.reset() == 1
    assert ring.head == 0 and ring.base is None and ring.read(0, 10)[1].shape == (0, 2)
    ring.write(0, block(0, 50))
    lo, data, valid = ring.read(0, 100)
    assert lo == 0 and len(valid) == 50 and valid.all()


def test_runs_since_gives_valid_runs_and_skips_gaps():
    ring = SampleRing(2, 1000)
    ring.write(0, block(0, 100))
    ring.write(120, block(120, 30))
    runs, cursor, epoch = ring.runs_since(0)
    assert cursor == 150 and epoch == 0
    assert [(f, len(d)) for f, d in runs] == [(0, 100), (120, 30)]
    assert np.array_equal(runs[1][1], block(120, 30))
    ring.write(150, block(150, 10))
    runs, cursor, _ = ring.runs_since(cursor)
    assert [(f, len(d)) for f, d in runs] == [(150, 10)] and cursor == 160
    assert ring.runs_since(cursor) == ([], 160, 0)


def test_runs_since_splits_long_runs():
    ring = SampleRing(1, 1000)
    ring.write(0, block(0, 500, 1))
    runs, _, _ = ring.runs_since(0, max_frames=200)
    assert [(f, len(d)) for f, d in runs] == [(0, 200), (200, 200), (400, 100)]


def test_read_last():
    ring = SampleRing(2, 1000)
    ring.write(0, block(0, 300))
    lo, data, valid = ring.read_last(50)
    assert lo == 250 and np.array_equal(data, block(250, 50))
