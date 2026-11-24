"""Throwaway (scratch/): can the two geophones in the case tell which side a step came from? (D-027, proposed)

Reads one Lab recording (``<session>.adc.wav``, adc_raw, 2 channels: ch0 = Click CH1 = geophone 1, ch1 = CH2 =
geophone 2), finds the steps and prints, per step, the arrival-time difference between the geophones (sub-sample,
from the cross-correlation peak) and the amplitude ratio. A positive delay means geophone 1 heard the step first.

    python scratch/side_test.py D:/rezonating-recordings/<session>/<session>.adc.wav

Record it with the Lab: stand about 1-2 m to the side of the device, beyond geophone 1, take 10 steps (or stamp),
then the same beyond geophone 2. With Lab labels named "g1" and "g2" around the two parts, the script also scores them.
Not the pack code: the real side estimate goes into ml/ (Tier 1) once D-027 is accepted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy import signal

from rezonating_ml.io import read_wav


def band(x: np.ndarray, fs: float) -> np.ndarray:
    sos = signal.butter(4, [5, 400], btype="bandpass", fs=fs, output="sos")
    return signal.sosfiltfilt(sos, x, axis=0)  # zero phase: no delay between the channels


def onsets(e: np.ndarray, fs: float, sta_ms: float, lta_ms: float, ratio: float, dead_ms: float) -> list[int]:
    """STA/LTA on the summed energy of both channels (the same idea as the pack trigger, not its exact code)."""
    sta = np.convolve(e, np.ones(int(fs * sta_ms / 1000)) / (fs * sta_ms / 1000), "same")
    n_lta = int(fs * lta_ms / 1000)
    lta = np.convolve(e, np.ones(n_lta) / n_lta, "full")[: len(e)]  # trailing: only the past
    r = sta / np.maximum(lta, 1e-12)
    out, i, dead = [], n_lta, int(fs * dead_ms / 1000)
    while i < len(r):
        if r[i] > ratio:
            out.append(i)
            i += dead
        else:
            i += 1
    return out


def delay_ms(a: np.ndarray, b: np.ndarray, fs: float, max_lag: int) -> tuple[float, float]:
    """Delay of b behind a in ms (positive: a first), from the cross-correlation peak with parabolic interpolation."""
    a = a - a.mean()
    b = b - b.mean()
    full = signal.correlate(b, a, mode="full")
    lags = signal.correlation_lags(len(b), len(a), mode="full")
    keep = np.abs(lags) <= max_lag
    c, lg = full[keep], lags[keep]
    k = int(np.argmax(c))
    frac = 0.0
    if 0 < k < len(c) - 1:
        y0, y1, y2 = c[k - 1], c[k], c[k + 1]
        den = y0 - 2 * y1 + y2
        frac = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    peak = c[k] / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12)
    return (lg[k] + frac) / fs * 1000.0, float(peak)


def side_of(x: np.ndarray, i: int, fs: float, win_ms: float, max_lag: int) -> tuple[float, float, float]:
    """Delay (ms, positive: geophone 1 first), correlation peak and amplitude ratio (dB) of the step triggered at i.

    The trigger fires early (STA window), so the window is anchored on the energy peak within 250 ms after it:
    from 20 ms before the peak (the first arrival) to win_ms after that start."""
    e = (x[i : i + int(fs * 0.25)] ** 2).sum(axis=1)
    p = i + int(np.argmax(e)) if len(e) else i
    s = max(0, p - int(fs * 0.02))
    seg = x[s : s + int(fs * win_ms / 1000)]
    a, b = seg[:, 0], seg[:, 1]
    d, peak = delay_ms(a, b, fs, max_lag)
    db = 20 * np.log10((np.abs(a).max() + 1e-12) / (np.abs(b).max() + 1e-12))
    return d, peak, float(db)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav", type=Path)
    ap.add_argument("--ratio", type=float, default=3.5, help="STA/LTA trigger ratio (pack default 3.5)")
    ap.add_argument("--win-ms", type=float, default=60.0, help="window after the onset used for the delay")
    ap.add_argument("--max-lag", type=int, default=6, help="largest delay searched, in samples (6 = 3 ms at 2 kSPS)")
    args = ap.parse_args()

    codes, fs_nominal = read_wav(args.wav)
    side = args.wav.with_suffix(".json")
    fs = float(fs_nominal)
    labels: list[dict] = []
    if side.exists():
        doc = json.loads(side.read_text(encoding="utf-8"))
        fs = float(doc.get("sample_rate_measured") or doc.get("sample_rate") or fs)
        labels = doc.get("labels") or []
    x = band(codes.astype(np.float64), fs)

    # The geophones read with opposite polarity on 2026-11-23: take the sign from the background correlation.
    sign = np.sign(np.corrcoef(x[:, 0], x[:, 1])[0, 1]) or 1.0
    x[:, 1] *= sign
    print(f"{len(x)} frames at {fs:.3f} Hz; channel 1 multiplied by {sign:+.0f} (polarity)")

    on = onsets((x**2).sum(axis=1), fs, 50, 2000, args.ratio, 300)
    print(" t (s)   delay_ms  corr   amp_g1/g2 (dB)  side    label")
    score = {"g1": [0, 0], "g2": [0, 0]}
    for i in on:
        d, peak, db = side_of(x, i, fs, args.win_ms, args.max_lag)
        guess = "g1" if d > 0 else "g2"
        t = i / fs
        lab = next((L.get("label", "") for L in labels if L.get("i0", -1) <= i < L.get("i1", -1)), "")
        if lab in score:
            score[lab][0] += guess == lab
            score[lab][1] += 1
        print(f"{t:7.2f}  {d:+8.3f}  {peak:5.2f}  {db:+8.2f}       {guess}      {lab}")
    for k, (ok, n) in score.items():
        if n:
            print(f"label {k}: {ok}/{n} steps put on the right side")


if __name__ == "__main__":
    main()
