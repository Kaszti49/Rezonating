"""Locate page maths (core/locate.py), its step finder (server/locate.py) and the room simulator (sim/room.py)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from rezonating_lab.core.locate import (
    SPACING_M,
    LocateCalibration,
    calibrate,
    distance_band,
    locate,
    measure,
)
from rezonating_lab.core.ringbuf import SampleRing
from rezonating_lab.server.locate import Locator, StepDetector
from rezonating_lab.sim.room import ROOM_C_MPS, ROOM_CH1_SENS, RoomAdcSignal
from rezonating_lab.sim.scenarios import ScenarioConfig

FS = 1996.1  # the S3 rig's measured rate


def burst(t: np.ndarray) -> np.ndarray:
    d = np.clip(t, 0, None)
    return np.where(t >= 0, np.exp(-d / 0.04) * (np.sin(2 * np.pi * 35 * d) + 0.4 * np.sin(2 * np.pi * 90 * d)), 0.0)


def pair(
    delay0_s: float,
    delay1_s: float,
    a0: float = 1.0,
    a1: float = 1.0,
    noise: float = 0.0,
    n: int = 700,
    seed: int = 0,
) -> np.ndarray:
    t = np.arange(n) / FS - 0.05
    x = np.stack([a0 * burst(t - delay0_s), a1 * burst(t - delay1_s)], axis=1)
    x += 5.0  # a DC offset, like real codes
    if noise:
        x += noise * np.random.default_rng(seed).standard_normal(x.shape)
    return x


def geometry_delays(x_m: float, y_m: float, c: float = 100.0) -> tuple[float, float, float, float]:
    r0 = math.hypot(x_m + SPACING_M / 2, y_m)
    r1 = math.hypot(x_m - SPACING_M / 2, y_m)
    return r0 / c, r1 / c, r0, r1


# --------------------------------------------------------------------------------------------- measure


@pytest.mark.parametrize("lag_samples", [-2.6, -1.3, -0.4, 0.0, 0.7, 1.9])
def test_measure_finds_sub_sample_delay(lag_samples: float) -> None:
    m = measure(pair(0.0, lag_samples / FS, noise=0.01), FS)
    assert m.tau_s * FS == pytest.approx(lag_samples, abs=0.1)
    assert m.cc > 0.9
    assert not m.lag_limited


def test_measure_reversed_polarity_keeps_the_delay() -> None:
    m = measure(pair(0.0, 1.2 / FS, a1=-1.0, noise=0.01), FS)
    assert m.tau_s * FS == pytest.approx(1.2, abs=0.1)
    assert m.cc < -0.9


def test_measure_amplitudes_follow_the_channels() -> None:
    m = measure(pair(0.0, 0.0, a0=2.0, a1=1.0), FS)
    assert m.amp[0] / m.amp[1] == pytest.approx(2.0, rel=0.02)
    m2 = measure(pair(0.0, 0.0, a0=2.0, a1=1.0), FS, gain_ratio=0.5)  # ch1 is half as sensitive
    assert m2.amp[0] / m2.amp[1] == pytest.approx(1.0, rel=0.02)


def test_measure_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError):
        measure(np.zeros((100, 3)), FS)


# ---------------------------------------------------------------------------------------------- locate


@pytest.mark.parametrize("phi_deg", [-75, -45, -20, 20, 45, 75])
def test_locate_bearing_and_side(phi_deg: float) -> None:
    x, y = math.sin(math.radians(phi_deg)) * 1.5, math.cos(math.radians(phi_deg)) * 1.5
    d0, d1, r0, r1 = geometry_delays(x, y)
    m = measure(pair(d0, d1, 1 / r0, 1 / r1, noise=0.002), FS)
    cal = LocateCalibration(c_mps=100.0, calibrated=["left", "right"])
    fix = locate(m, cal, FS)
    assert fix.side == ("left" if phi_deg < 0 else "right")
    assert fix.phi_deg is not None
    assert fix.phi_deg == pytest.approx(phi_deg, abs=6)


def test_locate_straight_ahead_is_unsure_by_timing() -> None:
    m = measure(pair(0.01, 0.01, noise=0.002), FS)
    fix = locate(m, LocateCalibration(), FS)
    assert fix.side_votes["timing"] == "none"
    assert fix.phi_deg == pytest.approx(0, abs=5)


def test_locate_distance_from_reference_amplitude() -> None:
    near = measure(pair(0.0, 0.0, 1.0, 1.0), FS)
    cal = LocateCalibration(ref_amp=0.5 * (near.amp[0] + near.amp[1]), ref_m=1.0, decay_n=1.0)
    far = measure(pair(0.0, 0.0, 0.4, 0.4), FS)
    fix = locate(far, cal, FS)
    assert fix.distance_m == pytest.approx(2.5, rel=0.05)
    assert fix.distance_band == "far"
    assert distance_band(None) == "unknown"
    assert distance_band(0.5) == "near"
    assert distance_band(1.5) == "mid"


def test_uncalibrated_distance_is_unknown() -> None:
    fix = locate(measure(pair(0.0, 0.0005), FS), LocateCalibration(), FS)
    assert fix.distance_m is None
    assert fix.distance_band == "unknown"
    assert fix.phi_sigma_deg >= 20  # the wave speed is only a guess


# ------------------------------------------------------------------------------------------- calibrate


def _spot(x: float, y: float, c: float, tau0: float, sens1: float, swap: bool, k: int = 5):
    d0, d1, r0, r1 = geometry_delays(x, y, c)
    a0, a1 = 1 / r0, sens1 / r1
    if swap:
        d0, d1, a0, a1 = d1, d0, a1, a0
    return [measure(pair(d0, d1 + tau0, a0, a1, noise=0.003, seed=i), FS) for i in range(k)]


@pytest.mark.parametrize("swap", [False, True])
def test_calibrate_recovers_speed_offset_gain_and_sides(swap: bool) -> None:
    c, tau0, sens1 = 60.0, 0.2 / FS, 0.9
    spots = {"left": _spot(-1.0, 0.0, c, tau0, sens1, swap), "right": _spot(1.0, 0.0, c, tau0, sens1, swap)}
    new, notes = calibrate(spots, LocateCalibration())
    assert new.swap_sides is swap
    assert new.c_mps == pytest.approx(c * SPACING_M / (math.hypot(1 + SPACING_M / 2, 0) - (1 - SPACING_M / 2)), rel=0.1)
    if not swap:
        assert new.tau0_s * FS == pytest.approx(0.2, abs=0.1)
        assert new.gain_ratio == pytest.approx(sens1, rel=0.03)
    assert new.ref_amp is not None
    assert sorted(new.calibrated) == ["left", "right"]
    assert any("swapped" in n for n in notes) is swap
    # a step 1.5 m to the left now locates on the left
    d0, d1, r0, r1 = geometry_delays(-1.5, 0.4, c)
    a0, a1 = 1 / r0, sens1 / r1
    if swap:
        d0, d1, a0, a1 = d1, d0, a1, a0
    fix = locate(measure(pair(d0, d1 + tau0, a0, a1, noise=0.003), FS, gain_ratio=new.gain_ratio), new, FS)
    assert fix.side == "left"


def test_calibrate_one_spot_sets_speed_and_warns() -> None:
    new, notes = calibrate({"left": _spot(-1.0, 0.0, 80.0, 0.0, 1.0, False)}, LocateCalibration())
    assert new.c_mps == pytest.approx(80.0, rel=0.15)
    assert any("only one spot" in n for n in notes)


# ------------------------------------------------------------------------------------- step detector


def test_detector_finds_each_burst_once() -> None:
    rng = np.random.default_rng(3)
    n = int(FS * 6)
    x = 100.0 + 0.01 * rng.standard_normal((n, 2))
    onsets = [int(FS * s) for s in (1.0, 1.6, 2.4, 3.1, 4.5)]
    t = np.arange(n) / FS
    for o in onsets:
        b = burst(t - o / FS)
        x[:, 0] += b
        x[:, 1] += 0.8 * b
    det = StepDetector(FS)
    found: list[int] = []
    for i in range(0, n, 80):  # arbitrary chunking
        found += det.feed(i, x[i : i + 80])
    assert len(found) == len(onsets)
    for f, o in zip(found, onsets, strict=True):
        assert abs(f - o) <= det.block + 2


# ------------------------------------------------------------------------- end to end on the room sim


class FakeManager:
    def __init__(self, ring: SampleRing) -> None:
        self.rings = {0: ring}
        self.events: list[dict] = []
        self.logs: list[str] = []

    def stream_names(self) -> dict[int, str]:
        return {0: "adc_raw"}

    def stream_info(self, sid: int) -> dict:
        return {"fs_hz": FS}

    def publish(self, ev: dict) -> None:
        self.events.append(ev)

    def host_log(self, msg: str, level: int = 3) -> None:
        self.logs.append(msg)


def _run_room(loc: Locator, sig: RoomAdcSignal, ring: SampleRing, start: int, seconds: float) -> int:
    chunk = int(FS * 0.04)
    i = start
    for _ in range(int(seconds / 0.04)):
        codes, _ = sig.block(i, chunk, FS, (4, 4))
        ring.write(i, codes)
        i += chunk
        loc.tick()
    return i


def test_room_sim_end_to_end_side_after_calibration(tmp_path) -> None:
    ring = SampleRing(2, int(FS * 30))
    mgr = FakeManager(ring)
    loc = Locator(mgr, tmp_path / "locate.json")
    sig = RoomAdcSignal(ScenarioConfig(seed=5, walk_s=1000.0, rest_s=1.0), acq_id=1)
    # calibration from the walker's own steps would need it to stand still; set it from the sim's truth instead
    loc.set_values(c_mps=ROOM_C_MPS, decay_n=None, spacing_m=None)
    loc.cal.gain_ratio = ROOM_CH1_SENS
    loc.cal.calibrated = ["left", "right"]
    _run_room(loc, sig, ring, 0, 40.0)
    steps = [e for e in mgr.events if e["type"] == "locate_step"]
    truth = {round(s.t_s * FS): s for s in sig._steps}
    assert len(steps) >= 0.9 * len([s for s in sig._steps if s.t_s < 39.5])
    right = wrong = 0
    for ev in steps:
        near = min(truth, key=lambda k: abs(k - ev["index"]))
        st = truth[near]
        assert abs(near - ev["index"]) < FS * 0.05  # the onset is the true step
        if abs(st.x_m) < 0.5 or ev["side"] == "unsure":
            continue
        if ev["side"] == ("left" if st.x_m < 0 else "right"):
            right += 1
        else:
            wrong += 1
    assert right >= 10
    assert right / (right + wrong) >= 0.9
    assert loc.skipped_gaps == 0
    assert (tmp_path / "locate.json").is_file()


def test_locator_counts_steps_with_lost_samples() -> None:
    ring = SampleRing(2, int(FS * 30))
    mgr = FakeManager(ring)
    loc = Locator(mgr, None)
    sig = RoomAdcSignal(ScenarioConfig(seed=2, walk_s=1000.0, rest_s=1.0), acq_id=1)
    chunk = int(FS * 0.04)
    i = 0
    first_step = int(sig.cfg.first_step_s * FS)
    for _ in range(int(3.0 / 0.04)):
        codes, _ = sig.block(i, chunk, FS, (4, 4))
        if i <= first_step + 100 < i + chunk:
            codes = codes[: first_step + 100 - i]  # lose the rest of this chunk, inside the first step's window
            ring.write(i, codes)
        else:
            ring.write(i, codes)
        i += chunk
        loc.tick()
    assert loc.skipped_gaps >= 1


# ------------------------------------------------------------------------------------------- REST API


def test_locate_api_with_the_room_simulator(tmp_path) -> None:
    import time

    from fastapi.testclient import TestClient
    from rezonating_lab.recorder.config import LabConfig
    from rezonating_lab.server.app import create_app
    from rezonating_lab.server.device import DeviceManager
    from rezonating_lab.sim.node import SimConfig
    from rezonating_lab.sim.server import SimThread

    cfg = LabConfig(config_path=tmp_path / "rzlab" / "config.toml", staging_dir=tmp_path / "staging")
    app = create_app(8765, manager=DeviceManager(embedded_sim=False), static_dir=tmp_path / "no-static", lab_config=cfg)
    with (
        SimThread(SimConfig(speed=10.0, adc_signal=RoomAdcSignal)) as sim,
        TestClient(app, base_url="http://127.0.0.1:8765") as c,
    ):
        v = c.get("/api/locate").json()
        assert v["type"] == "locate" and v["steps"] == 0 and v["calibration"]["c_mps"] == 100.0
        assert c.post("/api/locate/calibrate", json={"spot": "front"}).status_code == 422
        assert c.post("/api/locate/settings", json={"c_mps": 5}).status_code == 422
        r = c.post("/api/connect", json={"kind": "tcp", "host": "127.0.0.1", "port": sim.port, "start": True})
        assert r.status_code == 200, r.text
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and c.get("/api/locate").json()["steps"] < 5:
            time.sleep(0.2)
        v = c.get("/api/locate").json()
        assert v["steps"] >= 5, v
        step = v["recent"][-1]
        assert step["type"] == "locate_step" and step["side"] in ("left", "right", "unsure")
        v = c.post("/api/locate/calibrate", json={"spot": "left", "steps": 3}).json()
        assert v["calibrating"] == {"spot": "left", "got": 0, "want": 3}
        assert c.post("/api/locate/calibrate/cancel").json()["calibrating"] is None
        assert c.post("/api/locate/settings", json={"c_mps": 150}).json()["calibration"]["c_mps"] == 150
        assert (tmp_path / "rzlab" / "locate.json").is_file()
        assert c.post("/api/locate/clear").json()["recent"] == []
        assert c.post("/api/locate/calibrate/reset").json()["calibration"]["c_mps"] == 100.0
        c.post("/api/disconnect")
