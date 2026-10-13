"""STA/LTA trigger: synthetic footstep bursts at known indices, warm-up, refractory and chunking rules."""

from __future__ import annotations

import platform

import numpy as np
import pytest

from rezonating_ml.trigger import (
    Event,
    StaLta,
    StaLtaParams,
    close_windows,
    detect_events,
    events_from_ratio,
    window_n_invalid,
)

FS_HZ = 1000.0
PACK_TRIGGER = {"type": "sta_lta", "sta_ms": 50, "lta_ms": 2000, "ratio": 3.5, "pre_ms": 100, "post_ms": 400}
PARAMS = StaLtaParams.from_pack(PACK_TRIGGER)
X86 = platform.machine().lower() in ("x86_64", "amd64")


def _clip(onsets: list[int], n: int, seed: int = 0, amp: float = 50.0) -> np.ndarray:
    """Noise (sigma 1) plus 35 Hz bursts decaying with 25 ms, starting exactly at ``onsets``."""
    rng = np.random.default_rng(seed)
    x = rng.normal(0.0, 1.0, n)
    for i0 in onsets:
        t_s = np.arange(n - i0) / FS_HZ
        x[i0:] += amp * np.exp(-t_s / 0.025) * np.sin(2 * np.pi * 35.0 * t_s)
    return x.astype(np.float32)


def test_params_in_samples():
    assert PARAMS.samples(FS_HZ) == {"n_sta": 50, "n_lta": 2000, "n_pre": 100, "n_post": 400}


def test_bad_trigger_config():
    with pytest.raises(ValueError, match="not sta_lta"):
        StaLtaParams.from_pack({"type": "threshold", "level": 1.0})
    with pytest.raises(ValueError, match="missing"):
        StaLtaParams.from_pack({"type": "sta_lta", "sta_ms": 50, "ratio": 3})
    with pytest.raises(ValueError, match="n_sta"):
        StaLtaParams(sta_ms=100, lta_ms=50, ratio=3).samples(FS_HZ)


def test_footsteps_detected_at_their_onsets():
    onsets = [2500, 3100, 3700, 4300, 4900]
    _, events = detect_events(_clip(onsets, 6000), PARAMS, FS_HZ)
    assert len(events) == len(onsets)
    for ev, true in zip(events, onsets, strict=True):
        assert true <= ev.onset <= true + 10  # the STA needs a few samples of burst energy
        assert ev.start == ev.onset - 100 and ev.end == ev.onset + 400


def test_no_event_during_warm_up():
    _, events = detect_events(_clip([500, 2600], 4000), PARAMS, FS_HZ)
    assert [e.onset for e in events if e.onset < 2000] == []
    assert len(events) == 1 and 2600 <= events[0].onset <= 2610


def test_refractory_merges_steps_closer_than_post():
    _, close = detect_events(_clip([2500, 2700], 4000), PARAMS, FS_HZ)  # 200 ms apart < post 400 ms
    _, apart = detect_events(_clip([2500, 3000], 4000), PARAMS, FS_HZ)  # 500 ms apart
    assert len(close) == 1
    assert len(apart) == 2 and apart[1].onset - apart[0].onset >= 400


def test_sustained_high_ratio_gives_one_event():
    rng = np.random.default_rng(1)
    x = rng.normal(0, 1, 6000)
    t_s = np.arange(3000) / FS_HZ
    x[3000:] *= 20.0 * np.exp(1.5 * t_s)  # keeps growing, so the ratio stays above 3.5 (about 6)
    ratio, events = detect_events(x.astype(np.float32), PARAMS, FS_HZ)
    assert np.all(ratio[3010:] >= 3.5)
    assert len(events) == 1 and 3000 <= events[0].onset <= 3005  # one onset, not one per refractory period


def test_level_jump_retriggers_only_after_the_ratio_dips():
    # A step in background level: the ratio falls below 3.5 once the LTA catches up (about 0.6 s here), and
    # STA noise may then cross again. Known STA/LTA behaviour without a separate off-ratio; events stay >= post.
    rng = np.random.default_rng(1)
    x = rng.normal(0, 1, 6000)
    x[3000:] *= 20.0
    ratio, events = detect_events(x.astype(np.float32), PARAMS, FS_HZ)
    assert 3000 <= events[0].onset <= 3005
    onsets = [e.onset for e in events]
    assert all(b - a >= 400 for a, b in zip(onsets, onsets[1:], strict=False))
    for a, b in zip(onsets, onsets[1:], strict=False):
        assert np.any(ratio[a + 400 : b] < 3.5)  # re-armed only after a dip below the threshold


def test_ratio_is_zero_while_lta_is_zero():
    ratio, events = detect_events(np.zeros(3000, dtype=np.float32), PARAMS, FS_HZ)
    assert ratio.dtype == np.float32 and not ratio.any() and events == []


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_chunked_is_byte_identical(seed):
    rng = np.random.default_rng(seed)
    x = _clip([2300, 2900, 3500, 3600, 4400, 5100], 7000, seed=seed)
    ratio_b, events_b = detect_events(x, PARAMS, FS_HZ)
    trig = StaLta(PARAMS, FS_HZ)
    ratios, events = [], []
    i = 0
    while i < x.size:
        n = int(rng.integers(0, 400))
        r, ev = trig.process(x[i : i + n])
        ratios.append(r)
        events += ev
        i += n
    assert np.concatenate(ratios).tobytes() == ratio_b.tobytes()
    assert events == events_b and all(isinstance(e, Event) for e in events)


@pytest.mark.skipif(not X86, reason="exact float32 match assumes no fused multiply-add in scipy's build (x86-64)")
def test_averages_run_the_documented_recurrence():
    x = _clip([2500], 3000)
    trig = StaLta(PARAMS, FS_HZ)
    got = trig.ratio(x)
    f = np.float32
    c_s, c_l = f(1) / f(50), f(1) / f(2000)
    d_s, d_l = f(f(1) - c_s), f(f(1) - c_l)
    sta = lta = f(0)
    ref = np.empty_like(x)
    for n, xn in enumerate(x):
        cf = f(xn * xn)
        sta = f(f(d_s * sta) + f(c_s * cf))
        lta = f(f(d_l * lta) + f(c_l * cf))
        ref[n] = f(sta / lta) if lta > 0 else f(0)
    assert np.array_equal(got, ref)


# ------------------------------------------------------------------------------------------- lost samples


def test_lost_samples_are_skipped_not_fed_as_zeros():
    rng = np.random.default_rng(4)
    x = rng.normal(0, 1, 9000).astype(np.float32)
    valid = np.ones(x.size, dtype=bool)
    valid[3000:6000] = False
    x_zero = x.copy()
    x_zero[~valid] = 0.0
    # Fed as data, 3 s of zeros drain the LTA and plain noise afterwards looks like an event.
    _, ev_zero = detect_events(x_zero, PARAMS, FS_HZ)
    assert any(6000 <= e.onset < 6100 for e in ev_zero)
    # Skipped: the averages resume where they stopped, ratio 0 in the gap, no event.
    ratio, ev_skip = detect_events(x_zero, PARAMS, FS_HZ, valid=valid)
    assert ev_skip == [] and not ratio[~valid].any()
    assert ratio[valid].tobytes() == StaLta(PARAMS, FS_HZ).ratio(x[valid]).tobytes()


@pytest.mark.parametrize("seed", [0, 1])
def test_lost_samples_chunked_is_byte_identical(seed):
    rng = np.random.default_rng(seed)
    x = _clip([2300, 2900, 3500, 4400, 5100], 7000, seed=seed)
    valid = np.ones(x.size, dtype=bool)
    valid[2950:3100] = False
    valid[4000:4010] = False
    ratio_b, events_b = detect_events(x, PARAMS, FS_HZ, valid=valid)
    trig = StaLta(PARAMS, FS_HZ)
    ratios, events, i = [], [], 0
    while i < x.size:
        n = int(rng.integers(0, 400))
        r, ev = trig.process(x[i : i + n], valid[i : i + n])
        ratios.append(r)
        events += ev
        i += n
    assert np.concatenate(ratios).tobytes() == ratio_b.tobytes()
    assert events == events_b and len(events_b) >= 4


def test_events_from_ratio_is_the_same_rule():
    x = _clip([2500, 3100, 3700], 5000)
    ratio, events = detect_events(x, PARAMS, FS_HZ)
    assert events_from_ratio(ratio, PARAMS, FS_HZ) == events


def test_trigger_events_leave_n_invalid_unknown():
    """The trigger emits at the onset, before the window is complete: n_invalid is None and not in as_dict."""
    ev = Event(10, 0, 20)
    assert ev.n_invalid is None and ev.as_dict() == {"onset": 10, "start": 0, "end": 20}
    assert Event(10, 0, 20, n_invalid=3).as_dict()["n_invalid"] == 3


def test_window_n_invalid_counts_invalid_and_missing_samples():
    valid = np.ones(100, dtype=bool)
    valid[[10, 11, 50]] = False
    assert window_n_invalid(Event(20, 5, 30), valid) == 2  # inside
    assert window_n_invalid(Event(60, 40, 60), valid) == 1
    assert window_n_invalid(Event(5, -5, 15), valid) == 5 + 2  # before index 0: no sample there
    assert window_n_invalid(Event(95, 90, 130), valid) == 30  # past the end of the stream
    assert window_n_invalid(Event(150, 120, 160), valid) == 40  # wholly past the end
    assert window_n_invalid(Event(0, -10, 0), valid) == 10
    assert window_n_invalid(Event(0, -3, 3), np.ones(0, dtype=bool)) == 6  # empty stream
    out = close_windows([Event(20, 5, 30), Event(95, 90, 130)], valid)
    assert [e.n_invalid for e in out] == [2, 30] and [e.onset for e in out] == [20, 95]
