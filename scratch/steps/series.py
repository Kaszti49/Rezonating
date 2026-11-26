"""Throwaway: left/right on all one-side walks of 2026-11-26, with the limit picked on other recordings.

Walks: LEFT _01 _05 _07, RIGHT _02 _06 _08 (one side per recording). Coin taps _03 (left geophone) and _04 (right)
give the channel map: ch0 = right, ch1 = left. tau > 0 means ch0 (right) heard the step first.
Rule: tau above a limit -> RIGHT, else LEFT. The limit for a recording is picked on the OTHER recordings only
(leave one recording out), so every score is out-of-sample at the recording level.
"""

import contextlib
import io
import sys

import numpy as np

sys.path.insert(0, "scratch/steps")
with contextlib.redirect_stdout(io.StringIO()):
    import detect as d
    import side as S
from rezonating_lab.core import locate as L

WALKS = {"01": "LEFT", "05": "LEFT", "07": "LEFT", "02": "RIGHT", "06": "RIGHT", "08": "RIGHT"}
PRE_S, POST_S = 0.02, 0.06


def taus(s, band):
    L.TIMING_BAND_HZ = band
    x, fs = d.load(s)
    ts, h = S.steps(x, fs)
    out = []
    for t0, hh in zip(ts, h, strict=True):
        i0, i1 = int((t0 - PRE_S) * fs), int((t0 + POST_S) * fs)
        if i0 < 0 or i1 > len(x):
            continue
        m = L.measure(x[i0:i1], fs)
        if not m.lag_limited:
            out.append((m.tau_s * 1e3, hh, abs(m.cc)))
    return np.array(out)


def best_limit(tau, is_right):
    cands = np.unique(tau)
    accs = [np.mean((tau > c) == is_right) for c in cands]
    return cands[int(np.argmax(accs))]


for band in ((20, 60), (40, 200), (100, 400)):
    T = {s: taus(s, band) for s in WALKS}
    print(f"\n== timing band {band} Hz")
    tot_ok = tot_n = 0
    for s, side in WALKS.items():
        tr = np.concatenate([T[o][:, 0] for o in WALKS if o != s])
        lab = np.concatenate([np.full(len(T[o]), WALKS[o] == "RIGHT") for o in WALKS if o != s])
        lim = best_limit(tr, lab)
        tau = T[s][:, 0]
        ok = np.sum((tau > lim) == (side == "RIGHT"))
        tot_ok += ok
        tot_n += len(tau)
        strong = T[s][:, 1] >= np.median(T[s][:, 1])
        ok_s = np.mean((tau[strong] > lim) == (side == "RIGHT"))
        ok_w = np.mean((tau[~strong] > lim) == (side == "RIGHT"))
        print(
            f"  _{s} {side:5s}: {len(tau):3d} steps, tau median {np.median(tau):+.2f} ms, limit {lim:+.2f} "
            f"(from the other 5) -> {ok / len(tau):.0%} right | louder half {ok_s:.0%}, fainter half {ok_w:.0%}"
        )
    print(f"  all: {tot_ok}/{tot_n} = {tot_ok / tot_n:.0%} (leave one recording out)")
    # walk level: majority of a recording's steps
