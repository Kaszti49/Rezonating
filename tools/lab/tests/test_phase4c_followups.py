"""Phase 4a follow-ups: runner protocol must be the session's, ordered runner events, no pass on a complete step,
and a ``host:port`` in the marker settings gets its own message."""

from __future__ import annotations

import pytest
from rec_helpers import form, lab, make_cfg
from rezonating_lab.recorder import config as rconfig
from rezonating_lab.recorder.marker import MarkerHostError, choose_bind
from rezonating_lab.recorder.recording import Recorder
from rezonating_lab.server.device import DeviceManager
from rezonating_lab.sim.node import SimConfig
from test_runner_e2e import SCALE, key_mark, wait_runner


def test_runner_start_refuses_another_protocol_and_a_pass_on_a_complete_step(tmp_path):
    with lab(tmp_path, SimConfig(speed=10.0), recorder_opts={"timed_scale": SCALE}) as (client, _sim, _cfg):
        assert client.post("/api/record/start", json=form()).status_code == 200
        r = client.post("/api/record/runner/start", json={"protocol": "kill-test-phone"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "protocol_mismatch"
        assert client.get("/api/record/runner").json()["active"] is False
        r = client.post("/api/record/runner/start", json={"protocol": "walk-pass-v1"})  # naming it is fine
        assert r.status_code == 200 and r.json()["protocol"] == "walk-pass-v1"

        key_mark(client)  # the silence countdown (1 s here); the server ends it
        wait_runner(client, lambda v: v["steps"][0]["status"] == "done" and v["current"] == 1)
        assert client.post("/api/record/runner/goto", json={"index": 0}).json()["current"] == 0
        r = client.post("/api/record/mark", json={"edge": "toggle"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "step_complete"
        assert "already has" in r.json()["error"]["message"]
        assert client.get("/api/record/labels").json()["marking"] is False
        assert client.post("/api/record/stop").json()["ok"]


def test_runner_views_are_published_under_the_recorder_lock(tmp_path):
    """The ticker and the countdown's end both publish while holding the lock, so their views keep their order."""
    mgr = DeviceManager(embedded_sim=False)
    rec = Recorder(mgr, make_cfg(tmp_path))
    held: list[bool] = []
    mgr.publish = lambda ev: held.append(rec._lock._is_owned())  # type: ignore[method-assign]
    rec._publish_runner()
    assert held == [True]


@pytest.mark.parametrize("text", ["192.168.1.23:8766", "lab-pc:8766"])
def test_host_with_port_is_not_called_ipv6(tmp_path, text):
    assert not rconfig.is_ipv6(text) and rconfig.host_with_port(text)
    with pytest.raises(rconfig.ConfigError) as e:
        rconfig.load_config({"RZ_MARKER_BIND": text, "RZ_CONFIG": str(tmp_path / "none.toml")})
    assert "without ':port'" in e.value.message and "IPv6" not in e.value.message
    with pytest.raises(MarkerHostError) as e2:
        choose_bind("127.0.0.1", text)
    assert "without ':port'" in str(e2.value)


def test_ipv6_is_still_refused_as_ipv6():
    for text in ("::1", "[::1]", "[::1]:8766", "fe80::1%eth0", "::ffff:1.2.3.4"):
        assert rconfig.is_ipv6(text), text
        assert not rconfig.host_with_port(text), text
    assert not rconfig.is_ipv6("192.168.1.23") and not rconfig.host_with_port("192.168.1.23")
