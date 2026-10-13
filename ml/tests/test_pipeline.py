"""build_pipeline(pack_json): stages, known footstep onsets, and chunked == batch byte for byte."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pytest

from rezonating_ml.pipeline import (
    NOT_AVAILABLE,
    STAGE_NAMES,
    LostSampleMismatch,
    build_pipeline,
    concat_outputs,
    run_pipeline,
    sidecar_lost_total,
    valid_from_zero_fill,
    zero_fill_mask,
)
from rezonating_ml.trigger import close_windows
from rezonating_ml.vectors import synthetic_footstep_clip

PACKS = Path(__file__).resolve().parents[2] / "packs"
FOOTSTEP = PACKS / "footstep-id" / "pack.json"


def _assert_same(a, b):
    assert a.start_index == b.start_index
    for name in ("decimated", "filtered", "ratio"):
        xa, xb = getattr(a, name), getattr(b, name)
        if xa is None or xb is None:
            assert xa is None and xb is None
        else:
            assert xa.dtype == xb.dtype == np.float32
            assert xa.tobytes() == xb.tobytes(), name
    assert a.events == b.events
    assert a.windows == b.windows
    assert a.feature_windows == b.feature_windows
    if a.features is None or b.features is None:
        assert a.features is None and b.features is None
    else:
        assert a.features.dtype == b.features.dtype == np.float32
        assert a.features.shape == b.features.shape
        assert a.features.tobytes() == b.features.tobytes(), "features"
    assert a.model == b.model  # ModelOutput compares proba byte for byte


def test_footstep_id_stages():
    pipe = build_pipeline(FOOTSTEP)
    status = {s.name: s.status for s in pipe.stages}
    assert tuple(status) == STAGE_NAMES
    assert status == {
        "decimate": "ok",
        "dsp": "ok",
        "trigger": "ok",
        "features": "ok",
        "model": NOT_AVAILABLE,
    }
    assert "footstep_v1" in next(s for s in pipe.stages if s.name == "features").detail
    model = next(s for s in pipe.stages if s.name == "model")
    assert model.detail == "no model loaded (pack names model.tflite; TFLite export comes later)"


def test_footstep_id_detects_the_synthetic_steps():
    x, step_raw = synthetic_footstep_clip()
    out = run_pipeline(FOOTSTEP, x)
    pipe = build_pipeline(FOOTSTEP)
    assert out.decimated.shape == (x.size // 2,)
    expected = [(r + 30) // 2 for r in step_raw]  # decimated index of each onset (raw = 2k - 30)
    expected = [k for k in expected if k >= 2000]  # the step inside the 2 s warm-up is not an event
    assert len(out.events) == len(expected)
    for ev, k in zip(out.events, expected, strict=True):
        assert k <= ev.onset <= k + 10
        assert abs(pipe.to_input_index(ev.onset) - (2 * k - 30)) <= 20


def test_800hz_tone_and_drift_are_gone_after_dsp():
    x, _ = synthetic_footstep_clip()
    out = run_pipeline(FOOTSTEP, x)
    quiet = out.filtered[1000:2000]  # no step here, after the high-pass settles: noise only
    assert np.std(quiet) < 25.0  # input has 400 amplitude at 800 Hz and 300 +/- 200 offset/drift


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_chunked_is_byte_identical_to_batch(seed):
    x, _ = synthetic_footstep_clip()
    batch = run_pipeline(FOOTSTEP, x)
    rng = np.random.default_rng(seed)
    pipe = build_pipeline(FOOTSTEP)
    outs, i = [], 0
    while i < x.size:
        n = int(rng.integers(0, 1500))
        outs.append(pipe.process(x[i : i + n]))
        i += n
    _assert_same(concat_outputs([*outs, pipe.finish()]), batch)
    assert pipe.n_in == x.size and pipe.n_out == x.size // 2


def test_one_sample_chunks_are_byte_identical():
    x, _ = synthetic_footstep_clip()
    x = x[:5000]
    pipe = build_pipeline(FOOTSTEP)
    outs = [pipe.process(x[i : i + 1]) for i in range(x.size)]
    batch = run_pipeline(FOOTSTEP, x)
    _assert_same(concat_outputs([*outs, pipe.finish()]), batch)
    assert len(batch.windows) == len(batch.events) == 1  # the 2.2 s event's window runs past the end: cut


def test_start_index_and_reset():
    x, _ = synthetic_footstep_clip()
    pipe = build_pipeline(FOOTSTEP)
    a = pipe.process(x[:1001])
    b = pipe.process(x[1001:2000])
    assert a.start_index == 0 and a.decimated.size == 500  # odd raw indices 1..999
    assert b.start_index == 500 and b.decimated.size == 500
    pipe.reset()
    _assert_same(concat_outputs([pipe.process(x), pipe.finish()]), run_pipeline(FOOTSTEP, x))


def test_input_at_pack_rate_bypasses_the_decimator():
    pack = json.loads(FOOTSTEP.read_text(encoding="utf-8"))
    x = np.random.default_rng(0).normal(0, 10, 3000).astype(np.float32)
    pipe = build_pipeline(pack, input_fs_hz=1000.0)
    out = pipe.process(x)
    assert out.stage("decimate").status == "bypassed"
    assert out.decimated.tobytes() == x.tobytes()
    assert pipe.to_input_index(123) == 123
    assert build_pipeline(pack).to_input_index(123) == 2 * 123 - 30


def test_unsupported_input_rate():
    with pytest.raises(ValueError, match="decimator"):
        build_pipeline(FOOTSTEP, input_fs_hz=4000.0)


@pytest.mark.parametrize("pack_id", ["fall", "appliance"])
def test_other_packs_build_and_grey_out_their_trigger(pack_id):
    pipe = build_pipeline(PACKS / pack_id / "pack.json")
    out = pipe.process(np.zeros(100, dtype=np.float32))
    assert out.stage("trigger").status == NOT_AVAILABLE
    assert out.ratio is None and out.events is None and out.features is None
    assert out.stage("dsp").status == "ok"
    expected_dec = "bypassed" if pack_id == "appliance" else "ok"  # appliance runs at 2000 Hz
    assert out.stage("decimate").status == expected_dec


def test_rejects_multichannel_chunk():
    with pytest.raises(ValueError, match="1-D"):
        build_pipeline(FOOTSTEP).process(np.zeros((10, 2), dtype=np.float32))


# ------------------------------------------------------------------------------------------- lost samples


def _quiet_floor(n: int, seed: int = 0) -> np.ndarray:
    """2 kSPS int32 codes: DC offset 300 and noise, no steps."""
    rng = np.random.default_rng(seed)
    return np.round(300.0 + rng.normal(0, 20, n)).astype(np.int32)


def test_zero_filled_gap_needs_the_mask():
    codes = _quiet_floor(12000)
    lost = slice(6000, 6400)  # 200 ms lost, written as zeros like io.WavWriter.write_zeros
    codes[lost] = 0
    valid = valid_from_zero_fill(codes)
    assert not valid[lost].any() and valid[:6000].all() and valid[6400:].all()
    unmasked = run_pipeline(FOOTSTEP, codes)
    masked = run_pipeline(FOOTSTEP, codes, valid=valid)
    assert len(unmasked.events) >= 1  # the step 300 -> 0 -> 300 through the 5 Hz high-pass looks like an event
    assert masked.events == ()
    # output k is invalid when its FIR window 2k+1-62 .. 2k+1 touches raw 6000..6399: k = 3000 .. 3230
    assert np.flatnonzero(~masked.valid).tolist() == list(range(3000, 3231))
    assert not masked.filtered[~masked.valid].any() and not masked.ratio[~masked.valid].any()


def test_valid_from_zero_fill_keeps_short_zero_runs():
    codes = np.array([5, 0, 0, 0, 7] + [0] * 8 + [3], dtype=np.int32)
    assert valid_from_zero_fill(codes).tolist() == [True] * 5 + [False] * 8 + [True]
    assert valid_from_zero_fill(codes, min_run=3).tolist() == [True] + [False] * 3 + [True] + [False] * 8 + [True]


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_lost_samples_chunked_is_byte_identical(seed):
    x, _ = synthetic_footstep_clip()
    rng = np.random.default_rng(seed)
    valid = np.ones(x.size, dtype=bool)
    for a in rng.integers(0, x.size - 300, 3):
        valid[a : a + int(rng.integers(1, 300))] = False
    x = x.copy()
    x[~valid] = 0.0
    batch = run_pipeline(FOOTSTEP, x, valid=valid)
    pipe = build_pipeline(FOOTSTEP)
    outs, i = [], 0
    while i < x.size:
        n = int(rng.integers(0, 1500))
        outs.append(pipe.process(x[i : i + n], valid[i : i + n]))
        i += n
    joined = concat_outputs([*outs, pipe.finish()])
    _assert_same(joined, batch)
    assert np.array_equal(joined.valid, batch.valid)
    assert pipe.n_lost_in == int((~valid).sum()) and pipe.n_invalid_out == int((~batch.valid).sum())


def test_valid_is_all_true_without_a_mask_and_passes_through_at_pack_rate():
    x, _ = synthetic_footstep_clip()
    assert run_pipeline(FOOTSTEP, x).valid.all()
    valid = np.ones(3000, dtype=bool)
    valid[100:110] = False
    out = run_pipeline(FOOTSTEP, x[:3000], input_fs_hz=1000.0, valid=valid)
    assert np.array_equal(out.valid, valid)


# ----------------------------------------------------- short losses: the 1/3/7-sample probe (re-verify finding)


def _short_gap_recording(n_lost: int, n_ch: int = 2) -> np.ndarray:
    """(12000, n_ch) int32 frames: a quiet floor on every channel, ``n_lost`` frames zero-filled at raw 6000."""
    frames = np.stack([_quiet_floor(12000, seed=ch) for ch in range(n_ch)], axis=1)
    frames[6000 : 6000 + n_lost] = 0  # io.WavWriter.write_zeros zeroes whole frames
    return frames


def test_short_zero_fill_gap_gives_a_false_event_with_the_old_single_channel_heuristic():
    """Without the fix: runs < 8 are not marked, and a 3- or 7-sample gap looks like a footstep."""
    for n_lost in (3, 7):
        ch0 = _short_gap_recording(n_lost)[:, 0]
        valid = valid_from_zero_fill(ch0)  # one channel, min_run 8, no expected count: the old behaviour
        assert valid.all()
        out = run_pipeline(FOOTSTEP, ch0, valid=valid)
        assert len(out.events) == 1, n_lost
        onset_raw = 2 * out.events[0].onset - 30
        assert 6000 <= onset_raw <= 6000 + 400  # the event is the gap, not a step


@pytest.mark.parametrize("n_lost", [1, 3, 7])
def test_short_gap_on_one_channel_is_exact_when_every_zero_is_lost(n_lost):
    """One channel, no other zeros: the sidecar count equals the all-zero frames, so all of them are the loss."""
    ch0 = _short_gap_recording(n_lost)[:, 0]
    m = zero_fill_mask(ch0, expected_lost=n_lost)  # min_run 8 would miss the gap; E == Z settles it
    assert np.flatnonzero(~m.valid).tolist() == list(range(6000, 6000 + n_lost))
    assert m.covers_all_lost and m.n_surplus == 0
    assert run_pipeline(FOOTSTEP, ch0, valid=m.valid).events == ()


def _zero_mean_channel(n: int, sigma: float, seed: int) -> np.ndarray:
    """One live channel without a DC offset: it hits exactly 0 by chance, in isolated frames."""
    return np.round(np.random.default_rng(seed).normal(0, sigma, n)).astype(np.int32)


@pytest.mark.parametrize("n_lost", [1, 3, 7])
def test_short_gap_among_chance_zeros_on_one_channel_is_caught_by_the_count(n_lost):
    ch = _zero_mean_channel(12000, 20.0, seed=5)
    ch[6000 : 6000 + n_lost] = 0
    n_chance = int((ch == 0).sum()) - n_lost
    assert n_chance > 50  # many isolated zeros: min_run 8 must not mark them, so it can't see the gap either
    with pytest.raises(LostSampleMismatch, match=f"mark 0 lost frames, the sidecar loss totals {n_lost}.*unmarked"):
        valid_from_zero_fill(ch, expected_lost=n_lost)
    with pytest.warns(UserWarning, match="left unmarked"):
        m = zero_fill_mask(ch, expected_lost=n_lost, strict=False)
    assert not m.covers_all_lost and m.n_surplus is None
    # min_run=1 covers it, at the cost of the chance zeros
    m1 = zero_fill_mask(ch, min_run=1, expected_lost=n_lost)
    assert m1.covers_all_lost and not m1.valid[6000 : 6000 + n_lost].any() and m1.n_surplus == n_chance


@pytest.mark.parametrize("n_lost", [1, 3, 7])
def test_short_gap_is_masked_frame_wise_and_gives_no_event(n_lost):
    frames = _short_gap_recording(n_lost)
    loss = {"device": n_lost, "link": 0, "host": 0}
    valid = valid_from_zero_fill(frames, expected_lost=sidecar_lost_total(loss))
    assert np.flatnonzero(~valid).tolist() == list(range(6000, 6000 + n_lost))
    for ch in range(frames.shape[1]):
        out = run_pipeline(FOOTSTEP, frames[:, ch], valid=valid)
        assert out.events == () and out.windows == ()
        assert not out.valid.all()  # the loss is visible downstream, never hidden


def test_single_channel_min_run_1_with_the_count_also_works():
    ch0 = _short_gap_recording(3)[:, 0]
    valid = valid_from_zero_fill(ch0, min_run=1, expected_lost=3)
    assert run_pipeline(FOOTSTEP, ch0, valid=valid).events == ()


def test_frame_wise_ignores_a_zero_on_one_channel_only():
    frames = _short_gap_recording(0)
    frames[100:120, 0] = 0  # one head reads 0 (e.g. shorted); the other channel is live: not a lost frame
    assert valid_from_zero_fill(frames, expected_lost=0).all()
    # On that channel alone the 20 zeros are candidates, but the sidecar says nothing was lost: real data.
    m = zero_fill_mask(frames[:, 0], min_run=1, expected_lost=0)
    assert m.valid.all() and m.n_zero_frames == 20 and m.covers_all_lost and m.n_surplus == 0


def test_zero_fill_rejects_bad_arguments():
    with pytest.raises(ValueError, match="shape"):
        valid_from_zero_fill(np.zeros((2, 2, 2), dtype=np.int32))
    with pytest.raises(ValueError, match="min_run"):
        valid_from_zero_fill(np.ones(4, dtype=np.int32), min_run=0)
    with pytest.raises(ValueError, match="expected_lost"):
        valid_from_zero_fill(np.ones(4, dtype=np.int32), expected_lost=-1)


# ------------------------------------------------------------------------- windows and Event.n_invalid


def test_windows_repeat_events_with_n_invalid_once_complete():
    x, _ = synthetic_footstep_clip()
    out = run_pipeline(FOOTSTEP, x)
    assert all(e.n_invalid is None for e in out.events)
    complete = [e for e in out.events if e.end <= out.decimated.size]
    assert [(e.onset, e.start, e.end) for e in out.windows] == [(e.onset, e.start, e.end) for e in complete]
    assert all(w.n_invalid == 0 for w in out.windows)
    assert "n_invalid" not in out.events[0].as_dict() and out.windows[0].as_dict()["n_invalid"] == 0


def test_window_holding_a_lost_sample_counts_it():
    x, _ = synthetic_footstep_clip()
    clean = run_pipeline(FOOTSTEP, x)
    ev = clean.windows[0]
    pipe = build_pipeline(FOOTSTEP)
    k = ev.onset + 50  # inside the post window, after the onset: the trigger has already fired
    raw = int(pipe.to_input_index(k)) + 30  # a raw sample in the FIR window of decimated k
    valid = np.ones(x.size, dtype=bool)
    valid[raw] = False
    x2 = x.copy()
    x2[raw] = 0.0
    lost = run_pipeline(FOOTSTEP, x2, valid=valid)
    bad = int((~lost.valid[ev.start : ev.end]).sum())
    assert bad > 0
    w = next(w for w in lost.windows if w.onset == ev.onset)
    assert w.n_invalid == bad
    assert all(o.n_invalid == 0 for o in lost.windows if o.onset != ev.onset)
    # chunked gives the same windows, in the chunk where each one completes
    pipe = build_pipeline(FOOTSTEP)
    outs = [pipe.process(x2[i : i + 333], valid[i : i + 333]) for i in range(0, x2.size, 333)]
    _assert_same(concat_outputs([*outs, pipe.finish()]), lost)
    assert pipe.n_windows_invalid == 1


def test_unknown_feature_set_is_not_available_with_its_name():
    pack = json.loads(FOOTSTEP.read_text(encoding="utf-8"))
    pipe = build_pipeline({**pack, "features": "footstep_v9"})
    out = pipe.process(synthetic_footstep_clip()[0][:4000])
    assert out.stage("features").status == NOT_AVAILABLE and "'footstep_v9'" in out.stage("features").detail
    assert out.features is None and out.feature_windows is None and out.model is None
    assert out.stage("model").status == NOT_AVAILABLE


# ------------------------------------------- the zero-fill mask contract (verify-3 finding 1: false mismatch)


def _two_channels(n: int, sigma: float, seed: int, correlated: bool = False) -> np.ndarray:
    """(n, 2) int32 frames of two live zero-mean heads; they hit an all-zero frame by chance now and then."""
    rng = np.random.default_rng(seed)
    if correlated:  # the same floor vibration on both heads, plus a little noise of their own
        common = rng.normal(0, sigma, n)
        return np.round(np.stack([common, common + rng.normal(0, 0.3, n)], axis=1)).astype(np.int32)
    return np.round(rng.normal(0, sigma, (n, 2))).astype(np.int32)


@pytest.mark.parametrize("correlated", [False, True])
def test_loss_free_two_channel_file_with_chance_all_zero_frames_is_accepted_as_is(correlated):
    frames = _two_channels(120_000, 10.0, seed=1, correlated=correlated)  # 1 min at 2 kSPS
    n_zero = int(np.all(frames == 0, axis=1).sum())
    assert n_zero >= 1  # real all-zero frames: they used to raise LostSampleMismatch with expected_lost=0
    m = zero_fill_mask(frames, expected_lost=0)
    assert m.valid.all() and m.covers_all_lost and m.n_surplus == 0 and m.n_zero_frames == n_zero
    assert valid_from_zero_fill(frames, expected_lost=0).all()


def test_the_verifiers_all_zero_frame_at_16649():
    frames = _two_channels(40_000, 30.0, seed=2, correlated=True)
    frames[16649] = 0  # a real frame where both correlated heads read exactly 0
    assert valid_from_zero_fill(frames, expected_lost=0).all()


def _lose(frames: np.ndarray, runs: list[tuple[int, int]]) -> tuple[np.ndarray, np.ndarray]:
    """Zero-fill ``runs`` as the recorder does; returns (frames, true lost mask)."""
    frames = frames.copy()
    lost = np.zeros(frames.shape[0], dtype=bool)
    for a, b in runs:
        frames[a:b] = 0
        lost[a:b] = True
    return frames, lost


def test_two_channel_loss_among_chance_zero_frames_covers_with_surplus():
    frames, lost = _lose(_two_channels(120_000, 10.0, seed=3), [(0, 2), (5000, 5001), (7000, 7003), (9000, 9007)])
    frames, lost2 = _lose(frames, [(60_000, 60_040)])
    lost |= lost2
    n_zero = int(np.all(frames == 0, axis=1).sum())
    e = int(lost.sum())
    assert n_zero > e  # chance zeros on top of the loss: the positions are ambiguous
    m = zero_fill_mask(frames, expected_lost=e)  # used to raise: more marked than the sidecar total
    assert m.covers_all_lost and not m.valid[lost].any()  # every lost frame is marked
    assert m.n_marked == n_zero and m.n_surplus == n_zero - e  # the cost, reported, never hidden


def test_sidecar_total_above_the_all_zero_frames_raises():
    frames, _ = _lose(_two_channels(20_000, 100.0, seed=4), [(100, 110)])
    n_zero = int(np.all(frames == 0, axis=1).sum())
    with pytest.raises(LostSampleMismatch, match=f"only {n_zero} all-zero frames"):
        zero_fill_mask(frames, expected_lost=n_zero + 1)
    with pytest.warns(UserWarning, match="not zeros"):
        m = zero_fill_mask(frames, expected_lost=n_zero + 1, strict=False)
    assert not m.covers_all_lost and m.n_surplus is None


def test_one_channel_count_check_stays_two_way():
    ch = _zero_mean_channel(40_000, 20.0, seed=6)  # isolated chance zeros: min_run 8 leaves them valid
    ch[10_000:10_040] = 0  # a 40-frame loss
    with pytest.warns(UserWarning, match="backed by the count only"):
        ok = zero_fill_mask(ch, expected_lost=40)
    assert not ok.valid[10_000:10_040].any() and int((~ok.valid).sum()) == 40
    assert not ok.covers_all_lost and ok.n_surplus is None  # backed by the count only
    missed = ch.copy()
    missed[20_000:20_003] = 0  # plus a 3-frame loss the runs can't see
    with pytest.raises(LostSampleMismatch, match="left unmarked"):
        zero_fill_mask(missed, expected_lost=43)
    dead = ch.copy()
    dead[30_000:30_010] = 0  # plus a head reading exactly 0 for 10 frames: real data, but a run like a loss
    with pytest.raises(LostSampleMismatch, match="ambiguous"):
        zero_fill_mask(dead, expected_lost=40)


def test_one_channel_with_long_zero_runs_only_covers_with_surplus():
    ch = _short_gap_recording(40)[:, 0]  # DC offset: no chance zeros
    ch[9000:9010] = 0  # a head reading exactly 0 for 10 frames (real data)
    m = zero_fill_mask(ch, expected_lost=40)  # used to raise: 50 marked, sidecar 40
    assert m.covers_all_lost and m.n_surplus == 10 and not m.valid[6000:6040].any()


def test_without_the_sidecar_total_the_runs_are_unchecked():
    m = zero_fill_mask(_short_gap_recording(40)[:, 0])
    assert not m.covers_all_lost and m.n_surplus is None and m.expected_lost is None and m.n_marked == 40


@pytest.mark.parametrize("seed", range(40))
def test_mask_contract_holds_on_random_recordings(seed):
    """Property: only all-zero frames are marked; covers_all_lost means every lost frame is marked; with two or
    more channels and the default min_run it always covers (never a mismatch while the sidecar is right)."""
    rng = np.random.default_rng(seed)
    n_ch = int(rng.integers(1, 4))
    sigma = float(rng.choice([3.0, 10.0, 30.0]))
    offset = float(rng.choice([0.0, 300.0]))
    frames = np.round(offset + rng.normal(0, sigma, (20_000, n_ch))).astype(np.int32)
    runs = []
    for _ in range(int(rng.integers(0, 6))):
        a = int(rng.integers(0, 19_900))
        runs.append((a, a + int(rng.choice([1, 2, 3, 7, 40]))))
    frames, lost = _lose(frames, runs)
    zero = np.all(frames == 0, axis=1)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        m = zero_fill_mask(frames, expected_lost=int(lost.sum()), strict=False)
    assert zero[~m.valid].all()
    if m.covers_all_lost:
        assert not m.valid[lost].any() and m.n_surplus == m.n_marked - int(lost.sum()) >= 0
    if n_ch >= 2:
        assert m.covers_all_lost and not caught


# ------------------------------------------------- end of stream (verify-3 finding 2: windows left pending)


def test_finish_reports_the_window_the_end_of_the_stream_cuts():
    x, _ = synthetic_footstep_clip()
    pipe = build_pipeline(FOOTSTEP)
    out = pipe.process(x[:8300])  # 4150 pack-rate samples; the 4.0 s event's window runs to 4420
    assert [e.onset for e in out.events] == [2218, 2819, 3420, 4020]
    assert [w.onset for w in out.windows] == [2218, 2819, 3420] and all(w.n_invalid == 0 for w in out.windows)
    assert pipe.n_events == 4 and pipe.n_windows == 3 and pipe.n_windows_pending == 1
    fin = pipe.finish()
    assert fin.start_index == 4150 and fin.decimated.size == fin.ratio.size == 0 and fin.events == ()
    (cut,) = fin.windows
    assert (cut.onset, cut.start, cut.end) == (4020, 3920, 4420) and cut.n_invalid == 4420 - 4150
    assert pipe.n_windows_pending == 0 and pipe.n_events == pipe.n_windows == 4
    assert pipe.n_windows_invalid == pipe.n_windows_cut == 1
    assert pipe.finish().windows == ()  # nothing left
    with pytest.raises(RuntimeError, match="reset"):
        pipe.process(x[:10])
    pipe.reset()
    assert pipe.n_events == pipe.n_windows_cut == 0 and pipe.process(x[:10]).decimated.size == 5


def test_run_pipeline_reports_every_event_once():
    x, _ = synthetic_footstep_clip()
    out = run_pipeline(FOOTSTEP, x[:8300])
    assert [w.onset for w in out.windows] == [e.onset for e in out.events]
    assert [w.n_invalid for w in out.windows] == [0, 0, 0, 270]


def test_cut_window_also_counts_its_lost_samples():
    x, _ = synthetic_footstep_clip()
    valid = np.ones(8300, dtype=bool)
    valid[8100:8110] = False  # lost raw samples inside the cut window, before the end
    x2 = x[:8300].copy()
    x2[~valid] = 0.0
    out = run_pipeline(FOOTSTEP, x2, valid=valid)
    cut = out.windows[-1]
    assert cut.n_invalid == 270 + int((~out.valid[cut.start :]).sum()) and cut.n_invalid > 270


@pytest.mark.parametrize("seed", range(6))
def test_window_n_invalid_matches_the_reference_rule(seed):
    """The pipeline's incremental count (invalid runs, pruned as it goes) equals trigger.window_n_invalid on the
    whole stream's mask, for every window, chunked, with lost samples and a stream that ends anywhere."""
    x, _ = synthetic_footstep_clip()
    rng = np.random.default_rng(seed)
    n = int(rng.integers(6000, x.size + 1))
    x = x[:n].copy()
    valid = np.ones(n, dtype=bool)
    for a in rng.integers(4000, n - 10, 6):
        valid[a : a + int(rng.integers(1, 60))] = False
    x[~valid] = 0.0
    pipe = build_pipeline(FOOTSTEP)
    outs, i = [], 0
    while i < n:
        k = int(rng.integers(1, 900))
        outs.append(pipe.process(x[i : i + k], valid[i : i + k]))
        i += k
    joined = concat_outputs([*outs, pipe.finish()])
    assert list(joined.windows) == close_windows(joined.events, joined.valid)
    assert pipe.n_windows_invalid == sum(1 for w in joined.windows if w.n_invalid)


def test_finish_without_a_trigger_has_no_windows():
    pipe = build_pipeline(PACKS / "fall" / "pack.json")
    pipe.process(np.zeros(100, dtype=np.float32))
    out = pipe.finish()
    assert out.windows is None and out.events is None and out.ratio is None and pipe.n_windows_pending == 0
