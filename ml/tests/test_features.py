"""footstep_v1: known answers on synthetic signals, and the shared test vectors (D-021)."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from rezonating_ml import features as F
from rezonating_ml.trigger import Event

FS_HZ = 1000.0
N = 500
VEC_DIR = Path(__file__).parent / "vectors"


def _feat(x: np.ndarray) -> dict[str, float]:
    return dict(zip(F.FEATURE_NAMES, F.footstep_v1(x.astype(np.float32), FS_HZ).tolist(), strict=True))


def test_names_and_shape() -> None:
    assert F.N_FEATURES == len(F.FEATURE_NAMES) == 13
    assert len(set(F.FEATURE_NAMES)) == F.N_FEATURES
    out = F.footstep_v1(np.ones(N, dtype=np.float32), FS_HZ)
    assert out.shape == (F.N_FEATURES,) and out.dtype == np.float32


def test_band_bins_at_1khz() -> None:
    assert F.band_bins(FS_HZ) == [(3, 11), (11, 21), (21, 41), (41, 77), (77, 128), (128, 205)]


def test_impulse() -> None:
    x = np.zeros(N)
    x[200] = 4.0
    f = _feat(x)
    assert f["log_peak"] == pytest.approx(math.log(4.0), rel=1e-6)
    assert f["log_energy"] == pytest.approx(math.log(16.0 / N), rel=1e-6)
    assert f["crest"] == pytest.approx(math.sqrt(N), rel=1e-6)
    assert f["t_peak_s"] == pytest.approx(0.2)
    assert f["active_s"] == pytest.approx(0.001)
    assert f["zcr_hz"] == 0.0  # zeros count as non-negative: no sign change anywhere
    # A flat spectrum: each band's share is its bin count over all band bins; centroid in the middle of 3..204.
    counts = np.array([hi - lo for lo, hi in F.band_bins(FS_HZ)])
    fracs = [f[n] for n in F.FEATURE_NAMES if n.startswith("band_")]
    np.testing.assert_allclose(fracs, counts / counts.sum(), rtol=1e-5)
    assert f["centroid_hz"] == pytest.approx((3 + 204) / 2 * FS_HZ / F.N_FFT, rel=1e-5)


def test_first_peak_wins_ties() -> None:
    x = np.zeros(N)
    x[[50, 300]] = [-3.0, 3.0]
    assert _feat(x)["t_peak_s"] == pytest.approx(0.05)


@pytest.mark.parametrize(("f_hz", "band"), [(12.0, 0), (31.0, 1), (60.0, 2), (110.0, 3), (200.0, 4), (320.0, 5)])
def test_sine_lands_in_its_band(f_hz: float, band: int) -> None:
    t_s = np.arange(N) / FS_HZ
    f = _feat(np.sin(2 * np.pi * f_hz * t_s + 0.3))
    fracs = np.array([f[n] for n in F.FEATURE_NAMES if n.startswith("band_")])
    assert int(np.argmax(fracs)) == band
    assert fracs.sum() == pytest.approx(1.0, abs=1e-5)
    assert f["centroid_hz"] == pytest.approx(f_hz, abs=0.08 * f_hz + 2.0)
    assert f["zcr_hz"] == pytest.approx(2 * f_hz, abs=2 * FS_HZ / N)
    assert f["crest"] == pytest.approx(math.sqrt(2), rel=0.02)
    assert f["active_s"] == pytest.approx(N / FS_HZ, abs=0.02)


def test_decaying_burst_duration() -> None:
    t_s = np.arange(N) / FS_HZ
    x = np.where(t_s >= 0.1, np.exp(-(t_s - 0.1) / 0.025) * np.sin(2 * np.pi * 35 * (t_s - 0.1) + 1.0), 0.0)
    f = _feat(x)
    assert 0.03 < f["active_s"] < 0.07  # envelope above 10 % of peak for about 25 ms * ln 10 = 58 ms
    assert 0.1 <= f["t_peak_s"] < 0.13
    assert f["band_20_40_frac"] > 0.5


def test_zero_window_is_defined() -> None:
    f = _feat(np.zeros(N))
    assert f["log_energy"] == pytest.approx(math.log(F.EPS))
    assert all(f[n] == 0.0 for n in F.FEATURE_NAMES if n not in ("log_energy", "log_peak"))


def test_deterministic_and_scale_behaviour() -> None:
    x = np.random.default_rng(7).normal(0, 1, N).astype(np.float32)
    a, b = F.footstep_v1(x, FS_HZ), F.footstep_v1(x.copy(), FS_HZ)
    assert np.array_equal(a, b)
    c = F.footstep_v1(2 * x, FS_HZ)  # gain 2 shifts log_energy by ln 4 and log_peak by ln 2, nothing else
    np.testing.assert_allclose(c[:2] - a[:2], [math.log(4.0), math.log(2.0)], atol=1e-5)
    np.testing.assert_allclose(c[2:], a[2:], rtol=1e-5, atol=1e-6)


@pytest.mark.parametrize("bad", [np.zeros(1), np.zeros(F.N_FFT + 1), np.zeros((2, 10)), np.array([0.0, np.nan])])
def test_rejects_bad_windows(bad: np.ndarray) -> None:
    with pytest.raises(ValueError):
        F.footstep_v1(bad.astype(np.float32), FS_HZ)


def test_event_features_skips_cut_windows() -> None:
    x = np.random.default_rng(1).normal(0, 1, 2000).astype(np.float32)
    evs = [Event(50, -50, 450), Event(600, 500, 1000), Event(1800, 1700, 2200)]
    feats, kept = F.event_features(x, evs, FS_HZ)
    assert kept == [evs[1]] and feats.shape == (1, F.N_FEATURES)
    assert np.array_equal(feats[0], F.footstep_v1(x[500:1000], FS_HZ))


def test_vectors_match_current_code() -> None:
    assert F.check_feature_vectors(VEC_DIR) == []


def _close(got: list, exp: list, rel: float) -> bool:
    g, e = np.asarray(got, dtype=np.float64), np.asarray(exp, dtype=np.float64)
    return g.shape == e.shape and bool(np.all(np.abs(g - e) <= rel * np.maximum(np.abs(e), 1.0)))


def test_vectors_are_up_to_date(tmp_path: Path) -> None:
    """The committed file is what --write produces now, compared as parsed values (not bytes).

    Metadata, case names and event indices must match exactly; inputs and expected outputs within the vector
    tolerance, so another numpy/scipy build that moves a clip sample by an ulp does not fail the suite while
    ``--check`` passes.
    """
    F.write_feature_vectors(tmp_path)
    new = json.loads((tmp_path / F.VECTOR_FILE).read_text())
    old = json.loads((VEC_DIR / F.VECTOR_FILE).read_text())
    assert set(new) == set(old)
    for key in set(new) - {"input", "expected"}:
        assert new[key] == old[key], key
    rel = old["tolerance"]["rel"]
    for name, a, b in zip(old["case_names"], new["input"], old["input"], strict=True):
        assert _close(a, b, rel), f"input of {name}"
    for name, a, b in zip(old["case_names"], new["expected"], old["expected"], strict=True):
        assert _close(a, b, rel), f"expected of {name}"


def _case(name_start: str) -> tuple[np.ndarray, dict[str, float]]:
    v = json.loads((VEC_DIR / F.VECTOR_FILE).read_text())
    i = next(k for k, n in enumerate(v["case_names"]) if n.startswith(name_start))
    return np.asarray(v["input"][i], dtype=np.float32), dict(zip(F.FEATURE_NAMES, v["expected"][i], strict=True))


def test_vector_edge_cases_have_their_known_answers() -> None:
    """The hand-made cases in the vector file hold what their names claim (and survive the JSON round trip)."""
    x, f = _case("short window")
    assert x.size == 37 and f["zcr_hz"] == pytest.approx(np.count_nonzero(np.diff(x >= 0)) * FS_HZ / 37)

    x, f = _case("signed zeros")
    assert np.count_nonzero(np.signbit(x) & (x == 0)) == 18  # -0.0 kept in the file
    assert f["zcr_hz"] == pytest.approx(35 * FS_HZ / 60)  # signbit() as the sign test would count more
    assert np.count_nonzero(np.diff(np.signbit(x))) != 35

    x, f = _case("sample exactly at")
    thr = np.float32(np.float32(0.1) * np.abs(x).max())
    assert np.flatnonzero(np.abs(x) == thr).tolist() == [10, 300]
    assert f["active_s"] == pytest.approx(291 / FS_HZ)  # 10..300; the sample just below thr at 450 is out

    x, f = _case("peak tie across sign")
    assert x[50] == -x[300] == -3.0 and f["t_peak_s"] == pytest.approx(0.05)


def test_feature_module_does_not_import_the_generator() -> None:
    code = "import sys, rezonating_ml.features; sys.exit('rezonating_ml.vectors' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_vectors_detect_a_change(tmp_path: Path) -> None:
    v = json.loads((VEC_DIR / F.VECTOR_FILE).read_text())
    v["expected"][0][F.FEATURE_NAMES.index("centroid_hz")] += 1.0
    (tmp_path / F.VECTOR_FILE).write_text(json.dumps(v))
    problems = F.check_feature_vectors(tmp_path)
    assert len(problems) == 1 and "centroid_hz" in problems[0]
