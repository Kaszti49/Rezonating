"""A person walking a loop around the device, for the Locate page without hardware (``rzlab sim --room``,
``rzlab serve --sim-room``).

Each step has a position on the floor. Its burst reaches each geophone after ``r / c`` and with an amplitude that
falls as ``1 / r``; the higher tone fades faster with distance. Geometry as in ``core/locate.py``: channel 0 at
x = -d/2 (left), channel 1 at +d/2 (right), +y is front. Plausible, not physical: this is test input, not a model.
The ground truth (``--truth``) carries ``x_m`` and ``y_m`` for every step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.locate import SPACING_M
from .scenarios import BURST_F1_HZ, BURST_F2_HZ, BURST_LENGTH_S, BURST_TAU_S, AdcSignal, ScenarioConfig, Step

ROOM_C_MPS = 100.0  # wave speed of the simulated floor
ROOM_CH1_SENS = 0.97  # channel 1's geophone is 3 % less sensitive (the calibration should find it)
ROOM_HF_DECAY_PER_M = 0.4  # the 90 Hz part fades as exp(-0.4 r)
STRIDE_M = 0.65
FOOT_OFFSET_M = 0.1  # left and right foot sit this far either side of the path
# A loop that passes left, front, right and behind the device at 1 to 2.7 m.
WAYPOINTS = [(-2.5, 1.0), (2.5, 1.0), (2.5, -1.5), (-2.5, -1.5)]


@dataclass
class RoomStep(Step):
    x_m: float = 0.0
    y_m: float = 0.0

    def truth_fields(self) -> dict:
        return {"x_m": round(self.x_m, 3), "y_m": round(self.y_m, 3)}


def _loop_position(s_m: float) -> tuple[float, float, float, float]:
    """Point at path length ``s_m`` along the closed loop, and the unit direction of walking there."""
    pts = WAYPOINTS + WAYPOINTS[:1]
    seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(WAYPOINTS))]
    s = s_m % sum(seg)
    for i, L in enumerate(seg):
        if s <= L:
            (x0, y0), (x1, y1) = pts[i], pts[i + 1]
            ux, uy = (x1 - x0) / L, (y1 - y0) / L
            return x0 + ux * s, y0 + uy * s, ux, uy
        s -= L
    raise AssertionError("unreachable")


class RoomAdcSignal(AdcSignal):
    """Footsteps of one walker on the loop; the same timing and rests as the generic signal."""

    def __init__(self, cfg: ScenarioConfig, acq_id: int, shorted: bool = False) -> None:
        super().__init__(cfg, acq_id, shorted=shorted)
        self.positions = 0

    def _extend(self, until_s: float) -> None:
        before = len(self._steps)
        super()._extend(until_s)
        for i in range(before, len(self._steps)):
            st = self._steps[i]
            x, y, ux, uy = _loop_position(st.n * STRIDE_M)
            foot = FOOT_OFFSET_M if st.n % 2 == 0 else -FOOT_OFFSET_M
            # the foot sits to the side of the walking direction (normal = (uy, -ux))
            self._steps[i] = RoomStep(st.n, st.t_s, st.amp_v, x + foot * uy, y - foot * ux)

    def _add_steps(self, volts: np.ndarray, t: np.ndarray) -> None:
        t_a, t_b = float(t[0]), float(t[-1])
        half = SPACING_M / 2
        while self._active_from < len(self._steps) and self._steps[self._active_from].t_s + BURST_LENGTH_S + 0.1 < t_a:
            self._active_from += 1
        for step in self._steps[self._active_from :]:
            if step.t_s > t_b:
                break
            assert isinstance(step, RoomStep)
            for ch, (gx, sens) in enumerate(((-half, 1.0), (half, ROOM_CH1_SENS))):
                r = max(0.15, math.hypot(step.x_m - gx, step.y_m))
                dt = t - step.t_s - r / ROOM_C_MPS
                m = (dt >= 0) & (dt <= BURST_LENGTH_S)
                d = dt[m]
                hf = 0.4 * math.exp(-ROOM_HF_DECAY_PER_M * r)
                volts[m, ch] += (
                    step.amp_v
                    * sens
                    / r
                    * np.exp(-d / BURST_TAU_S)
                    * (np.sin(2 * np.pi * BURST_F1_HZ * d) + hf * np.sin(2 * np.pi * BURST_F2_HZ * d + 0.7))
                )
