"""The protocol runner through the REST API against the in-process simulator (WEB_API.md section 10).

A whole walk-pass-v1 session for two persons: the silence countdown (shortened with ``timed_scale``), then every pass
marked from the keyboard API or the phone path, with a mistaken pass deleted and redone, a page "reload" in the middle,
and the sidecars checked at the end: exactly 90 walk labels per person with the protocol's tags.
"""

from __future__ import annotations

import json
import time
from collections import Counter

from rec_helpers import REPO, form, lab
from rezonating_lab.recorder.validate import run_validate
from rezonating_lab.sim.node import SimConfig
from rezonating_ml import io

SCHEMA = REPO / "schemas" / "sidecar.schema.json"
SCALE = 60.0  # the 60 s silence lasts 1 s here
EXPECTED = {("normal", True): 50, ("normal", False): 20, ("slow", True): 10, ("fast", True): 10}


def runner(client) -> dict:
    r = client.get("/api/record/runner")
    assert r.status_code == 200, r.text
    return r.json()


def wait_runner(client, pred, timeout_s: float = 10.0) -> dict:
    end = time.time() + timeout_s
    while time.time() < end:
        v = runner(client)
        if pred(v):
            return v
        time.sleep(0.05)
    raise AssertionError(f"runner did not get there: {runner(client)}")


def key_mark(client, edge: str = "toggle", **over) -> dict:
    r = client.post("/api/record/mark", json={"edge": edge, **over})
    assert r.status_code == 200, r.text
    return r.json()


def snapshot_runner(client) -> dict:
    """What a freshly loaded page gets on its WebSocket: the cached `runner` event."""
    with client.websocket_connect(
        "/ws?streams=", headers={"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765"}
    ) as ws:
        for _ in range(60):
            msg = ws.receive()
            if msg.get("text"):
                ev = json.loads(msg["text"])
                if ev.get("type") == "runner":
                    return ev
    raise AssertionError("no runner event in the snapshot")


def test_runner_produces_90_labelled_passes_per_person(tmp_path):
    with lab(tmp_path, SimConfig(speed=10.0), recorder_opts={"timed_scale": SCALE}) as (client, sim, cfg):
        rec = client.app.state.recorder
        mgr = client.app.state.manager
        assert runner(client)["state"] == "off"
        r = client.post("/api/record/start", json=form(runner=True))
        assert r.status_code == 200, r.text
        v = runner(client)
        assert v["active"] and v["protocol"] == "walk-pass-v1" and v["persons"] == ["P1", "P2"]
        assert v["state"] == "ready" and v["current"] == 0 and v["overall"] == {"done": 0, "target": 180}
        assert [s["key"] for s in v["steps"]][:3] == ["silence", "P1/normal-shoes-on", "P1/normal-shoes-off"]
        assert v["steps"][0]["duration_s"] == 1.0  # 60 s / SCALE

        # 1. silence: Space starts the countdown, cannot end it, the server ends it
        started = key_mark(client)
        assert started["action"] == "start" and started["mark"]["label"] == "silence"
        assert started["mark"]["person"] is None and runner(client)["state"] == "countdown"
        early = client.post("/api/record/mark", json={"edge": "toggle"})
        assert early.status_code == 409 and early.json()["error"]["code"] == "countdown_running"
        nav = client.post("/api/record/runner/next")
        assert nav.status_code == 409 and nav.json()["error"]["code"] == "countdown_running"
        v = wait_runner(client, lambda x: x["current"] == 1)
        assert v["steps"][0]["status"] == "done" and v["steps"][0]["done"] == 1 and v["state"] == "ready"

        # 2. the passes; every 7th from the phone path, one clash, one mistaken pass deleted and redone
        n = 0
        deleted = None
        while runner(client)["state"] != "finished":
            n += 1
            if n == 3:
                clash = client.post("/api/record/mark", json={"edge": "start", "pace": "fast"})
                assert clash.status_code == 409 and clash.json()["error"]["code"] == "runner_owns_label"
            if n % 7 == 0:
                rec.mark_from_phone("start", mgr.host_us(), 30.0)
                time.sleep(0.01)
                rec.mark_from_phone("end", mgr.host_us(), 30.0)
            else:
                key_mark(client, "start")
                time.sleep(0.01)
                ended = key_mark(client, "end")
                if n == 5:  # a mistaken pass: delete it, the counter goes back, the pass is walked again
                    deleted = ended["mark"]["id"]
                    before = runner(client)["steps"][1]["done"]
                    assert client.delete(f"/api/record/labels/{deleted}").status_code == 200
                    assert runner(client)["steps"][1]["done"] == before - 1
            time.sleep(0.02)  # more than the phone's 15 ms correction: passes stay in order
            if n == 100:  # a browser reload in the middle: the same state comes back from the server
                snap, now = snapshot_runner(client), runner(client)
                assert (snap["current"], snap["overall"]) == (now["current"], now["overall"])
                assert now["current"] == 5 and now["per_person"]["P1"] == {"done": 90, "target": 90}
        assert n == 181  # 180 passes + the deleted one
        v = runner(client)
        assert v["overall"] == {"done": 180, "target": 180} and v["current"] is None
        assert v["per_person"] == {"P1": {"done": 90, "target": 90}, "P2": {"done": 90, "target": 90}}
        assert all(s["status"] == "done" for s in v["steps"])
        assert snapshot_runner(client)["state"] == "finished"
        after = client.post("/api/record/mark", json={"edge": "toggle"})
        assert after.status_code == 409 and after.json()["error"]["code"] == "runner_finished"

        res = client.post("/api/record/stop").json()
        assert res["ok"], res["problems"]
        assert res["runner"]["finished"] and res["runner"]["overall"] == {"done": 180, "target": 180}
        assert runner(client)["state"] == "off"

        folder = cfg.data_root / res["session"]
        for suffix in ("adc", "accel"):
            doc = json.loads((folder / f"{res['session']}.{suffix}.json").read_text(encoding="utf-8"))
            assert doc["protocol"] == "walk-pass-v1"
            labels = doc["labels"]
            assert len(labels) == 181
            assert deleted is not None
            silence = [x for x in labels if x["label"] == "silence"]
            assert len(silence) == 1 and not {"person", "pace", "shoes"} & set(silence[0])
            assert silence[0]["i1"] > silence[0]["i0"]
            walks = [x for x in labels if x["label"] == "walk"]
            assert len(walks) == 180 and all(x["i1"] > x["i0"] for x in walks)
            for p in ("P1", "P2"):
                mine = [x for x in walks if x["person"] == p]
                assert len(mine) == 90, (suffix, p, len(mine))
                assert Counter((x["pace"], x["shoes"]) for x in mine) == EXPECTED
            srcs = Counter(x["src"] for x in walks)
            assert srcs["phone"] == 25 and srcs["key"] == 155
            # labels come in protocol order: silence first, then P1's 90 passes, then P2's
            ordered = sorted(labels, key=lambda x: x["i0"])
            assert ordered[0]["label"] == "silence"
            assert [x["person"] for x in ordered[1:]] == ["P1"] * 90 + ["P2"] * 90
            assert io.check_pair(folder / f"{res['session']}.{suffix}.wav", doc, SCHEMA) == []
        assert run_validate(cfg.data_root, SCHEMA, out=lambda s: None) == 0


def test_runner_endpoints_errors_and_starting_mid_recording(tmp_path):
    with lab(tmp_path, SimConfig(speed=10.0), recorder_opts={"timed_scale": SCALE}) as (client, sim, cfg):
        opts = client.get("/api/record/options").json()
        assert opts["protocols"] == ["walk-pass-v1"]  # kill-test-phone is no longer offered
        proto = client.get("/api/record/protocols/walk-pass-v1").json()
        assert proto["passes_per_person"] == 90 and proto["blocks"][0]["steps"][0]["duration_s"] == 60
        assert client.get("/api/record/protocols/kill-test-phone").status_code == 404
        for path in ("next", "back", "skip", "stop", "cancel", "start"):
            r = client.post(f"/api/record/runner/{path}")
            assert r.status_code == 409 and r.json()["error"]["code"] == "not_recording", path

        # a runner needs persons for a per-person protocol: refused before anything is reserved
        r = client.post("/api/record/start", json=form(runner=True, persons=[]))
        assert r.status_code == 422 and r.json()["error"]["details"][0]["loc"] == ["persons"]
        assert list(cfg.data_root.iterdir()) == []
        # an IPv6 phone-marker address in the form: a clear refusal
        r = client.post("/api/record/start", json=form(marker=True, marker_host="::1"))
        assert r.status_code == 422 and r.json()["error"]["code"] == "bad_marker_host"
        assert "IPv6" in r.json()["error"]["message"]

        assert client.post("/api/record/start", json=form()).status_code == 200
        assert client.post("/api/record/runner/next").json()["error"]["code"] == "runner_off"
        manual = key_mark(client, "start", person="P2", pace="slow", shoes=False)
        assert manual["mark"]["pace"] == "slow"
        r = client.post("/api/record/runner/start")
        assert r.status_code == 409 and r.json()["error"]["code"] == "mark_open"
        key_mark(client, "end")
        r = client.post("/api/record/runner/start", json={})
        assert r.status_code == 200 and r.json()["current"] == 0
        assert client.post("/api/record/runner/start").json()["error"]["code"] == "runner_active"

        # cancel a countdown: its label is deleted
        sid = key_mark(client)["mark"]["id"]
        assert client.post("/api/record/runner/cancel").json()["state"] == "ready"
        assert sid not in [m["id"] for m in client.get("/api/record/labels").json()["labels"]]
        assert client.post("/api/record/runner/cancel").json()["error"]["code"] == "no_countdown"
        # deleting a running countdown's label stops the countdown too
        sid = key_mark(client)["mark"]["id"]
        assert client.delete(f"/api/record/labels/{sid}").status_code == 200
        v = runner(client)
        assert v["state"] == "ready" and v["countdown"] is None
        time.sleep(1.3)  # the cancelled timer must not end anything
        assert runner(client)["steps"][0]["done"] == 0 and client.get("/api/record/labels").json()["marking"] is False

        # navigation
        assert client.post("/api/record/runner/skip").json()["steps"][0]["status"] == "skipped"
        g = client.post("/api/record/runner/goto", json={"index": 3})
        assert g.status_code == 200 and g.json()["current"] == 3
        assert client.post("/api/record/runner/goto", json={"index": 42}).status_code == 404
        assert client.post("/api/record/runner/back").json()["current"] == 2
        assert client.post("/api/record/runner/next").json()["current"] == 3
        m = key_mark(client)["mark"]
        assert (m["label"], m["person"], m["pace"], m["shoes"]) == ("walk", "P1", "slow", True)
        assert client.post("/api/record/runner/stop").json()["error"]["code"] == "mark_open"
        key_mark(client)
        assert runner(client)["steps"][3]["done"] == 1
        assert client.post("/api/record/runner/stop").json()["state"] == "off"
        # back to the label form
        m = key_mark(client, "start", person="P2", pace="fast", shoes=True)["mark"]
        assert (m["person"], m["pace"]) == ("P2", "fast")
        key_mark(client, "end")
        res = client.post("/api/record/stop").json()
        assert res["ok"], res["problems"]
        assert res["runner"]["overall"]["done"] == 1 and res["runner"]["finished"] is False
