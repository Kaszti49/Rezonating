"""Simulated people (sim/people.py) and the simulated-dataset generator (sim/dataset.py)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from rezonating_lab.cli import main
from rezonating_lab.recorder.config import find_repo_root
from rezonating_lab.recorder.protocol import load_named
from rezonating_lab.recorder.validate import run_validate
from rezonating_lab.sim.dataset import DatasetConfig, generate_dataset
from rezonating_lab.sim.node import SimConfig, SimNode
from rezonating_lab.sim.people import POPULATION, WalkerAdcSignal, build_schedule, make_profile
from rezonating_lab.sim.scenarios import ScenarioConfig
from rezonating_ml import io

REPO = find_repo_root()
SCHEMA = REPO / "schemas" / "sidecar.schema.json"
PROTOCOL = load_named(REPO, "walk-pass-v1")
PACK = REPO / "packs" / "footstep-id" / "pack.json"


def _files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_profiles_and_schedule_are_deterministic_by_seed():
    a = make_profile("P2", seed=3)
    assert a == make_profile("P2", seed=3)
    assert a != make_profile("P2", seed=4)
    assert a != make_profile("P3", seed=3)
    same = make_profile("P2", seed=3, difficulty=1.0)
    assert same.f1_hz == pytest.approx(make_profile("P5", seed=3, difficulty=1.0).f1_hz)
    with pytest.raises(ValueError):
        make_profile("Kati", seed=1)
    plan = PROTOCOL.expand(["P1", "P2"])
    profiles = {p: make_profile(p, 3) for p in ("P1", "P2")}
    s1 = build_schedule(plan, profiles, seed=9, passes_scale=0.1)
    s2 = build_schedule(plan, profiles, seed=9, passes_scale=0.1)
    assert [(s.t_s, s.f1_hz, s.amp_v) for s in s1.steps] == [(s.t_s, s.f1_hz, s.amp_v) for s in s2.steps]
    assert s1.marks == s2.marks


def test_dataset_is_deterministic_by_seed(tmp_path):
    cfg = DatasetConfig(sessions=1, persons=["P1", "P2"], seed=5, passes_scale=0.05)
    generate_dataset(cfg, PROTOCOL, tmp_path / "a", SCHEMA)
    generate_dataset(cfg, PROTOCOL, tmp_path / "b", SCHEMA)
    a, b = _files(tmp_path / "a"), _files(tmp_path / "b")
    assert a == b and len(a) == 5  # 2 WAV + 2 sidecars + the ground truth
    cfg.seed = 6
    generate_dataset(cfg, PROTOCOL, tmp_path / "c", SCHEMA)
    c = _files(tmp_path / "c")
    wav = next(k for k in a if k.endswith(".adc.wav"))
    assert c.get(wav) != a[wav]


def _isolated_config(monkeypatch, tmp_path):
    """The CLI reads the lab config (data root, sidecar folder): keep the developer's own settings out of the test."""
    for key in ("RZ_DATA_ROOT", "RZ_SIDECAR_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RZ_CONFIG", str(tmp_path / "no-config.toml"))


def test_generated_sessions_validate_and_carry_labels(tmp_path, monkeypatch):
    _isolated_config(monkeypatch, tmp_path)
    out = tmp_path / "data"
    rc = main(
        [
            "sim-dataset",
            *("--out", str(out), "--sessions", "3", "--persons", "P1,P2", "--seed", "2", "--days", "2"),
            *("--floors", "lab", "office", "--passes-scale", "0.05", "--schema", str(SCHEMA)),
        ]
    )
    assert rc == 0
    lines: list[str] = []
    assert run_validate(out, SCHEMA, out=lines.append) == 0, lines
    folders = sorted(p for p in out.iterdir() if p.is_dir())
    assert len(folders) == 3
    assert len({f.name[:10] for f in folders}) == 2  # --days 2: two dates
    for folder in folders:
        name = folder.name
        for suffix in ("adc", "accel"):
            doc = io.load_sidecar(folder / f"{name}.{suffix}.json", SCHEMA)  # tools/validate.py's schema check
            assert io.check_pair(folder / f"{name}.{suffix}.wav", doc, SCHEMA) == []
            notes = io.parse_rzlab_notes(doc["notes"])
            assert notes["source"] == "sim" and notes["persons"] in ("P1,P2", "P2,P1")
            assert doc["sample_rate"] == round(doc["sample_rate_measured"]) and doc["sample_rate_measured"] != 2000
            walks = [lab for lab in doc["labels"] if lab["label"] == "walk"]
            assert {lab["src"] for lab in doc["labels"]} == {"auto"}
            assert doc["labels"][0]["label"] == "silence" and doc["labels"][0]["t1"] - doc["labels"][0]["t0"] > 59
            assert {(lab["person"], lab["pace"], lab["shoes"]) for lab in walks} >= {("P1", "normal", True)}
        truth = (out / f"{name}.truth.jsonl").read_text().splitlines()
        steps = [json.loads(t) for t in truth[1:]]
        assert all({"person", "pace", "shoes", "sample_adc_raw", "sample_accel"} <= set(s) for s in steps)
    assert main(["validate", str(out), "--schema", str(SCHEMA)]) == 0
    assert main(["sim-dataset", "--out", str(out), "--sessions", "1", "--persons", "Anna"]) == 2


@pytest.fixture(scope="module")
def footsteps_seed7(tmp_path_factory):
    """footstep_v1 rows of 6 simulated sessions (3 persons, 2 floors, seed 7, difficulty 0.5), labelled by pass."""
    from rezonating_ml.features import event_features
    from rezonating_ml.pipeline import run_pipeline

    cfg = DatasetConfig(
        sessions=6, persons=["P1", "P2", "P3"], seed=7, floors=["lab", "office"], passes_scale=0.2, difficulty=0.5
    )
    results = generate_dataset(cfg, PROTOCOL, tmp_path_factory.mktemp("sim7"), SCHEMA)
    pack = json.loads(PACK.read_text())
    X, y, groups = [], [], []
    for r in results:
        doc = io.load_sidecar(r.folder / f"{r.name}.adc.json")
        codes, _ = io.read_wav(r.folder / f"{r.name}.adc.wav")
        x = (codes[:, 0] * doc["channels"][0]["scale"]).astype(np.float32)
        out = run_pipeline(pack, x, input_fs_hz=2000.0)
        feats, kept = event_features(out.filtered, list(out.windows), 1000.0)
        walks = [lab for lab in doc["labels"] if lab.get("person")]
        for f, ev in zip(feats, kept, strict=True):
            lab = next((w for w in walks if w["i0"] <= 2 * ev.onset < w["i1"]), None)
            if lab is not None:
                X.append(f)
                y.append(lab["person"])
                groups.append(r.name)
    return np.array(X), y, groups, [r.name for r in results]


def test_persons_are_separable_but_not_trivially(footsteps_seed7):
    """footstep_v1 + baseline.evaluate, split by session. Synthetic data: this checks the simulator's difficulty,
    not the pack."""
    from rezonating_ml.baseline import evaluate

    X, y, groups, names = footsteps_seed7
    test = [names[2], names[5]]  # one session per floor
    res = evaluate(X, y, groups, split="session", test_groups=test, seed=0, model="logreg")
    assert res.n_test >= 100
    assert res.baseline.balanced_accuracy < 0.4
    assert 0.45 < res.scores.balanced_accuracy < 0.95, res.summary()


def test_window_split_scores_above_session_split(footsteps_seed7):
    """The leakage phase 7 must expose: windows of one walk on both sides of the split share that session's drift.
    Random forest (it can learn per-session clusters), averaged over 3 session folds (one session per floor each)
    and 3 random window splits of the same size. Synthetic data."""
    from rezonating_ml.baseline import evaluate

    X, y, groups, names = footsteps_seed7
    by_session = [
        evaluate(X, y, groups, split="session", test_groups=[names[i], names[i + 3]], seed=0, model="rf")
        for i in range(3)
    ]
    window_ids = [str(i) for i in range(len(y))]  # one group per window = a split by window
    by_window = [evaluate(X, y, window_ids, split="session", test_fraction=1 / 3, seed=s, model="rf") for s in range(3)]
    ses = float(np.mean([r.scores.balanced_accuracy for r in by_session]))
    win = float(np.mean([r.scores.balanced_accuracy for r in by_window]))
    assert win - ses >= 0.04, (ses, win)


def test_each_person_drifts_per_session(tmp_path):
    cfg = DatasetConfig(sessions=2, persons=["P1", "P2"], seed=3, passes_scale=0.05)
    results = generate_dataset(cfg, PROTOCOL, tmp_path, SCHEMA)
    heads = [json.loads((tmp_path / f"{r.name}.truth.jsonl").read_text().splitlines()[0]) for r in results]
    assert heads[0]["centres"] == heads[1]["centres"]  # the same walkers ...
    for p in ("P1", "P2"):
        walked = [h["profiles"][p] for h in heads]
        assert walked[0]["f1_hz"] != walked[1]["f1_hz"] and walked[0]["amp_v"] != walked[1]["amp_v"]  # ... drift
        ratio = walked[0]["f1_hz"] / heads[0]["centres"][p]["f1_hz"]
        assert 0.9 < ratio < 1.1 and ratio != 1.0
    # and the two persons do not drift alike
    f = [h["profiles"][p]["f1_hz"] / h["centres"][p]["f1_hz"] for h in heads for p in ("P1", "P2")]
    assert len(set(f)) == 4


def test_person_centres_are_independent_across_persons_and_parameters():
    profs = [make_profile(f"P{k}", seed=11, difficulty=0.0) for k in range(1, 201)]
    names = list(POPULATION)
    M = np.array([[getattr(p, n) for n in names] for p in profs])
    k = np.arange(1, 201)
    for j, n in enumerate(names):
        centre, spread, _ = POPULATION[n]
        u = (M[:, j] / centre - 1.0) / spread  # -1 .. 1
        assert u.min() < -0.8 and u.max() > 0.8, n  # every parameter uses its whole range (not 1.018 * k)
        assert abs(np.corrcoef(k, M[:, j])[0, 1]) < 0.3, n  # not monotonic in the person number
    c = np.corrcoef(M.T)
    assert np.abs(c[~np.eye(len(names), dtype=bool)]).max() < 0.3


def test_sim_dataset_refuses_out_in_repo_or_data_root(tmp_path, monkeypatch):
    _isolated_config(monkeypatch, tmp_path)
    in_repo = REPO / "scratch" / "sim-dataset-refusal-test"
    args = ["--sessions", "1", "--persons", "P1", "--passes-scale", "0.05", "--schema", str(SCHEMA)]
    assert main(["sim-dataset", "--out", str(in_repo), *args]) == 2
    assert not in_repo.exists()
    assert main(["sim-dataset", "--out", str(REPO / "data" / "sim"), *args]) == 2
    assert not (REPO / "data" / "sim").exists()
    with pytest.raises(ValueError, match="inside the repository"):
        generate_dataset(DatasetConfig(sessions=1, persons=["P1"]), PROTOCOL, in_repo, SCHEMA)

    root = tmp_path / "recordings"
    root.mkdir()
    monkeypatch.setenv("RZ_DATA_ROOT", str(root))
    assert main(["sim-dataset", "--out", str(root / "sim"), *args]) == 2
    assert not (root / "sim").exists()
    assert main(["sim-dataset", "--out", str(root / "sim"), "--into-data-root", *args]) == 0
    assert (root / "sim").is_dir()


def test_walkers_walk_the_whole_protocol():
    persons = ["P1", "P2", "P3"]
    make = WalkerAdcSignal.factory(persons, PROTOCOL.expand(persons), seed=1, start_s=10.0)
    sched = make.schedule
    per_person = Counter(m.person for m in sched.passes())
    assert per_person == {p: 90 for p in persons} == {p: PROTOCOL.passes_per_person for p in persons}
    per_step = Counter(m.plan_key for m in sched.passes())
    assert per_step["P2/normal-shoes-on"] == 50 and per_step["P2/normal-shoes-off"] == 20
    assert per_step["P3/slow-shoes-on"] == 10 and per_step["P3/fast-shoes-on"] == 10
    silence = sched.marks[0]
    assert silence.label == "silence" and silence.t1_s - silence.t0_s == 60.0
    assert not [s for s in sched.steps if s.t_s < silence.t1_s]  # nobody walks during the silence
    for a, b in zip(sched.passes(), sched.passes()[1:], strict=False):
        assert b.t0_s - a.t1_s >= 3.0  # the 3 s pause


def test_walker_signal_is_block_split_independent_and_logs_people():
    persons = ["P1"]
    make = WalkerAdcSignal.factory(persons, PROTOCOL.expand(persons), seed=4, start_s=-63.0)  # first step at 1.4 s
    cfg = ScenarioConfig(seed=4)
    rate = 2016.0

    def render(sizes):
        sig, out, steps, first = make(cfg, 1), [], [], 0
        for n in sizes:
            codes, new = sig.block(first, n, rate, (8, 8))
            out.append(codes)
            steps += new
            first += n
        return np.vstack(out), steps

    a, steps_a = render([8064] * 3)
    b, steps_b = render([96] * 252)
    assert np.abs(a.astype(np.int64) - b).max() <= 1
    assert [s.t_s for s in steps_a] == [s.t_s for s in steps_b] and len(steps_a) >= 8
    assert np.abs(a[: int(0.9 * rate)]).max() < 0.2 * np.abs(a).max()  # walking starts after the silence

    # the live node logs person, pace and shoes with every footstep
    now = [0.0]
    node = SimNode(SimConfig(seed=4, speed=1.0, adc_signal=make), clock=lambda: now[0])
    node.start_streams(0b111)
    now[0] = 6.0
    node.advance()
    foot = [e for e in node.truth.events if e["kind"] == "footstep"]
    assert foot and all(e["person"] == "P1" and e["pace"] == "normal" and e["shoes"] is True for e in foot)
    assert all("sample_accel" in e for e in foot)
    node.close()


def test_out_dir_guard_resolves_relative_paths_and_links(tmp_path, monkeypatch):
    from rezonating_lab.recorder.config import find_repo_root
    from rezonating_lab.sim.dataset import check_out_dir

    repo = find_repo_root()
    monkeypatch.chdir(repo / "tools" / "lab")
    with pytest.raises(ValueError):
        check_out_dir(Path("simout"), repo_root=repo)  # relative, resolves inside the repo
    link = tmp_path / "lntools"
    link.symlink_to(repo / "tools", target_is_directory=True)
    with pytest.raises(ValueError):
        check_out_dir(link / "x", repo_root=repo)  # a link into the repo
    check_out_dir(repo / "tools" / ".." / ".." / "outside-rz", repo_root=repo)  # resolves outside: allowed

