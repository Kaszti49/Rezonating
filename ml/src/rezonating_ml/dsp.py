"""Signal conditioning shared with the firmware ``dsp`` component (D-016, D-021).

Two stages, both stateful and chunkable: feeding a stream in any chunk sizes gives output that is byte-identical
to one call on the whole stream (every output sample is computed by the same float32 operations in the same order).

1. :class:`Decimator2`: the D-016 front end. A fixed 63-tap linear-phase FIR low-pass, then keep every 2nd
   sample: the 2 kSPS ``adc_raw`` stream becomes the 1 kSPS stream the packs run on.
2. :class:`FilterChain`: the pack's ``dsp`` list (``highpass_hz``, ``lowpass_hz``), each entry one biquad of the
   family and order in :data:`DSP_FILTER_FAMILY` / :data:`DSP_FILTER_ORDER` (Butterworth, 2nd order). The pack
   schema names only the cutoff; that choice is ours and is written down here (open question for Viktor).

Everything is float32, as in the firmware. The C side must follow the recurrences written in each docstring; the
test vectors in ``ml/tests/vectors/`` are what it must match.

**Build requirement (firmware):** compile the ``dsp`` and trigger sources with ``-ffp-contract=off``. Xtensa GCC
contracts ``a*b + c`` into one fused ``madd.s`` by default in GNU C mode, which rounds once instead of twice and
moves the result away from these vectors. The vector tolerances are measured against an FMA emulation with 10x
headroom, so a contracted build should still pass, but the requirement is to build without contraction.

Decimator index convention
--------------------------
Raw (2 kSPS) samples are numbered ``n = 0, 1, 2, ...`` from the start of the stream; the FIR history before
``n = 0`` is zeros. The FIR output ``y[n] = sum_{j=0}^{62} h[j] * x[n - j]`` is kept at odd ``n`` only:

    decimated[k] = y[2k + 1]

The FIR is symmetric, so its group delay is exactly 31 raw samples, and decimated sample ``k`` therefore describes
the signal at raw index ``2k + 1 - 31 = 2k - 30`` (:data:`DECIM_RAW_OFFSET`). Keeping the odd phase is what makes
that an integer on the raw grid. The first 15 decimated samples (``k < 15``) describe times before the stream
started (filter warm-up from zero history); they are kept, never dropped, so every sample is counted.
A stream of ``n_raw`` samples gives exactly ``n_raw // 2`` decimated samples.

Firmware: produce one output each time a raw sample with an odd index arrives, from the last 63 raw samples, with
``acc = 0.0f; for j in 0..62: acc += h[j] * x[n - j];`` (ascending ``j``, float32). Sample indices are 64-bit
(``u64`` in D-018), so they never wrap.

Lost raw samples (``tools/lab/PROTOCOL.md``, ``adc_dec``)
-----------------------------------------------------
Pass ``valid`` (one bool per raw sample, ``False`` = lost) to :meth:`Decimator2.process_valid`. Output ``k`` is
*invalid* when any raw sample in its FIR window (raw ``2k + 1 - 62 .. 2k + 1``) was lost: the node counts it as
``device_dropped`` and does not send it. Raw history before index 0 is start-up zeros, not lost. Inside the FIR a
lost raw sample is replaced by the previous good raw sample, or by 0 if there is none yet (hold-previous), as
``tools/lab/PROTOCOL.md`` specifies; this only sets the value of the invalid outputs (computed, never sent), since a
valid output's window holds no lost sample. What keeps a zero-filled gap out of the later stages is the validity
mask: :class:`FilterChain` and the trigger skip invalid samples (no state update, output 0).

Link values (``adc_dec`` stream)
--------------------------------
On the link the node sends ``to_adc_dec_codes(decimated)``: rounded to nearest, halves away from zero (C
``lroundf``), saturated to the 24-bit code range ``-8388608 .. 8388607``, as int32.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from scipy import signal

__all__ = [
    "ADC_CODE_MAX",
    "ADC_CODE_MIN",
    "DSP_FILTER_FAMILY",
    "DSP_FILTER_ORDER",
    "DECIM_FACTOR",
    "DECIM_FIR_TAPS",
    "DECIM_GROUP_DELAY_RAW",
    "DECIM_IN_FS_HZ",
    "DECIM_OUT_FS_HZ",
    "DECIM_PASS_HZ",
    "DECIM_RAW_OFFSET",
    "DECIM_STOP_HZ",
    "Biquad",
    "BiquadCoeffs",
    "Decimator2",
    "FilterChain",
    "biquad_highpass",
    "biquad_lowpass",
    "dec_to_raw_index",
    "design_decimator_taps",
    "filter_chain_from_pack",
    "to_adc_dec_codes",
]

DECIM_IN_FS_HZ = 2000.0
DECIM_OUT_FS_HZ = 1000.0
DECIM_FACTOR = 2
DECIM_PASS_HZ = 400.0
DECIM_STOP_HZ = 600.0
DECIM_N_TAPS = 63
DECIM_GROUP_DELAY_RAW = (DECIM_N_TAPS - 1) // 2  # 31 raw samples
DECIM_PHASE = 1  # keep FIR outputs at odd raw indices
DECIM_RAW_OFFSET = DECIM_PHASE - DECIM_GROUP_DELAY_RAW  # -30: decimated k <-> raw 2k - 30
ADC_CODE_MIN = -(1 << 23)
ADC_CODE_MAX = (1 << 23) - 1

# What a pack's {"highpass_hz": f} / {"lowpass_hz": f} means: one Butterworth biquad (2nd order, -3.01 dB at f).
# The pack schema gives only the cutoff, so this is a convention of ours, not of the pack; changing it changes
# every pack's filters and the dsp_biquads vectors (open question for Viktor, verifier flag F-261013-537e).
DSP_FILTER_FAMILY = "butterworth"
DSP_FILTER_ORDER = 2

# Frozen float32 taps of the D-016 decimator: design_decimator_taps() rounded to float32 (test_dsp checks they
# still match). Firmware copies this list verbatim. Measured on these float32 taps: passband 0-400 Hz
# +0.000094 / -0.000010 dB, attenuation >= 104.5 dB from 600 Hz to 1000 Hz. Exactly symmetric; sum 0.99999994.
# fmt: off
DECIM_FIR_TAPS: np.ndarray = np.array([
    -1.9752368e-05, 1.0312901e-07, 7.2250514e-05, -2.4318265e-07,
    -0.00019518388, 6.1545717e-07, 0.00044213777, -1.1609376e-06,
    -0.0008901965, 2.0815464e-06, 0.001644132, -3.310028e-06,
    -0.0028402489, 5.0157882e-06, 0.0046535046, -7.0589617e-06,
    -0.0073105283, 9.51753e-06, 0.011121361, -1.2161764e-05,
    -0.016553467, 1.4952673e-05, 0.024419704, -1.7579334e-05,
    -0.036403637, 1.9965431e-05, 0.056866363, -2.1782995e-05,
    -0.101892754, 2.2997356e-05, 0.31688485, 0.49997902,
    0.31688485, 2.2997356e-05, -0.101892754, -2.1782995e-05,
    0.056866363, 1.9965431e-05, -0.036403637, -1.7579334e-05,
    0.024419704, 1.4952673e-05, -0.016553467, -1.2161764e-05,
    0.011121361, 9.51753e-06, -0.0073105283, -7.0589617e-06,
    0.0046535046, 5.0157882e-06, -0.0028402489, -3.310028e-06,
    0.001644132, 2.0815464e-06, -0.0008901965, -1.1609376e-06,
    0.00044213777, 6.1545717e-07, -0.00019518388, -2.4318265e-07,
    7.2250514e-05, 1.0312901e-07, -1.9752368e-05,
], dtype=np.float32)
# fmt: on
DECIM_FIR_TAPS.flags.writeable = False


def design_decimator_taps() -> np.ndarray:
    """Re-run the D-016 FIR design; returns ``(63,)`` float64 taps.

    Parks-McClellan (``scipy.signal.remez``), 63 taps, fs 2000 Hz, pass 0-400 Hz, stop 600-1000 Hz, equal weights;
    then made exactly symmetric and scaled to a DC gain of 1. :data:`DECIM_FIR_TAPS` is this rounded to float32.
    """
    taps = signal.remez(
        DECIM_N_TAPS,
        [0.0, DECIM_PASS_HZ, DECIM_STOP_HZ, DECIM_IN_FS_HZ / 2],
        [1.0, 0.0],
        weight=[1.0, 1.0],
        fs=DECIM_IN_FS_HZ,
    )
    taps = 0.5 * (taps + taps[::-1])
    return taps / taps.sum()


def dec_to_raw_index(k: int | np.ndarray) -> int | np.ndarray:
    """Raw (2 kSPS) index that decimated sample ``k`` describes: ``2k - 30``."""
    return DECIM_FACTOR * k + DECIM_RAW_OFFSET


def _as_f32_1d(x: np.ndarray | Sequence[float]) -> np.ndarray:
    arr = np.asarray(x)
    if arr.ndim != 1:
        raise ValueError(f"expected a 1-D chunk (one channel), got shape {arr.shape}")
    return arr.astype(np.float32, copy=False)


class Decimator2:
    """D-016 FIR low-pass + keep every 2nd sample, 2 kSPS -> 1 kSPS. Stateful; see the module docstring.

    State: the last 62 raw samples after hold-previous (zeros at start) and which of them were lost, the last good
    raw sample (0 at start), and the number of raw samples seen so far (its parity picks which samples of the next
    chunk are kept). Counters: ``n_in``, ``n_out``, ``n_lost_in`` (raw samples marked lost), ``n_invalid_out``.
    """

    def __init__(self) -> None:
        self.taps = DECIM_FIR_TAPS
        self.reset()

    def reset(self) -> None:
        self._hist = np.zeros(DECIM_N_TAPS - 1, dtype=np.float32)
        self._hist_lost = np.zeros(DECIM_N_TAPS - 1, dtype=bool)
        self._last_good = np.float32(0.0)
        self.n_in = 0  # raw samples consumed
        self.n_out = 0  # decimated samples produced
        self.n_lost_in = 0  # raw samples marked lost
        self.n_invalid_out = 0  # decimated samples whose FIR window held a lost raw sample

    def process(self, x: np.ndarray, valid: np.ndarray | None = None) -> np.ndarray:
        """Feed raw samples ``x: (n,)`` (any numeric dtype, cast to float32); return the new decimated samples.

        Returns ``(m,)`` float32 where ``m`` is the number of odd global raw indices in this chunk; the first
        returned sample has decimated index ``self.n_out`` before the call. ``valid``: see :meth:`process_valid`.
        """
        return self.process_valid(x, valid)[0]

    def process_valid(self, x: np.ndarray, valid: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Like :meth:`process`, with lost samples: ``valid: (n,) bool`` (``False`` = lost raw sample, None = all
        good). Returns ``(decimated (m,) float32, decimated_valid (m,) bool)``.
        """
        x = _as_f32_1d(x)
        lost = _lost_mask(valid, x.size)
        if lost.any():
            good_idx = np.maximum.accumulate(np.where(lost, -1, np.arange(x.size)))
            x = np.where(good_idx >= 0, x[np.maximum(good_idx, 0)], self._last_good).astype(np.float32)
        if x.size and not lost.all():
            self._last_good = x[int(np.flatnonzero(~lost)[-1])]
        ext = np.concatenate([self._hist, x])
        ext_lost = np.concatenate([self._hist_lost, lost])
        # Global raw index of x[i] is n_in + i; keep the odd ones. Their position in ext is i + 62.
        first = (DECIM_PHASE - self.n_in) % DECIM_FACTOR
        pos = np.arange(first, x.size, DECIM_FACTOR) + (DECIM_N_TAPS - 1)
        acc = np.zeros(pos.size, dtype=np.float32)
        for j in range(DECIM_N_TAPS):  # ascending j, float32 multiply then float32 add, like the C loop
            acc = acc + self.taps[j] * ext[pos - j]
        n_lost = np.concatenate([[0], np.cumsum(ext_lost, dtype=np.int64)])
        ok = (n_lost[pos + 1] - n_lost[pos + 1 - DECIM_N_TAPS]) == 0  # no lost sample in ext[pos-62 .. pos]
        keep = ext.size - (DECIM_N_TAPS - 1)
        self._hist = ext[keep:].copy()
        self._hist_lost = ext_lost[keep:].copy()
        self.n_in += x.size
        self.n_out += acc.size
        self.n_lost_in += int(lost.sum())
        self.n_invalid_out += int((~ok).sum())
        return acc, ok


def _lost_mask(valid: np.ndarray | None, n: int) -> np.ndarray:
    if valid is None:
        return np.zeros(n, dtype=bool)
    v = np.asarray(valid)
    if v.shape != (n,) or v.dtype != bool:
        raise ValueError(f"valid must be a bool array of shape ({n},), got {v.dtype} {v.shape}")
    return ~v


def to_adc_dec_codes(y: np.ndarray) -> np.ndarray:
    """Decimated float32 -> the int32 values the node sends on the ``adc_dec`` link stream (PROTOCOL.md).

    Round to nearest with halves away from zero (C ``lroundf``; done in float64, where every float32 value and
    ``+-0.5`` are exact), then saturate to ``ADC_CODE_MIN .. ADC_CODE_MAX``. ``y: (m,)`` -> ``(m,)`` int32.
    """
    y64 = np.asarray(y, dtype=np.float32).astype(np.float64)
    r = np.where(y64 >= 0, np.floor(y64 + 0.5), np.ceil(y64 - 0.5))
    return np.clip(r, ADC_CODE_MIN, ADC_CODE_MAX).astype(np.int32)


@dataclass(frozen=True)
class BiquadCoeffs:
    """One biquad, normalised so ``a0 = 1``. All five values are float32.

    ``H(z) = (b0 + b1 z^-1 + b2 z^-2) / (1 + a1 z^-1 + a2 z^-2)``
    """

    b0: float
    b1: float
    b2: float
    a1: float
    a2: float
    kind: str = ""
    f_hz: float = 0.0
    fs_hz: float = 0.0

    def b(self) -> np.ndarray:
        return np.array([self.b0, self.b1, self.b2], dtype=np.float32)

    def a(self) -> np.ndarray:
        return np.array([1.0, self.a1, self.a2], dtype=np.float32)

    def as_dict(self) -> dict[str, float | str]:
        return {
            "kind": self.kind,
            "f_hz": self.f_hz,
            "fs_hz": self.fs_hz,
            "b0": self.b0,
            "b1": self.b1,
            "b2": self.b2,
            "a1": self.a1,
            "a2": self.a2,
        }


_Q_BUTTERWORTH = 1.0 / np.sqrt(2.0)


def _rbj(kind: str, f_hz: float, fs_hz: float) -> BiquadCoeffs:
    """RBJ Audio EQ Cookbook biquad with Q = 1/sqrt(2) (2nd-order Butterworth, bilinear with pre-warping).

    Computed in double, normalised by ``a0``, then each coefficient rounded to float32. Firmware: the same formulas
    in ``double`` at pack load, then cast to ``float``.
    """
    if not 0.0 < f_hz < fs_hz / 2:
        raise ValueError(f"{kind} cutoff {f_hz} Hz must be between 0 and fs/2 = {fs_hz / 2} Hz")
    w0 = 2.0 * np.pi * f_hz / fs_hz
    cos_w0 = float(np.cos(w0))
    alpha = float(np.sin(w0)) / (2.0 * _Q_BUTTERWORTH)
    a0 = 1.0 + alpha
    if kind == "lowpass":
        b0, b1, b2 = (1.0 - cos_w0) / 2.0, 1.0 - cos_w0, (1.0 - cos_w0) / 2.0
    elif kind == "highpass":
        b0, b1, b2 = (1.0 + cos_w0) / 2.0, -(1.0 + cos_w0), (1.0 + cos_w0) / 2.0
    else:
        raise ValueError(f"unknown biquad kind {kind!r}")
    a1, a2 = -2.0 * cos_w0, 1.0 - alpha

    def f32(v: float) -> float:
        return float(np.float32(v / a0))

    return BiquadCoeffs(f32(b0), f32(b1), f32(b2), f32(a1), f32(a2), kind=kind, f_hz=float(f_hz), fs_hz=float(fs_hz))


def biquad_lowpass(f_hz: float, fs_hz: float) -> BiquadCoeffs:
    """2nd-order Butterworth low-pass at ``f_hz`` (-3.01 dB there)."""
    return _rbj("lowpass", f_hz, fs_hz)


def biquad_highpass(f_hz: float, fs_hz: float) -> BiquadCoeffs:
    """2nd-order Butterworth high-pass at ``f_hz`` (-3.01 dB there)."""
    return _rbj("highpass", f_hz, fs_hz)


class Biquad:
    """A biquad in transposed direct form II, float32, state ``(z0, z1)`` starting at zero.

    Per sample, each operation rounded to float32, in this order (this is what ``scipy.signal.lfilter`` computes
    for float32 input on x86-64, checked in test_dsp)::

        y  = z0 + b0*x
        z0 = (z1 + b1*x) - a1*y
        z1 = b2*x - a2*y
    """

    def __init__(self, coeffs: BiquadCoeffs) -> None:
        self.coeffs = coeffs
        self._b = coeffs.b()
        self._a = coeffs.a()
        self.reset()

    def reset(self) -> None:
        self._z = np.zeros(2, dtype=np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        """Filter ``x: (n,)`` float32; returns ``(n,)`` float32 and keeps the state for the next chunk."""
        x = _as_f32_1d(x)
        if x.size == 0:
            return x.copy()
        y, self._z = signal.lfilter(self._b, self._a, x, zi=self._z)
        return y.astype(np.float32, copy=False)


class FilterChain:
    """Biquads applied in order (the pack's ``dsp`` list). An empty chain passes samples through (as float32)."""

    def __init__(self, sections: Sequence[BiquadCoeffs]) -> None:
        self.sections = tuple(sections)
        self._biquads = [Biquad(c) for c in self.sections]

    def reset(self) -> None:
        for bq in self._biquads:
            bq.reset()

    def process(self, x: np.ndarray, valid: np.ndarray | None = None) -> np.ndarray:
        """Filter ``x: (n,)`` float32. With ``valid: (n,) bool`` the invalid samples are skipped: the biquad state
        does not advance on them and their output is 0.
        """
        y = _as_f32_1d(x).copy()
        if valid is not None:
            ok = ~_lost_mask(valid, y.size)
            out = np.zeros_like(y)
            out[ok] = self.process(y[ok])
            return out
        for bq in self._biquads:
            y = bq.process(y)
        return y

    def process_stages(self, x: np.ndarray, valid: np.ndarray | None = None) -> list[np.ndarray]:
        """Like :meth:`process` but returns the output after every section (used for the test vectors).

        With ``valid``, every section skips the invalid samples (no state update, output 0), as :meth:`process`.
        """
        y = _as_f32_1d(x).copy()
        if valid is not None:
            ok = ~_lost_mask(valid, y.size)
            outs = [np.zeros_like(y) for _ in self._biquads]
            for out, s in zip(outs, self.process_stages(y[ok]), strict=True):
                out[ok] = s
            return outs
        outs = []
        for bq in self._biquads:
            y = bq.process(y)
            outs.append(y)
        return outs


def filter_chain_from_pack(dsp: Sequence[Mapping[str, float]], fs_hz: float) -> FilterChain:
    """Build the chain for a pack's ``dsp`` list at the pack rate ``fs_hz``.

    ``{"highpass_hz": f}`` and ``{"lowpass_hz": f}`` become one biquad each, of :data:`DSP_FILTER_FAMILY` and
    :data:`DSP_FILTER_ORDER` (Butterworth, 2nd order; our convention, the pack names only the cutoff). ``{"decimate": n}`` is in
    the pack schema but no pack uses it yet, so it is refused rather than guessed.
    """
    sections = []
    for i, step in enumerate(dsp):
        if len(step) != 1:
            raise ValueError(f"dsp[{i}] must have exactly one key, got {sorted(step)}")
        ((key, value),) = step.items()
        if key == "highpass_hz":
            sections.append(biquad_highpass(float(value), fs_hz))
        elif key == "lowpass_hz":
            sections.append(biquad_lowpass(float(value), fs_hz))
        else:
            raise ValueError(f"dsp[{i}]: {key!r} is not supported by rezonating_ml.dsp yet")
    return FilterChain(sections)
