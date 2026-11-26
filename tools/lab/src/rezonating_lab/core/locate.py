"""Where did a step come from: left, right, or neither (front, back or too far). Two geophones, one simple rule
(Kaszti, 2026-11-26: timing first, we need the precision):

1. The geophone that hears the step clearly **first** is on that side.
2. If neither is clearly first, the geophone that hears it **much louder** (1.5 times) is on that side.
3. Otherwise it is "same": the step came from the front, the back, or too far away to tell. Two geophones on a line
   cannot separate those three.

No position, angle, distance or calibration. Display maths for the Lab: never used by a pack (D-017). On the S3 rig
ADC channel 0 is the **right** geophone and channel 1 the left one (coin test 2026-11-26). Which side is which depends
on how the case is placed: *Swap left and right* turns them round.

How the limits were chosen (P-001), on the one-side walks of 2026-11-26 (EXP-005: one person, one floor, six walks of
60 s, three per side, steps up to about 4 m away): the zero point (0 ms) lies between the left and right walks' medians
when the limit is picked on the other five walks each time (79 % of 447 steps, leave one walk out). ``FIRST_S`` and
``LOUDER`` were picked on all 413 steps the live detector found there, so their numbers are **in-sample**: 69 % of the
steps get a side by timing, 89 % of those right; loudness at 1.10 was right for only 47 % of the rest, at 1.5 for 9
of 9. The rule of 2026-11-24 (louder, else first) got 52 % of its sided steps right on the same walks.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np

SPACING_M = 0.123  # cup centres at +-61.5 mm in the OTIO case v1 (used by the room simulator)
LOUDNESS_BAND_HZ = (10.0, 200.0)  # SM-24 flat from 10 Hz, spurious above 240 Hz
TIMING_BAND_HZ = (20.0, 60.0)
TAPER = 0.1  # Tukey window: flat but for 5 % at each end (a Hann window weighted the step's arrival to 19 %)
MAX_LAG_S = 6.15e-3  # the cross-correlation searches this far; a peak on the edge is not trusted
UPSAMPLE = 16  # cross-correlation resolution: 1/16 sample before the parabolic fit

CH0_SIDE = "right"  # the S3 rig: ADC channel 0 is the right geophone (coin test 2026-11-26), unless swapped
ZERO_TAU_S = 0.0  # ch1 - ch0 arrival of a step that is neither left nor right
FIRST_S = 0.1e-3  # clearly first: more than this before the other
FIRST_MAX_S = 3.0e-3  # and not more than this: larger is no arrival difference across 123 mm
LOUDER = 1.5  # much louder: the ch0 / ch1 loudness above this (or below 1 / this) when the timing is not clear
MIN_CC = 0.9  # the timing peak must be this clear for "first" to mean anything
ALIKE_MIN = 0.8  # |zero-lag correlation| from here on: the two geophones move alike (rig health)
WALK_STEPS = 3  # a walk's side is the majority of its last steps


@dataclass
class StepMeasure:
    """Measurements of one step window."""

    tau_s: float  # arrival ch1 - ch0; positive: channel 0 was first
    cc: float  # normalised cross-correlation at that delay, -1..1 (negative: channels in anti-phase)
    amp: tuple[float, float]  # band rms per channel (codes)
    lag_limited: bool  # the peak sat on the search edge
    corr: float = -1.0  # zero-lag correlation of the two channels in the loudness band, -1..1


@dataclass
class StepFix:
    """One step's answer."""

    side: str  # "left" | "right" | "same" (front, back or too far)
    reason: str  # "first" | "louder" | "same"
    tau_s: float
    lead_s: float  # how much earlier the side's geophone heard it (0 for "same" or "louder")
    cc: float
    amp: tuple[float, float]
    ratio: float  # ch0 / ch1 loudness
    agree: bool  # the geophones move alike (rig health; the rule does not use it)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["amp"] = list(self.amp)
        return d


def _band_mask(nfft: int, fs_hz: float, band_hz: tuple[float, float]) -> np.ndarray:
    f = np.fft.rfftfreq(nfft, 1.0 / fs_hz)
    return (f >= band_hz[0]) & (f <= band_hz[1])


def _tukey(n: int, taper: float = TAPER) -> np.ndarray:
    w = np.ones(n)
    k = int(taper * (n - 1) / 2)
    if k > 0:
        ramp = 0.5 * (1 - np.cos(math.pi * np.arange(k) / k))
        w[:k] = ramp
        w[-k:] = ramp[::-1]
    return w


def measure(x: np.ndarray, fs_hz: float) -> StepMeasure:
    """Arrival difference and loudness of one step window ``x`` ((n, 2) codes, DC included)."""
    if x.ndim != 2 or x.shape[1] != 2 or x.shape[0] < 16:
        raise ValueError("x must be (n >= 16, 2)")
    x = x.astype(np.float64)
    x = x - np.median(x, axis=0)
    n = x.shape[0]
    nfft = 1 << int(math.ceil(math.log2(2 * n)))

    # loudness and zero-lag correlation: flat window, loudness band (Parseval; the window's power is divided out)
    w = _tukey(n)[:, None]
    loud = np.fft.rfft(x * w, nfft, axis=0)
    loud = np.where(_band_mask(nfft, fs_hz, LOUDNESS_BAND_HZ)[:, None], loud, 0.0)
    wp = float(np.sum(w[:, 0] ** 2))
    p = [float(2.0 * np.sum(np.abs(loud[:, c]) ** 2) / nfft) for c in (0, 1)]
    amp = (math.sqrt(p[0] / wp), math.sqrt(p[1] / wp))
    cross0 = float(2.0 * np.sum((loud[:, 0] * np.conj(loud[:, 1])).real) / nfft)
    corr = cross0 / math.sqrt(p[0] * p[1]) if p[0] > 0 and p[1] > 0 else 0.0

    # arrival: cross-correlation r[k] = sum x1[i + k] x0[i] (Hann window, timing band), upsampled by zero-padding the
    # spectrum, strongest peak of either sign (the channels are in anti-phase on the rig)
    s = np.fft.rfft(x * np.hanning(n)[:, None], nfft, axis=0)
    s = np.where(_band_mask(nfft, fs_hz, TIMING_BAND_HZ)[:, None], s, 0.0)
    up = nfft * UPSAMPLE
    r = np.fft.irfft(s[:, 1] * np.conj(s[:, 0]), up) * UPSAMPLE
    norm = math.sqrt(float(np.sum(np.abs(s[:, 0]) ** 2)) * float(np.sum(np.abs(s[:, 1]) ** 2))) * 2.0 / nfft
    max_lag = min(int(math.ceil(MAX_LAG_S * fs_hz * UPSAMPLE)), up // 2 - 2)
    lags = np.arange(-max_lag, max_lag + 1)
    vals = r[lags % up]
    k = int(np.argmax(np.abs(vals)))
    lag_limited = k == 0 or k == len(lags) - 1
    frac = 0.0
    if not lag_limited:
        a, b, c = abs(vals[k - 1]), abs(vals[k]), abs(vals[k + 1])
        den = a - 2 * b + c
        if den < 0:
            frac = 0.5 * (a - c) / den
    cc = float(vals[k] / norm) if norm > 0 else 0.0
    return StepMeasure(
        tau_s=float((lags[k] + frac) / UPSAMPLE / fs_hz),
        cc=max(-1.0, min(1.0, cc)),
        amp=amp,
        lag_limited=bool(lag_limited),
        corr=float(max(-1.0, min(1.0, corr))),
    )


def decide(m: StepMeasure, swap_sides: bool = False) -> StepFix:
    """Left, right or the same: first, else much louder, else the same."""
    ratio = (m.amp[0] + 1e-12) / (m.amp[1] + 1e-12)
    lead = m.tau_s - ZERO_TAU_S  # positive: channel 0 was first
    clear = not m.lag_limited and abs(m.cc) >= MIN_CC and FIRST_S < abs(lead) <= FIRST_MAX_S
    ch1_side = "left" if CH0_SIDE == "right" else "right"
    if clear:
        side, reason = (CH0_SIDE if lead > 0 else ch1_side), "first"
    elif ratio > LOUDER or ratio < 1.0 / LOUDER:
        side, reason = (CH0_SIDE if ratio > 1.0 else ch1_side), "louder"
    else:
        side, reason = "same", "same"
    if swap_sides and side != "same":
        side = "right" if side == "left" else "left"
    return StepFix(
        side=side,
        reason=reason,
        tau_s=m.tau_s,
        lead_s=abs(lead) if reason == "first" else 0.0,
        cc=m.cc,
        amp=m.amp,
        ratio=ratio,
        agree=bool(abs(m.corr) >= ALIKE_MIN),
    )


def walk_side(sides: Sequence[str]) -> str:
    """The side of a walk: what at least two of its last ``WALK_STEPS`` steps say, else "same"."""
    last = list(sides)[-WALK_STEPS:]
    for side in ("left", "right"):
        if last.count(side) >= 2:
            return side
    return "same"
