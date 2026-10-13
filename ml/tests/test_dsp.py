"""D-016 decimator and pack dsp biquads: known answers from synthetic sines and impulses."""

from __future__ import annotations

import platform

import numpy as np
import pytest
from scipy import signal

from rezonating_ml.dsp import (
    ADC_CODE_MAX,
    ADC_CODE_MIN,
    DECIM_FIR_TAPS,
    DECIM_GROUP_DELAY_RAW,
    DECIM_RAW_OFFSET,
    DSP_FILTER_FAMILY,
    DSP_FILTER_ORDER,
    Biquad,
    Decimator2,
    biquad_highpass,
    biquad_lowpass,
    dec_to_raw_index,
    design_decimator_taps,
    filter_chain_from_pack,
    to_adc_dec_codes,
)

FS_RAW_HZ = 2000.0
FS_DEC_HZ = 1000.0
X86 = platform.machine().lower() in ("x86_64", "amd64")


def _sine(f_hz: float, fs_hz: float, n: int, amp: float = 1000.0) -> np.ndarray:
    return (amp * np.sin(2 * np.pi * f_hz * np.arange(n) / fs_hz)).astype(np.float32)


def _fit_amp_phase(y: np.ndarray, t_s: np.ndarray, f_hz: float) -> tuple[float, float]:
    """Least-squares fit y ~ A sin(2 pi f t + phi); returns (A, phi)."""
    m = np.column_stack([np.sin(2 * np.pi * f_hz * t_s), np.cos(2 * np.pi * f_hz * t_s)])
    (s, c), *_ = np.linalg.lstsq(m, y.astype(np.float64), rcond=None)
    return float(np.hypot(s, c)), float(np.arctan2(c, s))


def _random_chunks(x: np.ndarray, rng: np.random.Generator, max_len: int) -> list[np.ndarray]:
    cuts, i = [], 0
    while i < x.size:
        n = int(rng.integers(0, max_len + 1))  # 0-length chunks included on purpose
        cuts.append(x[i : i + n])
        i += n
    return cuts


# ------------------------------------------------------------------------------------------- FIR design


def test_frozen_taps_match_the_design():
    designed = design_decimator_taps()
    assert DECIM_FIR_TAPS.dtype == np.float32 and DECIM_FIR_TAPS.shape == (63,)
    # Same design, rounded to float32; allow one float32 ulp in case another scipy version lands a hair apart.
    np.testing.assert_allclose(DECIM_FIR_TAPS, designed.astype(np.float32), rtol=0, atol=6e-8)
    assert np.array_equal(DECIM_FIR_TAPS, DECIM_FIR_TAPS[::-1]), "linear phase needs exact symmetry"
    assert DECIM_GROUP_DELAY_RAW == 31 and DECIM_RAW_OFFSET == -30


def test_frozen_taps_frequency_response():
    w_hz, h = signal.freqz(DECIM_FIR_TAPS.astype(np.float64), worN=1 << 16, fs=FS_RAW_HZ)
    mag_db = 20 * np.log10(np.maximum(np.abs(h), 1e-300))
    passband = mag_db[w_hz <= 400.0]
    stopband = mag_db[w_hz >= 600.0]
    assert passband.max() < 0.001 and passband.min() > -0.001  # measured +0.000094 / -0.000010 dB
    assert stopband.max() < -104.0  # measured -104.5 dB


# ------------------------------------------------------------------------------------------- decimator


@pytest.mark.parametrize("f_hz", [10.0, 100.0, 250.0, 400.0])
def test_decimator_passband_gain_and_index_convention(f_hz):
    x = _sine(f_hz, FS_RAW_HZ, 8000)
    y = Decimator2().process(x)
    k = np.arange(y.size)
    t_s = dec_to_raw_index(k) / FS_RAW_HZ  # time each decimated sample describes
    sl = slice(100, None)  # skip the filter warm-up
    amp, phase = _fit_amp_phase(y[sl], t_s[sl], f_hz)
    assert abs(20 * np.log10(amp / 1000.0)) < 0.002
    assert abs(phase) < 1e-4  # zero phase on the 2k - 30 grid: the group delay is exactly accounted for


@pytest.mark.parametrize("f_hz", [600.0, 750.0, 900.0, 990.0])
def test_decimator_stopband_is_removed_before_folding(f_hz):
    x = _sine(f_hz, FS_RAW_HZ, 8000)
    y = Decimator2().process(x)[100:]
    assert np.max(np.abs(y)) < 1000.0 * 10 ** (-100 / 20)  # >= 100 dB down (design: 104.5 dB)


def test_decimator_impulse_lands_at_documented_index():
    r = 100  # raw index of the impulse (even, so it falls on the decimated grid)
    x = np.zeros(400, dtype=np.float32)
    x[r] = 1.0
    y = Decimator2().process(x)
    k_peak = int(np.argmax(y))
    assert k_peak == (r - DECIM_RAW_OFFSET) // 2 == 65
    assert dec_to_raw_index(k_peak) == r
    # Each output is one tap: y[k] = h[2k + 1 - r]
    for k in range(y.size):
        j = 2 * k + 1 - r
        assert y[k] == (DECIM_FIR_TAPS[j] if 0 <= j < 63 else 0.0)


def test_decimator_counts_every_sample():
    dec = Decimator2()
    sizes = [0, 1, 1, 2, 3, 5, 0, 7]
    total = 0
    for n in sizes:
        dec.process(np.ones(n, dtype=np.float32))
        total += n
        assert dec.n_in == total and dec.n_out == total // 2


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_decimator_chunked_is_byte_identical(seed):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1e5, 6001).astype(np.float32)
    batch = Decimator2().process(x)
    dec = Decimator2()
    parts = [dec.process(c) for c in _random_chunks(x, rng, 300)]
    assert np.concatenate(parts).tobytes() == batch.tobytes()


def test_decimator_accepts_int32_codes():
    codes = np.array([0, 8388607, -8388608, 12345] * 50, dtype=np.int32)
    assert np.array_equal(Decimator2().process(codes), Decimator2().process(codes.astype(np.float32)))


def test_decimator_rejects_2d():
    with pytest.raises(ValueError):
        Decimator2().process(np.zeros((10, 2)))


# ------------------------------------------------------------------------------------------- biquads


@pytest.mark.parametrize(
    ("make", "f_hz", "btype"), [(biquad_highpass, 5.0, "highpass"), (biquad_lowpass, 400.0, "lowpass")]
)
def test_biquad_coefficients_are_butterworth(make, f_hz, btype):
    c = make(f_hz, FS_DEC_HZ)
    b, a = signal.butter(2, f_hz, btype=btype, fs=FS_DEC_HZ)
    np.testing.assert_allclose([c.b0, c.b1, c.b2], b / a[0], rtol=2e-6)
    np.testing.assert_allclose([c.a1, c.a2], a[1:] / a[0], rtol=2e-6)
    assert all(np.float32(v) == v for v in (c.b0, c.b1, c.b2, c.a1, c.a2))


@pytest.mark.parametrize(
    ("make", "f_cut_hz", "f_hz", "gain_db", "tol_db"),
    [
        (biquad_highpass, 5.0, 5.0, -3.0103, 0.01),  # -3 dB at the cutoff
        (biquad_highpass, 5.0, 50.0, -0.0005, 0.01),
        (biquad_lowpass, 400.0, 400.0, -3.0103, 0.01),
        (biquad_lowpass, 400.0, 100.0, 0.0, 0.01),
    ],
)
def test_biquad_sine_gain(make, f_cut_hz, f_hz, gain_db, tol_db):
    n = 6000
    x = _sine(f_hz, FS_DEC_HZ, n)
    y = Biquad(make(f_cut_hz, FS_DEC_HZ)).process(x)
    t_s = np.arange(n) / FS_DEC_HZ
    amp, _ = _fit_amp_phase(y[2000:], t_s[2000:], f_hz)
    assert abs(20 * np.log10(amp / 1000.0) - gain_db) < tol_db


def test_highpass_removes_dc():
    y = Biquad(biquad_highpass(5.0, FS_DEC_HZ)).process(np.full(3000, 5000.0, dtype=np.float32))
    assert np.max(np.abs(y[2000:])) < 1e-2  # 5000 -> below 1e-2


@pytest.mark.skipif(not X86, reason="exact float32 match assumes no fused multiply-add in scipy's build (x86-64)")
def test_biquad_runs_the_documented_recurrence():
    rng = np.random.default_rng(3)
    x = rng.normal(0, 1000, 1500).astype(np.float32)
    c = biquad_highpass(5.0, FS_DEC_HZ)
    got = Biquad(c).process(x)
    f = np.float32
    b0, b1, b2, a1, a2 = (f(v) for v in (c.b0, c.b1, c.b2, c.a1, c.a2))
    z0 = z1 = f(0.0)
    ref = np.empty_like(x)
    for n, xn in enumerate(x):
        yn = f(z0 + f(b0 * xn))
        z0 = f(f(z1 + f(b1 * xn)) - f(a1 * yn))
        z1 = f(f(b2 * xn) - f(a2 * yn))
        ref[n] = yn
    assert np.array_equal(got, ref)


@pytest.mark.parametrize("seed", [0, 1])
def test_filter_chain_chunked_is_byte_identical(seed):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1e4, 5000).astype(np.float32)
    dsp = [{"highpass_hz": 5}, {"lowpass_hz": 400}]
    batch = filter_chain_from_pack(dsp, FS_DEC_HZ).process(x)
    chain = filter_chain_from_pack(dsp, FS_DEC_HZ)
    parts = [chain.process(c) for c in _random_chunks(x, rng, 250)]
    assert np.concatenate(parts).tobytes() == batch.tobytes()


def test_filter_chain_refuses_what_it_does_not_implement():
    with pytest.raises(ValueError, match="decimate"):
        filter_chain_from_pack([{"decimate": 2}], FS_DEC_HZ)
    with pytest.raises(ValueError, match="fs/2"):
        filter_chain_from_pack([{"lowpass_hz": 500}], FS_DEC_HZ)
    with pytest.raises(ValueError, match="exactly one key"):
        filter_chain_from_pack([{"lowpass_hz": 100, "highpass_hz": 5}], FS_DEC_HZ)
    assert filter_chain_from_pack([], FS_DEC_HZ).process(np.arange(3)).dtype == np.float32


# ------------------------------------------------------------------------------------------- lost samples


def _window_has_lost(lost: np.ndarray, n_out: int) -> np.ndarray:
    """Reference: output k is invalid when any raw index in 2k+1-62 .. 2k+1 is lost."""
    return np.array([lost[max(0, 2 * k + 1 - 62) : 2 * k + 2].any() for k in range(n_out)])


def test_lost_samples_are_held_and_flagged():
    rng = np.random.default_rng(5)
    x = (300.0 + rng.normal(0, 20, 2000)).astype(np.float32)
    valid = np.ones(x.size, dtype=bool)
    valid[700:760] = False
    x_zero = x.copy()
    x_zero[~valid] = 0.0  # as a recording stores them
    held = x.copy()
    held[700:760] = x[699]  # hold-previous by hand
    dec = Decimator2()
    y, ok = dec.process_valid(x_zero, valid)
    assert y.tobytes() == Decimator2().process(held).tobytes()
    assert np.array_equal(ok, ~_window_has_lost(~valid, y.size))
    assert dec.n_lost_in == 60 and dec.n_invalid_out == int((~ok).sum()) == 61
    assert np.all(np.abs(y[ok][200:] - 300.0) < 100.0)  # no step towards 0 anywhere


def test_lost_at_start_is_held_as_zero():
    x = np.full(200, 1000.0, dtype=np.float32)
    valid = np.ones(200, dtype=bool)
    valid[:10] = False
    y, ok = Decimator2().process_valid(x, valid)
    expected = x.copy()
    expected[:10] = 0.0  # no good sample yet: 0
    assert y.tobytes() == Decimator2().process(expected).tobytes()
    assert not ok[:36].any() and ok[36:].all()  # window of output k reaches raw 9 while 2k + 1 - 62 <= 9


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_lost_samples_chunked_is_byte_identical(seed):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1e4, 6000).astype(np.float32)
    valid = rng.random(x.size) > 0.002
    for a in rng.integers(0, x.size - 100, 4):
        valid[a : a + int(rng.integers(1, 90))] = False
    x[~valid] = 0.0
    y_b, ok_b = Decimator2().process_valid(x, valid)
    dec = Decimator2()
    ys, oks, i = [], [], 0
    while i < x.size:
        n = int(rng.integers(0, 300))
        y, ok = dec.process_valid(x[i : i + n], valid[i : i + n])
        ys.append(y)
        oks.append(ok)
        i += n
    assert np.concatenate(ys).tobytes() == y_b.tobytes()
    assert np.array_equal(np.concatenate(oks), ok_b)
    assert np.array_equal(ok_b, ~_window_has_lost(~valid, y_b.size))


def test_valid_mask_must_be_bool_of_the_chunk_length():
    with pytest.raises(ValueError, match="valid"):
        Decimator2().process_valid(np.zeros(10), np.ones(9, dtype=bool))
    with pytest.raises(ValueError, match="valid"):
        Decimator2().process_valid(np.zeros(10), np.ones(10))


def test_filter_chain_skips_invalid_samples():
    rng = np.random.default_rng(7)
    x = rng.normal(0, 100, 3000).astype(np.float32)
    valid = np.ones(x.size, dtype=bool)
    valid[1000:1200] = False
    dsp = [{"highpass_hz": 5}, {"lowpass_hz": 400}]
    y = filter_chain_from_pack(dsp, FS_DEC_HZ).process(x, valid)
    assert not y[~valid].any()
    assert y[valid].tobytes() == filter_chain_from_pack(dsp, FS_DEC_HZ).process(x[valid]).tobytes()


def test_process_stages_with_a_mask_matches_process_and_skips_per_section():
    rng = np.random.default_rng(8)
    x = rng.normal(0, 100, 2000).astype(np.float32)
    valid = np.ones(x.size, dtype=bool)
    valid[[0, 1, 500]] = False
    valid[818:825] = False
    dsp = [{"highpass_hz": 5}, {"lowpass_hz": 400}]
    stages = filter_chain_from_pack(dsp, FS_DEC_HZ).process_stages(x, valid)
    assert all(not s[~valid].any() for s in stages)
    assert stages[-1].tobytes() == filter_chain_from_pack(dsp, FS_DEC_HZ).process(x, valid).tobytes()
    plain = filter_chain_from_pack(dsp, FS_DEC_HZ).process_stages(x[valid])
    assert all(s[valid].tobytes() == p.tobytes() for s, p in zip(stages, plain, strict=True))


# ------------------------------------------------------------------------------------------- link codes


def test_adc_dec_codes_round_half_away_and_saturate():
    y = np.array([0.5, -0.5, 1.4999999, 2.5, -2.5, -0.4, 1e7, -1e7, 8388606.6, -8388608.4], dtype=np.float32)
    codes = to_adc_dec_codes(y)
    assert codes.dtype == np.int32
    assert codes.tolist() == [1, -1, 1, 3, -3, 0, 8388607, -8388608, 8388607, -8388608]
    assert ADC_CODE_MIN == -(1 << 23) and ADC_CODE_MAX == (1 << 23) - 1


# ------------------------------------------------------------------------------------------- filter choice


def test_filter_choice_is_the_named_convention():
    assert DSP_FILTER_FAMILY == "butterworth" and DSP_FILTER_ORDER == 2
    chain = filter_chain_from_pack([{"highpass_hz": 5}, {"lowpass_hz": 400}], FS_DEC_HZ)
    for c, btype in zip(chain.sections, ("highpass", "lowpass"), strict=True):
        b, a = signal.butter(DSP_FILTER_ORDER, c.f_hz, btype=btype, fs=FS_DEC_HZ)
        np.testing.assert_allclose([c.b0, c.b1, c.b2, c.a1, c.a2], np.r_[b, a[1:]] / a[0], rtol=2e-6)
