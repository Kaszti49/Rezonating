"""Throwaway: whitened broadband step detector on the 2026-11-26 side recordings.

Idea: a step is a short impulse that lights up MANY frequency bands at once. Machines are steady tones (removed by
normalising every frequency bin by its own running median), speech lights up a few harmonics (few bands).
Score per 16 ms frame = median over 20-700 Hz bins of log(power / running median power of that bin), both channels
summed. Peaks of that score above median + K * MAD (robust) and at least 0.25 s apart are steps.
"""

import numpy as np
import soundfile as sf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import signal, ndimage

ROOT = r"C:\Users\benedek.kaszti\Desktop\EP_RezonatingProject\Recordings"
OUT = (
    r"C:\Users\BENEDE~1.KAS\AppData\Local\Temp\claude\e8ab88dd72435045\09eaad62-199d-42ab-9ac0-688bfb94b62f\scratchpad"
)
NPERSEG, HOP = 64, 32  # 32 ms window, 16 ms hop at ~2 kHz
BAND_HZ = (20.0, 700.0)
BG_S = 3.0  # running median length for the per-bin background
K = 6.0  # threshold in robust sigmas
GAP_S = 0.25


def load(s):
    x, fs = sf.read(f"{ROOT}/2026-11-26_office_pc-10_{s}/2026-11-26_office_pc-10_{s}.adc.wav", dtype="float64")
    return x - np.median(x, axis=0), fs


def score(x, fs):
    f, t, Z = signal.stft(x.T, fs=fs, nperseg=NPERSEG, noverlap=NPERSEG - HOP, boundary=None, padded=False)
    P = np.abs(Z) ** 2 + 1e-30  # (ch, f, t)
    m = (f >= BAND_HZ[0]) & (f <= BAND_HZ[1])
    P = P[:, m]
    nbg = int(BG_S * fs / HOP) | 1
    bg = ndimage.median_filter(P, size=(1, 1, nbg), mode="nearest")
    W = np.log(P / bg)  # whitened: 0 = usual for that bin at that time
    frac = np.median(W, axis=1).sum(0)  # broadband: median over bins, summed over channels
    return t, frac, P, bg


def peaks(t, sc, fs):
    med = np.median(sc)
    mad = 1.4826 * np.median(abs(sc - med))
    thr = med + K * mad
    pk, _ = signal.find_peaks(sc, height=thr, distance=max(1, int(GAP_S / (t[1] - t[0]))))
    return pk, thr


res = {}
fig, ax = plt.subplots(2, 1, figsize=(18, 8))
for i, (s, side) in enumerate((("01", "LEFT"), ("02", "RIGHT"))):
    x, fs = load(s)
    t, sc, P, bg = score(x, fs)
    pk, thr = peaks(t, sc, fs)
    res[side] = (x, fs, t[pk])
    gaps = np.diff(t[pk])
    print(
        f"{side}: {len(pk)} step candidates, thr {thr:.2f}, median gap {np.median(gaps):.2f} s, "
        f"gaps<0.4 s {np.mean(gaps < 0.4):.0%}, score at peaks pct 10/50/90 {np.round(np.percentile(sc[pk], [10, 50, 90]), 1)}"
    )
    ax[i].plot(t, sc, lw=0.6)
    ax[i].axhline(thr, color="k", ls="--", lw=0.8)
    ax[i].plot(t[pk], sc[pk], "rv", ms=5)
    ax[i].set_ylabel(f"{side} broadband score")
    ax[i].set_xlim(0, 63)
fig.tight_layout()
fig.savefig(OUT + r"\detect.png", dpi=70)
np.save(OUT + r"\steps_left.npy", res["LEFT"][2])
np.save(OUT + r"\steps_right.npy", res["RIGHT"][2])
