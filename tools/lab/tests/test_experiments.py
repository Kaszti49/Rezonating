"""Experiments page (Lab phase 7): labels to windows, split refusals, baseline, determinism, runs, EXP drafts.

The end-to-end tests run on a small ``rzlab sim-dataset`` (synthetic: three simulated persons, four sessions) built
once per module in a temp folder. Nothing here writes into the real vault, the repository's runs folder or cache.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from rec_helpers import PORT, REPO, make_cfg
from rezonating_lab.recorder.protocol import load_named
from rezonating_lab.server import experiments as ex
from rezonating_lab.server.app import create_app
from rezonating_lab.server.device import DeviceManager
from rezonating_lab.sim.dataset import DatasetConfig, generate_dataset
from rezonating_ml import baseline as rzb
from rezonating_ml import pipeline as rzp

SCHEMA = REPO / "schemas" / "sidecar.schema.json"
PACKS = REPO / "packs"


@pytest.fixture(scope="module")
def simroot(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("sim") / "dataroot"
    cfg = DatasetConfig(sessions=4, persons=["P1", "P2", "P3"], seed=7, passes_scale=0.25)
    generate_dataset(cfg, load_named(REPO, "walk-pass-v1"), out, SCHEMA)
    return out


def sources(root: Path) -> list[ex.SessionSource]:
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        sc = json.loads((d / f"{d.name}.adc.json").read_text(encoding="utf-8"))
        out.append(
            ex.SessionSource(
                session=d.name,
                wav=d / f"{d.name}.adc.wav",
                sidecar=d / f"{d.name}.adc.json",
                simulated="source=sim" in sc["notes"],
                people=sorted({lab["person"] for lab in sc["labels"] if "person" in lab}),
                protocol=sc["protocol"],
                floor="lab",
            )
        )
    return out


@pytest.fixture(scope="module")
def pack():
    return ex.load_pack(PACKS, "footstep-id")


def run(simroot, pack, cache, **kw):
    srcs = sources(simroot)
    cfg = ex.ExperimentConfig(pack="footstep-id", sessions=[s.session for s in srcs], **kw)
    return ex.run_experiment(cfg, srcs, pack[0], pack[1], cache)


# ------------------------------------------------------------------------------------------------ labels


def test_label_to_window_assignment_drops_and_counts():
    labels = [
        {"i0": 0, "i1": 1000, "label": "silence"},
        {"i0": 1000, "i1": 2000, "label": "walk", "person": "P1", "pace": "slow", "shoes": True},
        {"i0": 3000, "i1": 4000, "label": "walk", "person": "P2", "shoes": False},  # no pace
    ]
    onsets = np.array([10, 999, 1000, 1999, 2000, 2500, 3500, 5000])
    got, dropped = ex.assign_labels(onsets, labels, "pace")
    assert [g["y"] if g else None for g in got] == [None, None, "slow", "slow", None, None, None, None]
    assert dropped == Counter({"silence": 2, "outside_labels": 3, "no_target": 1})
    got, dropped = ex.assign_labels(onsets, labels, "person")
    assert [g["y"] if g else None for g in got] == [None, None, "P1", "P1", None, None, "P2", None]
    assert got[6] == {"y": "P2", "person": "P2", "pace": "-", "shoes": "no_shoes"}
    assert sum(dropped.values()) + sum(g is not None for g in got) == onsets.size  # every window accounted for


def test_shoes_and_non_pseudonym_people():
    assert ex.target_value({"shoes": True}, "shoes") == "shoes"
    assert ex.target_value({"shoes": False}, "shoes") == "no_shoes"
    assert ex.target_value({"person": "Alice"}, "person") is None  # only pseudonyms ever become labels


def test_onsets_map_back_with_the_2k_minus_30_convention(pack):
    pipe = rzp.build_pipeline(pack[0], input_fs_hz=2000.0)
    assert int(pipe.to_input_index(100)) == 170


def test_windows_outside_labels_are_dropped_and_counted(simroot, pack, tmp_path):
    src = sources(simroot)[:1]
    ws = ex.build_windows(src, pack[0], pack[1], "person", tmp_path / "cache")
    s = ws.per_session[0]
    assert s["windows"] == s["kept"] + sum(s["dropped"].values())
    assert s["kept"] == ws.y.size > 0
    assert set(ws.y.tolist()) <= {"P1", "P2", "P3"}
    # drop every other walk label from a copy: exactly the windows of those passes go to "outside_labels"
    src0 = src[0]
    sc = json.loads(src0.sidecar.read_text(encoding="utf-8"))
    walks = [lab for lab in sc["labels"] if lab["label"] == "walk"]
    gone = walks[1::2]
    sc["labels"] = [lab for lab in sc["labels"] if lab not in gone]
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / src0.sidecar.name).write_text(json.dumps(sc), encoding="utf-8")
    (copy / src0.wav.name).write_bytes(src0.wav.read_bytes())
    cut = ex.SessionSource(**{**src0.__dict__, "wav": copy / src0.wav.name, "sidecar": copy / src0.sidecar.name})
    ws2 = ex.build_windows([cut], pack[0], pack[1], "person", tmp_path / "cache2")
    feats, _, _ = ex.session_features(src0, pack[0], pack[1], None)
    in_gone = sum(any(g["i0"] <= t < g["i1"] for g in gone) for t in feats.onset_in.tolist())
    assert in_gone > 0
    assert ws2.dropped["outside_labels"] == ws.dropped["outside_labels"] + in_gone
    assert ws2.y.size == ws.y.size - in_gone
    # the cache is used the second time and gives the same windows
    again = ex.build_windows(src, pack[0], pack[1], "person", tmp_path / "cache")
    assert again.per_session[0]["cached"] and np.array_equal(again.X, ws.X) and list(again.y) == list(ws.y)


# ------------------------------------------------------------------------------------------------ refusals


def test_person_split_for_person_id_is_refused_with_a_clear_message():
    cfg = ex.ExperimentConfig(pack="footstep-id", sessions=["a", "b"], split="person", target="person")
    with pytest.raises(ex.ExperimentError) as err:
        cfg.check()
    assert err.value.code == "person_split_for_person"
    assert "Split by session" in err.value.message and "never saw in training" in err.value.message


def _ws(session, person, y):
    n = len(y)
    return ex.WindowSet(
        X=np.zeros((n, 13), np.float32),
        y=np.array(y),
        session=np.array(session),
        person=np.array(person),
        pace=np.array(["-"] * n),
        shoes=np.array(["-"] * n),
    )


def test_person_split_sharing_a_session_is_refused():
    ws = _ws(["s1", "s1", "s2", "s2"], ["P1", "P2", "P1", "P2"], ["slow", "fast", "slow", "fast"])
    cfg = ex.ExperimentConfig(
        pack="footstep-id", sessions=["s1", "s2"], split="person", target="pace", test_groups=["P2"]
    )
    with pytest.raises(ex.ExperimentError) as err:
        ex.check_split(ws, cfg)
    assert err.value.code == "overlap" and "s1" in err.value.message


def test_session_and_person_overlap_refused_even_if_the_splitter_leaked(monkeypatch):
    def leaky(groups, **kw):
        n = len(groups)
        return np.arange(n), np.arange(n // 2, n)

    monkeypatch.setattr(rzb, "split_by_group", leaky)
    ws = _ws(["s1", "s1", "s2", "s2"], ["P1", "P1", "P2", "P2"], ["P1", "P1", "P2", "P2"])
    for split, target in (("session", "person"), ("person", "pace")):
        cfg = ex.ExperimentConfig(pack="footstep-id", sessions=["s1", "s2"], split=split, target=target)
        with pytest.raises(ex.ExperimentError) as err:
            ex.check_split(ws, cfg)
        assert err.value.code == "overlap"


def test_person_split_on_shared_sim_sessions_is_refused(simroot, pack, tmp_path):
    with pytest.raises(ex.ExperimentError) as err:
        run(simroot, pack, tmp_path, split="person", target="pace", test_groups=["P3"])
    assert err.value.code == "overlap"


def test_invalid_session_is_refused():
    row = {"session": "s1", "valid": False, "errors": ["v1: wav: missing"], "streams": []}
    with pytest.raises(ex.ExperimentError) as err:
        ex.resolve_sessions([row], ["s1"], Path("/nowhere"), None)
    assert err.value.code == "invalid_session"


# ------------------------------------------------------------------------------------------------ results


@pytest.fixture(scope="module")
def sim_result(simroot, pack, tmp_path_factory):
    names = sorted(p.name for p in simroot.iterdir() if p.is_dir())
    cache = tmp_path_factory.mktemp("cache")
    return run(simroot, pack, cache, split="session", target="person", seed=3, test_groups=names[2:])


def test_sim_model_beats_baseline_and_is_marked_simulated(sim_result):
    r = sim_result
    ev = r["result"]
    assert r["simulated"] is True and r["flags"][0].startswith(ex.SIMULATED_MARK)
    assert ev["baseline"]["balanced_accuracy"] <= 0.34  # majority class of three persons
    assert r["beats_baseline"] and ev["scores"]["balanced_accuracy"] > ev["baseline"]["balanced_accuracy"]
    assert not set(r["split"]["train_sessions"]) & set(r["split"]["test_sessions"])
    assert set(r["per_person"]) == {"P1", "P2", "P3"}
    print("\nSYNTHETIC sim-dataset result:", r["summary"])


def test_baseline_is_always_present(sim_result):
    ev = sim_result["result"]
    assert set(ev["baseline"]) >= {"accuracy", "balanced_accuracy", "confusion", "per_class", "per_group"}
    assert "majority baseline" in sim_result["summary"]


def test_deterministic_by_seed(simroot, pack, tmp_path):
    a = run(simroot, pack, tmp_path / "c1", seed=5, fraction=0.5, model="rf")
    b = run(simroot, pack, tmp_path / "c2", seed=5, fraction=0.5, model="rf")
    for r in (a, b):
        for k in ("created", "elapsed_s"):
            r.pop(k)
        for s in r["sessions"]:
            s.pop("cached")
    assert a == b


def test_run_folder_written_under_a_temp_runs_root(sim_result, tmp_path):
    runs = tmp_path / "runs"
    run_id = ex.save_run(runs, sim_result)
    folder = runs / run_id
    assert ex.RUN_ID_RE.match(run_id) and run_id.endswith("_footstep-id_session")
    assert {p.name for p in folder.iterdir()} == {"config.json", "results.json", "confusion.svg"}
    assert ex.load_run(runs, run_id)["result"] == sim_result["result"]
    assert "SIMULATED DATA" in (folder / "confusion.svg").read_text(encoding="utf-8")
    assert ex.list_runs(runs)[0]["run_id"] == run_id
    assert ex.save_run(runs, sim_result) != run_id  # never overwrites
    with pytest.raises(ex.ExperimentError):
        ex.load_run(runs, "../../etc")


# ------------------------------------------------------------------------------------------------ EXP draft


def make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "00 Inbox").mkdir(parents=True)
    (vault / "50 Experiments").mkdir()
    (vault / "40 Packs").mkdir()
    (vault / "40 Packs" / "footstep-id.md").write_text("---\ntype: pack\nstage: idea\n---\n", encoding="utf-8")
    (vault / "50 Experiments" / "EXP-004 Older.md").write_text("---\ntype: experiment\n---\n", encoding="utf-8")
    (vault / "00 Inbox" / "EXP-001 Phone.md").write_text("---\ntype: inbox\n---\n", encoding="utf-8")
    return vault


def test_exp_draft_passes_vault_schema_in_a_temp_vault(sim_result, tmp_path):
    real = {f: sorted(p.name for p in (REPO / f).iterdir()) for f in ("00 Inbox", "50 Experiments")}
    vault = make_vault(tmp_path)
    runs = REPO / "tools" / "lab" / "runs"  # only used to make the path relative; nothing is written there
    out = ex.draft_exp_note(sim_result, runs / "2026-10-13_120000_footstep-id_session", vault, REPO, "Sim person ID")
    assert out["ok"], out["check"]
    assert out["id"] == "EXP-005" and out["path"] == "50 Experiments/EXP-005 Sim person ID.md"
    text = (vault / out["path"]).read_text(encoding="utf-8")
    assert text.startswith("---\ntype: experiment\nid: EXP-005\nstatus: running\n")
    assert "SIMULATED DATA" in text and "| Majority baseline |" in text
    assert "tools/lab/runs/2026-10-13_120000_footstep-id_session" in text
    assert out["check"]["cli_rc"] == 0 and "1 notes checked: 0 errors" in out["check"]["cli"]
    assert {f: sorted(p.name for p in (REPO / f).iterdir()) for f in real} == real  # the real vault is untouched
    assert sorted(p.name for p in (vault / "00 Inbox").iterdir()) == ["EXP-001 Phone.md"]
    assert ex.next_exp_id(vault) == "EXP-006"


def test_a_failing_exp_draft_is_deleted(sim_result, tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    monkeypatch.setattr(ex, "exp_note_text", lambda *a: "---\ntype: experiment\nid: EXP-005\nstatus: bogus\n---\n")
    out = ex.draft_exp_note(sim_result, tmp_path / "r", vault, REPO, "Bad")
    assert not out["ok"] and out["path"] is None and out["check"]["errors"]
    assert not (vault / "50 Experiments" / "EXP-005 Bad.md").exists()
    assert out["deleted"] == "50 Experiments/EXP-005 Bad.md" and "status" in " ".join(out["check"]["errors"])


# ------------------------------------------------------------------------------------------------ REST


def test_api_run_list_detail_and_draft(simroot, tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    monkeypatch.setenv("RZ_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("RZ_FEATURE_CACHE", str(tmp_path / "feat"))
    monkeypatch.setenv("RZ_VAULT_ROOT", str(vault))
    cfg = make_cfg(tmp_path, data_root=simroot, sidecar_dir=tmp_path / "repo-data", index_db=tmp_path / "ix.sqlite")
    (tmp_path / "repo-data").mkdir()
    app = create_app(PORT, manager=DeviceManager(embedded_sim=False), static_dir=tmp_path / "nostatic", lab_config=cfg)
    names = sorted(p.name for p in simroot.iterdir() if p.is_dir())
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        opts = c.get("/api/experiments/options").json()
        assert "footstep-id" in [p["id"] for p in opts["packs"]]
        bad = c.post("/api/experiments/run", json={"sessions": names, "split": "person", "target": "person"})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "person_split_for_person"
        job = c.post("/api/experiments/run", json={"sessions": names, "test_groups": names[2:], "seed": 1}).json()
        for _ in range(300):
            st = c.get(f"/api/experiments/jobs/{job['job']}").json()
            if st["state"] != "running":
                break
            time.sleep(0.1)
        assert st["state"] == "done", st
        run_id = st["run_id"]
        assert st["result"]["simulated"] and st["result"]["result"]["baseline"]
        assert c.get("/api/experiments/runs").json()["runs"][0]["run_id"] == run_id
        assert c.get(f"/api/experiments/runs/{run_id}/confusion.svg").text.startswith("<svg")
        d = c.post(f"/api/experiments/runs/{run_id}/draft", json={"title": "API sim"}).json()
        assert d["ok"] and d["path"] == "50 Experiments/EXP-005 API sim.md", d
        assert c.get(f"/api/experiments/runs/{run_id}").json()["draft"]["id"] == "EXP-005"
    assert (tmp_path / "runs" / run_id / "results.json").is_file()
