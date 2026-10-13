"""core/view.py: display maths against synthetic signals with known answers."""

import numpy as np
import pytest
from rezonating_lab.core import view

FS = 2000.0


def sine(f_hz, amp, n, fs=FS, phase=0.0):
    t = np.arange(n) / fs
    return amp * np.sin(2 * np.pi * f_hz * t + phase)


# ------------------------------------------------------------------------------------------ envelope


def test_envelope_bounds_hold_every_sample():
    x = sine(5.0, 1000.0, 20_000)
    env = view.envelope(x, 100)
    assert env.columns == 100 and env.vmin.shape == (100, 1)
    for c in range(100):
        seg = x[env.edges[c] : env.edges[c + 1]]
        assert env.vmin[c, 0] == seg.min() and env.vmax[c, 0] == seg.max()
    assert np.all(env.vmin <= env.vmax)
    assert int(env.n_valid.sum()) == len(x)


def test_envelope_never_loses_a_single_sample_spike():
    x = np.zeros(100_000)
    x[54_321] = 7.0
    x[12_345] = -9.0
    env = view.envelope(x, 500)
    assert env.vmax.max() == 7.0 and env.vmin.min() == -9.0


def test_envelope_with_fewer_samples_than_columns_is_one_per_column():
    x = np.arange(10, dtype=float)
    env = view.envelope(x, 100)
    assert env.columns == 10 and np.array_equal(env.vmin[:, 0], x) and np.array_equal(env.vmax[:, 0], x)


def test_envelope_columns_without_valid_samples_are_nan_and_gaps_are_ignored():
    x = np.full((1000, 2), 5.0)
    x[:, 1] = -3.0
    valid = np.ones(1000, bool)
    valid[200:400] = False
    x[200:400] = 1e9  # garbage under the gap must not leak into the bounds
    env = view.envelope(x, 10, valid)  # columns of 100 samples
    assert np.isnan(env.vmin[2:4]).all() and np.isnan(env.vmax[2:4]).all()
    assert (env.n_valid[2:4] == 0).all()
    assert np.nanmax(env.vmax[:, 0]) == 5.0 and np.nanmin(env.vmin[:, 1]) == -3.0


def test_envelope_empty_input():
    env = view.envelope(np.zeros((0, 2)), 50)
    assert env.columns == 0


# ------------------------------------------------------------------------------------------------ PSD


@pytest.mark.parametrize("f_hz", [50.0, 125.0, 437.5])
def test_psd_peak_is_at_the_right_bin(f_hz):
    x = sine(f_hz, 1.0, 20_000)
    p = view.welch_psd(x, FS, nperseg=1024)
    k = int(np.argmax(p.psd[0]))
    assert abs(p.freq_hz[k] - f_hz) <= FS / 1024  # within one bin
    assert p.n_segments > 30


def test_psd_total_power_of_a_sine_is_amp_squared_over_2():
    x = sine(300.0, 2.0, 40_000)
    p = view.welch_psd(x, FS, nperseg=1024)
    power = float(np.sum(p.psd[0]) * (p.freq_hz[1] - p.freq_hz[0]))
    assert power == pytest.approx(2.0**2 / 2, rel=0.03)


def test_psd_matches_scipy_welch_when_available():
    signal = pytest.importorskip("scipy.signal")
    rng = np.random.default_rng(3)
    x = rng.normal(size=16_384) + sine(200.0, 1.0, 16_384)
    ref_f, ref_p = signal.welch(x, fs=FS, window="hann", nperseg=512, noverlap=256, detrend="constant")
    mine = view.welch_psd(x, FS, nperseg=512)
    assert np.allclose(mine.freq_hz, ref_f)
    assert np.allclose(mine.psd[0], ref_p, rtol=1e-9)


def test_psd_skips_segments_with_gaps():
    x = sine(100.0, 1.0, 8192)
    valid = np.ones(8192, bool)
    valid[3000:3100] = False
    x[3000:3100] = 1e6  # garbage in the gap
    p = view.welch_psd(x, FS, nperseg=512, valid=valid)
    clean = view.welch_psd(sine(100.0, 1.0, 8192), FS, nperseg=512)
    assert 0 < p.n_segments < clean.n_segments
    assert abs(p.freq_hz[int(np.argmax(p.psd[0]))] - 100.0) <= FS / 512
    assert float(p.psd[0].max()) < 2 * float(clean.psd[0].max())  # the garbage did not get in


def test_psd_multichannel_and_short_input():
    x = np.stack([sine(100.0, 1.0, 4096), sine(300.0, 1.0, 4096)], axis=1)
    p = view.welch_psd(x, FS, nperseg=512)
    assert p.psd.shape[0] == 2
    assert abs(p.freq_hz[int(np.argmax(p.psd[0]))] - 100.0) <= 4
    assert abs(p.freq_hz[int(np.argmax(p.psd[1]))] - 300.0) <= 4
    short = view.welch_psd(sine(100.0, 1.0, 100), FS, nperseg=1024)
    assert short.nperseg == 100 and short.n_segments == 1
    assert view.welch_psd(np.zeros(3), FS).n_segments == 0


def test_psd_all_gaps_is_nan_not_zero():
    p = view.welch_psd(np.ones(2048), FS, nperseg=256, valid=np.zeros(2048, bool))
    assert p.n_segments == 0 and np.isnan(p.psd).all()


# ------------------------------------------------------------------------------------------- spectrogram


def test_stft_follows_a_frequency_step():
    n = 8000
    x = np.concatenate([sine(100.0, 1.0, n // 2), sine(600.0, 1.0, n // 2)])
    sp = view.stft_db(x, FS, nfft=256, hop=128, first_index=1000)
    peaks = sp.freq_hz[np.argmax(sp.power_db, axis=1)]
    bin_hz = FS / 256
    first = peaks[sp.center_index < 1000 + n // 2 - 256]
    last = peaks[sp.center_index > 1000 + n // 2 + 256]
    assert np.all(np.abs(first - 100.0) <= bin_hz) and np.all(np.abs(last - 600.0) <= bin_hz)
    assert sp.center_index[0] == 1000 + 128  # first column centre = first_index + nfft / 2
    assert np.all(np.diff(sp.center_index) == 128)


def test_stft_marks_columns_touching_a_gap_as_nan_and_caps_columns():
    x = sine(100.0, 1.0, 4000)
    valid = np.ones(4000, bool)
    valid[1000:1010] = False
    sp = view.stft_db(x, FS, nfft=256, hop=128, valid=valid)
    nan_cols = np.isnan(sp.power_db).all(axis=1)
    assert 0 < nan_cols.sum() < len(nan_cols)
    capped = view.stft_db(sine(100.0, 1.0, 40_000), FS, nfft=256, max_columns=100)
    assert capped.power_db.shape[0] <= 100


def test_stft_level_matches_psd_of_a_sine():
    x = sine(250.0, 1.0, 4096)
    sp = view.stft_db(x, FS, nfft=512)
    psd = view.welch_psd(x, FS, nperseg=512)
    mid = sp.power_db[len(sp.power_db) // 2]
    ref = 10 * np.log10(np.maximum(psd.psd[0], 1e-30))
    k = int(np.argmax(ref))
    assert abs(mid[k] - ref[k]) < 0.5


# -------------------------------------------------------------------------------------------- levels


def test_levels_rms_peak_and_clipping():
    n = 4000
    codes = np.zeros((n, 2), np.int32)
    codes[:, 0] = np.round(sine(50.0, 1000.0, n)).astype(np.int32)
    codes[:, 1] = 100
    codes[10:15, 1] = 2**23 - 1  # 5 samples at positive full scale
    codes[20, 1] = -(2**23)  # 1 at negative full scale
    lv = view.channel_levels(codes, np.array([2e-6, 1.0]), 2**23)
    assert lv[0].rms == pytest.approx(1000 * 2e-6 / np.sqrt(2), rel=0.01)
    assert lv[0].peak == pytest.approx(1000 * 2e-6, rel=0.01)
    assert lv[0].clipped == 0 and lv[1].clipped == 6
    assert lv[1].peak == 2**23


def test_levels_ignore_invalid_samples():
    codes = np.full((100, 1), 10, np.int32)
    valid = np.ones(100, bool)
    valid[:50] = False
    codes[:50] = 2**23 - 1
    lv = view.channel_levels(codes, np.array([1.0]), 2**23, valid)
    assert lv[0].n == 50 and lv[0].clipped == 0 and lv[0].peak == 10.0
    assert np.isnan(view.channel_levels(codes[:0], np.array([1.0]), 2**23)[0].rms)
