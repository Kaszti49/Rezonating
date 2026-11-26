"""Throwaway: per-step left/right features on detected steps (K=3 local-spike detector)."""

import sys

sys.path.insert(0, "scratch/steps")
import io
import contextlib
import numpy as np
from scipy import ndimage, signal

with contextlib.redirect_stdout(io.StringIO()):
    import detect as d
BANDS = [(10, 40), (40, 80), (80, 150), (150, 300), (300, 600)]
PRE_S, POST_S = 0.03, 0.15


def steps(x, fs, K=3.0):
    t, sc, _, _ = d.score(x, fs)
    dt = t[1] - t[0]
    loc = sc - ndimage.median_filter(sc, size=int(0.5 / dt) | 1, mode="nearest")
    sig = 1.4826 * np.median(abs(loc - np.median(loc)))
    pk, _ = signal.find_peaks(loc, height=K * sig, distance=int(0.25 / dt))
    return t[pk], loc[pk] / sig


def feats(x, fs, ts):
    out = []
    # background per channel and band: median energy of 180 ms windows across the file
    bgs = []
    for lo, hi in BANDS:
        y = signal.sosfiltfilt(signal.butter(4, [lo, hi], "bp", fs=fs, output="sos"), x, axis=0)
        bgs.append(y)
    n = int((PRE_S + POST_S) * fs)
    for k in range(len(BANDS)):
        y = bgs[k]
        w = y[: len(y) // n * n].reshape(-1, n, 2)
        bgs[k] = (y, np.median((w**2).mean(1), axis=0))
    hp = signal.sosfiltfilt(signal.butter(4, [15, 300], "bp", fs=fs, output="sos"), x, axis=0)
    for t0 in ts:
        i0 = int((t0 - PRE_S) * fs)
        i1 = i0 + n
        if i0 < 0 or i1 > len(x):
            continue
        row = {}
        for (lo, hi), (y, bg) in zip(BANDS, bgs, strict=True):
            e = (y[i0:i1] ** 2).mean(0)
            row[f"lr_{lo}_{hi}"] = 0.5 * np.log(e[0] / e[1]) - 0.5 * np.log(bg[0] / bg[1])  # >0: ch0 louder than usual
            row[f"snr_{lo}_{hi}"] = 10 * np.log10(e.sum() / bg.sum())
        seg = hp[i0 : i0 + int(0.06 * fs)]
        a, b = seg[:, 0] / np.std(seg[:, 0]), seg[:, 1] / np.std(seg[:, 1])
        cc = signal.correlate(b, a, mode="full") / len(a)
        lags = signal.correlation_lags(len(b), len(a))
        m = abs(lags) <= int(0.006 * fs)
        j = np.argmax(abs(cc[m]))
        row["lag_ms"] = 1e3 * lags[m][j] / fs
        row["cc"] = cc[m][j]
        # onset: first sample where each channel's envelope passes 30 % of its own peak
        env = np.abs(signal.hilbert(hp[i0:i1], axis=0))
        on = [np.argmax(env[:, c] > 0.3 * env[:, c].max()) for c in range(2)]
        row["onset_ms"] = 1e3 * (on[1] - on[0]) / fs  # >0: ch0 first
        out.append(row)
    return out


def auc(a, b):  # P(feature of a LEFT step > feature of a RIGHT step)
    a, b = np.asarray(a), np.asarray(b)
    return (a[:, None] > b[None]).mean() + 0.5 * (a[:, None] == b[None]).mean()


if __name__ == "__main__":
    F = {}
    for s, side in (("01", "LEFT"), ("02", "RIGHT")):
        x, fs = d.load(s)
        ts, h = steps(x, fs)
        F[side] = feats(x, fs, ts)
        print(f"{side}: {len(F[side])} steps")
    keys = F["LEFT"][0].keys()
    print(f"{'feature':14s} {'LEFT median':>12s} {'RIGHT median':>13s}  AUC(L>R)")
    for k in keys:
        L = [r[k] for r in F["LEFT"]]
        R = [r[k] for r in F["RIGHT"]]
        print(f"{k:14s} {np.median(L):12.2f} {np.median(R):13.2f}  {auc(L, R):.2f}")
