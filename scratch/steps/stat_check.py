"""Throwaway: median vs mean over bins: synthetic bursts, the room sim, the real walks."""

import sys

import numpy as np

sys.path.insert(0, "scratch/steps")
sys.path.insert(0, "tools/lab/tests")
from online import FS, WALKS, Broadband, load
from rezonating_lab.core import locate as L
from rezonating_lab.sim.room import RoomAdcSignal
from rezonating_lab.sim.scenarios import ScenarioConfig
from test_locate import burst

L.TIMING_BAND_HZ = (20, 60)


def make_feed(stat):
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
            sc = None
            if len(self.bg) >= 30:
                lr = np.log(p / np.median(np.array(self.bg), axis=0))
                sc = float((np.median(lr, axis=0) if stat == "median" else lr.mean(0)).sum())
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

    return feed


def run(x):
    d = Broadband(FS, k=3.0)
    o = []
    for i in range(0, len(x), 80):
        o += d.feed(i, x[i : i + 80])
    return o


for stat in ("median", "mean"):
    Broadband.feed = make_feed(stat)
    rng = np.random.default_rng(3)
    n = int(FS * 8)
    t = np.arange(n) / FS
    x = 100.0 + 0.01 * rng.standard_normal((n, 2))
    for o in (3.0, 3.6, 4.4, 5.1, 6.5):
        x += (burst(t - o))[:, None]
    syn = run(x)
    sig = RoomAdcSignal(ScenarioConfig(seed=5, walk_s=1000.0, rest_s=1.0), acq_id=1)
    chunk = int(FS * 0.04)
    codes = []
    for i in range(0, int(FS * 40), chunk):
        c, _ = sig.block(i, chunk, FS, (4, 4))
        codes.append(c)
    room = run(np.concatenate(codes).astype(float))
    truth = len([s for s in sig._steps if s.t_s < 39.5])
    ok = n_ = cnt = 0
    for s, side in WALKS.items():
        x = load(s)
        on = run(x)
        cnt += len(on)
        for idx, _h in on:
            i0, i1 = idx - int(0.05 * FS), idx + int(0.15 * FS)
            if i0 < 0 or i1 > len(x):
                continue
            m = L.measure(x[i0:i1], FS)
            n_ += 1
            ok += (m.tau_s > 0) == (side == "right")
    print(f"{stat}: synthetic {len(syn)}/5; room sim {len(room)} of {truth}; real {cnt} steps, sign right {ok / n_:.0%}")
