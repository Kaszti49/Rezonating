"""``footstep_v1``: per-event features for the footstep-id pack (D-021). Shared with firmware (Tier 1).

Input: one event window ``x[start:end]`` of the *filtered* pack-rate signal (after the decimator and the pack
``dsp`` biquads; 1 kSPS and 500 samples for footstep-id), float32. Output: ``(N_FEATURES,)`` float32 in the order
of :data:`FEATURE_NAMES`. Any window length ``2 <= n <= N_FFT`` is accepted.

Exact definitions (``n`` = window length, ``fs`` = ``fs_hz``, ``x[i]`` float32, ``EPS = 1e-12``)::

    e         = sum(x[i]^2) / n                          mean energy
    peak      = max |x[i]|,  i_peak = first i where |x[i]| == peak
    rms       = sqrt(e)
     0 log_energy   = ln(e + EPS)
     1 log_peak     = ln(peak + EPS)
     2 crest        = peak / rms                         (0 when rms == 0)
     3 t_peak_s     = i_peak / fs                        seconds from window start
     4 zcr_hz       = c * fs / n,  c = #{i in 1..n-1 : (x[i] >= 0) != (x[i-1] >= 0)}   (no mean removal)
     5 active_s     = (i_last - i_first + 1) / fs, over i with |x[i]| >= thr, thr = fl32(0.1f * peak)
                      (0 when peak == 0)
    Spectrum: X = real DFT of x zero-padded to N_FFT = 512 points, rectangular window (no taper),
              P[k] = |X[k]|^2 for k = 0..N_FFT/2, f[k] = k * fs / N_FFT.
    Bands b = 0..5 with edges BAND_EDGES_HZ = (5, 20, 40, 80, 150, 250, 400) Hz:
              bins k_lo[b] <= k < k_hi[b], k_lo = ceil(edge_lo * N_FFT / fs), k_hi = ceil(edge_hi * N_FFT / fs),
              clipped to N_FFT/2 + 1. At fs = 1000: [3,11) [11,21) [21,41) [41,77) [77,128) [128,205).
              E[b] = sum of P[k] over the band; T = sum of E[b].
     6..11 band_<lo>_<hi>_frac = E[b] / T                (0 when T == 0); the six fractions sum to 1
    12 centroid_hz  = sum(f[k] P[k]) / T over all band bins k_lo[0] <= k < k_hi[5]   (0 when T == 0)

The time-domain features 3, 4 and 5 involve no arithmetic on the samples beyond comparisons, so a firmware port
gets the same counts and indices exactly. The Python reference computes energies, the DFT and the logs in float64
and rounds the results to float32; a float32 firmware (e.g. a radix-2 float32 FFT) differs slightly, which the
test-vector tolerance (:data:`VECTOR_TOL_REL`, relative to ``max(|expected|, 1)``) allows for.

Test vectors: ``python -m rezonating_ml.features --write`` / ``--check`` (``ml/tests/vectors/footstep_v1.json``).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from .trigger import Event

# The vector generator (``vectors``: synthetic clip, JSON helpers) and the dsp/trigger stages it runs are imported
# inside the generator functions only, so the feature definitions above stand alone at import time.

__all__ = [
    "BAND_EDGES_HZ",
    "EPS",
    "FEATURE_NAMES",
    "N_FEATURES",
    "N_FFT",
    "VECTOR_FILE",
    "VECTOR_TOL_REL",
    "band_bins",
    "build_feature_vectors",
    "check_feature_vectors",
    "event_features",
    "footstep_v1",
    "write_feature_vectors",
]

N_FFT = 512
EPS = 1e-12
BAND_EDGES_HZ: tuple[float, ...] = (5.0, 20.0, 40.0, 80.0, 150.0, 250.0, 400.0)
ACTIVE_THRESHOLD = np.float32(0.1)
_BAND_NAMES = tuple(f"band_{lo:g}_{hi:g}_frac" for lo, hi in zip(BAND_EDGES_HZ[:-1], BAND_EDGES_HZ[1:], strict=True))
FEATURE_NAMES: tuple[str, ...] = (
    "log_energy",
    "log_peak",
    "crest",
    "t_peak_s",
    "zcr_hz",
    "active_s",
    *_BAND_NAMES,
    "centroid_hz",
)
N_FEATURES = len(FEATURE_NAMES)
VECTOR_FILE = "footstep_v1.json"
VECTOR_TOL_REL = 1e-4


def band_bins(fs_hz: float) -> list[tuple[int, int]]:
    """Half-open DFT bin ranges ``[k_lo, k_hi)`` of each band at ``fs_hz`` (see the module docstring)."""
    k_max = N_FFT // 2 + 1
    ks = [min(math.ceil(f * N_FFT / fs_hz), k_max) for f in BAND_EDGES_HZ]
    return list(zip(ks[:-1], ks[1:], strict=True))


def footstep_v1(window: np.ndarray, fs_hz: float) -> np.ndarray:
    """Features of one event window.

    window: (n,), float32, filtered pack-rate samples ``x[start:end]``; ``2 <= n <= N_FFT``.
    Returns (N_FEATURES,), float32, in :data:`FEATURE_NAMES` order.
    """
    x32 = np.asarray(window)
    if x32.ndim != 1 or not 2 <= x32.size <= N_FFT:
        raise ValueError(f"window must be 1-D with 2..{N_FFT} samples, got shape {x32.shape}")
    if fs_hz <= 0:
        raise ValueError(f"fs_hz must be > 0, got {fs_hz}")
    x32 = x32.astype(np.float32, copy=False)
    if not np.all(np.isfinite(x32)):
        raise ValueError("window contains NaN or inf")
    n = x32.size
    x = x32.astype(np.float64)

    e = float(np.dot(x, x)) / n
    absx = np.abs(x32)
    peak32 = absx.max()
    peak = float(peak32)
    i_peak = int(np.argmax(absx))
    rms = math.sqrt(e)
    crest = peak / rms if rms > 0 else 0.0

    pos = x32 >= 0
    crossings = int(np.count_nonzero(pos[1:] != pos[:-1]))
    zcr_hz = crossings * fs_hz / n

    if peak32 > 0:
        active = np.flatnonzero(absx >= np.float32(ACTIVE_THRESHOLD * peak32))
        active_s = (int(active[-1]) - int(active[0]) + 1) / fs_hz
    else:
        active_s = 0.0

    p = np.abs(np.fft.rfft(x, N_FFT)) ** 2
    bins = band_bins(fs_hz)
    e_band = np.array([p[lo:hi].sum() for lo, hi in bins])
    total = float(e_band.sum())
    if total > 0:
        frac = e_band / total
        k0, k1 = bins[0][0], bins[-1][1]
        f_hz = np.arange(k0, k1) * (fs_hz / N_FFT)
        centroid_hz = float(np.dot(f_hz, p[k0:k1])) / total
    else:
        frac = np.zeros(len(bins))
        centroid_hz = 0.0

    out = [math.log(e + EPS), math.log(peak + EPS), crest, i_peak / fs_hz, zcr_hz, active_s, *frac, centroid_hz]
    return np.asarray(out, dtype=np.float64).astype(np.float32)


def event_features(x: np.ndarray, events: Sequence[Event], fs_hz: float) -> tuple[np.ndarray, list[Event]]:
    """Features for each event whose window ``[start, end)`` lies fully inside ``x``.

    x: (n_samples,), float32, the filtered pack-rate stream the events index into (index 0 = ``x[0]``).
    Returns ``(F, kept)``: F is (len(kept), N_FEATURES) float32; events cut off at either end are skipped.
    """
    kept = [ev for ev in events if ev.start >= 0 and ev.end <= len(x)]
    feats = np.zeros((len(kept), N_FEATURES), dtype=np.float32)
    for i, ev in enumerate(kept):
        feats[i] = footstep_v1(x[ev.start : ev.end], fs_hz)
    return feats, kept


def _edge_cases(n_win: int, filt: np.ndarray, onset: int) -> list[tuple[str, np.ndarray]]:
    """Hand-made windows that pin down the definitions a firmware port is most likely to get wrong."""
    impulse = np.zeros(n_win, dtype=np.float32)
    impulse[123] = -2.5

    # Short window (n < 500): every per-n normalisation (e, zcr) and the zero padding to N_FFT.
    short = filt[onset - 5 : onset + 32].astype(np.float32)

    # Signed zeros: -0.0 counts as non-negative (x >= 0), so it is NOT a sign change (signbit() would say it is).
    pattern = np.array([1.0, -0.0, 2.0, -1.0, -0.0, -2.0, 0.0, -0.0, 0.5, -0.5], dtype=np.float32)
    signed_zeros = np.tile(pattern, 6)  # 60 samples, 35 crossings (x >= 0 rule)

    # active_s threshold: one sample exactly at fl32(0.1f * peak) counts (>=); the next float below does not.
    peak = np.float32(3.0)
    thr = np.float32(ACTIVE_THRESHOLD * peak)
    at_thr = np.zeros(n_win, dtype=np.float32)
    at_thr[[10, 200, 300, 450]] = [thr, peak, -thr, np.nextafter(thr, np.float32(0.0))]  # active 10..300

    # Peak tie across sign: -3 first, +3 later; i_peak is the first |x| maximum (50), not argmax(x) (300).
    tie = np.zeros(n_win, dtype=np.float32)
    tie[[50, 300]] = [-3.0, 3.0]

    return [
        ("all zeros", np.zeros(n_win, dtype=np.float32)),
        ("impulse -2.5 at index 123", impulse),
        (f"short window n=37 (onset {onset} - 5 .. + 32)", short),
        ("signed zeros: -0.0 is non-negative for zcr", signed_zeros),
        ("sample exactly at fl32(0.1f*peak) counts for active_s", at_thr),
        ("peak tie across sign: first |x| max wins", tie),
    ]


def build_feature_vectors(seed: int | None = None) -> dict[str, Any]:
    """The ``footstep_v1`` vector file: the synthetic clip through decimator, dsp and STA/LTA, then features.

    Inputs are the full event windows of the clip plus the edge cases of :func:`_edge_cases`.
    ``seed`` defaults to ``rezonating_ml.vectors.CLIP_SEED``.
    """
    from .dsp import Decimator2, filter_chain_from_pack
    from .trigger import StaLta, StaLtaParams
    from .vectors import CLIP_SEED, FOOTSTEP_ID_DSP, FOOTSTEP_ID_TRIGGER, _f32_list, synthetic_footstep_clip

    seed = CLIP_SEED if seed is None else seed
    x_raw, _ = synthetic_footstep_clip(seed)
    fs_hz = 1000.0
    dec = Decimator2().process(x_raw)
    filt = filter_chain_from_pack(FOOTSTEP_ID_DSP, fs_hz).process(dec)
    _, events = StaLta(StaLtaParams.from_pack(FOOTSTEP_ID_TRIGGER), fs_hz).process(filt)
    _, kept = event_features(filt, events, fs_hz)
    if not kept:
        raise RuntimeError(f"seed {seed}: no complete event window in the synthetic clip")
    n_win = kept[0].end - kept[0].start
    edge = _edge_cases(n_win, filt, kept[0].onset)
    cases = [filt[ev.start : ev.end] for ev in kept] + [w for _, w in edge]
    names = [f"event onset {ev.onset}" for ev in kept] + [name for name, _ in edge]
    expected = [footstep_v1(w, fs_hz) for w in cases]
    return {
        "name": "footstep_v1",
        "decisions": ["D-021"],
        "description": (__doc__ or "").split("Exact definitions", 1)[1].split("The time-domain", 1)[0].strip(),
        "generator": "python -m rezonating_ml.features --write",
        "clip": f"rezonating_ml.vectors.synthetic_footstep_clip(seed={seed}) -> decimator -> dsp -> sta_lta",
        "fs_hz": fs_hz,
        "n_fft": N_FFT,
        "eps": EPS,
        "band_edges_hz": list(BAND_EDGES_HZ),
        "band_bins": [list(b) for b in band_bins(fs_hz)],
        "feature_names": list(FEATURE_NAMES),
        "tolerance": {"rel": VECTOR_TOL_REL, "note": "per feature: |got - expected| <= rel * max(|expected|, 1)"},
        "input_note": "Window lengths vary (2..512). Inputs keep the sign of zero: -0.0 must parse as -0.0.",
        "case_names": names,
        "events": [ev.as_dict() for ev in kept],
        "input": [_f32_list(w) for w in cases],
        "expected": [_f32_list(f) for f in expected],
    }


def write_feature_vectors(out_dir: Path, seed: int | None = None) -> Path:
    from .vectors import _dumps

    path = Path(out_dir) / VECTOR_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dumps(build_feature_vectors(seed)), encoding="utf-8")
    return path


def check_feature_vectors(vec_dir: Path) -> list[str]:
    """Run :func:`footstep_v1` on the file's inputs and compare with its expected outputs. Returns the problems."""
    path = Path(vec_dir) / VECTOR_FILE
    if not path.is_file():
        return [f"{VECTOR_FILE}: missing"]
    v = json.loads(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if v["feature_names"] != list(FEATURE_NAMES):
        problems.append(f"{VECTOR_FILE}: feature_names differ from FEATURE_NAMES")
    if v["band_bins"] != [list(b) for b in band_bins(v["fs_hz"])]:
        problems.append(f"{VECTOR_FILE}: band bins differ")
    rel = v["tolerance"]["rel"]
    for name, inp, exp in zip(v["case_names"], v["input"], v["expected"], strict=True):
        got = footstep_v1(np.asarray(inp, dtype=np.float64).astype(np.float32), v["fs_hz"]).astype(np.float64)
        e = np.asarray(exp, dtype=np.float64).astype(np.float32).astype(np.float64)
        if got.shape != e.shape:
            problems.append(f"{VECTOR_FILE} [{name}]: shape {got.shape} != {e.shape}")
            continue
        bad = np.abs(got - e) > rel * np.maximum(np.abs(e), 1.0)
        for i in np.flatnonzero(bad):
            problems.append(f"{VECTOR_FILE} [{name}]: {FEATURE_NAMES[i]} = {got[i]:.7g}, expected {e[i]:.7g}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rezonating_ml.features", description="footstep_v1 test vectors")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help=f"regenerate {VECTOR_FILE}")
    mode.add_argument("--check", action="store_true", help=f"compare the current code with {VECTOR_FILE}")
    ap.add_argument("--dir", type=Path, default=None, help="vector folder (default: ml/tests/vectors)")
    args = ap.parse_args(argv)
    if args.dir is not None:
        vec_dir = args.dir
    else:
        from .vectors import default_vector_dir

        vec_dir = default_vector_dir()
    if args.write:
        print(f"wrote {write_feature_vectors(vec_dir)}")
        return 0
    problems = check_feature_vectors(vec_dir)
    for p in problems:
        print(p, file=sys.stderr)
    print("footstep_v1 vectors OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
