"""Throwaway: a causal (live) version of the whitened broadband detector, and a study of the step window and the
timing limits on the 2026-11-26 walks, with leave-one-recording-out limits."""

import sys
from collections import deque

import numpy as np
import soundfile as sf

sys.path.insert(0, "scratch/steps")
from rezonating_lab.core import locate as L

ROOT = r"C:\Users\benedek.kaszti\Desktop\EP_RezonatingProject\Recordings"
WALKS = {"01": "left", "05": "left", "07": "left", "02": "right", "06": "right", "08": "right"}


class Broadband:
    """Causal: 32 ms Hann frames every 16 ms; each bin over its own 3 s running median; median over 20..700 Hz,
    summed over both channels; minus the median of the last 0.5 s; over a robust sigma of the last 10 s."""

    def __init__(self, fs, k=3.0, frame=64, hop=32, bg_s=3.0, lvl_s=0.5, sig_s=10.0, gap_s=0.25, band=(20, 700)):
        self.fs, self.k, self.n, self.hop = fs, k, frame, hop
        f = np.fft.rfftfreq(frame, 1 / fs)
        self.m = (f >= band[0]) & (f <= band[1])
        self.win = np.hanning(frame)[:, None]
        fr = fs / hop
        self.bg = deque(maxlen=int(bg_s * fr))
        self.lvl = deque(maxlen=int(lvl_s * fr))
        self.sig = deque(maxlen=int(sig_s * fr))
        self.refr = int(gap_s * fs)
        self.buf = np.zeros((0, 2))
        self.first = 0
        self.last = -(10**12)

    def feed(self, first, x):
        if not len(self.buf):
            self.first = first
        self.buf = np.concatenate([self.buf, x]) if len(self.buf) else x
        out = []
        while len(self.buf) >= self.n:
            seg = self.buf[: self.n]
            idx = self.first
            self.buf = self.buf[self.hop :]
            self.first += self.hop
            seg = seg - seg.mean(0)
            p = np.abs(np.fft.rfft(seg * self.win, axis=0))[self.m] ** 2 + 1e-12
            if len(self.bg) >= 30:
                bg = np.median(np.array(self.bg), axis=0)
                sc = float(np.median(np.log(p / bg), axis=0).sum())
            else:
                sc = None
            self.bg.append(p)
            if sc is None:
                continue
            if len(self.lvl) >= 10:
                loc = sc - float(np.median(self.lvl))
                if len(self.sig) >= 60:
                    s = np.array(self.sig)
                    sigma = 1.4826 * float(np.median(np.abs(s - np.median(s)))) + 1e-9
                    if loc > self.k * sigma and idx - self.last >= self.refr:
                        self.last = idx
                        out.append((idx, loc / sigma))
                self.sig.append(loc)
            self.lvl.append(sc)
        return out


def load(s):
    x, _ = sf.read(f"{ROOT}/2026-11-26_office_pc-10_{s}/2026-11-26_office_pc-10_{s}.adc.wav", dtype="int32")
    return x.astype(np.float64)


FS = 1994.9

if __name__ == "__main__":
    X = {s: load(s) for s in WALKS}
    for k in (3.0, 4.0):
        on = {}
        for s, x in X.items():
            d = Broadband(FS, k=k)
            o = []
            for i in range(0, len(x), 80):
                o += d.feed(i, x[i : i + 80])
            on[s] = o
        print(f"k={k}: steps " + " ".join(f"_{s}:{len(o)}" for s, o in on.items()))
        for band in ((20, 60), (20, 120)):
            L.TIMING_BAND_HZ = band
            for pre, post in ((0.02, 0.06), (0.03, 0.10), (0.05, 0.15), (0.05, 0.30)):
                T = {}
                for s, x in X.items():
                    r = []
                    for idx, h in on[s]:
                        i0, i1 = idx - int(pre * FS), idx + int(post * FS)
                        if i0 < 0 or i1 > len(x):
                            continue
                        m = L.measure(x[i0:i1], FS)
                        r.append((m.tau_s * 1e3, abs(m.cc), m.lag_limited, m.amp[0] / m.amp[1], h))
                    T[s] = np.array(r, dtype=float)
                # leave one recording out: limit = midpoint of the other recordings' side medians
                ok = n = 0
                for s in WALKS:
                    others = [o for o in WALKS if o != s]
                    ml = np.median(np.concatenate([T[o][:, 0] for o in others if WALKS[o] == "left"]))
                    mr = np.median(np.concatenate([T[o][:, 0] for o in others if WALKS[o] == "right"]))
                    lim = 0.5 * (ml + mr)
                    good = T[s][:, 2] == 0
                    tau = T[s][good, 0]
                    ok += np.sum((tau > lim) == (WALKS[s] == "right"))
                    n += len(T[s])
                allL = np.concatenate([T[o][:, 0] for o in WALKS if WALKS[o] == "left"])
                allR = np.concatenate([T[o][:, 0] for o in WALKS if WALKS[o] == "right"])
                print(
                    f"  band {band} win -{pre * 1e3:.0f}/+{post * 1e3:.0f} ms: {ok}/{n} = {ok / n:.0%} | medians L {np.median(allL):+.2f} R {np.median(allR):+.2f}"
                )
