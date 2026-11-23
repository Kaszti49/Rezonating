"""Where did a step come from: side, bearing (front/back mirrored) and a rough distance from two geophones.

Display maths for the Lab's Locate page, like ``view.py``: never used by a pack (D-017). The side estimate that a pack
will ship is shared feature code in ``ml/`` and needs D-027 accepted first. The maths and its limits are in the vault
note ``60 Research/Footstep direction with two geophones.md``.

Geometry (top view, metres): the device sits at the origin, the two geophones on the x axis at ``-d/2`` (ADC channel 0,
"left") and ``+d/2`` (channel 1, "right"); +y is "front". A bearing ``phi`` is measured from +y towards +x (right), so
-90 deg is straight left and +90 deg straight right. Two sensors on a line cannot tell ``phi`` from ``180 - phi``: every
fix carries both.

Per step:
1. ``tau`` = arrival at channel 1 minus arrival at channel 0, from a band-limited cross-correlation upsampled in the
   frequency domain plus a parabolic peak fit (sub-sample). A step on the left reaches channel 0 first: ``tau > 0``.
2. ``sin(phi) = -c * (tau - tau0) / d``. ``c`` (floor wave speed) and ``tau0`` (fixed timing offset between the
   channels) come from the two-spot calibration.
3. Band amplitude per channel. Their ratio helps the side; their mean, against the amplitude of the calibration steps
   at 1 m, gives the distance: ``r = r_ref * (a_ref / a) ** (1 / n)``. A step's strength changes from person to person,
   so this is a band (near / mid / far), not a measurement.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

SPACING_M = 0.123  # cup centres at +-61.5 mm in the OTIO case v1
DEFAULT_C_MPS = 100.0  # 30-300 m/s on real floors (GaitVibe+); calibrate on site
BAND_HZ = (10.0, 200.0)  # SM-24 flat from 10 Hz, spurious above 240 Hz
UPSAMPLE = 16  # cross-correlation resolution: 1/16 sample before the parabolic fit
MIN_C_MPS = 20.0  # bounds the lag search: |tau| <= d / MIN_C_MPS
DEFAULT_DECAY_N = 1.0  # amplitude ~ r^-n (inferred 0.5..1); 1 is the cautious choice for the band edges
NEAR_M = 1.0
FAR_M = 2.0


@dataclass
class LocateCalibration:
    """Everything the site calibration sets. Defaults are the uncalibrated guess."""

    spacing_m: float = SPACING_M
    c_mps: float = DEFAULT_C_MPS
    tau0_s: float = 0.0  # fixed timing offset ch1 - ch0 (cables, filters); the two-spot calibration measures it
    gain_ratio: float = 1.0  # ch1 sensitivity / ch0 sensitivity (SM-24: +-2.5 % each)
    swap_sides: bool = False  # True: channel 0 is on the right after all
    ref_amp: float | None = None  # band amplitude of a step at ref_m (codes); None: distance not calibrated
    ref_m: float = 1.0
    decay_n: float = DEFAULT_DECAY_N
    calibrated: list[str] = field(default_factory=list)  # spots done: "left", "right"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> LocateCalibration:
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


@dataclass
class StepMeasure:
    """Calibration-free measurements of one step window."""

    tau_s: float  # arrival ch1 - ch0
    cc: float  # normalised cross-correlation at the chosen lag, -1..1 (negative: channels in anti-phase)
    amp: tuple[float, float]  # band rms per channel (codes), after the gain correction
    lag_limited: bool  # the peak sat on the search edge: the timing is not trustworthy


@dataclass
class StepFix:
    """One located step, ready for the UI."""

    tau_s: float
    cc: float
    amp: tuple[float, float]
    side: str  # "left" | "right" | "unsure"
    side_votes: dict  # {"timing": "left"|"right"|"none", "amplitude": ...}
    phi_deg: float | None  # bearing, -90 (left) .. +90 (right), front half; the mirror is 180 - phi
    phi_sigma_deg: float  # half-width of the wedge to draw
    distance_m: float | None  # None: distance not calibrated
    distance_band: str  # "near" | "mid" | "far" | "unknown"
    confidence: float  # 0..1
    lag_limited: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        d["amp"] = list(self.amp)
        return d


def _band_mask(nfft: int, fs_hz: float, band_hz: tuple[float, float]) -> np.ndarray:
    f = np.fft.rfftfreq(nfft, 1.0 / fs_hz)
    return (f >= band_hz[0]) & (f <= band_hz[1])


def measure(
    x: np.ndarray,
    fs_hz: float,
    spacing_m: float = SPACING_M,
    gain_ratio: float = 1.0,
    band_hz: tuple[float, float] = BAND_HZ,
    noise_rms: tuple[float, float] | None = None,
) -> StepMeasure:
    """Timing and amplitude of one step window ``x`` ((n, 2), codes or volts, DC included).

    The lag search covers ``|tau| <= spacing_m / MIN_C_MPS``. ``noise_rms`` (band rms per channel of a quiet stretch)
    is subtracted from the amplitudes in quadrature when given."""
    if x.ndim != 2 or x.shape[1] != 2 or x.shape[0] < 16:
        raise ValueError("x must be (n >= 16, 2)")
    x = x.astype(np.float64)
    x = x - np.median(x, axis=0)
    n = x.shape[0]
    w = np.hanning(n)[:, None]
    nfft = 1 << int(math.ceil(math.log2(2 * n)))
    spec = np.fft.rfft(x * w, nfft, axis=0)
    mask = _band_mask(nfft, fs_hz, band_hz)
    spec[~mask] = 0.0
    s0, s1 = spec[:, 0], spec[:, 1] / gain_ratio

    # band rms per channel (Parseval on the windowed, band-limited signal; the window's own power is divided out)
    wp = float(np.sum(w[:, 0] ** 2))
    p0 = float(2.0 * np.sum(np.abs(s0) ** 2) / nfft / wp)
    p1 = float(2.0 * np.sum(np.abs(s1) ** 2) / nfft / wp)
    if noise_rms is not None:
        p0 = max(p0 - noise_rms[0] ** 2, 0.0)
        p1 = max(p1 - (noise_rms[1] / gain_ratio) ** 2, 0.0)
    amp = (math.sqrt(p0), math.sqrt(p1))

    # cross-correlation r[k] = sum x1[i + k] x0[i], upsampled by zero-padding the spectrum
    cross = s1 * np.conj(s0)
    up = nfft * UPSAMPLE
    r = np.fft.irfft(cross, up) * UPSAMPLE
    norm = math.sqrt(float(np.sum(np.abs(s0) ** 2)) * float(np.sum(np.abs(s1) ** 2))) * 2.0 / nfft
    max_lag = int(math.ceil(spacing_m / MIN_C_MPS * fs_hz * UPSAMPLE))
    max_lag = min(max_lag, up // 2 - 2)
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
    lag = (lags[k] + frac) / UPSAMPLE
    cc = float(vals[k] / norm) if norm > 0 else 0.0
    return StepMeasure(tau_s=lag / fs_hz, cc=max(-1.0, min(1.0, cc)), amp=amp, lag_limited=bool(lag_limited))


def distance_band(r_m: float | None) -> str:
    if r_m is None:
        return "unknown"
    if r_m < NEAR_M:
        return "near"
    if r_m <= FAR_M:
        return "mid"
    return "far"


def locate(m: StepMeasure, cal: LocateCalibration, fs_hz: float) -> StepFix:
    """Turn a measurement into side, bearing and distance with the current calibration."""
    d = cal.spacing_m
    sign = -1.0 if cal.swap_sides else 1.0
    tau = sign * (m.tau_s - cal.tau0_s)

    # timing vote: a clear lead of at least a quarter sample
    lead_min = 0.25 / fs_hz
    if m.lag_limited or abs(m.cc) < 0.3 or abs(tau) < lead_min:
        t_vote = "none"
    else:
        t_vote = "left" if tau > 0 else "right"
    # amplitude vote: louder on the nearer geophone, by more than the sensors' own tolerance
    a0, a1 = (m.amp[1], m.amp[0]) if cal.swap_sides else m.amp
    ratio = (a0 + 1e-12) / (a1 + 1e-12)
    a_vote = "left" if ratio > 1.05 else "right" if ratio < 1 / 1.05 else "none"
    votes = {"timing": t_vote, "amplitude": a_vote}
    if t_vote != "none" and (a_vote == t_vote or a_vote == "none"):
        side = t_vote
    elif t_vote == "none" and a_vote != "none":
        side = a_vote
    else:
        side = "unsure"

    # bearing
    phi: float | None = None
    sigma = 90.0
    s = -cal.c_mps * tau / d
    if not m.lag_limited and abs(m.cc) >= 0.3 and abs(s) <= 1.3:
        s_c = max(-1.0, min(1.0, s))
        phi = math.degrees(math.asin(s_c))
        # 0.1 sample timing error and a 20 % wave-speed error, propagated through asin
        ds = math.hypot(cal.c_mps * (0.1 / fs_hz) / d, 0.2 * abs(s_c))
        cos_phi = math.cos(math.radians(phi))
        sigma = math.degrees(ds / max(cos_phi, 0.25))
        sigma = max(4.0, min(45.0, sigma))
        if "left" not in cal.calibrated and "right" not in cal.calibrated:
            sigma = max(sigma, 20.0)  # the wave speed is only a guess

    # distance
    r_m: float | None = None
    amp = 0.5 * (m.amp[0] + m.amp[1])
    if cal.ref_amp is not None and amp > 0:
        r_m = cal.ref_m * (cal.ref_amp / amp) ** (1.0 / cal.decay_n)
        r_m = max(0.1, min(10.0, r_m))

    conf = abs(m.cc)
    if side == "unsure":
        conf *= 0.5
    if t_vote != "none" and a_vote != "none" and t_vote != a_vote:
        conf *= 0.5
    if m.lag_limited:
        conf *= 0.3
    return StepFix(
        tau_s=m.tau_s,
        cc=m.cc,
        amp=m.amp,
        side=side,
        side_votes=votes,
        phi_deg=phi,
        phi_sigma_deg=sigma,
        distance_m=r_m,
        distance_band=distance_band(r_m),
        confidence=round(max(0.0, min(1.0, conf)), 3),
        lag_limited=m.lag_limited,
    )


def calibrate(
    spot_measures: dict[str, list[StepMeasure]],
    cal: LocateCalibration,
    ref_m: float = 1.0,
) -> tuple[LocateCalibration, list[str]]:
    """New calibration from steps at known spots, ``ref_m`` straight left and/or right of the device.

    With both spots: the wave speed ``c = d / ((tau_L - tau_R) / 2)``, the timing offset ``tau0 = (tau_L + tau_R) / 2``,
    the gain ratio ``sqrt(ratio_L * ratio_R)`` (the distance effect cancels) and ``swap_sides`` if the "left" spot leads
    on channel 1. With one spot: only the reference amplitude, and ``c`` from that spot's delay alone (assuming no
    timing offset). Returns the new calibration and notes for the UI."""
    notes: list[str] = []
    new = LocateCalibration(**{**cal.to_dict(), "calibrated": list(cal.calibrated)})
    new.ref_m = ref_m
    med: dict[str, tuple[float, float, float]] = {}  # spot -> (tau, amp ch0, amp ch1), raw (no gain correction)
    for spot, ms in spot_measures.items():
        good = [m for m in ms if not m.lag_limited]
        if not good:
            notes.append(f"{spot}: no usable step (all timing peaks on the search edge)")
            continue
        med[spot] = (
            float(np.median([m.tau_s for m in good])),
            float(np.median([m.amp[0] for m in good])),
            float(np.median([m.amp[1] for m in good])),
        )
        if spot not in new.calibrated:
            new.calibrated.append(spot)
    if "left" in med and "right" in med:
        tl, tr = med["left"][0], med["right"][0]
        half = (tl - tr) / 2.0
        new.swap_sides = half < 0
        if new.swap_sides:
            notes.append("the left spot reached channel 1 first: channel 0 is on the right; sides swapped")
        if abs(half) > 1e-9:
            new.c_mps = float(min(2000.0, max(MIN_C_MPS, new.spacing_m / abs(half))))
        else:
            notes.append("left and right gave the same delay: wave speed not changed")
        new.tau0_s = (tl + tr) / 2.0
        rl = med["left"][1] / max(med["left"][2], 1e-12)
        rr = med["right"][1] / max(med["right"][2], 1e-12)
        new.gain_ratio = float(1.0 / math.sqrt(rl * rr)) if rl > 0 and rr > 0 else 1.0
    elif med:
        spot, (t, _, _) = next(iter(med.items()))
        if abs(t) > 1e-9:
            new.c_mps = float(min(2000.0, max(MIN_C_MPS, new.spacing_m / abs(t))))
            want_positive = spot == "left"
            new.swap_sides = (t > 0) != want_positive
        notes.append("only one spot: the timing offset between the channels is assumed 0; do the other side too")
    if med:
        amps = [0.5 * (a0 + a1 / new.gain_ratio) for _, a0, a1 in med.values()]
        new.ref_amp = float(np.median(amps))
    return new, notes
