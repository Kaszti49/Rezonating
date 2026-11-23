"""The Locate page's server side: follows the ``adc_raw`` ring, finds steps, locates them (``core/locate.py``) and
publishes them. Contract: WEB_API.md section 15.

Events (WebSocket, JSON):
- ``locate`` (cached, part of the snapshot): calibration, the calibration in progress, counters.
- ``locate_step``: one located step.

Display maths only (D-017). Every step window that holds a lost sample is skipped and counted (``skipped_gaps``),
never located from patched data.
"""

from __future__ import annotations

import json
import math
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..core.locate import LocateCalibration, StepMeasure, calibrate, locate, measure
from ..link import codec

BLOCK_S = 0.01  # detector block
PRE_S = 0.05  # window before the onset block
POST_S = 0.30  # window after it
REFRACTORY_S = 0.30  # one step per this much time (walking: ~0.55 s between steps)
TRIGGER_K = 5.0  # block rms over the noise floor
NOISE_ALPHA = 0.05  # noise floor EMA per quiet block
DC_ALPHA = 0.02
WARMUP_BLOCKS = 30
RECENT_KEPT = 60
CAL_STEPS = 5  # steps per calibration spot


@dataclass
class _Cal:
    spot: str
    want: int
    got: list[StepMeasure] = field(default_factory=list)


class StepDetector:
    """Online step onsets on two channels: 10 ms blocks, rms of the DC-removed data against a slow noise floor."""

    def __init__(self, fs_hz: float, k: float = TRIGGER_K) -> None:
        self.fs_hz = fs_hz
        self.block = max(4, int(round(BLOCK_S * fs_hz)))
        self.k = k
        self.reset()

    def reset(self) -> None:
        self._buf = np.zeros((0, 2))
        self._buf_first = 0
        self._dc: np.ndarray | None = None
        self._noise: float | None = None
        self._warm: list[float] = []
        self._last_onset = -(10**12)
        self.noise_rms = 0.0

    def gap(self) -> None:
        """The next ``feed`` is not contiguous with the last one (lost samples): drop the partial block."""
        self._buf = np.zeros((0, 2))

    def feed(self, first: int, x: np.ndarray) -> list[int]:
        """Samples ``x`` ((n, 2) float) at indices ``first ...`` (contiguous with the previous call unless reset).
        Returns onset indices (start of the triggering block)."""
        if len(self._buf) == 0:
            self._buf_first = first
        self._buf = np.concatenate([self._buf, x]) if len(self._buf) else x
        out: list[int] = []
        b = self.block
        refractory = int(REFRACTORY_S * self.fs_hz)
        while len(self._buf) >= b:
            blk, self._buf = self._buf[:b], self._buf[b:]
            idx = self._buf_first
            self._buf_first += b
            mean = blk.mean(axis=0)
            if self._dc is None:
                self._dc = mean
            e = float(np.sqrt(np.mean((blk - self._dc) ** 2)))
            if self._noise is None:
                self._warm.append(e)
                self._dc = (1 - 0.2) * self._dc + 0.2 * mean
                if len(self._warm) >= WARMUP_BLOCKS:
                    self._noise = max(float(np.median(self._warm)), 1e-9)
                continue
            if e > self.k * self._noise and idx - self._last_onset >= refractory:
                self._last_onset = idx
                out.append(idx)
            elif e < 2.0 * self._noise:
                self._noise = (1 - NOISE_ALPHA) * self._noise + NOISE_ALPHA * e
                self._dc = (1 - DC_ALPHA) * self._dc + DC_ALPHA * mean
            self.noise_rms = self._noise
        return out


class Locator:
    """Owns the detector, the calibration and the recent steps. ``tick()`` is called about 10 times a second."""

    def __init__(self, mgr: Any, cal_path: Path | None = None) -> None:
        self.mgr = mgr
        self.cal_path = cal_path
        self.cal = self._load()
        self._lock = threading.Lock()
        self._ring: Any = None
        self._epoch = -1
        self._cursor = 0
        self._det: StepDetector | None = None
        self._pending: list[int] = []
        self._calib: _Cal | None = None
        self._cal_done: dict[str, list[StepMeasure]] = {}
        self._notes: list[str] = []
        self.recent: deque[dict] = deque(maxlen=RECENT_KEPT)
        self.steps = 0
        self.skipped_gaps = 0
        self._next_id = 1

    # ---------------------------------------------------------------------------------- persistence

    def _load(self) -> LocateCalibration:
        if self.cal_path is not None and self.cal_path.is_file():
            try:
                return LocateCalibration.from_dict(json.loads(self.cal_path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                pass
        return LocateCalibration()

    def _save(self) -> None:
        if self.cal_path is None:
            return
        try:
            self.cal_path.parent.mkdir(parents=True, exist_ok=True)
            self.cal_path.write_text(json.dumps(self.cal.to_dict(), indent=2), encoding="utf-8")
        except OSError as exc:
            self.mgr.host_log(f"locate: cannot save the calibration to {self.cal_path}: {exc}", 2)

    # ---------------------------------------------------------------------------------------- views

    def view(self) -> dict:
        with self._lock:
            calib = None
            if self._calib is not None:
                calib = {"spot": self._calib.spot, "got": len(self._calib.got), "want": self._calib.want}
            return {
                "type": "locate",
                "calibration": self.cal.to_dict(),
                "calibrating": calib,
                "notes": list(self._notes),
                "steps": self.steps,
                "skipped_gaps": self.skipped_gaps,
                "noise_rms": self._det.noise_rms if self._det else None,
                "fs_hz": self._det.fs_hz if self._det else None,
                "recent": list(self.recent),
            }

    def _publish_state(self) -> None:
        v = self.view()
        v.pop("recent")
        self.mgr.publish(v)

    # -------------------------------------------------------------------------------------- commands

    def start_calibration(self, spot: str, steps: int = CAL_STEPS) -> dict:
        with self._lock:
            self._calib = _Cal(spot, steps)
            self._notes = [f"Step {steps} times at 1 m straight {spot} of the device."]
        self._publish_state()
        return self.view()

    def cancel_calibration(self) -> dict:
        with self._lock:
            self._calib = None
            self._notes = []
        self._publish_state()
        return self.view()

    def reset_calibration(self) -> dict:
        with self._lock:
            self.cal = LocateCalibration(spacing_m=self.cal.spacing_m)
            self._cal_done = {}
            self._calib = None
            self._notes = ["Calibration reset to the defaults (wave speed 100 m/s, no distance)."]
        self._save()
        self._publish_state()
        return self.view()

    def set_values(self, c_mps: float | None, decay_n: float | None, spacing_m: float | None) -> dict:
        with self._lock:
            if c_mps is not None:
                self.cal.c_mps = c_mps
            if decay_n is not None:
                self.cal.decay_n = decay_n
            if spacing_m is not None:
                self.cal.spacing_m = spacing_m
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
            self._handle(onset, w[:, :2].astype(np.float64), fs, det.noise_rms)
        self._pending = keep

    def _handle(self, onset: int, w: np.ndarray, fs: float, noise: float) -> None:
        with self._lock:
            cal = self.cal
            calib = self._calib
        nr = (noise, noise) if noise > 0 else None
        if calib is not None:
            m_raw = measure(w, fs, spacing_m=cal.spacing_m, gain_ratio=1.0, noise_rms=nr)
            done = None
            with self._lock:
                if self._calib is calib:
                    calib.got.append(m_raw)
                    if len(calib.got) >= calib.want:
                        self._cal_done[calib.spot] = list(calib.got)
                        done = dict(self._cal_done)
                        self._calib = None
            if done is not None:
                new, notes = calibrate(done, cal, ref_m=1.0)
                with self._lock:
                    self.cal = new
                    self._notes = notes or [f"Calibrated: wave speed {new.c_mps:.0f} m/s."]
                self._save()
            self._publish_state()
        m = measure(w, fs, spacing_m=cal.spacing_m, gain_ratio=cal.gain_ratio, noise_rms=nr)
        fix = locate(m, self.cal, fs)
        ev = {
            "type": "locate_step",
            "id": self._next_id,
            "index": onset,
            "epoch": self._epoch,
            "calibration_step": calib is not None,
            **_finite(fix.to_dict()),
        }
        with self._lock:
            self._next_id += 1
            self.steps += 1
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
