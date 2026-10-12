import json

import numpy as np
from rezonating_lab.sim.faults import FaultConfig, FaultInjector
from rezonating_lab.sim.scenarios import (
    ACCEL_LSB_PER_G,
    AccelSignal,
    AdcSignal,
    GroundTruthLog,
    ScenarioConfig,
)

RATE = 2016.0


def render(cfg, acq_id, block_sizes, gains=(8, 8)):
    sig = AdcSignal(cfg, acq_id)
    out, steps, first = [], [], 0
    for n in block_sizes:
        codes, new = sig.block(first, n, RATE, gains)
        out.append(codes)
        steps += new
        first += n
    return np.vstack(out), steps


def test_seeded_and_independent_of_the_block_split():
    cfg = ScenarioConfig(seed=5)
    a, steps_a = render(cfg, 1, [8000] * 3)
    b, steps_b = render(cfg, 1, [80] * 300)
    assert np.abs(a.astype(np.int64) - b).max() <= 1  # float summation order may move a code by one
    assert [s.t_s for s in steps_a] == [s.t_s for s in steps_b]
    c, _ = render(ScenarioConfig(seed=6), 1, [8000] * 3)
    assert not np.array_equal(a, c)
    d, _ = render(cfg, 2, [8000] * 3)  # a new acquisition draws new noise
    assert not np.array_equal(a, d)


def test_footsteps_are_visible_over_the_noise_floor_at_walking_cadence():
    cfg = ScenarioConfig(seed=1)
    codes, steps = render(cfg, 1, [4032] * 5)  # 10 s
    assert 12 <= len(steps) <= 22  # about 1.8 steps/s for 10 s, first at 0.5 s
    gaps = np.diff([s.t_s for s in steps])
    assert 0.4 < gaps.mean() < 0.7
    noise = np.median(np.abs(codes[:, 0] - np.median(codes[:, 0]))) * 1.4826
    assert np.abs(codes[:, 0]).max() > 20 * noise
    # each reported step is followed by a burst on channel 0
    for s in steps[:5]:
        i = int(s.t_s * RATE)
        assert np.abs(codes[i : i + 100, 0]).max() > 10 * noise


def test_rest_between_walking_bouts_has_no_steps():
    cfg = ScenarioConfig(seed=1, walk_s=5.0, rest_s=5.0)
    _, steps = render(cfg, 1, [4032] * 5)
    assert all((s.t_s % 10.0) < 5.0 for s in steps)


def test_steps_are_reported_once_each():
    _, steps = render(ScenarioConfig(), 1, [100] * 100)
    assert len({s.n for s in steps}) == len(steps)


def test_gain_scales_the_codes():
    a, _ = render(ScenarioConfig(), 1, [4032], gains=(1, 1))
    b, _ = render(ScenarioConfig(), 1, [4032], gains=(8, 8))
    assert np.abs(b).max() > 6 * np.abs(a).max()


def test_accel_is_about_one_g_on_z_with_hum():
    cfg = ScenarioConfig()
    sig = AccelSignal(cfg, 1)
    codes = sig.block(0, 4000, 2000.0, 2)
    z = codes[:, 2] / ACCEL_LSB_PER_G[2]
    assert abs(z.mean() - 1.0) < 0.01
    spectrum = np.abs(np.fft.rfft(z - z.mean()))
    assert abs(np.fft.rfftfreq(4000, 1 / 2000.0)[spectrum.argmax()] - cfg.hum_hz) < 1.0
    assert codes.dtype == np.int32 and np.abs(codes).max() < 2**19
    # range 8 g: fewer codes per g
    assert abs(sig.block(0, 100, 2000.0, 8)[:, 2].mean() / ACCEL_LSB_PER_G[8] - 1.0) < 0.05


def test_ground_truth_log_writes_jsonl(tmp_path):
    path = tmp_path / "truth.jsonl"
    log = GroundTruthLog(path)
    log.add({"a": 1})
    log.add({"a": 2})
    log.close()
    assert [json.loads(line) for line in path.read_text().splitlines()] == [{"a": 1}, {"a": 2}]
    assert log.events == [{"a": 1}, {"a": 2}]


def test_fault_injector_is_seeded_and_corrupt_never_makes_zero_bytes():
    cfg = FaultConfig(device_drop_rate=0.1, link_drop_rate=0.3, corrupt_rate=1.0)
    a, b = FaultInjector(cfg, 4), FaultInjector(cfg, 4)
    assert np.array_equal(a.device_dropped(1000), b.device_dropped(1000))
    assert [a.link_dropped() for _ in range(50)] == [b.link_dropped() for _ in range(50)]
    wire = bytes(range(1, 200)) + b"\x00"
    for _ in range(200):
        bad = a.corrupt(wire)
        assert bad is not None and bad != wire and bad[-1] == 0 and 0 not in bad[:-1]
        assert sum(x != y for x, y in zip(bad, wire, strict=False)) == 1
    rate = a.device_dropped(100_000).mean()
    assert 0.09 < rate < 0.11
    assert FaultInjector(FaultConfig(), 1).corrupt(wire) is None
