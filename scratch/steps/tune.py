"""Throwaway: false steps in silence vs steps kept on the walks, for detector settings."""

import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, "scratch/steps")
import rezonating_lab.server.locate as SL
from rezonating_lab.core import locate as L
from rezonating_lab.core.locate import decide, measure

ROOT = r"C:\Users\benedek.kaszti\Desktop\EP_RezonatingProject\Recordings"
WALKS = {"01": "left", "05": "left", "07": "left", "02": "right", "06": "right", "08": "right"}
FS = 1994.9
X = {s: sf.read(f"{ROOT}/2026-11-26_office_pc-10_{s}/2026-11-26_office_pc-10_{s}.adc.wav", dtype="int32")[0].astype(float) for s in WALKS}
rng = np.random.default_rng(0)
n = int(FS * 120)
t = np.arange(n) / FS
noise = 300 * rng.standard_normal((n, 2)) + 2000 * np.sin(2 * np.pi * 100 * t)[:, None] + 800 * np.sin(2 * np.pi * 245 * t + 1)[:, None]


def run(x, k, energy_k):
    det = SL.StepDetector(FS, k=k)
    out = []
    for i in range(0, len(x), 80):
        for o in det.feed(i, x[i : i + 80]):
            seg = x[o : o + SL.FRAME]
            # energy gate: band rms of the onset frame and the next two against the quiet level
            e = np.sqrt(np.mean((seg - seg.mean(0)) ** 2))
            if energy_k <= 0 or e > energy_k * det.noise_rms:
                out.append(o)
    return out


for sig_s in (10.0, 5.0):
    SL.SIGMA_S = sig_s
    for k in (3.0, 3.5, 4.0):
        for ek in (0.0,):
            fp = len(run(noise, k, ek)) / (len(noise) / FS / 60)
            ok = wrong = same = cnt = 0
            for s, side in WALKS.items():
                x = X[s]
                on = run(x, k, ek)
                cnt += len(on)
                for o in on:
                    i0, i1 = o - int(SL.PRE_S * FS), o + int(SL.POST_S * FS)
                    if i0 < 0 or i1 > len(x):
                        continue
                    f = decide(measure(x[i0:i1], FS))
                    ok += f.side == side
                    same += f.side == "same"
                    wrong += f.side not in (side, "same")
            print(f"sigma {sig_s:4.1f} s k {k}: false steps in noise {fp:4.1f}/min | walks {cnt} steps, right {ok} wrong {wrong} same {same}, sided right {ok / (ok + wrong):.0%}")
_ = L
