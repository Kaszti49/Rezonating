"""Throwaway: spectrograms + band envelopes of the two side recordings."""

import numpy as np
import soundfile as sf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import signal

ROOT = r"C:\Users\benedek.kaszti\Desktop\EP_RezonatingProject\Recordings"
OUT = (
    r"C:\Users\BENEDE~1.KAS\AppData\Local\Temp\claude\e8ab88dd72435045\09eaad62-199d-42ab-9ac0-688bfb94b62f\scratchpad"
)
fig, ax = plt.subplots(6, 1, figsize=(18, 20), sharex=True)
for r, (s, side) in enumerate((("01", "LEFT"), ("02", "RIGHT"))):
    x, fs = sf.read(f"{ROOT}/2026-11-26_office_pc-10_{s}/2026-11-26_office_pc-10_{s}.adc.wav", dtype="float64")
    x = x - np.median(x, axis=0)
    t = np.arange(len(x)) / fs
    for c in range(2):
        f, tt, S = signal.spectrogram(x[:, c], fs=fs, nperseg=256, noverlap=192)
        a = ax[3 * r + c]
        a.pcolormesh(
            tt,
            f,
            10 * np.log10(S + 1e-30),
            shading="auto",
            vmin=np.percentile(10 * np.log10(S + 1e-30), 5),
            vmax=np.percentile(10 * np.log10(S + 1e-30), 99.9),
        )
        a.set_ylim(0, 700)
        a.set_ylabel(f"{side} ch{c} Hz")
    a = ax[3 * r + 2]
    for lo, hi, col in ((10, 80, "C0"), (150, 600, "C3")):
        y = signal.sosfiltfilt(signal.butter(4, [lo, hi], "bp", fs=fs, output="sos"), x, axis=0)
        env = np.sqrt(signal.sosfiltfilt(signal.butter(2, 10, fs=fs, output="sos"), (y**2).sum(1)).clip(0))
        env /= np.median(env)
        a.semilogy(t, env, col, lw=0.6, label=f"{lo}-{hi} Hz (x median)")
    a.legend(loc="upper right")
    a.set_ylabel(f"{side} envelope")
ax[-1].set_xlabel("s")
fig.tight_layout()
fig.savefig(OUT + r"\look.png", dpi=70)
