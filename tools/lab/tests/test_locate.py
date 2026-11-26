"""Locate page: the left / right / same rule (core/locate.py), the step finder and state (server/locate.py), the room sim."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from rezonating_lab.core.locate import (
    CH0_SIDE,
    FIRST_S,
    LOUDER,
    SPACING_M,
    ZERO_TAU_S,
    StepMeasure,
    decide,
    measure,
    walk_side,
)
from rezonating_lab.core.ringbuf import SampleRing
from rezonating_lab.server.locate import Locator, StepDetector
from rezonating_lab.sim.room import ROOM_C_MPS, RoomAdcSignal
from rezonating_lab.sim.scenarios import ScenarioConfig

FS = 1996.1  # the S3 rig's measured rate
WARM_S = 2.5  # the step detector learns the floor first (about 1.7 s); test steps start after this


def burst(t: np.ndarray) -> np.ndarray:
    d = np.clip(t, 0, None)
    return np.where(t >= 0, np.exp(-d / 0.04) * (np.sin(2 * np.pi * 35 * d) + 0.4 * np.sin(2 * np.pi * 90 * d)), 0.0)


def knock(t: np.ndarray) -> np.ndarray:
    """A step as the geophones hear it on a real floor: a short broadband knock (a 250 Hz Ricker pulse, energy up
    to about 600 Hz, as in the spectrograms of 2026-11-26) on top of the ringing ``burst``."""
    a = (np.pi * 250.0 * (t - 0.004)) ** 2
    return burst(t) + np.where(t >= 0, (1 - 2 * a) * np.exp(-a), 0.0)


def pair(
    delay0_s: float, delay1_s: float, a0: float = 1.0, a1: float = 1.0, noise: float = 0.0, n: int = 700, seed: int = 0
) -> np.ndarray:
    t = np.arange(n) / FS - 0.05
    x = np.stack([a0 * burst(t - delay0_s), a1 * burst(t - delay1_s)], axis=1) + 5.0  # a DC offset, like real codes
    if noise:
        x += noise * np.random.default_rng(seed).standard_normal(x.shape)
    return x


# --------------------------------------------------------------------------------------------- measure


@pytest.mark.parametrize("lag_samples", [-2.6, -1.3, -0.4, 0.0, 0.7, 1.9])
def test_measure_finds_sub_sample_delay(lag_samples: float) -> None:
    m = measure(pair(0.0, lag_samples / FS, noise=0.01), FS)
    assert m.tau_s * FS == pytest.approx(lag_samples, abs=0.15)
    assert m.cc > 0.9 and not m.lag_limited


def test_measure_reversed_polarity_keeps_the_delay() -> None:
    m = measure(pair(0.0, 1.2 / FS, a1=-1.0, noise=0.01), FS)
    assert m.tau_s * FS == pytest.approx(1.2, abs=0.15)
    assert m.cc < -0.9


def test_measure_amplitudes_follow_the_channels() -> None:
    m = measure(pair(0.0, 0.0, a0=2.0, a1=1.0), FS)
    assert m.amp[0] / m.amp[1] == pytest.approx(2.0, rel=0.02)


def test_measure_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError):
        measure(np.zeros((100, 3)), FS)


# ---------------------------------------------------------------------------------------------- decide


def _m(
    lead_ms: float, ratio: float = 1.0, cc: float = -0.99, lag_limited: bool = False, corr: float = -0.95
) -> StepMeasure:
    """A measured step: ``lead_ms`` > 0 means channel 0 heard it first; ``ratio`` is ch0 / ch1 loudness."""
    return StepMeasure(ZERO_TAU_S + lead_ms / 1e3, cc, (1000.0 * ratio, 1000.0), lag_limited, corr)


def test_channel_0_is_the_right_geophone() -> None:
    # coin test 2026-11-26: taps by the right geophone reached ch0 first (0.83 ms), by the left one ch1 (0.62 ms)
    assert CH0_SIDE == "right"
    assert decide(_m(0.83)).side == "right" and decide(_m(-0.62)).side == "left"


def test_first_decides_the_side() -> None:
    f = decide(_m(1.0))
    assert f.side == "right" and f.reason == "first" and f.lead_s == pytest.approx(1e-3)
    assert decide(_m(-1.0)).side == "left"


def test_the_medians_of_the_one_side_walks_of_2026_11_26() -> None:
    # left walks -0.17 .. -0.22 ms, right walks +0.15 .. +0.17 ms (EXP-005)
    assert decide(_m(-0.2)).side == "left" and decide(_m(0.16)).side == "right"


def test_first_beats_louder() -> None:
    f = decide(_m(-1.0, ratio=1.8))
    assert f.side == "left" and f.reason == "first"


def test_much_louder_decides_when_the_timing_is_not_clear() -> None:
    f = decide(_m(0.0, ratio=1.8))
    assert f.side == "right" and f.reason == "louder" and f.lead_s == 0.0
    assert decide(_m(0.0, ratio=0.55)).side == "left"


def test_neither_is_the_same() -> None:
    # loudness that differs by 10 to 30 % was right for only 47 % of the walks' steps (2026-11-26): no side
    for ratio in (0.8, 0.93, 1.0, 1.1, 1.3):
        f = decide(_m(0.0, ratio=ratio))
        assert f.side == "same" and f.reason == "same" and f.lead_s == 0.0


def test_limits() -> None:
    assert decide(_m(0.0, ratio=LOUDER * 0.999)).side == "same"
    assert decide(_m(0.0, ratio=1.0 / LOUDER * 1.001)).side == "same"
    assert decide(_m(FIRST_S * 1e3 * 0.99)).side == "same"
    assert decide(_m(FIRST_S * 1e3 * 1.01)).side == "right"


@pytest.mark.parametrize("bad", [dict(cc=-0.6), dict(cc=0.5), dict(lag_limited=True), dict(lead=6.0)])
def test_an_unclear_timing_peak_is_never_first(bad: dict) -> None:
    lead = bad.pop("lead", -2.0)
    for ratio, side in ((1.8, "right"), (0.55, "left"), (1.0, "same")):
        assert decide(_m(lead, ratio=ratio, **bad)).side == side


def test_agree_is_the_zero_lag_correlation_of_either_sign() -> None:
    assert decide(_m(0.0, corr=-0.95)).agree and decide(_m(0.0, corr=0.95)).agree
    assert not decide(_m(0.0, corr=-0.25)).agree


def test_measure_correlation() -> None:
    assert measure(pair(0.0, 0.0), FS).corr == pytest.approx(1.0, abs=0.01)
    assert measure(pair(0.0, 0.0, a1=-0.7), FS).corr == pytest.approx(-1.0, abs=0.01)
    assert abs(measure(np.random.default_rng(1).standard_normal((700, 2)), FS).corr) < 0.5


def test_the_arrival_of_the_step_counts_for_the_loudness() -> None:
    # a burst that is only there for the first 40 ms after the onset: a Hann window would give it 19 % weight
    t = np.arange(700) / FS - 0.05
    x = np.where((t >= 0) & (t < 0.04), np.sin(2 * np.pi * 50 * t), 0.0)
    late = np.where((t >= 0.1) & (t < 0.14), np.sin(2 * np.pi * 50 * (t - 0.1)), 0.0)
    m = measure(np.stack([x, late], axis=1), FS)
    assert m.amp[0] / m.amp[1] == pytest.approx(1.0, abs=0.1)


def test_swap_sides_turns_left_and_right_but_not_same() -> None:
    assert decide(_m(1.0), swap_sides=True).side == "left"
    assert decide(_m(-1.0), swap_sides=True).side == "right"
    assert decide(_m(0.0, ratio=1.8), swap_sides=True).side == "left"
    assert decide(_m(0.0), swap_sides=True).side == "same"


def test_the_lag_limited_steps_of_2026_11_24_0915_with_that_days_placement() -> None:
    # left steps whose timing peak sat on the search edge; the case stood the other way round (ch0 on the left)
    ratios = [2.31, 1.97, 2.54, 1.04, 1.44, 1.79, 1.44, 1.72]
    got = [decide(StepMeasure(6.17e-3, -0.7, (1000.0 * r, 1000.0), True), swap_sides=True).side for r in ratios]
    assert got.count("left") == 5 and got.count("same") == 3 and "right" not in got


@pytest.mark.parametrize(
    ("sides", "want"),
    [
        (["left"], "same"),
        (["left", "left"], "left"),
        (["left", "right", "left"], "left"),
        (["left", "right", "same"], "same"),
        (["left", "left", "right", "right", "right"], "right"),
        ([], "same"),
    ],
)
def test_walk_side_is_the_majority_of_the_last_three(sides: list[str], want: str) -> None:
    assert walk_side(sides) == want


# ------------------------------------------------------------------------------------- step detector


def test_detector_finds_each_burst_once() -> None:
    rng = np.random.default_rng(3)
    n = int(FS * (WARM_S + 5))
    x = 100.0 + 0.01 * rng.standard_normal((n, 2))
    onsets = [int(FS * (WARM_S + s)) for s in (0.0, 0.6, 1.4, 2.1, 3.5)]
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
        assert abs(f - o) <= det.frame + 2  # the onset is the start of the frame that holds the step


def test_detector_one_onset_for_a_long_ringing_step() -> None:
    rng = np.random.default_rng(4)
    n = int(FS * (WARM_S + 4))
    t = np.arange(n) / FS
    d = np.clip(t - WARM_S, 0, None)
    ring = np.where(t >= WARM_S, 2000.0 * np.exp(-d / 0.25) * np.sin(2 * np.pi * 14 * d), 0.0)
    x = 100.0 + rng.standard_normal((n, 2)) + ring[:, None]
    det = StepDetector(FS)
    found = det.feed(0, x)
    assert len(found) == 1
    assert abs(found[0] - int(FS * WARM_S)) <= det.frame + 2


def test_detector_finds_small_steps_after_loud_walking() -> None:
    rng = np.random.default_rng(8)
    n = int(FS * 35)
    t = np.arange(n) / FS
    x = 100.0 * rng.standard_normal((n, 2))
    onsets: list[float] = []
    for k in range(40):  # 1.0 s .. 24 s loud walking, ringing tails
        s = 1.0 + 0.6 * k
        d = np.clip(t - s, 0, None)
        x += (np.where(t >= s, 20000.0 * np.exp(-d / 0.2) * np.sin(2 * np.pi * 15 * d), 0.0))[:, None]
    for k in range(5):
        s = 30.0 + 0.8 * k  # 5.6 s after the last loud step: the floor needs its 5 s to come down
        onsets.append(s)
        x += (1500.0 * knock(t - s))[:, None]
    det = StepDetector(FS)
    found = np.array(det.feed(0, x))
    assert det.noise_rms < 400  # the floor is the noise, not the tails
    assert sum(any(abs(found - int(o * FS)) <= det.frame + 2) for o in onsets) == len(onsets)


def test_detector_floor_follows_a_rise_of_the_background() -> None:
    rng = np.random.default_rng(9)
    n = int(FS * 40)
    x = 100.0 * rng.standard_normal((n, 2))
    x[n // 2 :] *= 3.0
    det = StepDetector(FS)
    found = det.feed(0, x)
    assert len(found) <= 2  # the jump itself may trigger, the new background may not
    assert det.noise_rms > 200


def test_detector_ignores_dc_and_slow_drift_and_a_jump_after_a_gap() -> None:
    rng = np.random.default_rng(5)
    n = int(FS * 4)
    t = np.arange(n) / FS
    x = 5000.0 + 300.0 * np.sin(2 * np.pi * 0.5 * t)[:, None] + rng.standard_normal((n, 2))
    det = StepDetector(FS)
    assert det.feed(0, x) == []
    det.gap()
    assert det.feed(n + 100, x[: int(FS)] + 40000.0) == []


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


def _run_room(loc: Locator, sig: RoomAdcSignal, ring: SampleRing, seconds: float) -> None:
    chunk = int(FS * 0.04)
    i = 0
    for _ in range(int(seconds / 0.04)):
        codes, _ = sig.block(i, chunk, FS, (4, 4))
        ring.write(i, codes)
        i += chunk
        loc.tick()


def test_room_sim_says_the_right_side_for_steps_at_the_sides() -> None:
    ring = SampleRing(2, int(FS * 30))
    mgr = FakeManager(ring)
    loc = Locator(mgr, None)
    sig = RoomAdcSignal(ScenarioConfig(seed=5, walk_s=1000.0, rest_s=1.0), acq_id=1)
    _run_room(loc, sig, ring, 40.0)
    steps = [e for e in mgr.events if e["type"] == "locate_step"]
    assert len(steps) >= 0.9 * len([s for s in sig._steps if s.t_s < 39.5])
    right = wrong = 0
    for ev in steps:
        st = min(sig._steps, key=lambda s: abs(round(s.t_s * FS) - ev["index"]))
        assert abs(round(st.t_s * FS) - ev["index"]) < FS * 0.05  # the onset is the true step
        delay = (math.hypot(st.x_m - SPACING_M / 2, st.y_m) - math.hypot(st.x_m + SPACING_M / 2, st.y_m)) / ROOM_C_MPS
        if abs(delay) < 1e-3:  # the simulated floor is ideal: only steps clearly to one side
            continue
        right += ev["side"] == ("left" if delay > 0 else "right")
        wrong += ev["side"] == ("right" if delay > 0 else "left")
    assert right >= 10 and wrong == 0


# --------------------------------------------------------------------------------- Locator


def _feed_steps(loc: Locator, ring: SampleRing, amps: list[float], period_s: float, full_scale: bool = False) -> None:
    """Steps of the given peak codes every ``period_s`` on both channels, after ``WARM_S`` of quiet."""
    n = int(FS * (WARM_S + 0.5 + period_s * len(amps)))
    t = np.arange(n) / FS
    x = 20.0 * np.random.default_rng(6).standard_normal((n, 2))
    for i, a in enumerate(amps):
        x += (a * burst(t - WARM_S - i * period_s))[:, None]
    if full_scale:
        x = np.clip(x, -(2**23), 2**23 - 1)
    loc.tick()
    for i in range(0, n, 80):
        ring.write(i, np.round(x[i : i + 80]).astype(np.int32))
        loc.tick()


def test_detector_finds_a_step_right_after_a_gap_once() -> None:
    rng = np.random.default_rng(11)
    n = int(FS * 4)
    x = 20.0 * rng.standard_normal((n, 2))
    det = StepDetector(FS)
    assert det.feed(0, x) == []
    det.gap()
    y = 20.0 * rng.standard_normal((n, 2)) + 3000.0  # a new DC level after the gap is no step
    t = np.arange(n) / FS
    y += (5e3 * knock(t - 0.02))[:, None]  # 20 ms after the gap
    found = det.feed(n + 50, y)
    assert len(found) == 1 and abs(found[0] - (n + 50 + int(0.02 * FS))) <= det.frame + 2


def test_detector_ignores_noise_with_mains_hum_and_finds_knocks() -> None:
    # k = 3 alone took 25 false steps a minute here; the energy check removes them (2026-11-26)
    rng = np.random.default_rng(13)
    n = int(FS * 60)
    t = np.arange(n) / FS
    x = 300 * rng.standard_normal((n, 2)) + 2000 * np.sin(2 * np.pi * 100 * t)[:, None]
    x += 800 * np.sin(2 * np.pi * 245 * t + 1)[:, None]
    det = StepDetector(FS)
    assert det.feed(0, x[: n // 2]) == []
    onsets = [n // 2 + int(FS * s) for s in (1.0, 1.6, 2.2, 2.8)]
    for o in onsets:
        x[:, 0] += 8000.0 * knock(t - o / FS)  # a step about as strong as the hum
        x[:, 1] += 7000.0 * knock(t - o / FS)
    found = det.feed(n // 2, x[n // 2 :])
    assert len(found) == len(onsets)


def test_health_agreement_rest_level_and_baseline(tmp_path) -> None:
    ring = SampleRing(2, int(FS * 60))
    loc = Locator(FakeManager(ring), tmp_path / "locate.json")
    assert loc.save_baseline() is None  # no signal yet
    _feed_steps(loc, ring, [5e4] * 6, 0.7)
    loc._health_at = 0.0
    loc.tick()
    h = loc.view()["health"]
    assert h["agree"] == 1.0 and h["agree_n"] == 6 and h["warnings"] == []
    assert h["rest"] is not None and h["quiet"] > 0
    assert loc.save_baseline()["health"]["baseline"]["quiet"] > 0
    assert Locator(FakeManager(ring), tmp_path / "locate.json").baseline == loc.baseline  # kept over a restart
    # the rest level of channel 0 moves by 1600 codes (2026-11-24 09:11)
    head = ring.head
    x = np.round(20.0 * np.random.default_rng(12).standard_normal((int(FS * 3), 2))).astype(np.int32)
    x[:, 0] += 1600
    ring.write(head, x)
    loc._health_at = 0.0
    loc.tick()
    assert any("rest level" in w for w in loc.view()["health"]["warnings"])


def test_health_warns_when_the_geophones_do_not_move_alike() -> None:
    loc = Locator(FakeManager(SampleRing(2, 100)), None)
    for k in range(10):
        loc.recent.append({"agree": k < 5})
    assert any("move alike" in w for w in loc.view()["health"]["warnings"])


def test_steps_carry_the_walk_side_and_a_pause_starts_a_new_walk() -> None:
    ring = SampleRing(2, int(FS * 60))
    mgr = FakeManager(ring)
    loc = Locator(mgr, None)
    n = int(FS * (WARM_S + 7))
    t = np.arange(n) / FS
    x = 20.0 * np.random.default_rng(6).standard_normal((n, 2))
    for o in (WARM_S, WARM_S + 0.7, WARM_S + 1.4, WARM_S + 5.0):
        x[:, 0] += 5e4 * knock(t - o)
        x[:, 1] += 5e4 * knock(t - o - 1e-3)  # channel 0 (right) hears it 1 ms first
    loc.tick()
    for i in range(0, n, 80):
        ring.write(i, np.round(x[i : i + 80]).astype(np.int32))
        loc.tick()
    steps = [e for e in mgr.events if e["type"] == "locate_step"]
    assert [s["side"] for s in steps] == ["right"] * 4
    assert [s["reason"] for s in steps] == ["first"] * 4
    assert [s["walk_side"] for s in steps] == ["same", "right", "right", "same"]
    assert [s["walk_steps"] for s in steps] == [1, 2, 3, 1]
    assert loc.view()["sides"] == {"left": 0, "right": 4, "same": 0}


def test_locator_publishes_steps_and_state(tmp_path) -> None:
    ring = SampleRing(2, int(FS * 30))
    mgr = FakeManager(ring)
    loc = Locator(mgr, tmp_path / "locate.json")
    _feed_steps(loc, ring, [5e4] * 4, 0.7)
    steps = [e for e in mgr.events if e["type"] == "locate_step"]
    assert len(steps) == 4 and loc.steps == 4
    assert {"side", "reason", "tau_s", "cc", "amp", "ratio", "agree"} <= set(steps[0])
    json.dumps(mgr.events)  # plain JSON, no numpy values
    assert loc.view()["recent"] and loc.clear()["recent"] == []


def test_locator_skips_and_counts_clipped_steps() -> None:
    ring = SampleRing(2, int(FS * 30))
    loc = Locator(FakeManager(ring), None)
    _feed_steps(loc, ring, [5e4, 5e7, 5e4], 1.0, full_scale=True)
    assert loc.skipped_clipped == 1 and loc.steps == 2
    assert loc.view()["skipped_clipped"] == 1


def test_locator_counts_steps_with_lost_samples() -> None:
    ring = SampleRing(2, int(FS * 30))
    loc = Locator(FakeManager(ring), None)
    sig = RoomAdcSignal(ScenarioConfig(seed=2, walk_s=1000.0, rest_s=1.0), acq_id=1)
    chunk = int(FS * 0.04)
    blocks = [sig.block(i, chunk, FS, (4, 4))[0] for i in range(0, int(FS * (WARM_S + 6)), chunk)]  # makes the steps
    first_step = int(next(st.t_s for st in sig._steps if st.t_s > WARM_S + 0.5) * FS)
    i = 0
    for codes in blocks:
        if i <= first_step + 100 < i + chunk:
            codes = codes[: first_step + 100 - i]  # lose the rest of this chunk, inside a step's window
        ring.write(i, codes)
        i += chunk
        loc.tick()
    assert loc.skipped_gaps >= 1


def test_swap_is_saved_and_an_old_calibration_file_is_ignored(tmp_path) -> None:
    p = tmp_path / "locate.json"
    p.write_text('{"version": 3, "swap_sides": true, "spots": {}}', encoding="utf-8")
    loc = Locator(FakeManager(SampleRing(2, 100)), p)
    assert loc.swap_sides is False
    assert loc.set_swap(True)["swap_sides"] is True
    assert Locator(FakeManager(SampleRing(2, 100)), p).swap_sides is True
    p.write_text("not json", encoding="utf-8")
    assert Locator(FakeManager(SampleRing(2, 100)), p).swap_sides is False


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
        assert v["type"] == "locate" and v["steps"] == 0 and v["swap_sides"] is False
        assert c.post("/api/locate/calibrate", json={"spot": "left"}).status_code in (404, 405)
        assert c.post("/api/locate/settings", json={}).status_code == 422
        assert c.post("/api/locate/baseline").status_code == 409
        r = c.post("/api/connect", json={"kind": "tcp", "host": "127.0.0.1", "port": sim.port, "start": True})
        assert r.status_code == 200, r.text
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and c.get("/api/locate").json()["steps"] < 5:
            time.sleep(0.2)
        v = c.get("/api/locate").json()
        assert v["steps"] >= 5, v
        step = v["recent"][-1]
        assert step["type"] == "locate_step" and step["side"] in ("left", "right", "same")
        assert c.post("/api/locate/settings", json={"swap_sides": True}).json()["swap_sides"] is True
        assert (tmp_path / "rzlab" / "locate.json").is_file()
        assert c.post("/api/locate/clear").json()["recent"] == []
        c.post("/api/disconnect")
