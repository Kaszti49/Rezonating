"""Test vectors for the firmware: decimator, pack dsp biquads and STA/LTA (D-016, D-021).

Regenerate after changing any of those stages, then tell the firmware side::

    python -m rezonating_ml.vectors --write            # into ml/tests/vectors/
    python -m rezonating_ml.vectors --check            # compare the current code with the files

Every file holds ``input``, ``expected``, the parameters and a ``tolerance``. Float values (inputs, outputs, taps,
biquad coefficients, tolerances) are float32 written in their shortest round-trip form (read them as float64 and
cast to float32 to get the exact bits). Python on x86-64 reproduces the files exactly.

Lost samples: ``decimator_fir.json`` has a ``valid`` mask over its input; ``dsp_biquads.json`` and
``sta_lta.json`` have a ``masked`` case (a ``valid`` mask over the same input, and its own ``expected``). The
masks hold short runs (1 to 7 samples), a run at index 0 and a longer run, so the hold-previous rule (0 before the
first good sample), the skip rule and the window ``n_invalid`` count (including a window the end of the stream
cuts) all have values for the firmware to match.

**Build requirement:** the firmware ``dsp`` and trigger sources are compiled with ``-ffp-contract=off``. Each
tolerance is still derived from measurements, not chosen: 10x the larger of (a) the error of an FMA emulation
(every ``a*b + c`` fused, product exact in float64, one rounding to float32) and (b) the error of a float64
reference, both against ``expected``. So a contracted build should pass too, with headroom.

The input is a deterministic synthetic clip (:func:`synthetic_footstep_clip`), never a recording.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from scipy import signal

from .dsp import (
    DECIM_FIR_TAPS,
    DECIM_IN_FS_HZ,
    DECIM_OUT_FS_HZ,
    DECIM_RAW_OFFSET,
    BiquadCoeffs,
    Decimator2,
    FilterChain,
    filter_chain_from_pack,
    to_adc_dec_codes,
)
from .trigger import Event, StaLta, StaLtaParams, close_windows

__all__ = [
    "CLIP_SEED",
    "FOOTSTEP_ID_DSP",
    "FOOTSTEP_ID_TRIGGER",
    "VECTOR_FILES",
    "build_vectors",
    "check_vectors",
    "default_vector_dir",
    "synthetic_footstep_clip",
    "write_vectors",
]

# 2027, not 2026: with 2026 one ratio sample lies within 2e-5 of the threshold, closer than the vector
# tolerance, so a firmware build that rounds differently could flip an event. build_vectors() asserts the margin.
CLIP_SEED = 2027
# Copied from packs/footstep-id/pack.json (2026-10-13) so the vectors don't change when the pack is tuned;
# the pack test checks the pipeline reads the same keys.
FOOTSTEP_ID_DSP: list[dict[str, float]] = [{"highpass_hz": 5}, {"lowpass_hz": 400}]
FOOTSTEP_ID_TRIGGER: dict[str, Any] = {
    "type": "sta_lta",
    "sta_ms": 50,
    "lta_ms": 2000,
    "ratio": 3.5,
    "pre_ms": 100,
    "post_ms": 400,
}
VECTOR_FILES = ("decimator_fir.json", "dsp_biquads.json", "sta_lta.json")

_CLIP_DURATION_S = 4.5
_STEP_TIMES_S = (0.8, 2.2, 2.8, 3.4, 4.0)  # the 0.8 s step falls in the 2 s STA/LTA warm-up: no event
_DEC_VECTOR_RAW = 4000
_DSP_VECTOR_DEC = 2500
# Lost runs [a, b), written as zeros in the input as in a WAV. Raw indices for the decimator: 3 before the first
# good sample (held at 0), 1 at an odd and 2 at an even index, 7, and 40.
_DEC_LOST_RAW = ((0, 3), (1001, 1002), (1300, 1302), (1700, 1707), (2500, 2540))
# Pack-rate indices for the dsp masked case: 2 at index 0, 1, 7 inside the 0.8 s step's ring-down, 40.
_DSP_LOST = ((0, 2), (500, 501), (818, 825), (1500, 1540))
# Pack-rate indices for the sta_lta masked case, on the first _STA_MASKED_N samples: 5 at index 0 and 1 + 7 in the
# warm-up; 5 over the 2.2 s step's onset (the onset moves to the first valid sample after them); 3 in the 2.8 s
# event's post window; 3 between events. The stream ends inside the last event's window, which is reported cut.
_STA_LOST = ((0, 5), (1500, 1501), (1700, 1707), (2216, 2221), (2830, 2833), (3250, 3253))
_STA_MASKED_N = 4300
_HEADROOM = 10.0
_FLOOR_ABS = 1e-3  # tolerance floor: never ask for less than this (codes units)
_IDX_NOTE = "Sample indices are 64-bit (u64, D-018) in the firmware; they never wrap."
_BUILD_NOTE = "Firmware builds the dsp/trigger sources with -ffp-contract=off (no fused multiply-add)."


def synthetic_footstep_clip(seed: int = CLIP_SEED) -> tuple[np.ndarray, list[int]]:
    """A 4.5 s, 2 kSPS synthetic geophone clip in ADC-code-like units, and the raw index of each step onset.

    Contents: Gaussian noise (sigma 20), a DC offset (300) with a 0.5 Hz drift (amplitude 200) for the high-pass,
    an 800 Hz tone (amplitude 400) that the decimator must remove, and five "footsteps": 35 Hz sinusoids decaying
    with a 25 ms time constant, amplitude 3000, starting at :data:`_STEP_TIMES_S`.

    Returns ``(x, step_raw)``: ``x`` is ``(9000,)`` float32; ``step_raw`` lists the onset raw indices.
    """
    rng = np.random.default_rng(seed)
    n = int(round(_CLIP_DURATION_S * DECIM_IN_FS_HZ))
    t_s = np.arange(n) / DECIM_IN_FS_HZ
    x = rng.normal(0.0, 20.0, n)
    x += 300.0 + 200.0 * np.sin(2 * np.pi * 0.5 * t_s)
    x += 400.0 * np.sin(2 * np.pi * 800.0 * t_s)
    step_raw = []
    for t0_s in _STEP_TIMES_S:
        i0 = int(round(t0_s * DECIM_IN_FS_HZ))
        tt_s = t_s[i0:] - t_s[i0]
        x[i0:] += 3000.0 * np.exp(-tt_s / 0.025) * np.sin(2 * np.pi * 35.0 * tt_s)
        step_raw.append(i0)
    return x.astype(np.float32), step_raw


def _f32_list(a: np.ndarray) -> list[float]:
    """float32 values as the shortest decimal that round-trips to the same float32."""
    return [float(str(v)) for v in np.asarray(a, dtype=np.float32)]


# ------------------------------------------------------------------- FMA and float64 references (tolerances)


def _hold_previous(x: np.ndarray, lost: np.ndarray) -> np.ndarray:
    good_idx = np.maximum.accumulate(np.where(lost, -1, np.arange(x.size)))
    return np.where(good_idx >= 0, x[np.maximum(good_idx, 0)], 0.0).astype(np.float32)


def _fir_alt(x: np.ndarray, lost: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Decimator outputs (fused, float64) for a stream from index 0."""
    ext = np.concatenate([np.zeros(62, np.float32), _hold_previous(x, lost)])
    pos = np.arange(1, x.size, 2) + 62
    fused = np.zeros(pos.size, dtype=np.float32)
    ref = np.zeros(pos.size, dtype=np.float64)
    h = DECIM_FIR_TAPS.astype(np.float64)
    for j in range(63):
        prod = h[j] * ext[pos - j].astype(np.float64)
        fused = (prod + fused.astype(np.float64)).astype(np.float32)  # fma(h, x, acc)
        ref += prod
    return fused, ref


def _biquad_alt(c: BiquadCoeffs, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """One biquad, fused (every a*b + c contracted) and float64."""

    def f(v: float) -> float:
        return float(np.float32(v))

    b0, b1, b2, a1, a2 = c.b0, c.b1, c.b2, c.a1, c.a2  # float32 values held exactly in Python floats
    z0 = z1 = 0.0
    out = np.empty(x.size, dtype=np.float32)
    for n, xn in enumerate(x.tolist()):
        y = f(b0 * xn + z0)  # fma(b0, x, z0)
        z0 = f(-a1 * y + f(b1 * xn + z1))  # fma(-a1, y, fma(b1, x, z1))
        z1 = f(-a2 * y + f(b2 * xn))  # fma(-a2, y, b2*x)
        out[n] = y
    ref = signal.lfilter(np.array([b0, b1, b2]), np.array([1.0, a1, a2]), x.astype(np.float64))
    return out, ref


def _ratio_alt(x: np.ndarray, n_sta: int, n_lta: int) -> tuple[np.ndarray, np.ndarray]:
    """STA/LTA ratio, fused (s = fma(d, s, c*cf)) and float64."""
    f32 = np.float32
    c_s, c_l = f32(1) / f32(n_sta), f32(1) / f32(n_lta)
    d_s, d_l = f32(f32(1) - c_s), f32(f32(1) - c_l)
    cf = (x * x).astype(np.float32)
    sta = lta = 0.0
    fused = np.zeros(x.size, dtype=np.float32)
    for n, v in enumerate(cf.tolist()):
        sta = float(f32(float(d_s) * sta + float(f32(c_s * f32(v)))))
        lta = float(f32(float(d_l) * lta + float(f32(c_l * f32(v)))))
        fused[n] = f32(sta / lta) if lta > 0 else f32(0)
    cf64 = x.astype(np.float64) ** 2
    s64 = signal.lfilter([1.0 / n_sta], [1.0, -(1.0 - 1.0 / n_sta)], cf64)
    l64 = signal.lfilter([1.0 / n_lta], [1.0, -(1.0 - 1.0 / n_lta)], cf64)
    ref = np.divide(s64, l64, out=np.zeros_like(s64), where=l64 > 0)
    return fused, ref


def _max_abs(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.max(np.abs(a.astype(np.float64) - b.astype(np.float64)))) if a.size else 0.0


def _valid_mask(n: int, lost_runs: Sequence[tuple[int, int]]) -> np.ndarray:
    valid = np.ones(n, dtype=bool)
    for a, b in lost_runs:
        valid[a:b] = False
    return valid


def _dsp_err(chain_sections: Sequence[BiquadCoeffs], x: np.ndarray, stages: Sequence[np.ndarray]) -> float:
    """Largest FMA-emulation or float64-reference error over every section (``x`` and ``stages`` valid-only)."""
    err = 0.0
    sec_in = x
    for c, out in zip(chain_sections, stages, strict=True):
        fused, ref = _biquad_alt(c, sec_in)
        err = max(err, _max_abs(fused, out), _max_abs(ref, out))
        sec_in = out
    return err


def _ratio_case(
    x: np.ndarray, valid: np.ndarray, params: StaLtaParams, fs_hz: float, seed: int, label: str
) -> tuple[np.ndarray, list[Event], float, float]:
    """Ratio and events with the skip rule, the measured relative error and the threshold margin (valid samples).

    Raises when the FMA emulation or the float64 reference would give other events.
    """
    trig = StaLta(params, fs_hz)
    ratio, events = trig.process(x, None if valid.all() else valid)
    idx = np.flatnonzero(valid).astype(np.int64)
    rc = ratio[idx]
    r_fused, r_ref = _ratio_alt(x[idx], trig.n_sta, trig.n_lta)
    scale = np.maximum(np.abs(rc.astype(np.float64)), 1.0)
    err = max(
        float(np.max(np.abs(r_fused - rc.astype(np.float64)) / scale)),
        float(np.max(np.abs(r_ref - rc.astype(np.float64)) / scale)),
    )
    margin = float(np.min(np.abs(rc[idx >= trig.n_lta] - trig.on)) / trig.on)
    for name, alt in (("FMA emulation", r_fused), ("float64 reference", r_ref)):
        if StaLta(params, fs_hz)._step(np.asarray(alt, dtype=np.float32), idx) != events:
            raise RuntimeError(f"seed {seed}, {label}: events differ under the {name}; pick another seed")
    return ratio, events, err, margin


def _f32_num(v: float) -> float:
    return float(str(np.float32(v)))


def _section_dict(c: BiquadCoeffs) -> dict[str, Any]:
    """A biquad's parameters with the five float32 coefficients in shortest float32 form (as every vector value)."""
    d: dict[str, Any] = c.as_dict()
    for k in ("b0", "b1", "b2", "a1", "a2"):
        d[k] = _f32_num(d[k])
    return d


def build_vectors(seed: int = CLIP_SEED) -> dict[str, dict[str, Any]]:
    """Compute all vector files from the synthetic clip with the current code."""
    x_raw, step_raw = synthetic_footstep_clip(seed)
    common = {
        "generator": "python -m rezonating_ml.vectors --write",
        "clip": f"rezonating_ml.vectors.synthetic_footstep_clip(seed={seed})",
        "build": _BUILD_NOTE,
    }

    # Decimator: integer codes (as the ADC gives), with runs of lost samples written as zeros (as in a WAV).
    dec_in = np.round(x_raw[:_DEC_VECTOR_RAW]).astype(np.float32)
    dec_valid = _valid_mask(dec_in.size, _DEC_LOST_RAW)
    dec_in[~dec_valid] = 0.0
    dec_out, dec_ok = Decimator2().process_valid(dec_in, dec_valid)
    dec_codes = to_adc_dec_codes(dec_out)
    fir_fused, fir_ref = _fir_alt(dec_in, ~dec_valid)
    fir_err = max(_max_abs(fir_fused, dec_out), _max_abs(fir_ref, dec_out))
    code_diff = int(np.max(np.abs(to_adc_dec_codes(fir_fused).astype(np.int64) - dec_codes)))
    decimator = {
        "name": "decimator_fir",
        "decisions": ["D-016", "D-021"],
        "description": (
            "63-tap FIR then keep the outputs at odd raw indices: decimated[k] = sum_j taps[j]*x[2k+1-j], "
            "j = 0..62 ascending, float32, x[n<0] = 0. decimated[k] describes raw index 2k + raw_offset. "
            "Lost raw samples (valid = false; zeros in the input, as a WAV stores them) are replaced inside the "
            "FIR by the previous good raw sample (0 if none yet); expected_valid[k] is false when any raw sample "
            "in the FIR window 2k+1-62 .. 2k+1 was lost (the node counts it as device_dropped and does not send "
            "it); expected also holds those invalid outputs. Lost runs [a, b): "
            f"{', '.join(f'[{a}, {b})' for a, b in _DEC_LOST_RAW)} (the first one before any good sample). "
            "expected_codes = what the adc_dec link stream sends: round half away from zero (lroundf), "
            f"saturate to -8388608..8388607. {_IDX_NOTE}"
        ),
        **common,
        "fs_in_hz": DECIM_IN_FS_HZ,
        "fs_out_hz": DECIM_OUT_FS_HZ,
        "group_delay_raw": 31,
        "raw_offset": DECIM_RAW_OFFSET,
        "taps": _f32_list(DECIM_FIR_TAPS),
        "tolerance": {
            "abs": _f32_num(max(_HEADROOM * fir_err, _FLOOR_ABS)),
            "codes_abs": max(code_diff, 1),
            "measured_err": _f32_num(fir_err),
            "note": "abs on expected = 10x the larger of the FMA-emulation and float64-reference errors "
            "(floor 1e-3); codes may differ by 1 where a value lies within rounding error of a half; "
            "expected_valid must match exactly.",
        },
        "input": [int(v) for v in dec_in],
        "valid": [bool(v) for v in dec_valid],
        "expected": _f32_list(dec_out),
        "expected_valid": [bool(v) for v in dec_ok],
        "expected_codes": [int(v) for v in dec_codes],
    }

    fs_hz = DECIM_OUT_FS_HZ
    dec_full = Decimator2().process(x_raw)
    chain = filter_chain_from_pack(FOOTSTEP_ID_DSP, fs_hz)
    dsp_in = dec_full[:_DSP_VECTOR_DEC]
    stages = chain.process_stages(dsp_in)
    dsp_valid = _valid_mask(dsp_in.size, _DSP_LOST)
    chain.reset()  # the masked case starts from zero state too
    m_stages = chain.process_stages(dsp_in, dsp_valid)
    dsp_err = max(
        _dsp_err(chain.sections, dsp_in, stages),
        _dsp_err(chain.sections, dsp_in[dsp_valid], [s[dsp_valid] for s in m_stages]),
    )
    dsp = {
        "name": "dsp_biquads",
        "decisions": ["D-021"],
        "description": (
            "footstep-id dsp: each entry one 2nd-order Butterworth biquad (DSP_FILTER_FAMILY/ORDER; RBJ cookbook, "
            "Q = 1/sqrt(2), computed in double, normalised by a0, rounded to float32), transposed direct form II "
            "in float32, zero state: y = z0 + b0*x; z0 = (z1 + b1*x) - a1*y; z1 = b2*x - a2*y. Input = the "
            "decimated clip; expected[i] = output after section i. masked: the same input with valid = false at "
            "the lost (invalid) samples; every section skips them: no state update, output 0, and the input "
            "value there is ignored (it is not zero)."
        ),
        **common,
        "fs_hz": fs_hz,
        "dsp": FOOTSTEP_ID_DSP,
        "sections": [_section_dict(c) for c in chain.sections],
        "tolerance": {
            "abs": _f32_num(max(_HEADROOM * dsp_err, _FLOOR_ABS)),
            "measured_err": _f32_num(dsp_err),
            "note": "abs, every section, both cases = 10x the larger of the FMA-emulation and float64-reference "
            "errors (the 5 Hz high-pass on the clip's DC offset dominates).",
        },
        "input": _f32_list(dsp_in),
        "expected": [_f32_list(s) for s in stages],
        "masked": {"valid": [bool(v) for v in dsp_valid], "expected": [_f32_list(s) for s in m_stages]},
    }

    filt_full = filter_chain_from_pack(FOOTSTEP_ID_DSP, fs_hz).process(dec_full)
    params = StaLtaParams.from_pack(FOOTSTEP_ID_TRIGGER)
    smp = params.samples(fs_hz)
    ratio, events, ratio_err, margin_rel = _ratio_case(
        filt_full, np.ones(filt_full.size, dtype=bool), params, fs_hz, seed, "unmasked"
    )
    sta_in = filt_full[:_STA_MASKED_N]
    sta_valid = _valid_mask(sta_in.size, _STA_LOST)
    m_ratio, m_events, m_err, m_margin = _ratio_case(sta_in, sta_valid, params, fs_hz, seed, "masked")
    m_windows = close_windows(m_events, sta_valid)
    tol_rel = max(_HEADROOM * max(ratio_err, m_err), 1e-6)
    for label, margin in (("unmasked", margin_rel), ("masked", m_margin)):
        if margin < tol_rel:
            raise RuntimeError(
                f"seed {seed}, {label}: a ratio sample lies {margin:.1e} (relative) from the threshold, inside the "
                f"vector tolerance {tol_rel:.1e}; events would not be robust across implementations. "
                "Pick another seed."
            )
    sta_lta = {
        "name": "sta_lta",
        "decisions": ["D-021"],
        "description": (
            "Recursive STA/LTA on cf = x*x, float32: s = fl(fl(d*s) + fl(c*cf)), c = 1.0f/N, d = 1.0f - c, "
            "s starts at 0; ratio = sta/lta (0 when lta <= 0). Trigger: no event while n < n_lta; then the "
            "ratio must be < ratio_on once before arming; armed: first n with ratio >= ratio_on is an onset, "
            "event [onset - n_pre, onset + n_post); refractory until n >= max(onset + n_post, onset + 1), then "
            "wait-low again. Invalid (lost) samples are skipped: no update, ratio 0, neither low nor high, the "
            "input value there is ignored; warm-up and refractory still count them (they are time). "
            f"Input = the decimated, filtered clip. {_IDX_NOTE} The global index n and quiet_until "
            "(the refractory end) are int64/uint64. The trigger emits an event at its onset (no n_invalid). "
            "Every event is then reported once as a window with n_invalid = samples of [start, end) that are "
            "invalid, before index 0, or at or past the end of the stream (when the stream ends before end); "
            "the features stage skips windows with n_invalid > 0 and counts the skip. masked: the stream is "
            "input[:len(valid)] with that valid mask, and it ends there (the last window is cut)."
        ),
        **common,
        "fs_hz": fs_hz,
        "trigger": FOOTSTEP_ID_TRIGGER,
        "samples": smp,
        "step_onsets_dec_approx": [int(round((r - DECIM_RAW_OFFSET) / 2)) for r in step_raw],
        "tolerance": {
            "rel": _f32_num(tol_rel),
            "measured_err_rel": _f32_num(max(ratio_err, m_err)),
            "note": "on ratio, relative to max(|ratio|, 1), both cases = 10x the larger of the FMA-emulation and "
            "float64-reference errors; events and windows must match exactly (checked to hold under both).",
        },
        "threshold_margin_rel": _f32_num(margin_rel),
        "input": _f32_list(filt_full),
        "expected": {"ratio": _f32_list(ratio), "events": [e.as_dict() for e in events]},
        "masked": {
            "valid": [bool(v) for v in sta_valid],
            "threshold_margin_rel": _f32_num(m_margin),
            "expected": {
                "ratio": _f32_list(m_ratio),
                "events": [e.as_dict() for e in m_events],
                "windows": [w.as_dict() for w in m_windows],
            },
        },
    }
    return {"decimator_fir.json": decimator, "dsp_biquads.json": dsp, "sta_lta.json": sta_lta}


def _dumps(obj: dict[str, Any]) -> str:
    """One top-level key per line, values compact (keeps diffs readable and files small)."""
    lines = [f"  {json.dumps(k)}: {json.dumps(v, separators=(',', ':'))}" for k, v in obj.items()]
    return "{\n" + ",\n".join(lines) + "\n}\n"


def default_vector_dir() -> Path:
    """``ml/tests/vectors`` of the checkout this package is installed from (editable install)."""
    return Path(__file__).resolve().parents[2] / "tests" / "vectors"


def write_vectors(out_dir: Path, seed: int = CLIP_SEED) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, obj in build_vectors(seed).items():
        path = out_dir / name
        path.write_text(_dumps(obj), encoding="utf-8")
        written.append(path)
    return written


def _f32(a: Sequence[float]) -> np.ndarray:
    return np.asarray(a, dtype=np.float64).astype(np.float32)


def check_vectors(vec_dir: Path) -> list[str]:
    """Run the current code on each file's input and compare with its expected output. Returns the problems."""
    problems: list[str] = []
    vec_dir = Path(vec_dir)
    for name in VECTOR_FILES:
        path = vec_dir / name
        if not path.is_file():
            problems.append(f"{name}: missing")
            continue
        v = json.loads(path.read_text(encoding="utf-8"))
        if name == "decimator_fir.json":
            if not np.array_equal(_f32(v["taps"]), DECIM_FIR_TAPS):
                problems.append(f"{name}: taps differ from DECIM_FIR_TAPS")
            got, ok = Decimator2().process_valid(_f32(v["input"]), np.asarray(v["valid"], dtype=bool))
            problems += _cmp(name, got, _f32(v["expected"]), v["tolerance"]["abs"])
            if ok.tolist() != v["expected_valid"]:
                problems.append(f"{name}: expected_valid differs")
            codes = to_adc_dec_codes(got).astype(np.int64)
            exp_codes = np.asarray(v["expected_codes"], dtype=np.int64)
            if codes.shape != exp_codes.shape or np.any(np.abs(codes - exp_codes) > v["tolerance"]["codes_abs"]):
                problems.append(f"{name}: expected_codes differ")
        elif name == "dsp_biquads.json":
            chain = filter_chain_from_pack(v["dsp"], v["fs_hz"])
            if [_section_dict(c) for c in chain.sections] != v["sections"]:
                problems.append(f"{name}: biquad coefficients differ")
            x = _f32(v["input"])
            problems += _check_stages(name, chain, x, None, v["expected"], v["tolerance"]["abs"])
            if "masked" not in v:
                problems.append(f"{name}: no masked case")
                continue
            m = v["masked"]
            valid = np.asarray(m["valid"], dtype=bool)
            if valid.shape != x.shape:
                problems.append(f"{name} masked: valid has {valid.size} samples, input {x.size}")
                continue
            problems += _check_stages(f"{name} masked", chain, x, valid, m["expected"], v["tolerance"]["abs"])
        else:
            params = StaLtaParams.from_pack(v["trigger"])
            x = _f32(v["input"])
            problems += _check_trigger(name, params, v["fs_hz"], x, None, v["expected"], v["tolerance"]["rel"])
            if "masked" not in v:
                problems.append(f"{name}: no masked case")
                continue
            m = v["masked"]
            valid = np.asarray(m["valid"], dtype=bool)
            if valid.size > x.size:
                problems.append(f"{name} masked: valid has {valid.size} samples, input {x.size}")
                continue
            problems += _check_trigger(
                f"{name} masked", params, v["fs_hz"], x[: valid.size], valid, m["expected"], v["tolerance"]["rel"]
            )
    return problems


def _check_stages(
    label: str, chain: FilterChain, x: np.ndarray, valid: np.ndarray | None, expected: list[Any], tol_abs: float
) -> list[str]:
    chain.reset()
    got_stages = chain.process_stages(x, valid)
    if len(got_stages) != len(expected):
        return [f"{label}: {len(got_stages)} sections, file has {len(expected)}"]
    problems: list[str] = []
    for i, (got, exp) in enumerate(zip(got_stages, expected, strict=True)):
        problems += _cmp(f"{label} section {i}", got, _f32(exp), tol_abs)
    return problems


def _check_trigger(
    label: str,
    params: StaLtaParams,
    fs_hz: float,
    x: np.ndarray,
    valid: np.ndarray | None,
    expected: dict[str, Any],
    tol_rel: float,
) -> list[str]:
    ratio, events = StaLta(params, fs_hz).process(x, valid)
    exp_ratio = _f32(expected["ratio"])
    problems: list[str] = []
    if ratio.size != exp_ratio.size:
        problems.append(f"{label}: ratio has {ratio.size} samples, file has {exp_ratio.size}")
    else:
        bad = np.abs(ratio.astype(np.float64) - exp_ratio) > tol_rel * np.maximum(np.abs(exp_ratio), np.float32(1))
        if bad.any():
            problems.append(f"{label}: ratio differs at {int(np.argmax(bad))}")
    if [e.as_dict() for e in events] != expected["events"]:
        problems.append(f"{label}: events differ: {[e.as_dict() for e in events]}")
    if "windows" in expected:
        windows = close_windows(events, valid if valid is not None else np.ones(x.size, dtype=bool))
        if [w.as_dict() for w in windows] != expected["windows"]:
            problems.append(f"{label}: windows differ: {[w.as_dict() for w in windows]}")
    return problems


def _cmp(label: str, got: np.ndarray, exp: np.ndarray, tol_abs: float) -> list[str]:
    if got.shape != exp.shape:
        return [f"{label}: shape {got.shape} != {exp.shape}"]
    err = float(np.max(np.abs(got.astype(np.float64) - exp))) if got.size else 0.0
    return [f"{label}: max |error| {err:g} > {tol_abs:g}"] if err > tol_abs else []


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rezonating_ml.vectors", description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate the vector files")
    mode.add_argument("--check", action="store_true", help="compare the current code with the vector files")
    ap.add_argument("--dir", type=Path, default=None, help="vector folder (default: ml/tests/vectors)")
    args = ap.parse_args(argv)
    vec_dir = args.dir or default_vector_dir()
    if args.write:
        for p in write_vectors(vec_dir):
            print(f"wrote {p}")
        return 0
    problems = check_vectors(vec_dir)
    for p in problems:
        print(p, file=sys.stderr)
    print("vectors OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
