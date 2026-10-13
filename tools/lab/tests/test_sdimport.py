"""SD import (WEB_API.md 12.6, ``rzlab import-sd``): synthetic SD folders written with ``rezonating_ml.io``."""

from __future__ import annotations

import json

from rec_helpers import make_cfg
from review_helpers import NAME, SCHEMA, write_session
from rezonating_lab import cli
from rezonating_lab.recorder.sdimport import find_session_folders, import_sd, summary
from test_review import review_app

OTHER = "2026-10-12_home-a_kitchen_02"
BROKEN = "2026-10-12_home-a_kitchen_03"


def make_card(tmp_path):
    """A card with three sessions under DCIM/: good (adc+accel), good (adc), broken (WAV without its sidecar)."""
    card = tmp_path / "sd"
    write_session(card / "RZ", NAME, accel=True)
    write_session(card / "RZ", OTHER, seed=2)
    broken = write_session(card / "RZ" / "old", BROKEN, seed=3)
    (broken / f"{BROKEN}.adc.json").unlink()
    (card / "RZ" / "readme.txt").write_text("not a session")
    return card


def test_import_imported_skipped_invalid(tmp_path):
    cfg = make_cfg(tmp_path)
    card = make_card(tmp_path)
    assert {p.name for p in find_session_folders(card)} == {NAME, OTHER, BROKEN}
    write_session(cfg.data_root, OTHER, seed=9)  # already in the data root: never overwritten
    kept = (cfg.data_root / OTHER / f"{OTHER}.adc.wav").read_bytes()

    results = {r.session: r for r in import_sd(card, cfg.data_root, cfg.staging_dir, SCHEMA, cfg.sidecar_dir)}
    assert results[NAME].status == "imported"
    assert results[OTHER].status == "skipped"
    assert results[BROKEN].status == "invalid" and any("no sidecar" in p for p in results[BROKEN].problems)
    assert summary(list(results.values())) == {"imported": 1, "skipped": 1, "invalid": 1, "failed": 0}

    target = cfg.data_root / NAME
    assert sorted(p.name for p in target.iterdir()) == sorted(
        f"{NAME}.{s}.{e}" for s in ("adc", "accel") for e in ("wav", "json")
    )
    assert (target / f"{NAME}.adc.wav").read_bytes() == (card / "RZ" / NAME / f"{NAME}.adc.wav").read_bytes()
    assert (cfg.data_root / OTHER / f"{OTHER}.adc.wav").read_bytes() == kept
    assert not (cfg.data_root / BROKEN).exists()
    # only validated sidecars reach the repository's data/, never a WAV
    assert sorted(p.name for p in (cfg.sidecar_dir / NAME).iterdir()) == [f"{NAME}.accel.json", f"{NAME}.adc.json"]
    assert not (cfg.sidecar_dir / BROKEN).exists() and not (cfg.sidecar_dir / OTHER).exists()
    assert not any(cfg.staging_dir.iterdir())  # staging is cleaned up

    again = import_sd(card, cfg.data_root, cfg.staging_dir, SCHEMA, cfg.sidecar_dir)
    assert {r.session: r.status for r in again}[NAME] == "skipped"


def test_a_schema_invalid_sidecar_is_not_imported(tmp_path):
    cfg = make_cfg(tmp_path)
    folder = write_session(tmp_path / "sd", NAME)
    js = folder / f"{NAME}.adc.json"
    doc = json.loads(js.read_text())
    doc["labels"][0]["person"] = "Anna"  # a name, not a pseudonym
    js.write_text(json.dumps(doc))
    (r,) = import_sd(tmp_path / "sd", cfg.data_root, cfg.staging_dir, SCHEMA, cfg.sidecar_dir)
    assert r.status == "invalid" and any("person" in p for p in r.problems)
    assert not (cfg.data_root / NAME).exists() and not (cfg.sidecar_dir / NAME).exists()


def test_the_folder_may_be_one_session(tmp_path):
    cfg = make_cfg(tmp_path)
    folder = write_session(tmp_path / "sd", NAME)
    (r,) = import_sd(folder, cfg.data_root, cfg.staging_dir, SCHEMA, None)
    assert r.status == "imported" and "sidecar_dir" in (r.note or "")


def test_cli_import_sd(tmp_path, monkeypatch, capsys):
    cfg = make_cfg(tmp_path)
    card = make_card(tmp_path)
    monkeypatch.setenv("RZ_DATA_ROOT", str(cfg.data_root))
    monkeypatch.setenv("RZ_STAGING_DIR", str(cfg.staging_dir))
    monkeypatch.setenv("RZ_SIDECAR_DIR", str(cfg.sidecar_dir))
    monkeypatch.setenv("RZ_CONFIG", str(tmp_path / "none.toml"))
    rc = cli.main(["import-sd", str(card)])
    out = capsys.readouterr().out
    assert rc == 1  # one session was invalid
    assert f"imported {NAME}" in out and f"invalid  {BROKEN}" in out and "2 imported" in out
    assert cli.main(["import-sd", str(tmp_path / "missing")]) == 2


def test_import_endpoint(tmp_path):
    with review_app(tmp_path) as (client, cfg):
        card = make_card(tmp_path)
        r = client.post("/api/review/import-sd", json={"path": str(card)})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["summary"] == {"imported": 2, "skipped": 0, "invalid": 1, "failed": 0}
        assert {x["session"]: x["status"] for x in body["results"]}[BROKEN] == "invalid"
        assert NAME in [s["name"] for s in client.get("/api/review/sessions").json()["sessions"]]
        r = client.post("/api/review/import-sd", json={"path": "relative/path"})
        assert r.status_code == 422
        r = client.post("/api/review/import-sd", json={"path": str(tmp_path / "nope")})
        assert r.status_code == 404
        r = client.post("/api/review/import-sd", json={"path": str(cfg.data_root)})
        assert r.status_code == 422  # the data root itself is not a card
