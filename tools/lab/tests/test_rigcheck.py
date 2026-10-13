"""Rig checks against the simulator: the clean sim passes every check, and each rig fault fails its own check."""

from __future__ import annotations

import json
from contextlib import contextmanager

import numpy as np
import pytest
from fastapi.testclient import TestClient
from rec_helpers import make_cfg
from rezonating_lab.server import rigcheck as rc
from rezonating_lab.server.app import create_app
from rezonating_lab.server.device import ConnectSpec, DeviceManager
from rezonating_lab.sim.faults import FaultConfig
from rezonating_lab.sim.node import SimConfig, SimNode
from rezonating_lab.sim.scenarios import AccelSignal, AdcSignal, ScenarioConfig
from rezonating_lab.sim.server import SimThread

SPEED = 10.0
RATE_S = 3.0  # device seconds: enough for a 0.01 % fit with 10 us stamp jitter
CLEAN = {"shorted_inputs": True}  # the noise floor needs shorted inputs; everything else is the default sim


@contextmanager
def rig(tmp_path, sim_auto: bool = True, **faults):
    cfg = make_cfg(tmp_path)
    with SimThread(SimConfig(speed=SPEED, faults=FaultConfig(**faults))) as sim:
        mgr = DeviceManager(embedded_sim=False)
        mgr.start()
        try:
            mgr.connect(ConnectSpec("tcp", "127.0.0.1", sim.port)).result(timeout=10)
            yield rc.RigChecks(mgr, cfg, sim_auto=sim_auto), mgr, cfg
        finally:
            mgr.close()


def run(r: rc.RigChecks, ids=None) -> dict[str, dict]:
    r.run(ids, rate_s=RATE_S)
    assert r.wait(60), "rig checks did not finish"
    return {c["id"]: c for c in r.view()["checks"]}


# ------------------------------------------------------------------------------------------- the simulator


def test_fault_flags_change_only_their_signal():
    cfg = ScenarioConfig()
    clean, _ = AdcSignal(cfg, 1).block(0, 4000, 2000.0, (8, 8))
    shorted, steps = AdcSignal(cfg, 1, shorted=True).block(0, 4000, 2000.0, (8, 8))
    assert steps == [] and abs(shorted.mean()) < 50 and shorted.std() < clean.std() / 5
    noise = clean - shorted  # same noise stream: the difference is offset plus footsteps only
    assert np.abs(noise).max() > 10_000
    acc = AccelSignal(cfg, 1).block(0, 2000, 2000.0, 2).mean(axis=0) / 256000
    flat = AccelSignal(cfg, 1, gravity=False).block(0, 2000, 2000.0, 2).mean(axis=0) / 256000
    assert acc[2] == pytest.approx(1.0, abs=0.01) and abs(flat[2]) < 0.01
    assert flat[:2] == pytest.approx(acc[:2], abs=1e-9)


class _Sink:
    """A stand-in connection that keeps every DATA frame."""

    def __init__(self) -> None:
        self.out: list = []

    def backlog(self) -> int:
        return 0

    def send_data(self, d, _faults) -> bool:
        self.out.append(d)
        return False


@pytest.mark.parametrize(("swap", "loud"), [(False, 1), (True, 0)])
def test_sim_tap_lands_on_the_asked_channel_and_swap_moves_it(swap, loud):
    t = [0.0]
    node = SimNode(SimConfig(faults=FaultConfig(swap_channels=swap, shorted_inputs=True)), clock=lambda: t[0])
    sink = _Sink()
    node._ensure_acq(node.adc, node.now_dev_s())
    node.streams[0].sending = True
    node.active = sink
    t[0] = 0.2
    node.advance()
    idx = node.inject_tap(1)
    t[0] = 0.6
    node.advance()
    x = np.concatenate([d.samples for d in sink.out if d.stream == 0])
    win = np.abs(x[idx : idx + 200].astype(float))
    assert int(np.argmax(win.max(axis=0))) == loud
    assert node.truth.events[-1]["kind"] == "tap"


# --------------------------------------------------------------------------------------------- the checks


def test_clean_sim_passes_every_check_and_saves_the_report(tmp_path):
    with rig(tmp_path, **CLEAN) as (r, mgr, cfg):
        res = run(r)
        assert {k: v["state"] for k, v in res.items()} == dict.fromkeys(rc.CHECK_IDS, "pass"), res
        rate = res["rate"]["numbers"]
        assert rate["error_pct"] == pytest.approx(0.8, abs=0.02)  # the default sim clock error
        assert all(v < rc.NOISE_LIMIT_UV_RMS for v in res["noise"]["numbers"]["rms_uv"])
        assert res["noise"]["numbers"]["rms_uv"][0] == pytest.approx(6.0, rel=0.1)  # adc_noise_v in the scenario
        assert [t["detected"] for t in res["tap"]["numbers"]["taps"]] == [0, 1]
        assert res["accel"]["numbers"]["mean_g"][2] == pytest.approx(1.0, abs=0.01)
        view = r.view()
        assert not view["running"] and view["report_path"]
        path = cfg.data_root / "rigchecks" / r.report_filename()
        assert str(path) == view["report_path"]
        text = path.read_text(encoding="utf-8")
        assert "rzn-sim001" in text and "0.1.0-sim" in text and "5 of 5 checks passed" in text
        assert text.count("| PASS |") == 5 and "2016." in text
        # streams the checks started are stopped again
        assert not mgr.stream_running(0) and not mgr.stream_running(2)


def test_clock_error_165_fails_the_rate_check(tmp_path):
    with rig(tmp_path, clock_error=0.0165, **CLEAN) as (r, _mgr, _cfg):
        res = run(r, ["rate"])
        assert res["rate"]["state"] == "fail"
        assert res["rate"]["numbers"]["error_pct"] == pytest.approx(1.65, abs=0.02)


def test_negative_clock_error_inside_the_limit_passes(tmp_path):
    with rig(tmp_path, clock_error=-0.01, **CLEAN) as (r, _mgr, _cfg):
        assert run(r, ["rate"])["rate"]["state"] == "pass"


def test_swapped_channels_fail_the_tap_test(tmp_path):
    with rig(tmp_path, swap_channels=True, **CLEAN) as (r, _mgr, _cfg):
        res = run(r, ["tap"])
        assert res["tap"]["state"] == "fail"
        assert [t["detected"] for t in res["tap"]["numbers"]["taps"]] == [1, 0]


def test_no_gravity_fails_the_accel_check(tmp_path):
    with rig(tmp_path, no_gravity=True, **CLEAN) as (r, _mgr, _cfg):
        res = run(r, ["accel"])
        assert res["accel"]["state"] == "fail"
        assert abs(res["accel"]["numbers"]["mean_g"][2]) < 0.05


def test_no_adc_fails_the_adc_check(tmp_path):
    with rig(tmp_path, no_adc=True) as (r, _mgr, _cfg):
        res = run(r, ["adc"])
        assert res["adc"]["state"] == "fail"
        assert res["adc"]["numbers"]["samples"] == 0


def test_inputs_not_shorted_fail_the_noise_check(tmp_path):
    with rig(tmp_path) as (r, _mgr, _cfg):  # footsteps on the inputs: far above the noise limit
        res = run(r, ["noise"])
        assert res["noise"]["state"] == "fail"
        assert max(res["noise"]["numbers"]["rms_uv"]) > 5 * rc.NOISE_LIMIT_UV_RMS


def test_a_person_step_waits_for_continue_and_cancel_stops(tmp_path):
    with rig(tmp_path, sim_auto=False, **CLEAN) as (r, _mgr, _cfg):
        r.run(["noise", "accel"])
        assert r._wait_until(lambda: r.awaiting_confirm, 5)
        v = r.view()
        assert (
            v["current"] == "noise" and v["checks"][2]["state"] == "waiting" and "Short CH0" in v["checks"][2]["prompt"]
        )
        r.confirm()
        assert r.wait(30)
        res = {c["id"]: c for c in r.view()["checks"]}
        assert res["noise"]["state"] == "pass" and res["noise"]["numbers"]["confirmed"] == "person"
        assert res["accel"]["state"] == "pass"
        r.run(["tap"])
        assert r._wait_until(lambda: r.awaiting_confirm, 5)
        r.cancel()
        assert r.wait(10)
        assert r.view()["checks"][3]["state"] == "cancelled"


def test_rest_and_websocket(tmp_path):
    cfg = make_cfg(tmp_path)
    port = 8765
    base = f"http://127.0.0.1:{port}"
    with SimThread(SimConfig(speed=SPEED, faults=FaultConfig(**CLEAN))) as sim:
        app = create_app(port, manager=DeviceManager(embedded_sim=False), static_dir=tmp_path / "x", lab_config=cfg)
        with TestClient(app, base_url=base) as c:
            assert c.post("/api/rigcheck/run", json={}).json()["error"]["code"] == "not_connected"
            assert c.get("/api/rigcheck/report").status_code == 404
            r = c.post("/api/connect", json={"kind": "tcp", "host": "127.0.0.1", "port": sim.port})
            assert r.status_code == 200, r.text
            assert c.post("/api/rigcheck/run", json={"checks": ["nope"]}).status_code == 404
            with c.websocket_connect("/ws", headers={"Host": f"127.0.0.1:{port}"}) as ws:
                r = c.post("/api/rigcheck/run", json={"checks": ["adc", "rate", "accel"], "rate_s": 20})
                assert r.status_code == 200 and r.json()["running"]
                busy = c.post("/api/acquisition", json={"action": "start"})
                assert busy.status_code == 409 and busy.json()["error"]["code"] == "rigcheck_running"
                assert c.post("/api/rigcheck/run", json={}).json()["error"]["code"] == "rigcheck_running"
                seen = None
                for _ in range(5000):
                    msg = ws.receive()
                    if msg.get("text") and '"rigcheck"' in msg["text"]:
                        ev = json.loads(msg["text"])
                        if ev["type"] == "rigcheck" and not ev["running"] and ev["checks"][0]["state"] == "pass":
                            seen = ev
                            break
                assert seen is not None and seen["checks"][4]["state"] == "pass"
            rep = c.get("/api/rigcheck/report")
            assert rep.status_code == 200 and rep.headers["content-type"].startswith("text/markdown")
            assert "attachment" in rep.headers["content-disposition"] and "| ADC answers | PASS |" in rep.text
            assert "3 of 3 checks passed, 2 not run" in rep.text
            assert c.post("/api/rigcheck/confirm").json()["error"]["code"] == "no_prompt"
            assert c.get("/api/rigcheck").json()["thresholds"]["rate_tolerance_pct"] == rc.RATE_TOLERANCE_PCT
