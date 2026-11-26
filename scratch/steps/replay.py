"""Throwaway: replay the 2026-11-26 one-side walks through the Lab's real Locator (server/locate.py), as the live page
would see them, and score the sides. Usage: python scratch/steps/replay.py [--swap]"""

import sys
from collections import Counter

import numpy as np
import soundfile as sf
from rezonating_lab.core.ringbuf import SampleRing
from rezonating_lab.server.locate import Locator

ROOT = r"C:\Users\benedek.kaszti\Desktop\EP_RezonatingProject\Recordings"
WALKS = {"01": "left", "05": "left", "07": "left", "02": "right", "06": "right", "08": "right"}
FS = 1994.9


class Mgr:
    def __init__(self, ring):
        self.rings = {0: ring}
        self.events = []

    def stream_names(self):
        return {0: "adc_raw"}

    def stream_info(self, sid):
        return {"fs_hz": FS}

    def publish(self, ev):
        self.events.append(ev)

    def host_log(self, msg, level=3):
        pass


def replay(s, swap):
    x, _ = sf.read(f"{ROOT}/2026-11-26_office_pc-10_{s}/2026-11-26_office_pc-10_{s}.adc.wav", dtype="int32")
    ring = SampleRing(2, len(x) + 10)
    mgr = Mgr(ring)
    loc = Locator(mgr, None)
    loc.swap_sides = swap
    chunk = int(FS * 0.04)
    for i in range(0, len(x), chunk):
        ring.write(i, x[i : i + chunk])
        loc.tick()
    return [e for e in mgr.events if e["type"] == "locate_step"]


if __name__ == "__main__":
    swap = "--swap" in sys.argv
    tot = Counter()
    for s, truth in WALKS.items():
        steps = replay(s, swap)
        c = Counter(e["side"] for e in steps)
        w = Counter(e["walk_side"] for e in steps)
        other = "right" if truth == "left" else "left"
        tot.update({"n": len(steps), "ok": c[truth], "wrong": c[other], "same": c["same"]})
        print(
            f"_{s} {truth:5s}: {len(steps):3d} steps | right {c[truth]:3d} wrong {c[other]:3d} same {c['same']:3d} | "
            f"walk side right {w[truth]} wrong {w[other]} same {w['same']}"
        )
    n = tot["n"]
    print(
        f"all: {n} steps, right {tot['ok']} ({tot['ok'] / n:.0%}), wrong {tot['wrong']} ({tot['wrong'] / n:.0%}), "
        f"same {tot['same']} ({tot['same'] / n:.0%}); of those with a side: {tot['ok'] / max(1, tot['ok'] + tot['wrong']):.0%}"
    )
    _ = np
