"""Per-stream rate measurement from DATA timestamps (PROTOCOL.md sections 4.3 and 7).

``t_dev_us`` against ``first_sample`` is a line; its slope is the measured sample period. The fit uses a
trailing window of packets, so it follows slow drift and is not thrown off by an old gap.
"""

from __future__ import annotations

from collections import deque

import numpy as np

# Residual limits in sample periods (PROTOCOL.md 4.3): accel timestamps are estimated, so more slack.
RESIDUAL_LIMIT_ADC_PERIODS = 0.5
RESIDUAL_LIMIT_ACCEL_PERIODS = 1.5


class RateFit:
    def __init__(self, max_points: int = 400, min_points: int = 10, refit_every: int = 8) -> None:
        self._pts: deque[tuple[int, int]] = deque(maxlen=max_points)
        self._min_points = min_points
        self._refit_every = refit_every
        self._since_fit = 0
        self._fit: tuple[float, float, float] | None = None  # (index0, t0_us, slope_us_per_sample)
        self.n_added = 0

    def add(self, first_sample: int, t_dev_us: int) -> float | None:
        """Add a point. Returns its residual in microseconds against the fit of the earlier points
        (None until there are enough points)."""
        residual = self.residual_us(first_sample, t_dev_us)
        self._pts.append((first_sample, t_dev_us))
        self.n_added += 1
        self._since_fit += 1
        if self._fit is None or self._since_fit >= self._refit_every:
            self._refit()
        return residual

    def _refit(self) -> None:
        self._since_fit = 0
        if len(self._pts) < self._min_points:
            return
        arr = np.array(self._pts, dtype=np.float64)
        i0, t0 = arr[0, 0], arr[0, 1]
        x, y = arr[:, 0] - i0, arr[:, 1] - t0
        if x[-1] == x[0]:
            return
        slope, intercept = np.polyfit(x, y, 1)
        self._fit = (i0, t0 + intercept, float(slope))

    def residual_us(self, first_sample: int, t_dev_us: int) -> float | None:
        if self._fit is None:
            return None
        i0, t0, slope = self._fit
        return float(t_dev_us - (t0 + slope * (first_sample - i0)))

    def rate_hz(self) -> float | None:
        if self._fit is None or self._fit[2] <= 0:
            return None
        return 1e6 / self._fit[2]

    def period_us(self) -> float | None:
        return None if self._fit is None else self._fit[2]
