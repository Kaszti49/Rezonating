"""Extract a real 4 s walking stretch from the HARMAN Hackathon stage session for the poster.

Reads data/raw/hackathon/session_2026-11-14T01-41-28.log (not in git; home desktop only) and
writes assets/waveform.json: a min/max envelope of channel 1 plus the step events the on-device
trigger logged. The JSON is derived and small, so other machines can build the poster without
the recording.

Run: python docs/otio-poster/waveform.py [start_s] [length_s]
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE.parents[1] / "data/raw/hackathon/session_2026-11-14T01-41-28.log"
OUT = HERE / "assets/waveform.json"
BINS = 1600


def read_session(path):
    """Return [(t_ms, ch1_counts)] and the step events (start t_ms).

    Each S line starts a block: measured rate (about 1000 SPS) and the start time in ms."""
    samples, steps = [], []
    t = dt = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("S,"):
            _, rate, _, _, t0 = line.split(",")[:5]
            t, dt = float(t0), 1000.0 / float(rate)
        elif line.startswith("D,") and t is not None:
            samples.append((t, int(line.split(",")[1])))
            t += dt
        elif line.startswith("E,"):
            f = line.split(",")
            if f[5] in ("step", "newstep"):
                steps.append(int(f[2]))
    return samples, steps


def main():
    start_ms = int(float(sys.argv[1]) * 1000) if len(sys.argv) > 1 else 1392000
    length_ms = int(float(sys.argv[2]) * 1000) if len(sys.argv) > 2 else 4000
    samples, steps = read_session(LOG)
    window = [(t, v) for t, v in samples if start_ms <= t < start_ms + length_ms]
    vals = [v for _, v in window]
    mean = sum(vals) / len(vals)
    peak = max(abs(v - mean) for v in vals)
    bins = [[] for _ in range(BINS)]
    for t, v in window:
        bins[int((t - start_ms) / length_ms * BINS)].append(v)
    missing = sum(not b for b in bins)
    env = []
    for chunk in bins:
        env.append([round((min(chunk) - mean) / peak, 4), round((max(chunk) - mean) / peak, 4)] if chunk else [0, 0])
    marks = [round((s - start_ms) / length_ms, 4) for s in steps if start_ms <= s < start_ms + length_ms]
    OUT.write_text(json.dumps({"source": LOG.name, "start_ms": start_ms, "length_ms": length_ms,
                               "empty_bins": missing, "envelope": env, "steps": marks}))
    print(f"{OUT.name}: {length_ms} ms from {start_ms}, {len(vals)} samples, {missing} empty bins, {len(marks)} steps")


if __name__ == "__main__":
    main()
