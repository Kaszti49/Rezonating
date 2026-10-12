"""Synthetic signals for the simulator, in raw sensor codes, with ground truth.

ADC channels: a noise floor plus footstep-like bursts (decaying oscillations) at walking cadence, in walking
bouts separated by rests. Accelerometer: about 1 g on z plus a small mains-motor hum. Everything is seeded,
and a signal block depends only on the sample indices it covers, never on wall-clock time.

The signals are plausible, not physical: no pack maths lives here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import numpy as np

ADC_VREF_V = 1.2
ADC_FULL_SCALE = 2**23  # codes are 24-bit two's complement: -2^23 .. 2^23 - 1
ACCEL_FULL_SCALE = 2**19  # 20-bit two's complement
ACCEL_LSB_PER_G = {2: 256000, 4: 128000, 8: 64000}
# Burst waveform (decaying oscillation) and where the second channel sits relative to the first.
BURST_TAU_S = 0.04
BURST_F1_HZ = 35.0
BURST_F2_HZ = 90.0
BURST_LENGTH_S = 10 * BURST_TAU_S  # a burst is cut here (about 4 codes left), so a block never depends on its split
CH1_DELAY_S = 0.003
CH1_GAIN = 0.55


@dataclass
class ScenarioConfig:
    seed: int = 1
    cadence_hz: float = 1.8  # steps per second while walking
    cadence_jitter: float = 0.06  # relative standard deviation of the step interval
    walk_s: float = 14.0
    rest_s: float = 6.0
    first_step_s: float = 0.5
    step_amp_v: float = 0.0015  # burst peak at the ADC input, before gain
    step_amp_spread: float = 0.15  # relative standard deviation of the amplitude
    adc_noise_v: float = 6e-6  # rms at the ADC input
    adc_offset_v: float = 1e-5
    hum_hz: float = 50.0
    hum_g: float = 0.002
    accel_noise_g: float = 0.0005
    accel_offset_g: tuple[float, float, float] = (0.012, -0.018, 1.0)


@dataclass
class Step:
    n: int  # step number within the acquisition
    t_s: float  # onset, seconds since acquisition start
    amp_v: float


class GroundTruthLog:
    """Ground-truth events kept in memory and optionally appended to a .jsonl file."""

    def __init__(self, path: Path | None = None) -> None:
        self.events: list[dict] = []
        self._fh: IO[str] | None = open(path, "w", encoding="utf-8") if path else None

    def add(self, event: dict) -> None:
        self.events.append(event)
        if self._fh:
            self._fh.write(json.dumps(event) + "\n")
            self._fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


def _children(seed: int, acq_id: int, n: int) -> list[np.random.Generator]:
    return [np.random.default_rng(c) for c in np.random.SeedSequence([seed, acq_id]).spawn(n)]


class AdcSignal:
    """Two ADC channels for one acquisition. Index i is at time ``i / rate_hz`` since acquisition start."""

    def __init__(self, cfg: ScenarioConfig, acq_id: int) -> None:
        self.cfg = cfg
        self._step_rng, self._noise_rng = _children(cfg.seed, acq_id, 2)
        self._steps: list[Step] = []
        self._next_t_s = cfg.first_step_s
        self._reported = 0  # steps already returned to the caller as ground truth
        self._active_from = 0  # steps before this index are over for good

    def _extend(self, until_s: float) -> None:
        cfg = self.cfg
        period = 1.0 / cfg.cadence_hz
        cycle = cfg.walk_s + cfg.rest_s
        while self._next_t_s <= until_s:
            t = self._next_t_s
            pos = t % cycle
            if pos >= cfg.walk_s:  # resting: jump to the start of the next walking bout
                self._next_t_s = t - pos + cycle
                continue
            side = 1.0 if len(self._steps) % 2 == 0 else 0.85  # left and right foot differ a little
            amp = cfg.step_amp_v * side * max(0.2, 1.0 + cfg.step_amp_spread * float(self._step_rng.standard_normal()))
            self._steps.append(Step(len(self._steps), t, amp))
            self._next_t_s = t + period * max(0.5, 1.0 + cfg.cadence_jitter * float(self._step_rng.standard_normal()))

    def block(self, first_idx: int, n: int, rate_hz: float, gains: tuple[int, int]) -> tuple[np.ndarray, list[Step]]:
        """Codes (n, 2) int32 for indices ``first_idx .. first_idx + n - 1``, and the steps whose onset
        falls inside this block (ground truth, each reported exactly once)."""
        cfg = self.cfg
        t = (first_idx + np.arange(n)) / rate_hz
        t_a, t_b = float(t[0]), float(t[-1])
        self._extend(t_b)
        volts = cfg.adc_offset_v + cfg.adc_noise_v * self._noise_rng.standard_normal((n, 2))
        while self._active_from < len(self._steps) and self._steps[self._active_from].t_s + BURST_LENGTH_S < t_a:
            self._active_from += 1
        for step in self._steps[self._active_from :]:
            if step.t_s > t_b:
                break
            for ch, (delay, gain) in enumerate(((0.0, 1.0), (CH1_DELAY_S, CH1_GAIN))):
                dt = t - step.t_s - delay
                m = (dt >= 0) & (dt <= BURST_LENGTH_S)
                d = dt[m]
                volts[m, ch] += (
                    step.amp_v
                    * gain
                    * np.exp(-d / BURST_TAU_S)
                    * (np.sin(2 * np.pi * BURST_F1_HZ * d) + 0.4 * np.sin(2 * np.pi * BURST_F2_HZ * d + 0.7))
                )
        new = []
        while self._reported < len(self._steps) and self._steps[self._reported].t_s <= t_b:
            new.append(self._steps[self._reported])
            self._reported += 1
        g = np.array(gains, dtype=np.float64)
        codes = np.rint(volts * g / ADC_VREF_V * ADC_FULL_SCALE)
        return np.clip(codes, -ADC_FULL_SCALE, ADC_FULL_SCALE - 1).astype(np.int32), new


class AccelSignal:
    """Three accelerometer channels for one acquisition."""

    def __init__(self, cfg: ScenarioConfig, acq_id: int) -> None:
        self.cfg = cfg
        (self._noise_rng,) = _children(cfg.seed + 7919, acq_id, 1)

    def block(self, first_idx: int, n: int, rate_hz: float, range_g: int) -> np.ndarray:
        cfg = self.cfg
        t = (first_idx + np.arange(n)) / rate_hz
        g = np.empty((n, 3))
        g[:] = cfg.accel_offset_g
        g += cfg.accel_noise_g * self._noise_rng.standard_normal((n, 3))
        g[:, 2] += cfg.hum_g * np.sin(2 * np.pi * cfg.hum_hz * t)
        g[:, 0] += 0.3 * cfg.hum_g * np.sin(2 * np.pi * cfg.hum_hz * t + 1.1)
        codes = np.rint(g * ACCEL_LSB_PER_G[range_g])
        return np.clip(codes, -ACCEL_FULL_SCALE, ACCEL_FULL_SCALE - 1).astype(np.int32)
