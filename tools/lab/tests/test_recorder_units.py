"""Recorder building blocks without a node: time maps, form validation, session names, data root, sidecars, validate."""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from rec_helpers import FORM, REPO, form, make_cfg
from rezonating_lab.core.timing import ClockMap, fit_stream_rate, index_at_time
from rezonating_lab.recorder import config as rconfig
from rezonating_lab.recorder.forms import LabelState, SessionForm, list_protocols
from rezonating_lab.recorder.naming import SessionNameError, reserve_session, session_name, slugify
from rezonating_lab.recorder.sidecars import SensorProblem, channel_entries, measured_rate
from rezonating_lab.recorder.validate import run_validate, validate_root, validate_session_folder
from rezonating_ml import io

SCHEMA = REPO / "schemas" / "sidecar.schema.json"


# ---------------------------------------------------------------------------------------- time maps


def test_fit_stream_rate_recovers_rate_and_origin():
    rate = 2015.97
    first = np.arange(0, 200_000, 80, dtype=np.int64)
    t = (5_000_000 + first * 1e6 / rate).astype(np.int64)
    got_rate, t0 = fit_stream_rate(first, t)
    assert got_rate == pytest.approx(rate, rel=1e-6) and t0 == pytest.approx(5_000_000, abs=2)
    assert fit_stream_rate(first[:1], t[:1]) is None


def test_index_at_time_inside_and_extrapolated():
    rate = 2016.0
    first = np.arange(0, 100_000, 80, dtype=np.int64)
    t = (1_000_000 + first * 1e6 / rate).astype(np.int64)
    for idx in (5000.0, 77_777.0, 99_999.0):
        t_us = 1_000_000 + idx * 1e6 / rate
        assert index_at_time(first, t, t_us) == pytest.approx(idx, abs=0.2)
    t_us = 1_000_000 + 100_200 * 1e6 / rate  # a little beyond the last packet
    assert index_at_time(first, t, t_us) == pytest.approx(100_200, abs=0.5)
    assert index_at_time(first[:1], t[:1], 1e6) is None


def test_clock_map_follows_offset_and_drift_and_ignores_slow_replies():
    cm = ClockMap()
    rng = np.random.default_rng(3)
    for k in range(60):  # one PONG per 0.5 s for 30 s; the node clock runs 50 ppm fast, offset 7 s
        host = 1e6 * (100 + 0.5 * k)
        offset = 7e6 + 50e-6 * (host - 100e6)
        rtt = 800.0 + (6000.0 if k % 7 == 0 else float(rng.uniform(0, 300)))  # some replies are slow
        cm.add(host, host + rtt, host + rtt / 2 + offset)
    for host in (105e6, 112.3e6, 120e6):
        est = cm.offset_at(host)
        true = 7e6 + 50e-6 * (host - 100e6)
        assert est is not None and est.offset_us == pytest.approx(true, abs=150)
        assert 350 <= est.unc_us <= 700  # half the best round trip
    assert ClockMap().offset_at(1e6) is None


def test_measured_rate_fallbacks():
    first = np.arange(0, 8000, 80, dtype=np.int64)
    t = (2_000_000 + first * 500.0).astype(np.int64)
    rate, source, t_base = measured_rate(first, t, 2001.0, 2000.0, 0)
    assert source == "fit" and rate == pytest.approx(2000.0) and t_base == 2_000_000
    rate, source, _ = measured_rate(first[:1], t[:1], 2001.0, 2000.0, 0)
    assert (rate, source) == (2001.0, "status")
    rate, source, _ = measured_rate(first[:0], t[:0], None, 2000.0, 0)
    assert (rate, source) == (2000.0, "nominal")


# ------------------------------------------------------------------------------------------- forms


@pytest.mark.parametrize("bad", ["Alice", "p1", "P", "P1 ", "P-1", "Pe1", "", "P1;P2", "Kaszti Benedek"])
def test_persons_must_be_pseudonyms(bad):
    with pytest.raises(ValidationError) as exc:
        SessionForm(**form(persons=[bad]))
    if len(bad) > 3:
        assert bad not in str(exc.value.errors()[0]["msg"])  # the rejected text is not echoed
    with pytest.raises(ValidationError):
        LabelState(person=bad)


def test_valid_form_and_duplicates():
    f = SessionForm(**FORM)
    assert f.persons == ["P1", "P2"] and f.protocol == "walk-pass-v1"
    with pytest.raises(ValidationError):
        SessionForm(**form(persons=["P1", "P1"]))
    with pytest.raises(ValidationError):
        SessionForm(**form(site="!!!"))
    with pytest.raises(ValidationError):
        SessionForm(**form(notes="fine\nrzlab: loss=none"))
    with pytest.raises(ValidationError):
        SessionForm(**form(floor="a;b"))
    with pytest.raises(ValidationError):
        SessionForm(**form(streams=["adc_dec"]))  # adc_dec is not recorded (D-020)
    with pytest.raises(ValidationError):
        SessionForm(**form(unknown_field=1))


def test_protocols_listed_from_docs():
    names = list_protocols(REPO)
    assert names[0] == "walk-pass-v1"
    assert "kill-test-phone" not in names  # the kill test was dropped: only machine-readable protocols are offered
    assert (REPO / "docs" / "protocols" / "kill-test-phone.md").is_file()  # its write-up stays in docs
    assert list_protocols(None) == ["walk-pass-v1"]


def test_channel_entries_need_positions_and_use_node_values():
    stream = {
        "id": 0,
        "name": "adc_raw",
        "n_ch": 2,
        "nominal_hz": 2000,
        "clock": "ltc6903",
        "channels": [{"gain": 8, "scale": 1.5e-8, "units": "V"}, {"gain": 8, "scale": 1.5e-8, "units": "V"}],
    }
    heads = [{"port": 1, "descriptor": {"type": "geophone", "model": "sm24", "serial": "G-1", "mount": "spike"}}]
    entries = channel_entries(stream, SessionForm(**FORM), heads)
    assert entries[0]["head"] == "geophone/sm24" and entries[0]["port"] == 1 and entries[0]["mount"] == "spike"
    assert entries[1]["head"] == "unknown" and entries[1]["position_m"] == [2.0, 0.0]
    assert (
        entries[0]["units"] == "V" and entries[0]["gain"] == 8 and entries[0]["surface"] == "laminate on concrete slab"
    )
    with pytest.raises(SensorProblem) as exc:
        channel_entries(stream, SessionForm(**form(sensors=[FORM["sensors"][0]])), heads)
    assert "channel 1" in exc.value.details[0]["msg"]


# ------------------------------------------------------------------------------------------ names


def test_slugify_and_session_name_match_the_schema_pattern():
    assert slugify("Home A") == "home-a" and slugify("Konyha / Élő szoba") == "konyha-elo-szoba"
    assert slugify("???") == ""
    name = session_name(date(2026, 11, 17), "home-a", "kitchen", 3)
    assert name == "2026-11-17_home-a_kitchen_03" and io.SESSION_RE.match(name)
    with pytest.raises(SessionNameError):
        session_name(date(2026, 11, 17), "a", "b", 100)


def test_reserve_session_takes_next_nn_and_race_gives_unique_names(tmp_path: Path):
    root, staging = tmp_path / "root", tmp_path / "stg"
    root.mkdir()
    day = date(2026, 11, 17)
    first = reserve_session(root, staging, day, "home-a", "kitchen")
    assert first[0].endswith("_01") and first[1].is_dir() and first[2].is_dir()
    assert reserve_session(root, staging, day, "home-a", "kitchen")[0].endswith("_02")
    # a stale staging folder blocks its nn without losing the data in it, and the data-root folder is released
    (staging / "2026-11-17_home-a_kitchen_03").mkdir()
    got = reserve_session(root, staging, day, "home-a", "kitchen")
    assert got[0].endswith("_04") and not (root / "2026-11-17_home-a_kitchen_03").exists()

    n = 12
    names: list[str] = []
    barrier = threading.Barrier(n)

    def worker():
        barrier.wait()
        names.append(reserve_session(root, staging, day, "lab", "bench")[0])

    threads = [threading.Thread(target=worker) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(names) == [f"2026-11-17_lab_bench_{i:02d}" for i in range(1, n + 1)]


def test_reserve_session_runs_out_at_99(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    for i in range(1, 100):
        (root / f"2026-11-17_a_b_{i:02d}").mkdir()
    with pytest.raises(SessionNameError):
        reserve_session(root, tmp_path / "stg", date(2026, 11, 17), "a", "b")


# ------------------------------------------------------------------------------------- data root


def test_data_root_not_configured_is_a_clear_error(tmp_path: Path):
    st = rconfig.check_data_root(make_cfg(tmp_path, data_root=None, data_root_source=None))
    assert not st.ok and st.error_code == "no_data_root" and "RZ_DATA_ROOT" in (st.message or "")
    assert st.to_dict()["error"]["code"] == "no_data_root" and st.to_dict()["configured"] is False


def test_data_root_inside_the_repo_is_refused(tmp_path: Path):
    for inside in (REPO / "data", REPO / "scratch" / "nope-not-yet", REPO):
        st = rconfig.check_data_root(make_cfg(tmp_path, data_root=inside))
        assert not st.ok and st.error_code == "data_root_in_repo", inside
    assert rconfig.check_data_root(make_cfg(tmp_path)).ok  # a folder outside the repo is fine


def test_data_root_other_problems(tmp_path: Path):
    assert (
        rconfig.check_data_root(make_cfg(tmp_path, data_root=Path("relative/dir"))).error_code == "data_root_relative"
    )
    assert rconfig.check_data_root(make_cfg(tmp_path, data_root=tmp_path / "missing")).error_code == "data_root_missing"
    assert not (tmp_path / "missing").exists()  # never created


def test_env_wins_over_config_file_and_save_keeps_other_keys(tmp_path: Path):
    cfg_file = tmp_path / "c.toml"
    cfg_file.write_text('data_root = "D:\\\\from-file"\nmarker_port = 8766\n', encoding="utf-8")
    env = {"RZ_CONFIG": str(cfg_file), "RZ_DATA_ROOT": str(tmp_path / "from-env"), "RZ_REPO_ROOT": str(REPO)}
    cfg = rconfig.load_config(env)
    assert cfg.data_root == tmp_path / "from-env" and cfg.data_root_source == "env" and cfg.marker_port == 8766
    cfg = rconfig.load_config({"RZ_CONFIG": str(cfg_file), "RZ_REPO_ROOT": str(REPO)})
    assert cfg.data_root == Path("D:\\from-file") and cfg.data_root_source == "config"
    assert cfg.sidecar_dir == REPO / "data" and not cfg.copy_sim_sidecars and cfg.marker_bind == "auto"
    good = tmp_path / "newroot"
    good.mkdir()
    rconfig.save_data_root(cfg, str(good))
    again = rconfig.load_config({"RZ_CONFIG": str(cfg_file), "RZ_REPO_ROOT": str(REPO)})
    assert again.data_root == good and again.marker_port == 8766
    with pytest.raises(rconfig.ConfigError) as exc:
        rconfig.save_data_root(cfg, str(REPO / "data"))
    assert exc.value.code == "data_root_in_repo"


# -------------------------------------------------------------------------------------- validate


def write_session(root: Path, name: str = "2026-11-17_home-a_kitchen_01", frames: int = 4000) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    for stream, suffix, n_ch in (("adc_raw", "adc", 2), ("accel", "accel", 3)):
        doc = json.loads((REPO / "schemas" / "examples" / "sidecar.walk-pass-v1.json").read_text(encoding="utf-8"))
        doc.update(session=name, stream=stream, notes=f"rzlab: frames={frames}")
        doc["clock"] = "adxl355" if stream == "accel" else "ltc6903"
        doc["channels"] = [dict(doc["channels"][0], ch=c) for c in range(n_ch)]
        doc["labels"] = [{"t0": 0.5, "t1": 1.0, "i0": 1008, "i1": 2016, "src": "key", "label": "walk"}]
        io.write_wav(folder / f"{name}.{suffix}.wav", np.zeros((frames, n_ch), dtype=np.int32), doc["sample_rate"])
        io.save_sidecar(folder / f"{name}.{suffix}.json", doc, SCHEMA)
    return folder


def test_validate_passes_a_good_root_and_fails_each_defect(tmp_path: Path):
    root = tmp_path / "root"
    folder = write_session(root)
    lines: list[str] = []
    assert run_validate(root, SCHEMA, out=lines.append) == 0 and any(
        "1 session(s) checked, 0 failed" in x for x in lines
    )
    assert validate_session_folder(folder, SCHEMA).ok

    def fails(what: str) -> None:
        rep = validate_session_folder(folder, SCHEMA)
        assert not rep.ok and any(what in p for p in rep.problems), (what, rep.problems)

    stray = folder / "extra.wav"
    stray.write_bytes(b"x")
    fails("unexpected")
    stray.unlink()
    adc_json = folder / f"{folder.name}.adc.json"
    doc = json.loads(adc_json.read_text(encoding="utf-8"))
    bad = dict(doc, notes="rzlab: frames=3999")  # frame count differs from the WAV header
    adc_json.write_text(json.dumps(bad), encoding="utf-8")
    fails("frames")
    bad = dict(doc, labels=[dict(doc["labels"][0], i1=5000, t1=5000 / 2016)])  # label past the end of the file
    adc_json.write_text(json.dumps(bad), encoding="utf-8")
    fails("after the end of the file")
    bad = dict(doc, channels=doc["channels"][:1])
    adc_json.write_text(json.dumps(bad), encoding="utf-8")
    fails("channels")
    bad = dict(doc, session="2026-11-17_other_room_01")
    adc_json.write_text(json.dumps(bad), encoding="utf-8")
    fails("session")
    adc_json.write_text(json.dumps(doc), encoding="utf-8")
    (folder / f"{folder.name}.adc.wav").unlink()
    fails("no recording")
    assert run_validate(root, SCHEMA, out=lambda s: None) == 1


def test_validate_bad_names_empty_folders_and_missing_root(tmp_path: Path):
    root = tmp_path / "root"
    write_session(root)
    (root / "Not A Session").mkdir()
    (root / "2026-11-17_a_b_01").mkdir()  # an unused reservation: only a warning
    rep = {r.name: r for r in validate_root(root, SCHEMA)}
    assert not rep["Not A Session"].ok and rep["2026-11-17_a_b_01"].ok and rep["2026-11-17_a_b_01"].warnings
    assert run_validate(tmp_path / "nope", SCHEMA, out=lambda s: None) == 2
    (root / "loose.wav").write_bytes(b"x")
    assert run_validate(root, SCHEMA, out=lambda s: None) == 1


def test_validate_sidecars_only_folder(tmp_path: Path):
    folder = write_session(tmp_path / "full")
    only = tmp_path / "data" / folder.name
    only.mkdir(parents=True)
    for j in folder.glob("*.json"):
        (only / j.name).write_text(j.read_text(encoding="utf-8"), encoding="utf-8")
    assert run_validate(tmp_path / "data", SCHEMA, out=lambda s: None) == 1  # no WAVs
    assert run_validate(tmp_path / "data", SCHEMA, sidecars_only=True, out=lambda s: None) == 0


def test_capture_counts_zeros_that_are_not_packet_data(tmp_path: Path):
    """data_samples is what lets the recorder prove every zero in the file sits in a loss counter."""
    from rezonating_lab.recorder import capture as cap_mod

    old = cap_mod.QUEUE_PACKETS
    cap_mod.QUEUE_PACKETS = 3
    try:
        cap = cap_mod.StreamCapture(0, "adc_raw", 1, 2000.0, tmp_path / "x.wav", 2000)
    finally:
        cap_mod.QUEUE_PACKETS = old
    cap.start()
    pkt = np.ones(10, dtype=np.int32).reshape(10, 1)
    for k in range(6):  # the writer waits for the base, so only 3 fit; 3 overflow
        cap.on_data(k * 10, k * 5000, pkt)
    cap.set_base(0)
    res = cap.finish(window_end=60)
    assert res.overflow_packets == 3 and res.data_samples == 30
    assert res.end - res.base - res.data_samples == 30  # the dropped packets are zeros: 30 samples
    data, _ = io.read_wav(res.wav_path)
    assert len(data) == 60 and int((data != 0).sum()) == 30


def test_marker_does_not_listen_on_every_interface_by_default(monkeypatch):
    from rezonating_lab.recorder import marker

    assert rconfig.LabConfig().marker_bind == "auto"
    monkeypatch.setattr(marker, "lan_addresses", lambda: ["192.168.7.20", "10.0.0.5"])
    assert marker.resolve_bind("auto") == "192.168.7.20"  # the first LAN address, not 0.0.0.0
    assert marker.resolve_bind("0.0.0.0") == "0.0.0.0"  # only when someone asks for it
    monkeypatch.setattr(marker, "lan_addresses", lambda: [])
    assert marker.resolve_bind("auto") == "127.0.0.1"


def test_staging_inside_the_repo_is_refused(tmp_path: Path):
    ok = make_cfg(tmp_path)
    assert rconfig.check_staging_dir(ok) is None
    bad = rconfig.check_staging_dir(make_cfg(tmp_path, staging_dir=REPO / "scratch" / "staging"))
    assert bad is not None and bad.error_code == "staging_in_repo"
    rel = rconfig.check_staging_dir(make_cfg(tmp_path, staging_dir=Path("staging")))
    assert rel is not None and rel.error_code == "staging_relative"
