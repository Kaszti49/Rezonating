"""Throwaway: what do steps look like in the 2026-11-26 side recordings."""

import numpy as np
import soundfile as sf
from scipy import signal

ROOT = r"C:\Users\benedek.kaszti\Desktop\EP_RezonatingProject\Recordings"
for s, side in (("01", "LEFT"), ("02", "RIGHT")):
    x, fs = sf.read(f"{ROOT}/2026-11-26_office_pc-10_{s}/2026-11-26_office_pc-10_{s}.adc.wav", dtype="float64")
    x = x - np.median(x, axis=0)
    print(f"== {side}  fs={fs}  n={len(x)}  corr(ch0,ch1) all={np.corrcoef(x.T)[0, 1]:+.2f}")
    # where is the energy? Welch PSD of the whole file, and of the loudest 2 % of 50 ms windows vs the quietest 50 %
    w = int(0.05 * fs)
    n = len(x) // w
    seg = x[: n * w].reshape(n, w, 2)
    hp = signal.sosfiltfilt(signal.butter(4, 8, "hp", fs=fs, output="sos"), x, axis=0)
    e = (hp[: n * w].reshape(n, w, 2) ** 2).mean(1).sum(1) ** 0.5
    loud = np.argsort(e)[-int(0.02 * n) :]
    quiet = np.argsort(e)[: n // 2]

    def psd(idx, seg, w, fs):
        p = np.zeros((w // 2 + 1, 2))
        for i in idx:
            f, pp = signal.periodogram(seg[i] * np.hanning(w)[:, None], fs=fs, axis=0)
            p += pp
        return f, p / len(idx)

    f, pl = psd(loud, seg, w, fs)
    _, pq = psd(quiet, seg, w, fs)
    bands = [(0, 8), (8, 20), (20, 40), (40, 80), (80, 150), (150, 300), (300, 600), (600, 1000)]
    print("  band Hz      loud/quiet power (ch0, ch1)   quiet power share ch0")
    tot = pq.sum(0)
    for lo, hi in bands:
        m = (f >= lo) & (f < hi)
        r = pl[m].sum(0) / pq[m].sum(0)
        print(f"  {lo:4d}-{hi:<4d}   {r[0]:8.1f} {r[1]:8.1f}          {pq[m].sum(0)[0] / tot[0]:.2f}")
    # mains hum?
    for h in (50, 100, 150):
        k = np.argmin(abs(f - h))
        print(f"  quiet PSD at {h} Hz vs neighbours: {pq[k, 0] / np.median(pq[k - 5 : k + 6, 0]):.1f}x")
    # dynamic range of the 8 Hz hp envelope
    q = np.percentile(e, [10, 50, 90, 99, 99.9])
    print("  envelope pct 10/50/90/99/99.9 relative to median:", np.round(q / q[1], 1))
