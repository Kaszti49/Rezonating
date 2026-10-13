"""Datasets page: the session index, its SQLite cache, the filters and the manifest builder (WEB_API.md 13)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rec_helpers import PORT, REPO, form, make_cfg
from review_helpers import SCHEMA, sidecar, write_session
from rezonating_lab.datasets import DatasetError, DatasetIndex, Filters, totals
from rezonating_lab.server.app import create_app
from rezonating_lab.server.device import DeviceManager
from rezonating_ml import io
from rezonating_ml import manifest as mf

VALID = "2026-10-12_home-a_kitchen_01"
INVALID = "2026-10-13_home-a_hall_01"  # the repo sidecar says 1000 Hz, the WAV header 2000 Hz
NO_WAV = "2026-10-14_lab_bench_01"  # sidecar in the repo, nothing on the data root
SIM = "2026-10-15_lab_bench_02"  # rzlab: source=sim
ORPHAN = "2026-10-16_lab_bench_03"  # WAV on the data root, no sidecar anywhere
ROOT_SIM = "2026-10-17_lab_bench_04"  # simulated, WAV + sidecar on the data root only (copy_sim_sidecars off)
ROOT_REAL = "2026-10-18_lab_bench_05"  # not simulated, WAV + sidecar on the data root only


def _repo_sidecar(repo: Path, name: str, doc: dict) -> Path:
    path = repo / name / f"{name}.adc.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def _notes(**values: str) -> str:
    return io.format_rzlab_notes({"frames": "8000", "persons": "P1,P2", "floor": "laminate", **values})


def make_world(tmp_path: Path) -> tuple[Path, Path]:
    """``(data_root, repo_data)`` with the five sessions above."""
    root, repo = tmp_path / "dataroot", tmp_path / "repo-data"
    root.mkdir(parents=True, exist_ok=True)
    repo.mkdir(parents=True, exist_ok=True)
    for name in (VALID, INVALID, SIM, ORPHAN):
        write_session(root, name)
    (root / ORPHAN / f"{ORPHAN}.adc.json").unlink()
    _repo_sidecar(repo, VALID, sidecar(VALID))
    bad = sidecar(INVALID)
    bad["sample_rate"] = 1000
    _repo_sidecar(repo, INVALID, bad)
    dry = sidecar(NO_WAV)
    dry["notes"] = _notes(floor="2")
    _repo_sidecar(repo, NO_WAV, dry)
    sim = sidecar(SIM, labels=[{"t0": 0.0, "t1": 1.0, "i0": 0, "i1": 2000, "src": "auto", "label": "silence"}])
    sim["notes"] = _notes(source="sim", persons="P5")
    _repo_sidecar(repo, SIM, sim)
    return root, repo


def make_index(tmp_path: Path, repo: Path) -> DatasetIndex:
    return DatasetIndex(tmp_path / "cache" / "datasets.sqlite", repo, SCHEMA, "data", REPO)


def by_name(rows: list[dict]) -> dict[str, dict]:
    return {r["session"]: r for r in rows}


# ------------------------------------------------------------------------------------------------ index


def test_index_rows_from_synthetic_sessions(tmp_path):
    root, repo = make_world(tmp_path)
    ix = make_index(tmp_path, repo)
    stats = ix.refresh(root)
    assert stats["sidecars"] == 4 and stats["sessions_rebuilt"] == 4
    rows = ix.rows(root)
    assert [r["session"] for r in rows] == sorted([VALID, INVALID, NO_WAV, SIM, ORPHAN], reverse=True)
    r = by_name(rows)

    ok = r[VALID]
    assert ok["valid"] and ok["wav_present"] and not ok["simulated"] and not ok["incomplete"]
    assert (ok["date"], ok["site"], ok["room"], ok["take"]) == ("2026-10-12", "home-a", "kitchen", "01")
    assert ok["floor"] == "laminate" and ok["people"] == ["P1", "P2"] and ok["label_count"] == 3
    assert ok["duration_s"] == pytest.approx(4.0) and ok["loss"] == {"device": 0, "link": 0, "host": 0}
    assert ok["protocol"] and ok["errors"] == [] and ok["in_repo"] and ok["on_data_root"]
    assert ok["streams"][0]["sha256"] is None, "the index never hashes"

    bad = r[INVALID]
    assert not bad["valid"] and bad["wav_present"] and bad["errors"]

    dry = r[NO_WAV]
    assert not dry["valid"] and not dry["wav_present"] and dry["wav_missing"] == 1 and not dry["on_data_root"]
    assert any("wav: missing" in e for e in dry["errors"]) and dry["floor"] == "2"

    sim = r[SIM]
    assert sim["simulated"] and sim["valid"] and sim["people"] == ["P5"] and sim["label_count"] == 1

    orphan = r[ORPHAN]
    assert not orphan["in_repo"] and not orphan["valid"] and orphan["on_data_root"]
    assert orphan["unmatched_wavs"] == [f"{ORPHAN}.adc.wav"] and orphan["streams"] == []
    assert orphan["wav_present"] and orphan["wav_missing"] == 0, "a WAV that is there is never 'missing'"
    assert orphan["sidecar_source"] is None


def add_root_only_sessions(root: Path) -> None:
    """Two sessions that live only on the data root, as the recorder leaves them: WAV and sidecar side by side."""
    for name in (ROOT_SIM, ROOT_REAL):
        write_session(root, name)
    sim = sidecar(ROOT_SIM, labels=[{"t0": 0.0, "t1": 1.0, "i0": 0, "i1": 2000, "src": "auto", "label": "silence"}])
    sim["notes"] = _notes(source="sim", persons="P7")
    sim["protocol"] = "walk-pass-v1"
    io.save_sidecar(root / ROOT_SIM / f"{ROOT_SIM}.adc.json", sim, SCHEMA)


def test_data_root_only_sessions_are_read_from_the_data_root_sidecars(tmp_path):
    root, repo = make_world(tmp_path)
    add_root_only_sessions(root)
    assert not (repo / ROOT_SIM).exists() and not (repo / ROOT_REAL).exists()
    ix = make_index(tmp_path, repo)
    stats = ix.refresh(root)
    assert stats["sidecars_data_root"] == 2 and stats["sessions_rebuilt"] == 6
    r = by_name(ix.rows(root))

    sim = r[ROOT_SIM]
    assert sim["valid"] and sim["errors"] == [] and sim["warnings"] == []
    assert sim["wav_present"] and sim["wav_missing"] == 0
    assert not sim["in_repo"] and sim["sidecar_source"] == "data_root" and sim["on_data_root"]
    assert sim["simulated"] and sim["people"] == ["P7"] and sim["label_count"] == 1
    assert sim["protocol"] == "walk-pass-v1" and sim["duration_s"] == pytest.approx(4.0)
    assert sim["streams_n"] == 1 and sim["streams"][0]["sha256"] is None
    assert sim["size_bytes"] == (root / ROOT_SIM / f"{ROOT_SIM}.adc.wav").stat().st_size

    real = r[ROOT_REAL]
    assert real["valid"] and not real["simulated"] and not real["in_repo"] and real["sidecar_source"] == "data_root"
    assert real["people"] == ["P1", "P2"] and real["label_count"] == 3

    assert r[VALID]["sidecar_source"] == "repo" and r[VALID]["in_repo"]

    shown = [x for x in ix.rows(root) if x["session"] in (ROOT_SIM, ROOT_REAL)]
    t = totals(shown)
    assert t["simulated"] == 1 and t["wav_missing"] == 0 and t["invalid"] == 0 and t["labels"] == 4
    assert t["hours"] == pytest.approx(8.0 / 3600, abs=1e-3)

    # validated the same way: a data-root sidecar that disagrees with its WAV makes the row invalid
    bad = sidecar(ROOT_REAL)
    bad["sample_rate"] = 1000
    (root / ROOT_REAL / f"{ROOT_REAL}.adc.json").write_text(json.dumps(bad), encoding="utf-8")
    ix.refresh(root)
    real = by_name(ix.rows(root))[ROOT_REAL]
    assert not real["valid"] and real["wav_present"] and real["errors"]


def test_data_root_only_sessions_stay_out_of_the_manifest(tmp_path):
    root, repo = make_world(tmp_path)
    add_root_only_sessions(root)
    ix = make_index(tmp_path, repo)
    ix.refresh(root)
    reasons = {x["session"]: x["reason"] for x in ix.plan_manifest(root)["excluded"]}
    assert reasons[ROOT_SIM] == "simulated" and reasons[ROOT_REAL] == "sidecar not in repo; import or copy first"
    plan = ix.plan_manifest(root, sessions=[ROOT_SIM, ROOT_REAL, VALID], include_simulated=True)
    assert plan["sessions"] == [VALID]
    assert {x["session"]: x["reason"] for x in plan["excluded"]} == {
        ROOT_SIM: "sidecar not in repo; import or copy first",
        ROOT_REAL: "sidecar not in repo; import or copy first",
    }
    ix.build_manifest(root, sessions=[ROOT_REAL, VALID], created="2026-10-13T10:00:00Z")
    written = mf.read_manifest(repo / "manifest.json")
    assert [e["session"] for e in written["entries"]] == [VALID]


def test_a_repo_copy_replaces_the_data_root_sidecar(tmp_path):
    root, repo = make_world(tmp_path)
    add_root_only_sessions(root)
    ix = make_index(tmp_path, repo)
    ix.refresh(root)
    assert by_name(ix.rows(root))[ROOT_REAL]["sidecar_source"] == "data_root"
    _repo_sidecar(repo, ROOT_REAL, sidecar(ROOT_REAL))
    stats = ix.refresh(root)
    assert stats["sidecars_removed"] == 1 and stats["sidecars_data_root"] == 1
    row = by_name(ix.rows(root))[ROOT_REAL]
    assert row["in_repo"] and row["sidecar_source"] == "repo" and row["valid"]
    assert row["streams"][0]["sidecar"] == f"data/{ROOT_REAL}/{ROOT_REAL}.adc.json"


def test_index_without_a_data_root_marks_every_wav_missing(tmp_path):
    _root, repo = make_world(tmp_path)
    ix = make_index(tmp_path, repo)
    ix.refresh(None)
    rows = by_name(ix.rows(None))
    assert ORPHAN not in rows
    assert all(not r["wav_present"] and not r["valid"] for r in rows.values())


def test_cache_is_reused_and_rebuilt_after_deletion(tmp_path):
    root, repo = make_world(tmp_path)
    ix = make_index(tmp_path, repo)
    ix.refresh(root)
    first = ix.rows(root)
    again = ix.refresh(root)
    assert again["sessions_rebuilt"] == 0 and again["sidecars_reused"] == 4 and not again["cache_dropped"]
    ix.db_path.unlink()
    rebuilt = ix.refresh(root)
    assert rebuilt["sessions_rebuilt"] == 4 and rebuilt["cache_dropped"]
    assert ix.rows(root) == first
    forced = ix.refresh(root, force=True)
    assert forced["sessions_rebuilt"] == 4 and ix.rows(root) == first


def test_a_damaged_cache_file_is_replaced(tmp_path):
    root, repo = make_world(tmp_path)
    ix = make_index(tmp_path, repo)
    ix.db_path.parent.mkdir(parents=True)
    ix.db_path.write_bytes(b"this is not a database" * 100)
    assert ix.refresh(root)["sessions_rebuilt"] == 4
    assert len(ix.rows(root)) == 5


def test_cache_invalidated_on_sidecar_and_wav_change(tmp_path):
    root, repo = make_world(tmp_path)
    ix = make_index(tmp_path, repo)
    ix.refresh(root)
    path = repo / VALID / f"{VALID}.adc.json"
    before = path.stat().st_mtime_ns
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["sample_rate"] = 1000  # same byte count: only the mtime tells
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    os.utime(path, ns=(before + 2_000_000_000, before + 2_000_000_000))
    stats = ix.refresh(root)
    assert stats["sessions_rebuilt"] == 1
    assert not by_name(ix.rows(root))[VALID]["valid"]

    (root / SIM / f"{SIM}.adc.wav").unlink()
    assert ix.refresh(root)["sessions_rebuilt"] == 1
    assert not by_name(ix.rows(root))[SIM]["wav_present"]

    shutil.rmtree(repo / INVALID)
    stats = ix.refresh(root)
    assert stats["sidecars_removed"] == 1 and stats["sessions_rebuilt"] == 1
    gone = by_name(ix.rows(root))[INVALID]  # still on the data root: now read from the sidecar next to its WAV
    assert not gone["in_repo"] and gone["sidecar_source"] == "data_root" and gone["valid"]


def test_cache_dropped_when_the_data_root_changes(tmp_path):
    root, repo = make_world(tmp_path)
    ix = make_index(tmp_path, repo)
    ix.refresh(root)
    other = tmp_path / "other-root"
    other.mkdir()
    assert ix.refresh(other)["cache_dropped"]


def test_index_cache_may_not_lie_in_the_repository(tmp_path):
    with pytest.raises(DatasetError) as e:
        DatasetIndex(REPO / "scratch" / "datasets.sqlite", tmp_path, SCHEMA, "data", REPO)
    assert e.value.code == "index_in_repo"


def test_filters_and_totals(tmp_path):
    root, repo = make_world(tmp_path)
    ix = make_index(tmp_path, repo)
    ix.refresh(root)
    rows = ix.rows(root)

    def names(**kw) -> set[str]:
        return {r["session"] for r in rows if Filters(**kw).match(r)}

    assert names(valid=True) == {VALID, SIM}
    assert names(valid=False) == {INVALID, NO_WAV, ORPHAN}
    assert names(wav="missing") == {NO_WAV}
    assert names(wav="present") == {VALID, INVALID, SIM, ORPHAN}  # the orphan has a WAV, just no sidecar
    assert names(simulated=True) == {SIM}
    assert names(floor="2") == {NO_WAV}
    assert names(person="P5") == {SIM}
    assert names(person="P1") == {VALID, INVALID, NO_WAV}
    assert names(date_from="2026-10-13", date_to="2026-10-14") == {INVALID, NO_WAV}
    assert names(protocol="no-such-protocol") == set()

    t = totals([r for r in rows if Filters(valid=True).match(r)])
    assert t["sessions"] == 2 and t["labels"] == 4 and t["hours"] == pytest.approx(8 / 3600, abs=1e-3)
    assert [p["person"] for p in t["per_person"]] == ["P1", "P2", "P5"]


# ------------------------------------------------------------------------------------------------ manifest


def test_manifest_build_writes_only_selected_valid_entries(tmp_path):
    root, repo = make_world(tmp_path)
    ix = make_index(tmp_path, repo)
    ix.refresh(root)

    plan = ix.plan_manifest(root)
    assert plan["sessions"] == [VALID]
    reasons = {x["session"]: x["reason"] for x in plan["excluded"]}
    assert reasons[SIM] == "simulated" and reasons[ORPHAN].startswith("no sidecar")
    assert reasons[INVALID].startswith("invalid") and reasons[NO_WAV].startswith("invalid")
    assert not (repo / "manifest.json").exists(), "a preview writes nothing"

    result = ix.build_manifest(root, created="2026-10-13T10:00:00Z")
    assert result["entries"] == 1 and result["sessions"] == [VALID] and result["written"] == "data/manifest.json"
    written = mf.read_manifest(repo / "manifest.json")
    assert mf.validate_manifest(written) == []
    (entry,) = written["entries"]
    wav = root / VALID / f"{VALID}.adc.wav"
    assert entry["wav"] == f"{VALID}/{VALID}.adc.wav" and entry["sidecar"] == f"data/{VALID}/{VALID}.adc.json"
    assert entry["sha256"] == hashlib.sha256(wav.read_bytes()).hexdigest()
    assert by_name(ix.rows(root))[VALID]["streams"][0]["sha256"] == entry["sha256"], "the build's hash is kept"

    both = ix.build_manifest(root, sessions=[VALID, SIM, INVALID], include_simulated=True)
    assert both["sessions"] == [SIM, VALID]
    assert [x["session"] for x in both["excluded"]] == [INVALID]
    assert mf.validate_manifest(mf.read_manifest(repo / "manifest.json")) == []

    with pytest.raises(DatasetError) as e:
        ix.build_manifest(root, sessions=[INVALID])
    assert e.value.code == "empty_manifest"
    assert len(mf.read_manifest(repo / "manifest.json")["entries"]) == 2, "an empty build leaves the file alone"


def test_index_refresh_does_not_hash_but_hash_session_does(tmp_path, monkeypatch):
    root, repo = make_world(tmp_path)
    ix = make_index(tmp_path, repo)
    calls: list[Path] = []
    real = mf.sha256_file
    monkeypatch.setattr(mf, "sha256_file", lambda p, *a, **k: calls.append(p) or real(p, *a, **k))
    ix.refresh(root)
    assert calls == []
    out = ix.hash_session(root, VALID)
    wav = root / VALID / f"{VALID}.adc.wav"
    assert out == [{"wav": f"{VALID}/{VALID}.adc.wav", "sha256": hashlib.sha256(wav.read_bytes()).hexdigest()}]
    assert by_name(ix.rows(root))[VALID]["streams"][0]["sha256"] == out[0]["sha256"]
    wav.write_bytes(wav.read_bytes() + b"\0\0\0\0")  # a changed WAV: the stored hash no longer applies
    ix.refresh(root)
    assert by_name(ix.rows(root))[VALID]["streams"][0]["sha256"] is None


# ------------------------------------------------------------------------------------------------ REST


@pytest.fixture
def client(tmp_path):
    root, repo = make_world(tmp_path)
    cfg = make_cfg(tmp_path, data_root=root, sidecar_dir=repo, index_db=tmp_path / "cache" / "datasets.sqlite")
    app = create_app(PORT, manager=DeviceManager(embedded_sim=False), static_dir=tmp_path / "nostatic", lab_config=cfg)
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        yield c


def test_api_list_filters_detail_and_rebuild(client):
    r = client.get("/api/datasets/sessions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["all"] == 5 and body["totals"]["sessions"] == 5
    assert body["facets"]["floors"] == ["2", "laminate"] and body["facets"]["people"] == ["P1", "P2", "P5"]
    assert body["index"]["manifest"] == {"path": "data/manifest.json", "exists": False}

    r = client.get("/api/datasets/sessions", params={"valid": "true", "simulated": "false"})
    assert [s["session"] for s in r.json()["sessions"]] == [VALID]
    r = client.get("/api/datasets/sessions", params={"wav": "missing", "date_to": "2026-10-14"})
    assert [s["session"] for s in r.json()["sessions"]] == [NO_WAV]
    assert client.get("/api/datasets/sessions", params={"person": "Anna"}).status_code == 422

    r = client.get(f"/api/datasets/sessions/{SIM}")
    assert r.status_code == 200 and r.json()["simulated"]
    assert client.get("/api/datasets/sessions/2026-01-01_no_such_01").json()["error"]["code"] == "not_found"
    assert client.get("/api/datasets/sessions/..%2F..%2Fetc").status_code in (404, 422)

    r = client.post("/api/datasets/rebuild")
    assert r.status_code == 200 and r.json()["refresh"]["sessions_rebuilt"] == 4

    r = client.post(f"/api/datasets/sessions/{VALID}/hash")
    assert r.status_code == 200 and len(r.json()["wavs"][0]["sha256"]) == 64


def test_api_manifest_preview_then_build(client, tmp_path):
    r = client.post("/api/datasets/manifest/preview", json={})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["sessions"] == [VALID] and plan["out"] == "data/manifest.json" and not plan["exists"]
    assert {x["session"] for x in plan["excluded"]} == {INVALID, NO_WAV, SIM, ORPHAN}

    r = client.post("/api/datasets/manifest/preview", json={"filters": {"simulated": True}, "include_simulated": True})
    assert r.json()["sessions"] == [SIM]

    r = client.post("/api/datasets/manifest", json={"sessions": [VALID, SIM], "include_simulated": True})
    assert r.status_code == 200, r.text
    assert r.json()["entries"] == 2
    written = mf.read_manifest(tmp_path / "repo-data" / "manifest.json")
    assert {e["session"] for e in written["entries"]} == {VALID, SIM}

    r = client.post("/api/datasets/manifest", json={"sessions": [NO_WAV]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "empty_manifest"
    r = client.post("/api/datasets/manifest", json={"sessions": ["2026-01-01_no_such_01"]})
    assert r.status_code == 404
    assert client.post("/api/datasets/manifest", json={"bogus": 1}).status_code == 422


# ------------------------------------------------------------------------------------------------ 4b follow-ups


def test_record_start_refused_while_rig_checks_run(tmp_path):
    cfg = make_cfg(tmp_path, index_db=tmp_path / "cache.sqlite")
    app = create_app(PORT, manager=DeviceManager(embedded_sim=False), static_dir=tmp_path / "nostatic", lab_config=cfg)
    stop = threading.Event()
    worker = threading.Thread(target=stop.wait, daemon=True)
    worker.start()
    app.state.rigcheck._thread = worker  # the rig checks look busy
    try:
        with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
            r = c.post("/api/record/start", json=form())
            assert r.status_code == 409 and r.json()["error"]["code"] == "rigcheck_running", r.text
            assert c.get("/api/record/state").json()["state"] == "idle"
            blockers = [b["code"] for b in c.get("/api/record/options").json()["blockers"]]
            assert "rigcheck_running" in blockers
    finally:
        stop.set()
        worker.join(2)
        app.state.rigcheck._thread = None


def test_rigcheck_report_filename_is_ascii(tmp_path):
    from rezonating_lab.server.rigcheck import RigChecks

    rig = RigChecks(DeviceManager(embedded_sim=False), make_cfg(tmp_path))
    rig.node = {"node_id": "nöde-ß/1"}
    name = rig.report_filename()
    assert name.isascii() and name.endswith("_n_de-__1.md"), name
