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

BLOCK_S = 0.01  # detector block
PRE_S = 0.05  # window before the onset block
POST_S = 0.30  # window after it
REFRACTORY_S = 0.40  # one step per this much time (walking: ~0.55 s between steps)
TRIGGER_K = 5.0  # block rms over the noise floor
RISE_K = 2.5  # block rms over the median of the blocks just before it: the tail of a step is no new step
RISE_BLOCKS = 14  # how many blocks before it (the newest one is left out: it may hold the step's own rise)
HP_HZ = 10.0  # detector high-pass (2nd-order Butterworth): slow drift is no step
# Noise floor: a low percentile of the last blocks, so step tails don't lift it (the old average of "quiet" blocks sat
# 1.6 times (up to 6) above the real floor and missed small steps, 2026-11-24).
NOISE_PCT = 20.0
NOISE_WIN_S = 5.0
NOISE_EVERY = 25  # blocks between two updates of the floor
FULL_SCALE = 2**23  # codes; a window that touches it is clipped
WARMUP_BLOCKS = 30
RECENT_KEPT = 60
SETTLE_BLOCKS = 5  # blocks to wait after the filter (re)started; a loud block in them is counted (``missed``)
WALK_GAP_S = 2.0  # steps closer than this belong to one walk
HEALTH_EVERY_S = 1.0  # the rig health is worked out this often
HEALTH_WINDOW_S = 2.0  # over this much signal
HEALTH_STEPS = 20  # agreement of the geophones: over this many steps
REST_SHIFT = 1000.0  # codes: the rest level moved this far from the saved one (2026-11-24 09:11: 1600)
QUIET_FACTOR = 3.0  # the quiet level against the saved one
AGREE_MIN = 0.7  # below this share of alike steps: a warning


class StepDetector:
    """Online step onsets on two channels: 10 ms blocks, rms of the high-passed data against a slow noise floor and
    against the 140 ms before it (a step rises out of what came before; ringing and handling noise don't)."""

    def __init__(self, fs_hz: float, k: float = TRIGGER_K) -> None:
        self.fs_hz = fs_hz
        self.block = max(4, int(round(BLOCK_S * fs_hz)))
        self.k = k
        w0 = 2 * math.pi * HP_HZ / fs_hz
        alpha, cw = math.sin(w0) / math.sqrt(2.0), math.cos(w0)
        a0 = 1 + alpha
        self._b = ((1 + cw) / 2 / a0, -(1 + cw) / a0, (1 + cw) / 2 / a0)
        self._a = (-2 * cw / a0, (1 - alpha) / a0)
        self.reset()

    def reset(self) -> None:
        self._buf = np.zeros((0, 2))
        self._buf_first = 0
        self._z: list[list[float]] | None = None  # filter state per channel (transposed direct form II)
        self._hist: deque[float] = deque(maxlen=RISE_BLOCKS + 1)
        self._noise: float | None = None
        self._warm: list[float] = []
        self._recent: deque[float] = deque(maxlen=int(round(NOISE_WIN_S / BLOCK_S)))
        self._since_floor = 0
        self._last_onset = -(10**12)
        self._after_gap = False
        self.missed = 0  # loud blocks right after a gap, where no onset can be told (one per gap at most)
        self.noise_rms = 0.0

    def _floor(self) -> float:
        return max(float(np.percentile(self._recent, NOISE_PCT)), 1e-9)

    def gap(self) -> None:
        """The next ``feed`` is not contiguous with the last one (lost samples): drop the partial block and restart
        the filter, so the jump is not a step."""
        self._buf = np.zeros((0, 2))
        self._z = None
        self._hist.clear()
        self._after_gap = True

    def _high_pass(self, x: np.ndarray) -> np.ndarray:
        (b0, b1, b2), (a1, a2) = self._b, self._a
        if self._z is None:  # settled on the first sample's DC (a high-pass outputs 0 for it)
            self._z = [[-b0 * v, b2 * v] for v in x[0].tolist()]
        out = np.empty_like(x)
        for ch in range(x.shape[1]):
            z1, z2 = self._z[ch]
            y = []
            for v in x[:, ch].tolist():
                o = b0 * v + z1
                z1 = b1 * v - a1 * o + z2
                z2 = b2 * v - a2 * o
                y.append(o)
            self._z[ch] = [z1, z2]
            out[:, ch] = y
        return out

    def feed(self, first: int, x: np.ndarray) -> list[int]:
        """Samples ``x`` ((n, 2) float) at indices ``first ...`` (contiguous with the previous call unless reset).
        Returns onset indices (start of the triggering block)."""
        if len(x) == 0:
            return []
        if len(self._buf) == 0:
            self._buf_first = first
        x = self._high_pass(x)
        self._buf = np.concatenate([self._buf, x]) if len(self._buf) else x
        out: list[int] = []
        b = self.block
        refractory = int(REFRACTORY_S * self.fs_hz)
        while len(self._buf) >= b:
            blk, self._buf = self._buf[:b], self._buf[b:]
            idx = self._buf_first
            self._buf_first += b
            e = float(np.sqrt(np.mean(blk**2)))
            before = list(self._hist)[:-1]
            self._hist.append(e)
            if self._noise is None:
                self._warm.append(e)
                self._recent.append(e)
                if len(self._warm) >= WARMUP_BLOCKS:
                    self._noise = self._floor()
                continue
            self._recent.append(e)
            self._since_floor += 1
            if self._since_floor >= NOISE_EVERY:
                self._since_floor = 0
                self._noise = self._floor()
            settled = len(before) >= SETTLE_BLOCKS
            if self._after_gap:
                if settled:
                    self._after_gap = False
                elif e > self.k * self._noise:
                    self._after_gap = False
                    self.missed += 1
            rises = settled and e > RISE_K * float(np.median(before))
            if e > self.k * self._noise and rises and idx - self._last_onset >= refractory:
                self._last_onset = idx
                out.append(idx)
            self.noise_rms = self._noise
        return out


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
            if det.missed:
                with self._lock:
                    self.skipped_gaps += det.missed
                det.missed = 0
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
