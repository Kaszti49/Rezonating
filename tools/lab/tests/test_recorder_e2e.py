"""The recorder through the REST API against the simulator (D-019 sidecars, loss, zeros, files, errors)."""

from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path

import numpy as np
import pytest
from rec_helpers import REPO, form, lab, wait_idle
from rezonating_lab.recorder.validate import run_validate
from rezonating_ml import io
from rezonating_lab.sim.faults import FaultConfig
from rezonating_lab.sim.node import SimConfig

SCHEMA = REPO / "schemas" / "sidecar.schema.json"


def record(client, seconds: float, marks: bool = True, body: dict | None = None) -> dict:
    r = client.post("/api/record/start", json=body or form())
    assert r.status_code == 200, r.text
    time.sleep(seconds / 2)
    if marks:
        assert (
            client.post(
                "/api/record/mark", json={"edge": "start", "person": "P1", "pace": "normal", "shoes": True}
            ).status_code
            == 200
        )
        time.sleep(seconds / 4)
        assert client.post("/api/record/mark", json={"edge": "end"}).status_code == 200
        time.sleep(seconds / 4)
    else:
        time.sleep(seconds / 2)
    r = client.post("/api/record/stop")
    assert r.status_code == 200, r.text
    return r.json()


def sidecars(folder: Path, session: str) -> dict[str, dict]:
    return {s: json.loads((folder / f"{session}.{s}.json").read_text(encoding="utf-8")) for s in ("adc", "accel")}


def test_session_end_to_end_files_sidecars_and_validation(tmp_path):
    with lab(tmp_path, SimConfig(speed=10.0)) as (client, sim, cfg):
        res = record(client, 4.0)
        assert res["ok"] and res["stored"] == "data_root" and res["ended_by"] == "stop", res["problems"]
        session = res["session"]
        assert session.endswith("_home-a_kitchen_01") and io.SESSION_RE.match(session)
        folder = cfg.data_root / session
        assert sorted(p.name for p in folder.iterdir()) == sorted(
            f"{session}.{s}.{e}" for s in ("adc", "accel") for e in ("wav", "json")
        )
        assert list(cfg.staging_dir.iterdir()) == []  # staging is emptied after the move
        sc = sidecars(folder, session)
        for suffix, stream, n_ch, nominal in (("adc", "adc_raw", 2, 2000), ("accel", "accel", 3, 2000)):
            doc = sc[suffix]
            assert doc["schema"] == 1 and doc["stream"] == stream and doc["sample_rate_nominal"] == nominal
            assert doc["sample_rate"] == round(doc["sample_rate_measured"])
            assert abs(doc["sample_rate_measured"] / nominal - 1) > 0.001  # the simulated clocks are off nominal
            assert doc["loss"] == {"device": 0, "link": 0, "host": 0}
            assert doc["clock"] == ("ltc6903" if suffix == "adc" else "adxl355") and doc["first_sample"] == 0
            data, fs = io.read_wav(folder / f"{session}.{suffix}.wav")
            assert fs == doc["sample_rate"] and data.shape[1] == n_ch and data.dtype == np.int32
            notes = io.parse_rzlab_notes(doc["notes"])
            assert int(notes["frames"]) == len(data) and notes["floor"] == "laminate" and notes["persons"] == "P1,P2"
            assert "loss" not in notes
            assert io.check_pair(folder / f"{session}.{suffix}.wav", doc, SCHEMA) == []
            lab_ = doc["labels"][0]
            assert (
                lab_["src"] == "key" and lab_["person"] == "P1" and lab_["pace"] == "normal" and lab_["shoes"] is True
            )
            assert 0 < lab_["i0"] < lab_["i1"] <= len(data) and lab_["t0"] == lab_["i0"] / doc["sample_rate"]
            assert lab_["unc_ms"] > 0 and doc["channels"][0]["units"] in ("V", "g")
        assert [c["position_m"] for c in sc["adc"]["channels"]] == [[0.0, 0.0], [2.0, 0.0]]
        assert run_validate(cfg.data_root, SCHEMA, out=lambda s: None) == 0
        # only the validated sidecars went to the repo-side folder (a tmp folder here)
        copied = sorted(p.relative_to(cfg.sidecar_dir).as_posix() for p in cfg.sidecar_dir.rglob("*") if p.is_file())
        assert copied == sorted(f"{session}/{session}.{s}.json" for s in ("adc", "accel"))
        assert res["sidecars_copied"] and not any(p.suffix == ".wav" for p in cfg.sidecar_dir.rglob("*"))
        assert not list(cfg.sidecar_dir.rglob("*.wav"))
        assert client.get("/api/state").json()["status"]["recording"] is False


def test_simulated_sessions_are_not_copied_to_the_repo_by_default(tmp_path):
    with lab(tmp_path, SimConfig(speed=10.0), copy_sim_sidecars=False) as (client, sim, cfg):
        res = record(client, 2.5, marks=False)
        assert res["ok"] and res["sidecars_copied"] == [] and "simulated" in res["sidecars_copy_skipped"]
        assert not cfg.sidecar_dir.exists() or not any(cfg.sidecar_dir.rglob("*"))
        notes = io.parse_rzlab_notes(sidecars(cfg.data_root / res["session"], res["session"])["adc"]["notes"])
        assert notes["source"] == "sim"


def test_missing_samples_are_zeros_at_their_true_place(tmp_path):
    faults = FaultConfig(device_drop_rate=0.02, link_drop_rate=0.05)
    sim_cfg = SimConfig(speed=10.0, faults=faults, record_injections=True)
    with lab(tmp_path, sim_cfg) as (client, sim, cfg):
        res = record(client, 4.0, marks=False)
        session = res["session"]
        folder = cfg.data_root / session
        doc = sidecars(folder, session)["adc"]
        data, _ = io.read_wav(folder / f"{session}.adc.wav")
        inj = sim.node.streams[0].injected
        lost = np.zeros(len(data), dtype=bool)
        for a, b in inj.device + inj.link:
            lost[a - doc["first_sample"] : b - doc["first_sample"]] = True
        assert lost.sum() > 100, "the test needs real losses"
        assert not data[lost].any(), "lost samples must be zeros"
        assert (data[~lost] == 0).all(axis=1).mean() < 0.02  # received samples are not zeros
        assert doc["loss"]["device"] == inj.device_total and doc["loss"]["link"] == inj.link_total
        assert doc["loss"]["host"] == 0 and len(data) == int(io.parse_rzlab_notes(doc["notes"])["frames"])
        # true time: the footsteps the simulator generated start where the ground truth says, gaps or not
        steps = [e["sample_adc_raw"] for e in sim.node.truth.events if e["acq"] == sim.node.adc.acq_id][:4]
        assert len(steps) >= 3
        env = np.abs(data[:, 0].astype(np.float64))
        for idx in steps:
            before, after = env[max(0, idx - 400) : idx - 100].mean(), env[idx + 20 : idx + 220].mean()
            assert after > 5 * before, (idx, before, after)


def test_loss_incomplete_when_the_link_dies(tmp_path):
    with lab(tmp_path, SimConfig(speed=10.0)) as (client, sim, cfg):
        assert client.post("/api/record/start", json=form()).status_code == 200
        time.sleep(2.5)
        assert client.post("/api/record/mark", json={"edge": "start"}).status_code == 200  # left open on purpose
        time.sleep(0.5)
        sim.stop()  # no final STATUS and no STOP ACK will ever come
        st = wait_idle(client)
        res = st["last"]
        assert res["ended_by"] == "link_lost" and res["stored"] == "data_root" and not res["ok"]
        session = res["session"]
        for doc in sidecars(cfg.data_root / session, session).values():
            assert doc["notes"].splitlines()[0] == "rzlab: loss=incomplete"
            assert io.parse_rzlab_notes(doc["notes"])["loss"] == "incomplete"
            assert doc["labels"] and doc["labels"][0]["i1"] > doc["labels"][0]["i0"]  # the open mark was closed
            assert io.parse_rzlab_notes(doc["notes"])["open_mark_closed_at_stop"] == "1"
        assert all(s["incomplete"] for s in res["streams"])
        assert run_validate(cfg.data_root, SCHEMA, out=lambda s: None) == 0  # incomplete is still a consistent file set
        assert client.get("/api/state").json()["connection"]["state"] == "disconnected"


def test_gaps_are_host_loss_when_the_link_dies_before_any_status(tmp_path):
    """No STATUS ever arrived, so no counter names the zero-filled gaps: they must still sit in loss.host."""
    sim_cfg = SimConfig(speed=10.0, status_period_ms=10000, faults=FaultConfig(link_drop_rate=0.3))
    with lab(tmp_path, sim_cfg) as (client, sim, cfg):
        assert client.post("/api/record/start", json=form()).status_code == 200
        time.sleep(0.8)
        sim.stop()
        res = wait_idle(client)["last"]
        assert res["ended_by"] == "link_lost"
        session = res["session"]
        folder = cfg.data_root / session
        for suffix in ("adc", "accel"):
            doc = sidecars(folder, session)[suffix]
            data, _ = io.read_wav(folder / f"{session}.{suffix}.wav")
            zeros = int((data == 0).all(axis=1).sum())
            assert doc["loss"]["device"] == 0 and doc["loss"]["link"] == 0
            assert doc["loss"]["host"] >= zeros > 0, (suffix, doc["loss"], zeros)


def test_no_data_root_and_data_root_in_repo_are_clear_errors(tmp_path):
    with lab(tmp_path, SimConfig(speed=10.0), data_root=None, data_root_source=None) as (client, sim, cfg):
        r = client.post("/api/record/start", json=form())
        assert r.status_code == 409 and r.json()["error"]["code"] == "no_data_root"
        assert "RZ_DATA_ROOT" in r.json()["error"]["message"]
        dr = client.get("/api/record/data-root").json()
        assert dr["configured"] is False and dr["ok"] is False and dr["error"]["code"] == "no_data_root"
        opts = client.get("/api/record/options").json()
        assert opts["can_start"] is False and opts["blockers"][0]["code"] == "no_data_root"
        good = tmp_path / "chosen"
        good.mkdir()
        r = client.put("/api/record/data-root", json={"path": str(REPO / "data")})
        assert r.status_code == 409 and r.json()["error"]["code"] == "data_root_in_repo"
        r = client.put("/api/record/data-root", json={"path": str(good)})
        assert r.status_code == 200 and r.json()["ok"] is True and cfg.config_path.is_file()
    with lab(tmp_path / "b", SimConfig(speed=10.0), data_root=REPO / "data") as (client, sim, cfg):
        r = client.post("/api/record/start", json=form())
        assert r.status_code == 409 and r.json()["error"]["code"] == "data_root_in_repo"
        assert not list((REPO / "data").glob("*_home-a_*"))  # nothing was created in the repo


def test_data_root_from_env_cannot_be_changed_over_the_api(tmp_path):
    with lab(tmp_path, SimConfig(speed=10.0)) as (client, sim, cfg):
        r = client.put("/api/record/data-root", json={"path": str(tmp_path)})
        assert r.status_code == 409 and r.json()["error"]["code"] == "data_root_from_env"


def test_form_errors_are_422_and_never_echo_names(tmp_path):
    with lab(tmp_path, SimConfig(speed=10.0)) as (client, sim, cfg):
        r = client.post("/api/record/start", json=form(persons=["Alice Smith"]))
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
        assert "Alice" not in json.dumps(r.json()) and r.json()["error"]["details"][0]["loc"][-1] == "persons"
        r = client.post("/api/record/start", json=form(sensors=[]))
        assert r.status_code == 422 and "position" in r.json()["error"]["message"]
        r = client.post("/api/record/start", json=form(protocol="no-such-protocol"))
        assert r.status_code == 422
        r = client.put("/api/record/current-label", json={"person": "Bob"})
        assert r.status_code == 422 and "Bob" not in r.text
        assert list(cfg.data_root.iterdir()) == []  # a refused form reserves nothing


def test_state_rules_while_recording_and_label_api(tmp_path):
    with lab(tmp_path, SimConfig(speed=10.0)) as (client, sim, cfg):
        r = client.post("/api/record/mark", json={"edge": "start"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "not_recording"
        assert client.post("/api/record/stop").json()["error"]["code"] == "not_recording"
        assert client.post("/api/record/start", json=form()).status_code == 200
        for method, url, body in (
            ("post", "/api/connect", {"kind": "sim"}),
            ("post", "/api/disconnect", None),
            ("post", "/api/acquisition", {"action": "stop"}),
            ("post", "/api/record/start", form()),
        ):
            r = getattr(client, method)(url, **({"json": body} if body is not None else {}))
            assert r.status_code == 409 and r.json()["error"]["code"] == "recording_active", url
        assert client.get("/api/state").json()["status"]["recording"] is True
        assert (
            client.put(
                "/api/record/current-label", json={"label": "silence", "person": "P2", "pace": "slow"}
            ).status_code
            == 200
        )
        assert client.get("/api/record/current-label").json()["label"] == "silence"
        assert client.post("/api/record/mark", json={"edge": "end"}).json()["error"]["code"] == "no_open_mark"
        a = client.post("/api/record/mark", json={"edge": "toggle"}).json()
        assert a["action"] == "start" and a["mark"]["label"] == "silence" and a["mark"]["person"] == "P2"
        assert client.post("/api/record/mark", json={"edge": "start"}).json()["error"]["code"] == "mark_open"
        assert client.post("/api/record/mark", json={"edge": "toggle", "person": "P1"}).json()["action"] == "end"
        client.post("/api/record/mark", json={"edge": "start", "person": "P9"})  # not in this session's persons
        labels = client.get("/api/record/labels").json()
        assert [x["state"] for x in labels["labels"]] == ["closed"] and labels["marking"] is False
        lid = labels["labels"][0]["id"]
        assert client.delete(f"/api/record/labels/{lid}").json() == {"deleted": lid}
        assert client.delete(f"/api/record/labels/{lid}").status_code == 404
        assert client.post("/api/record/mark", json={"edge": "start"}).status_code == 200  # open at stop: closed there
        res = client.post("/api/record/stop").json()
        assert res["n_labels"] == 1 and res["ended_by"] == "stop"
        wait_idle(client)


@pytest.mark.skipif(
    os.environ.get("RZ_SLOW") != "1",
    reason="about 55 s of real time and sensitive to machine load; opt in with RZ_SLOW=1 (the 5-minute run is accept_record.py)",
)
def test_label_error_against_simulator_truth_short_run(tmp_path):
    """The 5-minute acceptance run (tools/lab/tests/accept_record.py) in miniature: about 55 s in real time."""
    spec = importlib.util.spec_from_file_location("accept_record", Path(__file__).with_name("accept_record.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "report.json"
    assert mod.main(["--minutes", "0.7", "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    for name, e in report["label_error_ms"].items():
        limit = 20.0 if name.startswith("key") else 150.0
        assert e["n"] >= 4 and e["max_abs_ms"] < limit, (name, e)


def test_mark_with_a_refused_name_is_422_and_nothing_is_logged(tmp_path, caplog):
    """The /mark body is validated like every other form: 422, and the refused text reaches no response or log."""
    with lab(tmp_path, SimConfig(speed=10.0)) as (client, sim, cfg):
        assert client.post("/api/record/start", json=form()).status_code == 200
        caplog.set_level("DEBUG")
        for body in ({"edge": "start", "person": "Zoltan Kovacs"}, {"edge": "start", "label": "Zoltan!!"}):
            r = client.post("/api/record/mark", json=body)
            assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request", r.text
            assert "Zoltan" not in r.text
        assert "Zoltan" not in caplog.text and "Zoltan" not in repr(client.get("/api/logs").json())
        assert client.get("/api/record/labels").json()["labels"] == []  # nothing was opened
        assert client.post("/api/record/stop").status_code == 200
        wait_idle(client)


def test_samples_the_recorder_drops_are_counted_as_host_loss(tmp_path, monkeypatch):
    """A writer queue that overflows leaves zeros in the WAV; they must show in loss.host, not vanish (D-019)."""
    from rezonating_lab.recorder import capture

    monkeypatch.setattr(capture, "QUEUE_PACKETS", 2)  # packets queue up until the first STATUS names the window start
    with lab(tmp_path, SimConfig(speed=10.0)) as (client, sim, cfg):
        res = record(client, 3.0, marks=False)
        session = res["session"]
        folder = cfg.data_root / session
        for suffix in ("adc", "accel"):
            doc = sidecars(folder, session)[suffix]
            notes = io.parse_rzlab_notes(doc["notes"])
            data, _ = io.read_wav(folder / f"{session}.{suffix}.wav")
            dropped = int(notes["writer_overflow_packets"])
            assert dropped > 0, "the test needs a real overflow"
            zeros = int((data == 0).all(axis=1).sum())
            loss = doc["loss"]
            assert loss["host"] >= int(notes["recorder_dropped_samples"]) > 0
            # every all-zero row of the file sits in a loss counter (the sim's noise has no exact all-zero rows)
            assert zeros <= loss["device"] + loss["link"] + loss["host"]
        assert res["ok"], res["problems"]
