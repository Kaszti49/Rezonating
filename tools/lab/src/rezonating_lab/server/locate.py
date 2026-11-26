"""The Locate page's server side: follows the ``adc_raw`` ring, finds steps, says left / right / same for each
(``core/locate.py``) and publishes them. Contract: WEB_API.md section 15.

Events (WebSocket, JSON):
- ``locate`` (cached, part of the snapshot): the sides switch and counters.
- ``locate_step``: one step.

Display maths only (D-017). Every step window that holds a lost sample is skipped and counted (``skipped_gaps``). A
window with a clipped sample is too (``skipped_clipped``): its loudness and its timing are wrong.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

from ..core.locate import decide, measure, walk_side
from ..link import codec

PRE_S = 0.05  # step window before the onset frame
POST_S = 0.15  # and after it (2026-11-26: 0.30 s took in the floor's ringing and blurred the timing)
FULL_SCALE = 2**23  # codes; a window that touches it is clipped
RECENT_KEPT = 60
WALK_GAP_S = 2.0  # steps closer than this belong to one walk
HEALTH_EVERY_S = 1.0  # the rig health is worked out this often
HEALTH_WINDOW_S = 2.0  # over this much signal
HEALTH_STEPS = 20  # agreement of the geophones: over this many steps
REST_SHIFT = 1000.0  # codes: the rest level moved this far from the saved one (2026-11-24 09:11: 1600)
QUIET_FACTOR = 3.0  # the quiet level against the saved one
AGREE_MIN = 0.7  # below this share of alike steps: a warning

# Step detector (2026-11-26, EXP-005). A step is a short knock that lifts almost every frequency at once; machines are
# steady tones and speech lifts a few harmonics. So each frequency is measured against its own usual level first.
FRAME = 64  # samples per frame (32 ms at 2 kSPS), Hann window
HOP = 32  # a new frame every 16 ms
BAND_HZ = (20.0, 700.0)  # the frequencies that vote
BG_S = 3.0  # each frequency's usual level: the median of its power over this long
LEVEL_S = 0.5  # the score's local level: its median over this long before the frame
SIGMA_S = 5.0  # the score's spread (robust sigma) over this long (10 s stayed deaf after loud walking)
TRIGGER_K = 3.0  # a step: the score this many sigmas above its local level
ENERGY_K = 1.5  # and the frame's band rms this many times the quiet level: noise lifts the shape, not the energy
# (k = 3 alone gave 25 false steps a minute on noise with hum; with this, none in 2 min, and 406 of 410 walk steps)
REFRACTORY_S = 0.25  # one step per this much time (walking: ~0.55 s between steps)
MIN_BG_FRAMES = 30  # frames before the usual levels mean anything (about 0.5 s)
BG_EVERY = 4  # the usual levels are worked out again every this many frames (64 ms; they move over seconds)
MIN_SIGMA_FRAMES = 60  # scores before the spread means anything (about 1 s)
NOISE_PCT = 20.0  # the quiet level (rig health): this percentile of the frames' band rms
NOISE_WIN_S = 5.0


class StepDetector:
    """Online step onsets on two channels. Each 32 ms frame: every frequency bin's power over its own median of the
    last 3 s (steady hum drops out, and so does a difference in the geophones' sensitivity), the median of that log
    ratio over 20..700 Hz, summed over both channels. A step is that score ``TRIGGER_K`` robust sigmas above its own
    level of the last 0.5 s, in a frame at least ``ENERGY_K`` times as strong as the quiet level. Needs about 1.7 s
    of signal first. Returns the first sample of the triggering frame."""

    def __init__(self, fs_hz: float, k: float = TRIGGER_K) -> None:
        self.fs_hz = fs_hz
        self.k = k
        self.frame = FRAME
        self.hop = HOP
        self.block = HOP  # onset resolution in samples
        f = np.fft.rfftfreq(FRAME, 1.0 / fs_hz)
        self._bins = (f >= BAND_HZ[0]) & (f <= BAND_HZ[1])
        self._win = np.hanning(FRAME)[:, None]
        self._wpow = float(np.sum(np.hanning(FRAME) ** 2))
        fr = fs_hz / HOP
        self._n_bg = max(MIN_BG_FRAMES, int(round(BG_S * fr)))
        self._n_level = max(4, int(round(LEVEL_S * fr)))
        self._n_sigma = max(MIN_SIGMA_FRAMES, int(round(SIGMA_S * fr)))
        self._n_noise = max(4, int(round(NOISE_WIN_S * fr)))
        self.reset()

    def reset(self) -> None:
        self._buf = np.zeros((0, 2))
        self._buf_first = 0
        self._bg = np.zeros((self._n_bg, int(self._bins.sum()), 2))  # ring of the last frames' powers
        self._bg_n = 0  # frames written so far
        self._usual: np.ndarray | None = None
        self._level: deque[float] = deque(maxlen=self._n_level)
        self._spread: deque[float] = deque(maxlen=self._n_sigma)
        self._rms: deque[float] = deque(maxlen=self._n_noise)
        self._sigma: float | None = None
        self._last_onset = -(10**12)
        self.noise_rms = 0.0

    def gap(self) -> None:
        """The next ``feed`` is not contiguous with the last one (lost samples): drop the partial frame, so the jump
        is not a step. The usual levels stay."""
        self._buf = np.zeros((0, 2))

    def _score(self, seg: np.ndarray) -> float | None:
        seg = seg - seg.mean(axis=0)
        p = np.abs(np.fft.rfft(seg * self._win, axis=0))[self._bins] ** 2 + 1e-12
        self._rms.append(float(np.sqrt(p.sum() / (FRAME * self._wpow))))  # band rms, mean of both channels (Parseval)
        score = None
        filled = min(self._bg_n, self._n_bg)
        if filled >= MIN_BG_FRAMES:
            if self._usual is None or self._bg_n % BG_EVERY == 0:
                self._usual = np.median(self._bg[:filled], axis=0)
            score = float(np.median(np.log(p / self._usual), axis=0).sum())
        self._bg[self._bg_n % self._n_bg] = p
        self._bg_n += 1
        return score

    def feed(self, first: int, x: np.ndarray) -> list[int]:
        """Samples ``x`` ((n, 2) float) at indices ``first ...`` (contiguous with the previous call unless reset or
        after ``gap``). Returns onset indices."""
        if len(x) == 0:
            return []
        if len(self._buf) == 0:
            self._buf_first = first
        self._buf = np.concatenate([self._buf, x]) if len(self._buf) else np.asarray(x, dtype=np.float64)
        out: list[int] = []
        refractory = int(REFRACTORY_S * self.fs_hz)
        while len(self._buf) >= FRAME:
            idx = self._buf_first
            score = self._score(self._buf[:FRAME])
            self._buf = self._buf[HOP:]
            self._buf_first += HOP
            if score is None:
                continue
            if len(self._level) >= self._n_level // 2:
                rel = score - float(np.median(self._level))
                if len(self._spread) >= MIN_SIGMA_FRAMES:
                    if self._sigma is None or self._bg_n % BG_EVERY == 0:  # it moves over seconds, like the levels
                        s = np.asarray(self._spread)
                        self._sigma = 1.4826 * float(np.median(np.abs(s - np.median(s)))) + 1e-9
                        self.noise_rms = self._quiet()
                    strong = self._rms[-1] > ENERGY_K * self.noise_rms
                    if rel > self.k * self._sigma and strong and idx - self._last_onset >= refractory:
                        self._last_onset = idx
                        out.append(idx)
                self._spread.append(rel)
            self._level.append(score)
        if self._rms:
            self.noise_rms = self._quiet()
        return out

    def _quiet(self) -> float:
        return max(float(np.percentile(self._rms, NOISE_PCT)), 1e-9)


class Locator:
    """Owns the detector, the sides switch and the recent steps. ``tick()`` is called about 10 times a second."""

    def __init__(self, mgr: Any, state_path: Path | None = None) -> None:
        self.mgr = mgr
        self.state_path = state_path
        self.swap_sides = False
        self.baseline: dict | None = None  # rest and quiet levels of a day when the rig was fine
        self._load()
        self._lock = threading.Lock()
        self._ring: Any = None
        self._epoch = -1
        self._cursor = 0
        self._det: StepDetector | None = None
        self._pending: list[int] = []
        self.recent: deque[dict] = deque(maxlen=RECENT_KEPT)
        self.steps = 0
        self.skipped_gaps = 0
        self.skipped_clipped = 0
        self.sides = {"left": 0, "right": 0, "same": 0}
        self._walk: deque[str] = deque(maxlen=8)
        self._walk_last = -(10**12)
        self._rest: list[float] | None = None
        self._health_at = 0.0
        self._next_id = 1

    # ---------------------------------------------------------------------------------- persistence

    def _load(self) -> None:
        """The sides switch and the saved rig levels. Files of the old calibration (no ``version`` 4) are not read."""
        if self.state_path is not None and self.state_path.is_file():
            try:
                d = json.loads(self.state_path.read_text(encoding="utf-8"))
                if d.get("version") == 4:
                    self.swap_sides = bool(d.get("swap_sides"))
                    b = d.get("baseline")
                    if isinstance(b, dict) and len(b.get("rest") or []) == 2 and float(b.get("quiet") or 0) > 0:
                        self.baseline = b
            except (OSError, ValueError, TypeError, AttributeError):
                pass

    def _save(self) -> None:
        if self.state_path is None:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps({"version": 4, "swap_sides": self.swap_sides, "baseline": self.baseline}, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            self.mgr.host_log(f"locate: cannot save the sides to {self.state_path}: {exc}", 2)

    # ---------------------------------------------------------------------------------------- views

    def view(self) -> dict:
        with self._lock:
            return {
                "type": "locate",
                "swap_sides": self.swap_sides,
                "steps": self.steps,
                "sides": dict(self.sides),
                "health": self._health(),
                "skipped_gaps": self.skipped_gaps,
                "skipped_clipped": self.skipped_clipped,
                "noise_rms": self._det.noise_rms if self._det else None,
                "fs_hz": self._det.fs_hz if self._det else None,
                "recent": list(self.recent),
            }

    def _publish_state(self) -> None:
        v = self.view()
        v.pop("recent")
        self.mgr.publish(v)

    # -------------------------------------------------------------------------------------- commands

    def set_swap(self, swap_sides: bool) -> dict:
        with self._lock:
            self.swap_sides = swap_sides
        self._save()
        self._publish_state()
        return self.view()

    def _health(self) -> dict:
        """Rig health from the signal itself (called with the lock held)."""
        last = list(self.recent)[-HEALTH_STEPS:]
        agree = sum(1 for s in last if s["agree"]) / len(last) if len(last) >= 5 else None
        quiet = self._det.noise_rms if self._det and self._det.noise_rms > 0 else None
        warnings: list[str] = []
        if agree is not None and agree < AGREE_MIN:
            warnings.append("The geophones do not move alike: check that the case stands flat and both are firm.")
        b = self.baseline
        if b is not None and self._rest is not None:
            if max(abs(r - r0) for r, r0 in zip(self._rest, b["rest"], strict=True)) > REST_SHIFT:
                warnings.append("The rest level moved: the case or a geophone may have shifted.")
        if b is not None and quiet is not None and quiet > QUIET_FACTOR * b["quiet"]:
            warnings.append("The floor is noisier than on the saved day.")
        return {
            "rest": self._rest,
            "quiet": quiet,
            "agree": agree,
            "agree_n": len(last),
            "baseline": b,
            "warnings": warnings,
        }

    def save_baseline(self) -> dict | None:
        """Keep today's rest and quiet levels as the good ones. None when there is no signal yet."""
        with self._lock:
            quiet = self._det.noise_rms if self._det else 0.0
            if self._rest is None or quiet <= 0:
                return None
            self.baseline = {"rest": list(self._rest), "quiet": quiet, "saved": time.strftime("%Y-%m-%d %H:%M")}
        self._save()
        self._publish_state()
        return self.view()

    def clear(self) -> dict:
        with self._lock:
            self.recent.clear()
        self._publish_state()
        return self.view()

    # ------------------------------------------------------------------------------------------ work

    def _adc_raw(self) -> tuple[Any, float] | None:
        names = self.mgr.stream_names()
        sid = next((s for s, n in names.items() if n == codec.STREAM_NAMES[codec.STREAM_ADC_RAW]), None)
        if sid is None:
            return None
        ring = self.mgr.rings.get(sid)
        info = self.mgr.stream_info(sid)
        if ring is None or info is None or ring.n_ch < 2 or not info.get("fs_hz"):
            return None
        return ring, float(info["fs_hz"])

    def tick(self) -> None:
        got = self._adc_raw()
        if got is None:
            return
        ring, fs = got
        if ring is not self._ring or ring.epoch != self._epoch or self._det is None:
            self._ring, self._epoch = ring, ring.epoch
            self._cursor = ring.head
            self._det = StepDetector(fs)
            self._pending = []
            self._walk.clear()
            self._walk_last = -(10**12)
            self._rest = None
        det = self._det
        lo, data, valid = ring.read(self._cursor, ring.head)
        if lo > self._cursor:  # the ring moved on without us: restart the detector there
            det.reset()
        if len(valid):
            # feed contiguous valid runs; a gap restarts the detector's buffer (its noise floor stays)
            edges = np.flatnonzero(np.diff(np.concatenate(([0], valid.view(np.int8), [0]))))
            for s, e in zip(edges[0::2].tolist(), edges[1::2].tolist(), strict=False):
                if s > 0 or lo != self._cursor:
                    det.gap()
                self._pending += det.feed(lo + s, data[s:e, :2].astype(np.float64))
            self._cursor = lo + len(valid)
        self._tick_health(ring, fs)
        pre, post = int(PRE_S * fs), int(POST_S * fs)
        keep: list[int] = []
        for onset in self._pending:
            if onset + post > ring.head:
                keep.append(onset)
                continue
            w_lo, w, ok = ring.read(onset - pre, onset + post)
            if w_lo != onset - pre or len(ok) != pre + post or not ok.all():
                with self._lock:
                    self.skipped_gaps += 1
                continue
            if int(np.abs(w[:, :2].astype(np.int64)).max()) >= FULL_SCALE - 1:
                with self._lock:
                    self.skipped_clipped += 1
                self._publish_state()
                continue
            self._handle(onset, w[:, :2].astype(np.float64), fs)
        self._pending = keep

    def _tick_health(self, ring: Any, fs: float) -> None:
        now = time.monotonic()
        if now - self._health_at < HEALTH_EVERY_S:
            return
        self._health_at = now
        _, data, valid = ring.read(ring.head - int(HEALTH_WINDOW_S * fs), ring.head)
        if valid.sum() < 0.5 * HEALTH_WINDOW_S * fs:
            return
        with self._lock:
            self._rest = [float(v) for v in np.median(data[valid][:, :2], axis=0)]
        self._publish_state()

    def _handle(self, onset: int, w: np.ndarray, fs: float) -> None:
        fix = decide(measure(w, fs), self.swap_sides)
        if onset - self._walk_last > WALK_GAP_S * fs:
            self._walk.clear()
        self._walk_last = onset
        self._walk.append(fix.side)
        ev = {
            "type": "locate_step",
            "id": self._next_id,
            "index": onset,
            "epoch": self._epoch,
            "walk_side": walk_side(self._walk),
            "walk_steps": len(self._walk),
            **_finite(fix.to_dict()),
        }
        with self._lock:
            self._next_id += 1
            self.steps += 1
            self.sides[fix.side] += 1
            self.recent.append(ev)
        self.mgr.publish(ev)
        self._publish_state()  # the counters (about two a second while someone walks)


def _finite(d: dict) -> dict:
    out: dict = {}
    for k, v in d.items():
        if isinstance(v, float) and not math.isfinite(v):
            out[k] = None
        elif isinstance(v, list):
            out[k] = [None if isinstance(x, float) and not math.isfinite(x) else x for x in v]
        else:
            out[k] = v
    return out
