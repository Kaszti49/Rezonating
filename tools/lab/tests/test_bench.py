"""Pack bench (Lab phase 5): bench == rezonating_ml, scoring, trigger save, compare, test vectors.

Data: a small ``rzlab sim-dataset`` (2 simulated persons, 1 session, passes_scale 0.1) built once per module in a
temp folder, plus a copy of it with zero-filled lost frames. Nothing here writes into packs/ or ml/tests/vectors.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from rec_helpers import PORT, REPO, lab, make_cfg
from rezonating_lab.recorder.protocol import load_named
from rezonating_lab.server import bench as B
from rezonating_lab.server.app import create_app
from rezonating_lab.server.bench_routes import Bench
from rezonating_lab.server.device import DeviceManager
from rezonating_lab.sim.dataset import DatasetConfig, generate_dataset
from rezonating_lab.sim.node import SimConfig
from rezonating_ml import io
from rezonating_ml.pipeline import run_pipeline, sidecar_lost_total, zero_fill_mask

SCHEMA = REPO / "schemas" / "sidecar.schema.json"
PACK = REPO / "packs" / "footstep-id" / "pack.json"
LOST = (133_000, 133_020)  # zero-filled frames in the lossy copy (inside the first walking pass)


@pytest.fixture(scope="module")
def simroot(tmp_path_factory) -> tuple[Path, str]:
    out = tmp_path_factory.mktemp("bench") / "simdata"
    cfg = DatasetConfig(sessions=1, persons=["P1", "P2"], seed=11, passes_scale=0.1)
    res = generate_dataset(cfg, load_named(REPO, "walk-pass-v1"), out, SCHEMA)
    return out, res[0].name


@pytest.fixture(scope="module")
def lossy(simroot, tmp_path_factory) -> tuple[Path, str]:
    """The session again, with LOST zero-filled on both channels and the sidecar's loss saying so."""
    src_root, name = simroot
    root = tmp_path_factory.mktemp("lossy")
    shutil.copytree(src_root / name, root / name)
    wav, js = root / name / f"{name}.adc.wav", root / name / f"{name}.adc.json"
    frames, fs = io.read_wav(wav)
    frames = frames.copy()
    frames[LOST[0] : LOST[1]] = 0
    io.write_wav(wav, frames, fs)
    doc = json.loads(js.read_text(encoding="utf-8"))
    doc["loss"]["device"] = LOST[1] - LOST[0]
    js.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return root, name


def _direct(root: Path, name: str, channel: int = 0):
    """What a user would do with rezonating_ml alone (README "Pack pipeline (D-021)")."""
    frames, _ = io.read_wav(root / name / f"{name}.adc.wav")
    side = json.loads((root / name / f"{name}.adc.json").read_text(encoding="utf-8"))
    m = zero_fill_mask(frames, expected_lost=sidecar_lost_total(side["loss"]))
    return run_pipeline(PACK, frames[:, channel], input_fs_hz=2000.0, valid=m.valid)


def _same(a, b) -> None:
    for f in ("decimated", "valid", "filtered", "ratio", "features"):
        x, y = getattr(a, f), getattr(b, f)
        assert x.dtype == y.dtype and x.shape == y.shape and x.tobytes() == y.tobytes(), f
    assert a.events == b.events and a.windows == b.windows and a.feature_windows == b.feature_windows
    assert a.stages == b.stages


@pytest.mark.parametrize("which", ["clean", "lossy"])
def test_bench_output_equals_a_direct_rezonating_ml_call_on_the_same_wav(simroot, lossy, which):
    root, name = simroot if which == "clean" else lossy
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    src = B.load_recording(root, name, 0)
    for chunk in (B.DEFAULT_CHUNK, 777):
        _, out = B.run_chunked(pack, src.x, src.valid, src.input_fs_hz, chunk=chunk)
        _same(out, _direct(root, name))
    if which == "lossy":
        assert src.info["n_marked_lost"] == LOST[1] - LOST[0] and src.info["mask_covers_all_lost"]
        assert not out.valid.all()


def _client(tmp_path: Path) -> TestClient:
    cfg = make_cfg(tmp_path)
    app = create_app(PORT, manager=DeviceManager(embedded_sim=False), static_dir=tmp_path / "nostatic", lab_config=cfg)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def test_bench_api_run_shows_every_stage_and_scores_triggers_against_truth(simroot, tmp_path):
    root, name = simroot
    direct = _direct(root, name)
    with _client(tmp_path) as c:
        packs = c.get("/api/bench/packs").json()["packs"]
        assert {"footstep-id", "fall", "appliance"} <= {p["id"] for p in packs}
        ses = c.get("/api/bench/sessions", params={"root": str(root)}).json()["sessions"]
        assert ses == [{"name": name, "truth": True}]
        body = {"pack": "footstep-id", "source": {"kind": "sim", "session": name, "root": str(root)}}
        r = c.post("/api/bench/run", json=body)
        assert r.status_code == 200, r.text
        v = r.json()
    assert v["stage_order"] == ["decimate", "dsp", "trigger", "features", "model"]
    assert [v["stages"][s]["status"] for s in v["stage_order"]] == ["ok", "ok", "ok", "ok", "not_available"]
    assert v["threshold"] == 3.5 and v["model"] is None
    assert [(e["onset"], e["start"], e["end"]) for e in v["events"]] == [
        (e.onset, e.start, e.end) for e in direct.events
    ]
    assert len(v["features"]) == len(direct.feature_windows) and len(v["features"][0]["values"]) == 13
    assert v["counts"]["windows"] == len(direct.windows)
    sc = v["score"]
    truth = B.read_truth(root / f"{name}.truth.jsonl")
    assert sc["n_truth"] == len(truth) > 50 and sc["n_events"] == len(direct.events)
    assert sc["true_positives"] + sc["false_negatives"] == sc["n_truth"]
    assert sc["recall"] > 0.5 and sc["precision"] > 0.5, sc  # the sim's steps are clear; a regression shows here
    assert abs(sc["onset_error_ms"]["mean"]) < B.MATCH_TOL_MS


def test_score_events_known_answer():
    # fs 2000 Hz: tolerance 50 ms = 100 samples (inclusive). Truth 1000, 3000, 5000; events 1040 (match, +20 ms),
    # 2899 (101 samples from 3000: unmatched), 4950 and 4990 both near 5000: the closer (4990, -5 ms) takes it
    assert B.score_events([2900], [3000], 2000.0)["true_positives"] == 1  # exactly 50 ms still matches
    s = B.score_events([1040, 2899, 4950, 4990], [1000, 3000, 5000], 2000.0)
    assert (s["true_positives"], s["false_positives"], s["false_negatives"]) == (2, 2, 1)
    assert s["precision"] == 0.5 and s["recall"] == round(2 / 3, 4)
    assert s["onset_error_ms"]["mean"] == 7.5  # (+20 - 5) / 2
    assert B.score_events([], [], 2000.0)["precision"] is None


def test_train_baseline_in_memory_turns_the_model_stage_on(simroot, tmp_path):
    root, name = simroot
    with _client(tmp_path) as c:
        src = {"kind": "sim", "session": name, "root": str(root)}
        r = c.post("/api/bench/train", json={"pack": "footstep-id", "sources": [src]})
        assert r.status_code == 200, r.text
        info = r.json()
        assert set(info["classes"]) == {"P1", "P2"} and info["n_windows"] > 10
        v = c.post("/api/bench/run", json={"pack": "footstep-id", "source": src}).json()
        assert v["stages"]["model"]["status"] == "ok" and set(v["model"]["classes"]) == {"P1", "P2"}
        assert len(v["model"]["rows"]) == len(v["features"])
        assert c.delete("/api/bench/model").status_code == 200
        v = c.post("/api/bench/run", json={"pack": "footstep-id", "source": src}).json()
        assert v["stages"]["model"]["status"] == "not_available"


def test_slider_values_rerun_the_pipeline(simroot, tmp_path):
    root, name = simroot
    with _client(tmp_path) as c:
        src = {"kind": "sim", "session": name, "root": str(root)}
        base = c.post("/api/bench/run", json={"pack": "footstep-id", "source": src}).json()
        hi = c.post("/api/bench/run", json={"pack": "footstep-id", "source": src, "trigger": {"ratio": 8}}).json()
    assert hi["threshold"] == 8 and hi["counts"]["events"] < base["counts"]["events"]
    pack = B.with_trigger(json.loads(PACK.read_text(encoding="utf-8")), {"ratio": 8})
    assert hi["counts"]["events"] == len(_direct_with(pack, root, name).events)


def _direct_with(pack, root, name):
    frames, _ = io.read_wav(root / name / f"{name}.adc.wav")
    return run_pipeline(pack, frames[:, 0], input_fs_hz=2000.0, valid=zero_fill_mask(frames, expected_lost=0).valid)


# ------------------------------------------------------------------------------------- save to pack.json


@pytest.fixture
def packs_copy(tmp_path) -> Path:
    d = tmp_path / "packs"
    shutil.copytree(REPO / "packs", d)
    return d


def test_save_writes_only_the_trigger_and_validates(packs_copy, tmp_path):
    bench = Bench(make_cfg(tmp_path), None, packs_dir=packs_copy)
    path = packs_copy / "footstep-id" / "pack.json"
    before = path.read_text(encoding="utf-8")
    from rezonating_lab.server.bench_routes import TriggerBody

    body = TriggerBody(pack="footstep-id", trigger={"ratio": 4.0, "sta_ms": 40})
    pre = bench.preview(body)
    assert B.FOOTSTEP_VECTORS_WARNING in pre["warnings"] and path.read_text(encoding="utf-8") == before
    assert [ln for ln in pre["diff"].splitlines() if ln.startswith(("+ ", "- "))] == [
        '-  "trigger": { "type": "sta_lta", "sta_ms": 50, "lta_ms": 2000, "ratio": 3.5, "pre_ms": 100, "post_ms": 400 },',
        '+  "trigger": { "type": "sta_lta", "sta_ms": 40, "lta_ms": 2000, "ratio": 4, "pre_ms": 100, "post_ms": 400 },',
    ]
    res = bench.save(body)
    assert res["saved"] and res["errors"] == []
    after = path.read_text(encoding="utf-8")
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b]
    assert len(changed) == 1 and '"trigger"' in changed[0][0]
    assert list(json.loads(after)) == list(json.loads(before))  # key order kept
    assert B.validate_pack_file(path, REPO) == []
    # the real repository pack is untouched
    assert json.loads(PACK.read_text(encoding="utf-8"))["trigger"]["ratio"] == 3.5


def test_save_refuses_and_rolls_back_an_invalid_trigger(packs_copy, tmp_path):
    path = packs_copy / "footstep-id" / "pack.json"
    before = path.read_text(encoding="utf-8")
    with pytest.raises(B.BenchError) as exc:  # schema: ratio > 1
        B.save_trigger(path, {"ratio": 0.5}, lambda p: B.validate_pack_file(p, REPO))
    assert exc.value.code == "invalid_pack" and "ratio" in exc.value.message
    assert path.read_text(encoding="utf-8") == before
    with pytest.raises(B.BenchError):
        B.save_trigger(path, {"lta_ms": 3000}, lambda p: ["validator says no"])
    assert path.read_text(encoding="utf-8") == before
    res = B.save_trigger(path, {"sta_ms": 300, "lta_ms": 200}, lambda p: [])  # schema-valid, refused by rezonating_ml
    assert res["saved"] is False and "rezonating_ml refuses" in res["errors"][0]
    assert path.read_text(encoding="utf-8") == before
    with pytest.raises(B.BenchError):
        B.save_trigger(path, {"type": "threshold"}, lambda p: [])  # only the tunable keys
    with pytest.raises(B.BenchError):
        B.save_trigger(packs_copy / "appliance" / "pack.json", {"ratio": 4}, lambda p: [])  # periodic trigger


def test_replace_trigger_text_keeps_a_multiline_block_multiline():
    text = '{\n  "id": "x",\n  "trigger": {\n    "type": "sta_lta",\n    "ratio": 3\n  },\n  "z": 1\n}\n'
    new = B.replace_trigger_text(text, {"type": "sta_lta", "ratio": 5})
    assert new == '{\n  "id": "x",\n  "trigger": {\n    "type": "sta_lta",\n    "ratio": 5\n  },\n  "z": 1\n}\n'


# ------------------------------------------------------------------------------------------ test vectors


def test_vector_create_and_check_round_trip(simroot, lossy, tmp_path):
    root, name = simroot
    lroot, lname = lossy
    with _client(tmp_path) as c:
        out_dir = tmp_path / "vectors"
        k_lost = (LOST[0] + 30) // 2  # pack-rate index of the lost run
        for src, k0, fn in (
            ({"kind": "sim", "session": name, "root": str(root)}, 63_000, "clean.json"),
            ({"kind": "recording", "session": lname, "root": str(lroot)}, k_lost - 3000, "masked.json"),
        ):
            body = {
                "pack": "footstep-id",
                "source": src,
                "k0": k0,
                "k1": k0 + 6000,
                "folder": str(out_dir),
                "filename": fn,
            }
            r = c.post("/api/bench/vector/create", json=body)
            assert r.status_code == 200, r.text
            assert r.json()["masked"] == (fn == "masked.json")
            vec = json.loads((out_dir / fn).read_text(encoding="utf-8"))
            ref = json.loads((REPO / "ml/tests/vectors/sta_lta.json").read_text(encoding="utf-8"))
            assert set(ref) - {"step_onsets_dec_approx", "build", "clip", "masked"} <= set(vec)  # same format
            assert len(vec["input"]) == 6000 and vec["expected"]["events"]
            ok = c.post("/api/bench/vector/check", json={"path": str(out_dir / fn)}).json()
            assert ok["ok"], ok["problems"]
            vec["expected"]["events"][0]["onset"] += 1
            (out_dir / fn).write_text(json.dumps(vec), encoding="utf-8")
            bad = c.post("/api/bench/vector/check", json={"path": str(out_dir / fn)}).json()
            assert not bad["ok"] and "events differ" in bad["problems"][0]
        refused = c.post(
            "/api/bench/vector/create",
            json={**body, "folder": str(REPO / "ml" / "tests" / "vectors")},
        )
        assert refused.status_code == 400 and refused.json()["error"]["code"] == "reserved"
        for inside, fn in ((REPO / "packs" / "footstep-id", "pack.json"), (REPO / "schemas", "x.json"),
                           (REPO / "ml" / "tests" / "vectors" / "sub", "x.json")):  # fmt: skip
            r = c.post("/api/bench/vector/create", json={**body, "folder": str(inside), "filename": fn})
            assert r.status_code == 400 and r.json()["error"]["code"] == "reserved", inside
        again = c.post("/api/bench/vector/create", json={**body, "folder": str(out_dir), "filename": "masked.json"})
        assert again.status_code == 409 and again.json()["error"]["code"] == "exists"
        (out_dir / "junk.json").write_text("{not json", encoding="utf-8")
        junk = c.post("/api/bench/vector/check", json={"path": str(out_dir / "junk.json")})
        assert junk.status_code == 400 and junk.json()["error"]["code"] == "bad_vector"
    # the committed vector passes the bench's check too (same contract)
    assert B.check_vector(json.loads((REPO / "ml/tests/vectors/sta_lta.json").read_text(encoding="utf-8"))) == []


# ------------------------------------------------------------------------------------- compare (live sim)


def test_compare_on_the_live_sim_has_no_missing_and_no_extra_events(tmp_path):
    with lab(tmp_path, SimConfig(speed=10.0)) as (client, sim, cfg):
        r = client.post("/api/acquisition", json={"action": "start", "streams": ["adc_raw"]})
        assert r.status_code == 200, r.text
        end = time.time() + 30
        res = None
        while time.time() < end:
            time.sleep(1.0)
            res = client.post("/api/bench/compare", json={"pack": "footstep-id"}).json()
            if res.get("matched", 0) >= 8:
                break
        assert res is not None and res["matched"] >= 8, res
        assert res["missing"] == 0 and res["extra"] == 0 and res["diffs"] == []
        assert res["starts_at_acquisition_start"]
        live = client.post("/api/bench/run", json={"pack": "footstep-id", "source": {"kind": "live"}}).json()
        assert live["source"]["kind"] == "live" and live["counts"]["events"] >= res["matched"]
        client.post("/api/acquisition", json={"action": "stop"})


def test_compare_events_reports_index_differences():
    r = B.compare_events([100, 200, 300], [100, 203, 400])
    assert (r["matched"], r["missing"], r["extra"]) == (1, 2, 2)
    assert r["diffs"] == [{"fw": 200, "py": 203, "diff": 3}]
    assert np.array_equal(r["missing_idx"], [200, 300]) and r["extra_idx"] == [203, 400]
