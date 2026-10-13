"""Review page backend (WEB_API.md section 12): sessions, views, label edits, save with .bak and validation."""

from __future__ import annotations

import json
from contextlib import contextmanager

import numpy as np
import pytest
from fastapi.testclient import TestClient
from rec_helpers import PORT, make_cfg
from review_helpers import FRAMES, NAME, RATE, SCHEMA, base_labels, write_session
from rezonating_lab.recorder.review import ReviewError, apply_edit, normalise_labels
from rezonating_lab.recorder.validate import validate_session_folder
from rezonating_lab.server.app import create_app
from rezonating_lab.server.device import DeviceManager
from rezonating_ml import io

PERSONS = ["P1", "P2"]
ALLOWED = ["silence", "walk", "noise", "other", "bad"]  # walk-pass-v1's label list (decision B, 2026-10-13)


@contextmanager
def review_app(tmp_path, **cfg_over):
    cfg = make_cfg(tmp_path, **cfg_over)
    app = create_app(PORT, manager=DeviceManager(embedded_sim=False), static_dir=None, lab_config=cfg)
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as client:
        yield client, cfg


def save_body(client, labels: list[dict], stream: str = "adc_raw") -> dict:
    """A save request naming the versions the page opened (both streams when the session has both)."""
    streams = client.get(f"/api/review/sessions/{NAME}").json()["streams"]
    body = {"stream": stream, "labels": labels, "version": streams[stream]["version"]}
    peer = next((v for k, v in streams.items() if k != stream), None)
    if peer is not None:
        body["peer_version"] = peer["version"]
    return body


def labels0() -> list[dict]:
    return normalise_labels(base_labels(), FRAMES, RATE, PERSONS)


def edit(labels, **op):
    return apply_edit(labels, op, FRAMES, RATE, PERSONS, ALLOWED)


def sidecar_with(labels: list[dict]) -> dict:
    from review_helpers import sidecar

    return sidecar(NAME, labels=labels)


def assert_valid(labels, tmp_path) -> None:
    """The edited list makes a valid sidecar for the synthetic WAV (schema + check_pair)."""
    folder = write_session(tmp_path / "chk")
    problems = io.check_pair(folder / f"{NAME}.adc.wav", sidecar_with(labels), SCHEMA)
    assert problems == []


# ------------------------------------------------------------------------------------------- pure edits


def test_move_split_merge_retag_delete_add_keep_the_sidecar_valid(tmp_path):
    cur = labels0()
    moved = edit(cur, kind="move", n=1, edge="start", i=2900)
    assert (moved[1]["i0"], moved[1]["t0"]) == (2900, 2900 / RATE)
    assert moved[1]["src"] == "key" and "unc_ms" not in moved[1]  # src kept; the live timing no longer applies
    moved = edit(moved, kind="move", n=1, edge="end", i=4100)
    assert moved[1]["i1"] == 4100 and moved[1]["t1"] == 4100 / RATE

    split = edit(cur, kind="split", n=1, i=3500)
    assert [(x["i0"], x["i1"]) for x in split[1:3]] == [(3000, 3500), (3500, 4000)]
    assert all(x["person"] == "P1" and x["pace"] == "normal" and x["src"] == "key" for x in split[1:3])

    merged = edit(split, kind="merge", n=1)
    assert len(merged) == 3 and (merged[1]["i0"], merged[1]["i1"]) == (3000, 4000)

    retag = edit(cur, kind="retag", n=2, set={"person": "P1", "pace": "fast", "shoes": None})
    assert retag[2]["person"] == "P1" and retag[2]["pace"] == "fast" and "shoes" not in retag[2]
    assert retag[2]["unc_ms"] == 40.0 and retag[2]["src"] == "phone"  # a retag keeps the timing

    deleted = edit(cur, kind="delete", n=0)
    assert [x["label"] for x in deleted] == ["walk", "walk"]

    added = edit(cur, kind="add", i0=6500, i1=7000, label="noise", person="P2")
    assert added[-1] == {
        "t0": 3.25,
        "t1": 3.5,
        "i0": 6500,
        "i1": 7000,
        "src": "review",
        "label": "noise",
        "person": "P2",
    }
    added = edit(cur, kind="add", i0=100, i1=200, label="other")
    assert [x["i0"] for x in added] == sorted(x["i0"] for x in added)  # kept in order

    for result in (moved, split, merged, retag, deleted, added):
        assert_valid(result, tmp_path)


@pytest.mark.parametrize(
    "op, code",
    [
        ({"kind": "move", "n": 1, "edge": "end", "i": FRAMES + 1}, "out_of_bounds"),
        ({"kind": "move", "n": 1, "edge": "start", "i": -1}, "out_of_bounds"),
        ({"kind": "move", "n": 1, "edge": "start", "i": 4001}, "bad_edit"),  # past its own end
        ({"kind": "add", "i0": 7000, "i1": FRAMES + 5, "label": "walk"}, "out_of_bounds"),
        ({"kind": "add", "i0": 700, "i1": 600, "label": "walk"}, "bad_edit"),
        ({"kind": "split", "n": 1, "i": 3000}, "bad_edit"),  # on an edge, not inside
        ({"kind": "merge", "n": 2}, "bad_edit"),  # no next neighbour
        ({"kind": "delete", "n": 9}, "bad_edit"),
        ({"kind": "retag", "n": 0, "set": {"person": "Anna"}}, "invalid_label"),
        ({"kind": "retag", "n": 0, "set": {"person": "P7"}}, "invalid_label"),  # not a person of the session
        ({"kind": "retag", "n": 0, "set": {"label": None}}, "invalid_label"),
        ({"kind": "retag", "n": 0, "set": {"pace": "run"}}, "invalid_label"),
        ({"kind": "explode", "n": 0}, "bad_edit"),
    ],
)
def test_bad_edits_are_refused(op, code):
    with pytest.raises(ReviewError) as e:
        edit(labels0(), **op)
    assert e.value.code == code


def test_incoming_labels_are_checked():
    bad = labels0()
    bad[0]["i1"] = FRAMES + 1
    with pytest.raises(ReviewError) as e:
        normalise_labels(bad, FRAMES, RATE, PERSONS)
    assert e.value.code == "out_of_bounds"
    with pytest.raises(ReviewError):
        normalise_labels([{**labels0()[0], "t0": 0, "extra": 1}], FRAMES, RATE, PERSONS)
    with pytest.raises(ReviewError):
        normalise_labels([{**labels0()[0], "i0": 1.5}], FRAMES, RATE, PERSONS)
    # t0/t1 come from the indices, whatever the browser sent
    fixed = normalise_labels([{**labels0()[1], "t0": 99.0}], FRAMES, RATE, PERSONS)
    assert fixed[0]["t0"] == 3000 / RATE


# --------------------------------------------------------------------------------------------- the API


def test_sessions_open_envelope_and_spectrogram(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        write_session(cfg.data_root, accel=True)
        (cfg.data_root / "2026-10-12_home-a_kitchen_02").mkdir()  # an empty reservation is not listed
        r = client.get("/api/review/sessions")
        assert r.status_code == 200, r.text
        sessions = r.json()["sessions"]
        assert [s["name"] for s in sessions] == [NAME]
        assert {s["stream"] for s in sessions[0]["streams"]} == {"adc_raw", "accel"}
        assert sessions[0]["streams"][0]["duration_s"] == FRAMES / RATE

        s = client.get(f"/api/review/sessions/{NAME}").json()
        adc = s["streams"]["adc_raw"]
        assert adc["frames"] == FRAMES and adc["sample_rate"] == RATE and len(adc["labels"]) == 3
        assert s["persons"] == PERSONS and len(adc["version"]) == 16

        env = client.get(f"/api/review/sessions/{NAME}/envelope", params={"columns": 100}).json()
        assert env["edges"][0] == 0 and env["edges"][-1] == FRAMES and len(env["min"][0]) == 100
        scale = adc["channels"][0]["scale"]
        assert max(env["max"][0]) == pytest.approx(1e6 * scale, rel=1e-3)  # the 50 Hz sine's peak in units
        zoom = client.get(
            f"/api/review/sessions/{NAME}/envelope", params={"i0": 1000, "i1": 1100, "columns": 400}
        ).json()
        assert zoom["edges"][0] == 1000 and len(zoom["min"][0]) == 100  # one column per sample when zoomed in

        sg = client.get(f"/api/review/sessions/{NAME}/spectrogram", params={"ch": 0, "columns": 50}).json()
        assert len(sg["power_db"]) <= 50
        peak = sg["freq_hz"][int(np.argmax(sg["power_db"][3]))]
        assert abs(peak - 50.0) <= RATE / sg["nfft"]  # the sine is where it should be

        for url, code in (
            (f"/api/review/sessions/{NAME}/envelope?i0=0&i1={FRAMES + 1}", "out_of_bounds"),
            (f"/api/review/sessions/{NAME}/spectrogram?ch=5", "invalid_request"),
            ("/api/review/sessions/..%2F..%2Fetc", "not_found"),
            ("/api/review/sessions/2026-01-01_x_y_01", "not_found"),
        ):
            r = client.get(url)
            assert r.status_code in (404, 422), (url, r.text)
            assert r.json()["error"]["code"] in (code, "invalid_request", "not_found"), url


def test_edit_endpoint_and_bounds(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        write_session(cfg.data_root)
        labels = client.get(f"/api/review/sessions/{NAME}").json()["streams"]["adc_raw"]["labels"]
        r = client.post(
            f"/api/review/sessions/{NAME}/edit",
            json={"stream": "adc_raw", "labels": labels, "op": {"kind": "split", "n": 1, "i": 3500}},
        )
        assert r.status_code == 200 and len(r.json()["labels"]) == 4
        r = client.post(
            f"/api/review/sessions/{NAME}/edit",
            json={"stream": "adc_raw", "labels": labels, "op": {"kind": "move", "n": 2, "edge": "end", "i": 10**7}},
        )
        assert r.status_code == 422 and r.json()["error"]["code"] == "out_of_bounds"


def test_save_keeps_a_backup_validates_and_updates_the_repo_copy(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root, accel=True)
        repo_copy = cfg.sidecar_dir / NAME
        repo_copy.mkdir(parents=True)
        js = folder / f"{NAME}.adc.json"
        (repo_copy / js.name).write_bytes(js.read_bytes())
        before = js.read_bytes()
        opened = client.get(f"/api/review/sessions/{NAME}").json()
        labels = opened["streams"]["adc_raw"]["labels"]
        edited = client.post(
            f"/api/review/sessions/{NAME}/edit",
            json={"stream": "adc_raw", "labels": labels, "op": {"kind": "delete", "n": 0}},
        ).json()["labels"]

        r = client.put(
            f"/api/review/sessions/{NAME}/labels",
            json={
                "stream": "adc_raw",
                "labels": edited,
                "version": opened["streams"]["adc_raw"]["version"],
                "peer_version": opened["streams"]["accel"]["version"],
            },
        )
        res = r.json()
        assert r.status_code == 200 and res["saved"] and res["problems"] == [], res
        assert res["validation"]["ok"], res["validation"]
        assert res["repo_copy"]["updated"] is True
        assert (folder / f"{js.name}.bak").read_bytes() == before
        saved = io.load_sidecar(js, SCHEMA)
        assert [x["label"] for x in saved["labels"]] == ["walk", "walk"]
        assert json.loads((repo_copy / js.name).read_text())["labels"] == saved["labels"]
        assert validate_session_folder(folder, SCHEMA).ok  # rzlab validate accepts the .bak next to its sidecar
        assert {k: v for k, v in saved.items() if k != "labels"} == {
            k: v for k, v in json.loads(before).items() if k != "labels"
        }  # only the labels changed

        # a stale version is refused: nothing written
        r = client.put(
            f"/api/review/sessions/{NAME}/labels",
            json={
                "stream": "adc_raw",
                "labels": labels,
                "version": opened["streams"]["adc_raw"]["version"],
                "peer_version": opened["streams"]["accel"]["version"],
            },
        )
        assert r.status_code == 409 and r.json()["error"]["code"] == "changed_on_disk"
        # out of bounds: refused before anything is written
        bad = [dict(edited[0], i1=FRAMES + 10)]
        now = client.get(f"/api/review/sessions/{NAME}").json()["streams"]
        r = client.put(
            f"/api/review/sessions/{NAME}/labels",
            json={
                "stream": "adc_raw",
                "labels": bad,
                "version": now["adc_raw"]["version"],
                "peer_version": now["accel"]["version"],
            },
        )
        assert r.status_code == 422 and r.json()["error"]["code"] == "out_of_bounds"
        assert io.load_sidecar(js)["labels"] == saved["labels"]


def test_save_refuses_an_invalid_sidecar_and_leaves_the_repo_copy(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root)
        js = folder / f"{NAME}.adc.json"
        before = js.read_bytes()
        no_src = [{k: v for k, v in labels0()[1].items() if k != "src"}]  # v1 requires src on every label
        r = client.put(f"/api/review/sessions/{NAME}/labels", json=save_body(client, no_src))
        res = r.json()
        assert r.status_code == 200 and res["saved"] is False
        assert any("src" in p for p in res["problems"]) and any("tools/validate.py" in p for p in res["problems"])
        assert js.read_bytes() == before and not (folder / f"{js.name}.bak").exists()


def test_save_does_not_update_the_repo_copy_when_the_session_fails(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root)
        (cfg.sidecar_dir / NAME).mkdir(parents=True)
        (folder / "stray.txt").write_text("x")  # the session folder fails rzlab validate
        r = client.put(f"/api/review/sessions/{NAME}/labels", json=save_body(client, labels0()[:1]))
        res = r.json()
        assert res["saved"] is True and res["validation"]["ok"] is False
        assert res["repo_copy"]["updated"] is False and not list((cfg.sidecar_dir / NAME).iterdir())


def test_review_needs_a_data_root(tmp_path):
    with review_app(tmp_path, data_root=None, data_root_source=None) as (client, _cfg):
        r = client.get("/api/review/sessions")
        assert r.status_code == 409 and r.json()["error"]["code"] == "no_data_root"
