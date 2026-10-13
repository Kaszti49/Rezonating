"""Phase 4c, attempt 2: both streams' labels in sync (decision A), the protocol's fixed label list (decision B), and
the verifier's findings on the SD import and the Review backend (F-261013-5c94)."""

from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rec_helpers import PORT, form, lab, make_cfg, wait_idle
from review_helpers import NAME, RATE, SCHEMA, base_labels, write_session
from rezonating_lab.recorder import sdimport
from rezonating_lab.recorder.recording import MarkRefused
from rezonating_lab.recorder.review import map_index
from rezonating_lab.recorder.validate import run_validate, validate_session_folder
from rezonating_lab.server.app import create_app
from rezonating_lab.server.device import DeviceManager
from rezonating_ml import io

ACCEL_DELAY_US = 100_000  # the accel file starts 0.1 s after the adc file on the device clock
ACCEL_RATE = 2000.4  # and its measured rate differs a little


@contextmanager
def review_app(tmp_path, **cfg_over):
    cfg = make_cfg(tmp_path, **cfg_over)
    app = create_app(PORT, manager=DeviceManager(embedded_sim=False), static_dir=None, lab_config=cfg)
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as client:
        yield client, cfg


def shift_accel(folder: Path, labels: list[dict] | None = None) -> dict:
    """Give the accel sidecar its own device-clock start and measured rate (as a real recording has)."""
    js = folder / f"{NAME}.accel.json"
    adc = io.load_sidecar(folder / f"{NAME}.adc.json")
    doc = io.load_sidecar(js)
    doc["t_dev_us"] = adc["t_dev_us"] + ACCEL_DELAY_US
    doc["sample_rate_measured"] = ACCEL_RATE
    if labels is not None:
        doc["labels"] = labels
    io.save_sidecar(js, doc, SCHEMA)
    return doc


def opened(client) -> dict:
    return client.get(f"/api/review/sessions/{NAME}").json()


def save(client, labels, stream="adc_raw", **over):
    o = opened(client)["streams"]
    body = {"stream": stream, "labels": labels, "version": o[stream]["version"]}
    peer = next((v for k, v in o.items() if k != stream), None)
    if peer is not None:
        body["peer_version"] = peer["version"]
    body.update(over)
    return client.put(f"/api/review/sessions/{NAME}/labels", json=body)


def edit(client, labels, op, stream="adc_raw"):
    return client.post(f"/api/review/sessions/{NAME}/edit", json={"stream": stream, "labels": labels, "op": op})


# ------------------------------------------------------------------------------- decision A: both streams


def test_a_save_writes_both_sidecars_mapped_through_the_device_clock(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root, accel=True)
        shift_accel(folder)
        repo = cfg.sidecar_dir / NAME
        repo.mkdir(parents=True)
        for suffix in ("adc", "accel"):
            shutil.copyfile(folder / f"{NAME}.{suffix}.json", repo / f"{NAME}.{suffix}.json")
        before = {s: (folder / f"{NAME}.{s}.json").read_bytes() for s in ("adc", "accel")}
        labels = opened(client)["streams"]["adc_raw"]["labels"]
        moved = edit(client, labels, {"kind": "move", "n": 1, "edge": "end", "i": 4400}).json()["labels"]
        added = edit(client, moved, {"kind": "add", "i0": 6400, "i1": 7000, "label": "noise"}).json()["labels"]

        r = save(client, added)
        res = r.json()
        assert r.status_code == 200 and res["saved"], res
        adc = io.load_sidecar(folder / f"{NAME}.adc.json", SCHEMA)
        acc = io.load_sidecar(folder / f"{NAME}.accel.json", SCHEMA)
        assert len(adc["labels"]) == len(acc["labels"]) == 4
        for a, b in zip(adc["labels"], acc["labels"], strict=True):
            assert {k: a.get(k) for k in ("label", "person", "pace", "shoes", "src")} == {
                k: b.get(k) for k in ("label", "person", "pace", "shoes", "src")
            }
            # the same instant on the device clock: adc frame i is accel frame (i/2000 - 0.1 s) * 2000.4
            for ka in ("i0", "i1"):
                want = min(max(round((a[ka] / RATE - ACCEL_DELAY_US / 1e6) * ACCEL_RATE), 0), 8000)
                assert b[ka] == want, (a, b)
            assert b["t0"] == b["i0"] / acc["sample_rate"] and b["t1"] == b["i1"] / acc["sample_rate"]
        assert map_index(4400, adc, acc, 8000) == round((4400 / RATE - 0.1) * ACCEL_RATE)
        # each sidecar has its .bak, both repo copies follow, the session validates without a sync warning
        for s in ("adc", "accel"):
            assert (folder / f"{NAME}.{s}.json.bak").read_bytes() == before[s]
            assert json.loads((repo / f"{NAME}.{s}.json").read_text()) == io.load_sidecar(folder / f"{NAME}.{s}.json")
        assert res["peer"]["stream"] == "accel" and res["peer"]["labels"] == acc["labels"]
        assert res["repo_copy"]["updated"] and len(res["repo_copy"]["paths"]) == 2
        rep = validate_session_folder(folder, SCHEMA)
        assert rep.ok and not any("label lists differ" in w for w in rep.warnings), rep
        # the page goes on with the new versions of both: a second save works
        assert res["version"] == opened(client)["streams"]["adc_raw"]["version"]
        assert res["peer"]["version"] == opened(client)["streams"]["accel"]["version"]


def test_a_label_already_in_step_keeps_the_other_streams_own_timing(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        own = base_labels()
        own[1]["unc_ms"] = 15.5  # the accel file's own uncertainty of the same live mark
        folder = write_session(cfg.data_root, accel=True)
        js = folder / f"{NAME}.accel.json"
        doc = io.load_sidecar(js)
        doc["labels"] = own
        io.save_sidecar(js, doc, SCHEMA)
        labels = opened(client)["streams"]["adc_raw"]["labels"]
        retag = edit(client, labels, {"kind": "retag", "n": 2, "set": {"pace": "fast"}}).json()["labels"]
        assert save(client, retag).json()["saved"]
        acc = io.load_sidecar(js)["labels"]
        assert acc[1]["unc_ms"] == 15.5  # unchanged label: kept as it was
        assert acc[2]["pace"] == "fast" and acc[2]["unc_ms"] == 40.0  # retagged: follows the edited stream


def test_a_save_needs_both_versions_and_writes_nothing_on_a_stale_one(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root, accel=True)
        labels = opened(client)["streams"]["adc_raw"]["labels"][1:]
        before = {s: (folder / f"{NAME}.{s}.json").read_bytes() for s in ("adc", "accel")}
        r = save(client, labels, peer_version=None)
        assert r.status_code == 422 and "peer_version" in r.json()["error"]["message"]
        r = save(client, labels, peer_version="0" * 16)
        assert r.status_code == 409 and r.json()["error"]["code"] == "changed_on_disk"
        body = {"stream": "adc_raw", "labels": labels}  # no version at all
        assert client.put(f"/api/review/sessions/{NAME}/labels", json=body).status_code == 422
        assert {s: (folder / f"{NAME}.{s}.json").read_bytes() for s in ("adc", "accel")} == before
        assert not list(folder.glob("*.bak"))


def test_a_save_writes_neither_sidecar_when_the_other_one_would_be_invalid(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root, accel=True)
        js = folder / f"{NAME}.accel.json"
        doc = json.loads(js.read_text())
        doc["sample_rate"] = 1000  # the accel WAV header says 2000: the pair no longer checks
        js.write_text(json.dumps(doc))
        before = {s: (folder / f"{NAME}.{s}.json").read_bytes() for s in ("adc", "accel")}
        res = save(client, opened(client)["streams"]["adc_raw"]["labels"][1:]).json()
        assert res["saved"] is False and any(p.startswith(js.name) for p in res["problems"]), res
        assert {s: (folder / f"{NAME}.{s}.json").read_bytes() for s in ("adc", "accel")} == before


def test_rzlab_validate_warns_when_the_two_label_lists_differ(tmp_path):
    folder = write_session(tmp_path, accel=True)
    assert not validate_session_folder(folder, SCHEMA).warnings
    js = folder / f"{NAME}.accel.json"
    doc = io.load_sidecar(js)
    doc["labels"] = doc["labels"][:2]
    io.save_sidecar(js, doc, SCHEMA)
    rep = validate_session_folder(folder, SCHEMA)
    assert rep.ok and any("label lists differ (3 and 2 labels)" in w for w in rep.warnings)
    doc["labels"] = base_labels()
    doc["labels"][2]["person"] = "P1"
    io.save_sidecar(js, doc, SCHEMA)
    assert any("label 2 has other tags" in w for w in validate_session_folder(folder, SCHEMA).warnings)
    lines: list[str] = []
    assert run_validate(tmp_path, SCHEMA, out=lines.append) == 0  # a warning, not a failure
    assert any("label lists differ" in line for line in lines)


# --------------------------------------------------------------------------- decision B: the label list


def test_b_review_refuses_labels_outside_the_protocol_list(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root, accel=True)
        o = opened(client)
        assert o["labels_allowed"] == ["silence", "walk", "noise", "other", "bad"]
        labels = o["streams"]["adc_raw"]["labels"]
        for op in (
            {"kind": "add", "i0": 6500, "i1": 7000, "label": "turn"},
            {"kind": "retag", "n": 0, "set": {"label": "door"}},
        ):
            r = edit(client, labels, op)
            assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_label", r.text
            assert "silence, walk, noise, other, bad" in r.json()["error"]["message"]
        assert edit(client, labels, {"kind": "retag", "n": 0, "set": {"label": "bad"}}).status_code == 200
        bad = [dict(labels[0], label="turn")]
        before = (folder / f"{NAME}.adc.json").read_bytes()
        for path, method in (("labels", client.put), ("check", client.post)):
            o2 = opened(client)["streams"]
            r = method(
                f"/api/review/sessions/{NAME}/{path}",
                json={
                    "stream": "adc_raw",
                    "labels": bad,
                    "version": o2["adc_raw"]["version"],
                    "peer_version": o2["accel"]["version"],
                }
                if path == "labels"
                else {"stream": "adc_raw", "labels": bad},
            )
            assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_label", r.text
        assert (folder / f"{NAME}.adc.json").read_bytes() == before


def test_b_label_form_and_live_marks_accept_only_the_protocol_labels(tmp_path):
    with lab(tmp_path) as (client, _sim, _cfg):
        allowed = ["silence", "walk", "noise", "other", "bad"]
        assert client.get("/api/record/options").json()["labels_allowed"] == allowed
        assert client.get("/api/record/state").json()["labels_allowed"] == allowed
        r = client.put("/api/record/current-label", json={"label": "turn"})  # the label form, before recording
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_label"
        assert client.put("/api/record/current-label", json={"label": "noise"}).status_code == 200
        assert client.post("/api/record/start", json=form()).status_code == 200
        r = client.post("/api/record/mark", json={"edge": "start", "label": "turn"})  # Space with an override
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_label", r.text
        assert "walk" in r.json()["error"]["message"]
        assert client.put("/api/record/current-label", json={"label": "door"}).status_code == 422
        rec = client.app.state.recorder
        rec.label_state = rec.label_state.model_copy(update={"label": "door"})  # as if it had slipped through
        with pytest.raises(MarkRefused) as exc:
            rec.mark_from_phone("start", client.app.state.recorder.mgr.host_us(), 10.0)
        assert exc.value.code == "invalid_label"
        assert client.get("/api/record/labels").json()["labels"] == []  # nothing was opened
        rec.label_state = rec.label_state.model_copy(update={"label": "walk"})
        assert client.post("/api/record/mark", json={"edge": "start"}).status_code == 200
        assert client.post("/api/record/mark", json={"edge": "end"}).status_code == 200
        assert client.post("/api/record/stop").status_code == 200
        wait_idle(client)


# ------------------------------------------------------------------------------------ SD import findings


def card_with_session(tmp_path: Path, accel: bool = True) -> Path:
    card = tmp_path / "card"
    write_session(card, accel=accel)
    return card


def test_a_failed_move_leaves_nothing_in_the_data_root_and_a_retry_imports(tmp_path, monkeypatch):
    """[med] sdimport: an OSError after the target folder exists removes what arrived and the folder."""
    card = card_with_session(tmp_path)
    root, staging = tmp_path / "root", tmp_path / "staging"
    root.mkdir()
    real_move = shutil.move
    calls = {"n": 0}

    def flaky_move(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # the first WAV arrived, the second fails
            raise OSError(28, "No space left on device")
        return real_move(src, dst)

    monkeypatch.setattr(sdimport.shutil, "move", flaky_move)
    res = sdimport.import_sd(card, root, staging, SCHEMA, None)
    assert [r.status for r in res] == ["failed"] and "No space left" in res[0].problems[0]
    assert not (root / NAME).exists() and list(root.iterdir()) == []
    monkeypatch.setattr(sdimport.shutil, "move", real_move)
    res = sdimport.import_sd(card, root, staging, SCHEMA, None)
    assert [r.status for r in res] == ["imported"] and validate_session_folder(root / NAME, SCHEMA).ok


def test_the_import_never_overwrites_sidecars_already_in_the_repository(tmp_path):
    """[med] sdimport: an existing data/<session>/ is left alone and the note says so."""
    card = card_with_session(tmp_path)
    root, repo = tmp_path / "root", tmp_path / "repo-data"
    root.mkdir()
    (repo / NAME).mkdir(parents=True)
    mine = repo / NAME / f"{NAME}.adc.json"
    mine.write_text('{"edited": "by hand"}')
    res = sdimport.import_sd(card, root, tmp_path / "staging", SCHEMA, repo)
    assert res[0].status == "imported" and res[0].sidecars_copied == []
    assert "already has" in (res[0].note or "") and mine.read_text() == '{"edited": "by hand"}'
    assert not (repo / NAME / f"{NAME}.accel.json").exists()


def test_a_simulated_session_from_the_card_is_not_copied_to_the_repository(tmp_path):
    card = card_with_session(tmp_path, accel=False)
    js = card / NAME / f"{NAME}.adc.json"
    doc = io.load_sidecar(js)
    notes = io.parse_rzlab_notes(doc["notes"])
    notes["source"] = "sim"
    doc["notes"] = io.format_rzlab_notes(notes)
    io.save_sidecar(js, doc, SCHEMA)
    root, repo = tmp_path / "root", tmp_path / "repo-data"
    root.mkdir()
    res = sdimport.import_sd(card, root, tmp_path / "staging", SCHEMA, repo)
    assert res[0].status == "imported" and res[0].sidecars_copied == [] and "simulated" in (res[0].note or "")
    assert not (repo / NAME).exists()
    shutil.rmtree(root / NAME)
    res = sdimport.import_sd(card, root, tmp_path / "staging", SCHEMA, repo, copy_sim=True)
    assert len(res[0].sidecars_copied) == 1


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlinks")
def test_links_are_not_followed_by_the_import_or_the_review(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    write_session(elsewhere)
    card = tmp_path / "card"
    card.mkdir()
    (card / NAME).symlink_to(elsewhere / NAME, target_is_directory=True)
    root = tmp_path / "root"
    root.mkdir()
    assert sdimport.import_sd(card, root, tmp_path / "staging", SCHEMA, None) == []
    with review_app(tmp_path / "app") as (client, cfg):
        (cfg.data_root / NAME).symlink_to(elsewhere / NAME, target_is_directory=True)
        assert client.get("/api/review/sessions").json()["sessions"] == []
        assert client.get(f"/api/review/sessions/{NAME}").status_code == 404


def test_a_corrupt_sidecar_is_a_422_not_a_server_error(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root)
        (folder / f"{NAME}.adc.json").write_text("{not json")
        for url in (f"/api/review/sessions/{NAME}", f"/api/review/sessions/{NAME}/envelope"):
            r = client.get(url)
            assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_sidecar", (url, r.text)
        r = client.put(
            f"/api/review/sessions/{NAME}/labels", json={"stream": "adc_raw", "labels": [], "version": "x" * 16}
        )
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_sidecar"


def test_the_sd_import_is_refused_while_recording(tmp_path):
    with review_app(tmp_path) as (client, _cfg):
        card = card_with_session(tmp_path)
        rec = client.app.state.recorder
        rec.state = "recording"
        try:
            r = client.post("/api/review/import-sd", json={"path": str(card)})
        finally:
            rec.state = "idle"
        assert r.status_code == 409 and r.json()["error"]["code"] == "recording_active"
        assert client.post("/api/review/import-sd", json={"path": str(card)}).json()["summary"]["imported"] == 1
