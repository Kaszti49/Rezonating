"""Per-stream rate measurement from DATA timestamps (PROTOCOL.md sections 4.3 and 7).

``t_dev_us`` against ``first_sample`` is a line; its slope is the measured sample period. The fit uses a
trailing window of packets, so it follows slow drift and is not thrown off by an old gap.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

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


# ----------------------------------------------------------------------------------- label time base
# A live mark is stamped on the PC. Two maps turn that stamp into a sample index (PROTOCOL.md section 7):
# host time -> node time (PING/PONG pairs), then node time -> sample index (the DATA packets' t_dev_us).


@dataclass(frozen=True)
class OffsetEstimate:
    offset_us: float  # node clock minus host clock at the asked host time
    unc_us: float  # half the round trip of the best PONG used (the NTP-style bound on its asymmetry)


class ClockMap:
    """Host clock to node clock from PING/PONG pairs.

    Each pair gives ``offset = t_dev - (host_send + rtt / 2)`` with an error of at most ``rtt / 2``. Around a
    host time ``T`` the pairs within ``window_s`` are used; of those only the ones with a round trip close to the
    smallest (the most trustworthy) feed a straight-line fit of offset against time, which follows the slow drift
    between the two crystals. Thread-safe: the device thread adds, any thread reads.
    """

    def __init__(self, max_points: int = 20000, window_s: float = 8.0) -> None:
        self._pts: deque[tuple[float, float, float]] = deque(maxlen=max_points)  # host_mid_us, offset_us, rtt_us
        self._window_us = window_s * 1e6
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._pts)

    def add(self, host_send_us: float, host_recv_us: float, t_dev_us: float) -> None:
        rtt = host_recv_us - host_send_us
        if rtt < 0:
            return
        mid = host_send_us + rtt / 2.0
        with self._lock:
            self._pts.append((mid, t_dev_us - mid, rtt))

    def offset_at(self, host_us: float) -> OffsetEstimate | None:
        with self._lock:
            pts = list(self._pts)
        if not pts:
            return None
        arr = np.array(pts, dtype=np.float64)
        near = arr[np.abs(arr[:, 0] - host_us) <= self._window_us]
        if len(near) == 0:  # no pair in the window: the closest one in time
            near = arr[[int(np.argmin(np.abs(arr[:, 0] - host_us)))]]
        rtt_min = float(near[:, 2].min())
        good = near[near[:, 2] <= rtt_min + max(500.0, 0.5 * rtt_min)]
        if len(good) >= 4 and good[-1, 0] - good[0, 0] > 1e6:
            x = good[:, 0] - host_us
            slope, icpt = np.polyfit(x, good[:, 1], 1)
            offset = float(icpt)
            # a slope beyond 1000 ppm is not crystal drift but noise: do not extrapolate it
            if abs(slope) > 1e-3:
                offset = float(np.median(good[:, 1]))
        else:
            offset = float(np.median(good[:, 1]))
        return OffsetEstimate(offset, rtt_min / 2.0)


def index_at_time(first_samples: np.ndarray, t_dev_us: np.ndarray, t_us: float, n_local: int = 60) -> float | None:
    """Sample index (float) of node time ``t_us``, from a straight line through the ``n_local`` DATA packets
    nearest in time. ``first_samples`` and ``t_dev_us`` are the packets' ``first_sample`` and ``t_dev_us``,
    sorted by time. Extrapolates a little beyond the first or last packet; returns None with fewer than 2 packets."""
    n = len(t_dev_us)
    if n < 2:
        return None
    k = int(np.searchsorted(t_dev_us, t_us))
    lo = max(0, min(k - n_local // 2, n - n_local))
    hi = min(n, lo + n_local)
    x = t_dev_us[lo:hi].astype(np.float64) - t_us
    y = first_samples[lo:hi].astype(np.float64)
    if hi - lo < 2 or x[-1] == x[0]:
        return None
    slope, icpt = np.polyfit(x, y, 1)  # index = icpt + slope * (t - t_us); at t = t_us: icpt
    return float(icpt)


def fit_stream_rate(first_samples: np.ndarray, t_dev_us: np.ndarray) -> tuple[float, float] | None:
    """Least-squares line through all DATA packets: ``(rate_hz, t_dev_us at index first_samples[0])``.
    None with fewer than 2 packets or no index spread."""
    if len(first_samples) < 2:
        return None
    x = first_samples.astype(np.float64) - float(first_samples[0])
    y = t_dev_us.astype(np.float64) - float(t_dev_us[0])
    if x[-1] == x[0]:
        return None
    slope, icpt = np.polyfit(x, y, 1)  # microseconds per sample
    if slope <= 0:
        return None
    return 1e6 / float(slope), float(t_dev_us[0]) + float(icpt)
