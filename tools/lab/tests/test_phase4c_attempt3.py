"""Phase 4c, attempt 3: the verifier's findings on the Review sync (small edits, pair writes, labels outside the other
file, the clock), the SD import's sidecar copy, and labels outside the protocol's list (decision B)."""

from __future__ import annotations

import json
import shutil

import pytest
from rec_helpers import REPO
from review_helpers import NAME, SCHEMA, base_labels, write_session
from rezonating_lab.recorder import review, sdimport
from rezonating_lab.recorder.validate import run_validate, validate_session_folder
from rezonating_ml import io
from test_review_sync import edit, opened, review_app, save, shift_accel

TAGS = ("label", "person", "pace", "shoes", "src")


def _set_labels(folder, suffix: str, labels: list[dict]) -> None:
    js = folder / f"{NAME}.{suffix}.json"
    doc = io.load_sidecar(js)
    doc["labels"] = labels
    io.save_sidecar(js, doc, SCHEMA)


# ------------------------------------------------------------------------------- decision A: small edits


def test_an_edge_moved_by_fewer_than_20_samples_reaches_the_other_stream(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root, accel=True)  # same clock start and rate: the mapping is the identity
        acc_labels = base_labels()
        acc_labels[0]["unc_ms"] = 99.0  # the accel file's own timing of the untouched label
        _set_labels(folder, "accel", acc_labels)
        labels = opened(client)["streams"]["adc_raw"]["labels"]
        labels = edit(client, labels, {"kind": "move", "n": 1, "edge": "end", "i": 4015}).json()["labels"]
        labels = edit(client, labels, {"kind": "move", "n": 2, "edge": "start", "i": 4985}).json()["labels"]
        r = save(client, labels)
        assert r.status_code == 200 and r.json()["saved"], r.text
        acc = io.load_sidecar(folder / f"{NAME}.accel.json", SCHEMA)["labels"]
        assert [(x["i0"], x["i1"]) for x in acc] == [(0, 2000), (3000, 4015), (4985, 6000)]
        assert acc[0]["unc_ms"] == 99.0  # unchanged: the accel label is kept as it was
        assert "unc_ms" not in acc[1] and "unc_ms" not in acc[2]  # moved: the live timing no longer applies
        assert [{k: x.get(k) for k in TAGS} for x in acc] == [{k: x.get(k) for k in TAGS} for x in labels]


def test_a_label_entirely_outside_the_other_file_is_dropped_with_a_warning(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root, accel=True)
        js = folder / f"{NAME}.accel.json"
        doc = io.load_sidecar(js)
        doc["t_dev_us"] += 1_200_000  # accel starts 1.2 s later: adc label 0 (0 to 1 s) lies before it
        io.save_sidecar(js, doc, SCHEMA)
        r = save(client, opened(client)["streams"]["adc_raw"]["labels"])
        res = r.json()
        assert r.status_code == 200 and res["saved"], res
        acc = io.load_sidecar(js, SCHEMA)["labels"]
        assert len(acc) == 2 and all(x["i1"] > x["i0"] for x in acc)
        assert res["peer"]["labels_dropped"] == 1
        assert any("labels_dropped" in w and "outside" in w for w in res["warnings"])


def test_the_sync_requires_the_measured_rate():
    doc = {"sample_rate": 2000, "t_dev_us": 0}
    with pytest.raises(review.ReviewError) as exc:
        review.map_index(10, doc, doc, 100)
    assert exc.value.code == "invalid_sidecar" and "sample_rate_measured" in exc.value.message


# ---------------------------------------------------------------------------------- the pair write


def test_a_failed_second_write_puts_the_first_sidecar_back(tmp_path, monkeypatch):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root, accel=True)
        shift_accel(folder)
        before = {s: (folder / f"{NAME}.{s}.json").read_bytes() for s in ("adc", "accel")}
        labels = opened(client)["streams"]["adc_raw"]["labels"]
        labels = edit(client, labels, {"kind": "move", "n": 1, "edge": "end", "i": 4400}).json()["labels"]
        real = io.save_sidecar
        calls = []

        def flaky(path, doc, schema):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("disk full")
            real(path, doc, schema)

        monkeypatch.setattr(review.io, "save_sidecar", flaky)
        r = save(client, labels)
        assert r.status_code == 500, r.text
        err = r.json()["error"]
        assert err["code"] == "write_failed"
        assert "unchanged" in err["message"] and "put back" in err["message"]
        for s in ("adc", "accel"):
            assert (folder / f"{NAME}.{s}.json").read_bytes() == before[s], s


def test_a_failed_second_repo_copy_puts_the_first_back(tmp_path, monkeypatch):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root, accel=True)
        shift_accel(folder)
        repo = cfg.sidecar_dir / NAME
        repo.mkdir(parents=True)
        for s in ("adc", "accel"):
            shutil.copyfile(folder / f"{NAME}.{s}.json", repo / f"{NAME}.{s}.json")
        before = {p.name: p.read_bytes() for p in repo.iterdir()}
        labels = opened(client)["streams"]["adc_raw"]["labels"]
        labels = edit(client, labels, {"kind": "move", "n": 1, "edge": "end", "i": 4400}).json()["labels"]
        real = review._atomic_copy
        n = {"repo": 0}

        def flaky(src, dest):
            if dest.parent == repo:
                n["repo"] += 1
                if n["repo"] == 2:
                    raise OSError("no space")
            real(src, dest)

        monkeypatch.setattr(review, "_atomic_copy", flaky)
        res = save(client, labels).json()
        assert res["saved"] and not res["repo_copy"]["updated"], res
        assert "failed" in res["repo_copy"]["reason"] and "put back" in res["repo_copy"]["reason"]
        assert {p.name: p.read_bytes() for p in repo.iterdir()} == before


# --------------------------------------------------------------------------------------- SD import


def test_a_failed_sidecar_copy_is_a_note_not_a_failed_import(tmp_path, monkeypatch):
    card, root, staging, data = (tmp_path / d for d in ("card", "root", "staging", "data"))
    for d in (card, root, data):
        d.mkdir()
    write_session(card)
    real = shutil.copyfile

    def flaky(src, dst, *a, **k):
        if str(dst).startswith(str(data)):
            raise OSError("read-only repository")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(sdimport.shutil, "copyfile", flaky)
    [res] = sdimport.import_sd(card, root, staging, SCHEMA, data)
    assert res.status == "imported" and (root / NAME / f"{NAME}.adc.json").is_file()
    assert "copying its sidecars to the repository failed" in (res.note or "")
    assert not (data / NAME).exists()  # the partial data/<session>/ is gone


# --------------------------------------------------------------------------- decision B: off-list labels


def _off_list_session(parent):
    folder = write_session(parent)
    labels = base_labels()
    labels[1]["label"] = "turn"  # not in walk-pass-v1's list (silence, walk + noise, other, bad)
    _set_labels(folder, "adc", labels)
    return folder


def test_validate_and_sd_import_warn_on_off_list_labels(tmp_path):
    card, root, staging = (tmp_path / d for d in ("card", "root", "staging"))
    for d in (card, root):
        d.mkdir()
    folder = _off_list_session(card)
    rep = validate_session_folder(folder, SCHEMA, repo_root=REPO)
    assert rep.ok and any("'turn' (1)" in w and "walk-pass-v1" in w for w in rep.warnings), rep
    assert not any("'turn'" in w for w in validate_session_folder(folder, SCHEMA).warnings)  # no checkout: no check
    lines: list[str] = []
    assert run_validate(card, SCHEMA, out=lines.append, repo_root=REPO) == 0  # a warning, not a failure
    assert any(ln.strip().startswith("warning:") and "'turn'" in ln for ln in lines), lines
    [res] = sdimport.import_sd(card, root, staging, SCHEMA, None, repo_root=REPO)
    assert res.status == "imported" and any("'turn'" in w for w in res.warnings)
    assert "warnings" in res.to_dict()


def test_review_marks_off_list_labels_and_save_needs_them_retagged(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        _off_list_session(cfg.data_root)
        st = opened(client)["streams"]["adc_raw"]
        assert st["labels_off_list"] == [1]
        r = save(client, st["labels"])
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_label"
        fixed = edit(client, st["labels"], {"kind": "retag", "n": 1, "set": {"label": "walk"}}).json()["labels"]
        assert save(client, fixed).json()["saved"]
        assert opened(client)["streams"]["adc_raw"]["labels_off_list"] == []


def test_a_protocol_without_yaml_offers_the_shared_labels(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        folder = write_session(cfg.data_root)
        js = folder / f"{NAME}.adc.json"
        doc = io.load_sidecar(js)
        doc["protocol"] = "kill-test-phone"  # only a .md exists: no YAML label list
        io.save_sidecar(js, doc, SCHEMA)
        o = opened(client)
        assert o["labels_allowed"] == ["noise", "other", "bad"] and "kill-test-phone" in o["labels_note"]
        labels = o["streams"]["adc_raw"]["labels"]
        assert o["streams"]["adc_raw"]["labels_off_list"] == [0, 1, 2]  # silence and walk are not shared labels
        r = edit(client, labels, {"kind": "add", "i0": 1, "i1": 2, "label": "walk"})
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_label"
        r = edit(client, labels, {"kind": "add", "i0": 6500, "i1": 7000, "label": "noise"})
        assert r.status_code == 200, r.text
        retagged = r.json()["labels"]
        for n in range(3):
            retagged = edit(client, retagged, {"kind": "retag", "n": n, "set": {"label": "other"}}).json()["labels"]
        res = save(client, retagged).json()
        assert res["saved"], res
        assert json.loads(js.read_text())["labels"][0]["label"] == "other"
