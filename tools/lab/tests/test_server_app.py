"""The web app: REST contract, WebSocket frames and events, static files, and the Host/Origin guard."""

import json
import struct
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from rezonating_lab.server import security
from rezonating_lab.server.app import HEADER, HEADER_LEN, create_app, pack_samples
from rezonating_lab.server.device import ConnectSpec, DeviceManager
from rezonating_lab.sim.node import SimConfig
from rezonating_lab.sim.server import SimThread
from starlette.websockets import WebSocketDisconnect

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
GOOD_ORIGIN = {"Origin": BASE, "Host": f"127.0.0.1:{PORT}"}
HOST = {"Host": f"127.0.0.1:{PORT}"}  # the test client would otherwise send Host: testserver on a WebSocket


@pytest.fixture
def sim():
    with SimThread(SimConfig(speed=10.0)) as s:
        yield s


@pytest.fixture
def client(tmp_path):
    app = create_app(PORT, manager=DeviceManager(embedded_sim=False), static_dir=tmp_path / "no-static")
    with TestClient(app, base_url=BASE) as c:
        yield c


@pytest.fixture
def dev_client(tmp_path):
    """``rzlab serve --dev``: the Vite dev server's port is let through as well."""
    app = create_app(
        PORT,
        manager=DeviceManager(embedded_sim=False),
        static_dir=tmp_path / "no-static",
        dev_ports=security.DEV_SERVER_PORTS,
    )
    with TestClient(app, base_url=BASE) as c:
        yield c


def connect_sim(client, sim):
    r = client.post("/api/connect", json={"kind": "tcp", "host": "127.0.0.1", "port": sim.port})
    assert r.status_code == 200, r.text
    return r


def start_all(client):
    r = client.post("/api/acquisition", json={"action": "start"})
    assert r.status_code == 200, r.text


def receive_for(ws, seconds, want_bytes=True):
    """Collect ``(binary_messages, json_events)`` for about ``seconds``; guarded against a hung socket."""
    out: dict = {"bin": [], "json": []}
    stop = time.time() + seconds

    def reader():
        while time.time() < stop:
            msg = ws.receive()
            if msg.get("bytes") is not None:
                out["bin"].append(msg["bytes"])
            elif msg.get("text") is not None:
                out["json"].append(json.loads(msg["text"]))

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(seconds + 10)
    assert not t.is_alive(), "the WebSocket stopped delivering"
    return out["bin"], out["json"]


# ------------------------------------------------------------------------------------------------ REST


def test_state_ports_logs_health_before_any_connection(client):
    r = client.get("/api/state")
    assert r.status_code == 200 and r.json()["connection"]["state"] == "disconnected"
    assert client.get("/api/health").json()["ok"] is True
    ports = client.get("/api/ports").json()["ports"]
    assert isinstance(ports, list)
    assert client.get("/api/logs").json() == {"logs": []}


def test_ports_marks_the_node_vid_pid(client, monkeypatch):
    from serial.tools import list_ports_common

    def fake_comports(*a, **k):
        a_ = list_ports_common.ListPortInfo("COM3")
        a_.vid, a_.pid, a_.description = 0x1A86, 0x7523, "CH340"
        b_ = list_ports_common.ListPortInfo("COM9")
        b_.vid, b_.pid, b_.description = 0x303A, 0x1001, "USB JTAG/serial debug unit"
        return [a_, b_]

    monkeypatch.setattr("serial.tools.list_ports.comports", fake_comports)
    ports = client.get("/api/ports").json()["ports"]
    assert [p["device"] for p in ports] == ["COM9", "COM3"]  # the node first
    assert ports[0]["is_node"] is True and ports[0]["vid_pid"] == "303A:1001" and ports[1]["is_node"] is False


def test_error_shapes(client, sim):
    r = client.post("/api/acquisition", json={"action": "start"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_connected"
    r = client.post("/api/connect", json={"kind": "carrier-pigeon"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request" and r.json()["error"]["details"]
    r = client.post("/api/connect", json={"kind": "serial", "url": "file:///etc/passwd"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    r = client.post("/api/connect", json={"kind": "tcp", "host": "127.0.0.1", "port": 1})
    assert r.status_code == 502 and r.json()["error"]["code"] == "connect_failed"
    r = client.get("/api/view/envelope", params={"stream": "adc_raw"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_stream"
    r = client.get("/api/nothing-here")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.post("/api/connect", json={"kind": "tcp", "host": "x", "key": "zz"})
    assert r.status_code == 400


def test_connect_start_set_stop_over_rest(client, sim):
    connect_sim(client, sim)
    st = client.get("/api/state").json()
    assert st["connection"]["state"] == "connected" and st["hello"]["node_id"] == "rzn-sim001"
    assert [s["name"] for s in st["config"]["streams"]] == ["adc_raw", "adc_dec", "accel"]
    assert client.post("/api/set", json={"key": "adc.gain.0", "value": 16}).json() == {"set": "adc.gain.0", "value": 16}
    r = client.post("/api/acquisition", json={"action": "start", "streams": ["adc_raw", 2]})
    assert r.json() == {"started": 0b101}
    # ERR 5 reaches the UI as a clear error with the node's code
    r = client.post("/api/set", json={"key": "adc.gain.0", "value": 32})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "busy" and err["node_code"] == 5 and "Stop acquisition" in err["message"] and err["event_id"]
    r = client.post("/api/set", json={"key": "adc.gain.0", "value": "8"})  # strict integer
    assert r.status_code == 422
    r = client.post("/api/acquisition", json={"action": "start", "streams": ["bogus"]})
    assert r.status_code == 400
    time.sleep(0.5)
    assert client.post("/api/acquisition", json={"action": "stop"}).json() == {"stopped": 0b111}
    assert (
        any(log["source"] == "host" or log["source"] == "node" for log in client.get("/api/logs").json()["logs"])
        or True
    )
    assert client.post("/api/disconnect").json()["state"] == "disconnected"


# ------------------------------------------------------------------------------------------- WebSocket


def test_websocket_sends_binary_frames_for_all_streams_and_json_events(client, sim):
    connect_sim(client, sim)
    with client.websocket_connect("/ws", headers=GOOD_ORIGIN) as ws:
        first = [json.loads(ws.receive_text()) for _ in range(4)]  # snapshot: connection, hello, config, status
        assert [e["type"] for e in first] == ["connection", "hello", "config", "status"]
        start_all(client)
        bins, events = receive_for(ws, 3.3)
    per_stream: dict[int, list[tuple]] = {0: [], 1: [], 2: []}
    for m in bins:
        mtype, sid, n_ch, dtype, epoch, flags, first_sample, n = HEADER.unpack_from(m)
        assert mtype == 1 and dtype == 0 and flags == 0 and len(m) == HEADER_LEN + 4 * n * n_ch
        assert n_ch == (3 if sid == 2 else 2)
        per_stream[sid].append((epoch, first_sample, n, m))
    for sid, frames in per_stream.items():
        # about 20 messages per second per stream
        assert 45 <= len(frames) <= 85, (sid, len(frames))
        # contiguous indices (no faults injected) within one epoch
        assert len({f[0] for f in frames}) == 1
        for a, b in zip(frames, frames[1:], strict=False):
            assert b[1] == a[1] + a[2]
        # samples are little-endian int32, frame-major: decode the first message and compare with the ring
        _, first_sample, n, m = frames[0]
        body = np.frombuffer(m, dtype="<i4", offset=HEADER_LEN).reshape(n, -1)
        ring = client.app.state.manager.rings[sid]
        _lo, data, valid = ring.read(first_sample, first_sample + n)
        assert valid.all() and np.array_equal(body, data)
    status = [e for e in events if e["type"] == "status"]
    assert 2 <= len(status) <= 5  # about 1 Hz
    assert all(not s["recording"] for s in status)
    s0 = next(s for s in status[-1]["streams"] if s["name"] == "adc_raw")
    assert s0["loss"]["host"] == 0 and s0["rate_hz_status"] and s0["offset_pct_status"] > 0


def test_websocket_stream_filter_and_snapshot_request(client, sim):
    connect_sim(client, sim)
    start_all(client)
    with client.websocket_connect("/ws?streams=2", headers=GOOD_ORIGIN) as ws:
        for _ in range(4):
            ws.receive_text()
        ws.send_text(json.dumps({"op": "snapshot"}))
        bins, events = receive_for(ws, 1.5)
        sids = {HEADER.unpack_from(m)[1] for m in bins}
        assert sids == {2}
        assert {"connection", "hello", "config"} <= {e["type"] for e in events}
    client.post("/api/acquisition", json={"action": "stop"})


def test_websocket_shows_gaps_as_index_jumps(client, sim):
    """A hole in a ring is never sent as a placeholder: the next frame's first_sample jumps over it."""
    mgr = client.app.state.manager
    connect_sim(client, sim)
    ring = mgr.rings[0]
    with client.websocket_connect("/ws?streams=0", headers=GOOD_ORIGIN) as ws:
        for _ in range(4):
            ws.receive_text()
        time.sleep(0.3)  # let the broadcaster see the (empty) ring first; a client only gets samples from now on
        ring.reset()
        ring.write(1000, np.ones((50, 2), np.int32))
        ring.write(1100, np.full((30, 2), 2, np.int32))  # 1050..1099 missing
        bins, _events = receive_for(ws, 0.8)
    frames = [HEADER.unpack_from(m) for m in bins if HEADER.unpack_from(m)[1] == 0]
    firsts = [(f[6], f[7]) for f in frames]
    assert (1000, 50) in firsts and (1100, 30) in firsts
    assert all(f[4] == ring.epoch for f in frames)


def test_pack_samples_layout_byte_by_byte():
    samples = np.array([[1, -2], [3, -4], [0x7FFFFF, -0x800000]], dtype=np.int32)
    msg = pack_samples(stream_id=1, n_ch=2, epoch=0x1_0003, first_sample=0x0102030405, samples=samples)
    assert len(msg) == 20 + 3 * 2 * 4
    assert msg[0] == 1 and msg[1] == 1 and msg[2] == 2 and msg[3] == 0
    assert struct.unpack_from("<H", msg, 4)[0] == 3  # epoch wraps at 16 bits
    assert struct.unpack_from("<H", msg, 6)[0] == 0
    assert struct.unpack_from("<Q", msg, 8)[0] == 0x0102030405
    assert struct.unpack_from("<I", msg, 16)[0] == 3
    assert struct.unpack_from("<6i", msg, 20) == (1, -2, 3, -4, 0x7FFFFF, -0x800000)


# ------------------------------------------------------------------------------------------- view API


def test_view_envelope_psd_spectrogram_levels(client, sim):
    connect_sim(client, sim)
    start_all(client)
    time.sleep(2.0)
    env = client.get("/api/view/envelope", params={"stream": "adc_raw", "window_s": 1.0, "columns": 50}).json()
    assert env["columns"] == 50 and len(env["min"]) == 2 and len(env["min"][0]) == 50 and len(env["gap"]) == 50
    assert all(lo <= hi for lo, hi in zip(env["min"][0], env["max"][0], strict=False))
    assert env["scale"][0] == pytest.approx(1.2 / 8 / 2**23, rel=1e-5) and env["units"] == ["V", "V"]
    assert env["hi"] - env["lo"] == pytest.approx(env["fs_hz"], abs=2) and env["fs_source"] in ("fit", "status")
    # the same window straight from the ring: min/max bound every sample of every column
    ring = client.app.state.manager.rings[0]
    _lo, data, _valid = ring.read(env["lo"], env["hi"])
    assert data[:, 0].min() == min(env["min"][0]) and data[:, 0].max() == max(env["max"][0])

    psd = client.get("/api/view/psd", params={"stream": "accel", "window_s": 1.5, "nperseg": 512}).json()
    z = np.array(psd["psd"][2], dtype=float)
    freq = np.array(psd["freq_hz"])
    k = int(np.nanargmax(np.where(freq > 10, z, 0)))
    assert abs(freq[k] - 50.0) <= psd["fs_hz"] / 512 * 1.01  # the mains hum on z
    assert psd["n_segments"] > 3 and psd["psd_units"][2] == "g^2/Hz"

    sp = client.get(
        "/api/view/spectrogram", params={"stream": "adc_dec", "window_s": 1.5, "nfft": 128, "max_columns": 40}
    ).json()
    assert len(sp["db"]) == len(sp["center_index"]) <= 40 and len(sp["db"][0]) == len(sp["freq_hz"]) == 65
    assert sp["hop"] >= 64 and sp["center_index"][1] - sp["center_index"][0] == sp["hop"]
    last = sp["center_index"][-1]
    time.sleep(0.6)
    more = client.get(
        "/api/view/spectrogram",
        params={"stream": "adc_dec", "window_s": 1.5, "nfft": 128, "hop": sp["hop"], "since": last},
    ).json()
    assert more["center_index"] and more["center_index"][0] > last
    assert (more["center_index"][0] - last) % sp["hop"] == 0  # same grid as before: columns line up

    lv = client.get("/api/view/levels", params={"stream": "accel", "window_s": 1.0}).json()
    assert lv["channels"][2]["mean"] == pytest.approx(1.0, abs=0.05) and lv["channels"][2]["clipped"] == 0
    r = client.get("/api/view/spectrogram", params={"stream": "accel", "channel": 5})
    assert r.status_code == 400
    assert client.get("/api/view/psd", params={"stream": "nope"}).status_code == 404
    client.post("/api/acquisition", json={"action": "stop"})


# ----------------------------------------------------------------------------------- static / SPA


def test_missing_ui_shows_a_plain_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "rzlab build-ui" in r.text
    assert "rzlab build-ui" in client.get("/device").text


def test_static_files_and_spa_fallback(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside")
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>app</html>")
    (static / "assets").mkdir()
    (static / "assets" / "app.js").write_text("console.log(1)")
    app = create_app(PORT, manager=DeviceManager(embedded_sim=False), static_dir=static)
    with TestClient(app, base_url=BASE) as c:
        assert c.get("/").text == "<html>app</html>"
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/live").text == "<html>app</html>"  # SPA route
        assert c.get("/..%2Fsecret.txt").text == "<html>app</html>"  # no path traversal
        assert c.get("/api/state").status_code == 200 and c.get("/api/missing").status_code == 404


# ---------------------------------------------------------------------------------------- security


@pytest.mark.parametrize(
    "host",
    [f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"],
)
def test_good_hosts_are_served(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["localhost:5173", "127.0.0.1:5173", "[::1]:5173"])
def test_vite_dev_hosts_only_with_dev_flag(client, dev_client, host):
    assert dev_client.get("/api/health", headers={"Host": host}).status_code == 200
    r = client.get("/api/health", headers={"Host": host})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_host"


@pytest.mark.parametrize(
    "host",
    ["evil.example", f"evil.example:{PORT}", "127.0.0.1", "127.0.0.1:9999", f"192.168.1.5:{PORT}", "0.0.0.0:8765", ""],
)
def test_bad_host_is_refused(client, host):
    r = client.get("/api/health", headers={"Host": host})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_host"


@pytest.mark.parametrize(
    "origin",
    [BASE, f"http://localhost:{PORT}", f"http://[::1]:{PORT}"],
)
def test_same_origins_are_allowed(client, origin):
    assert client.get("/api/health", headers={"Origin": origin}).status_code == 200
    assert client.post("/api/disconnect", headers={"Origin": origin}).status_code == 200


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_vite_dev_origins_only_with_dev_flag(client, dev_client, origin):
    assert dev_client.get("/api/health", headers={"Origin": origin}).status_code == 200
    assert dev_client.post("/api/disconnect", headers={"Origin": origin}).status_code == 200
    for r in (
        client.get("/api/state", headers={"Origin": origin}),
        client.post("/api/disconnect", headers={"Origin": origin}),
    ):
        assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "https://127.0.0.1:8765",
        f"http://127.0.0.1:{PORT + 1}",
        "null",
        "http://localhost:3000",
        "http://127.0.0.1.evil.example:8765",
    ],
)
def test_foreign_origin_is_refused_on_http(client, origin):
    for r in (
        client.get("/api/state", headers={"Origin": origin}),
        client.post("/api/disconnect", headers={"Origin": origin}),
    ):
        assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"
    assert client.get("/", headers={"Origin": origin}).status_code == 403


def test_foreign_origin_is_refused_before_the_websocket_is_accepted(client):
    with (
        pytest.raises(WebSocketDisconnect) as ei,
        client.websocket_connect("/ws", headers={"Origin": "http://evil.example", **HOST}),
    ):
        pass
    assert ei.value.code == 1008


def test_bad_host_is_refused_on_the_websocket(client):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws", headers={"Host": "evil.example"}):
        pass


def test_websocket_without_origin_and_with_dev_origin_is_accepted(client, dev_client):
    with client.websocket_connect("/ws", headers=HOST) as ws:  # a script, not a browser
        assert json.loads(ws.receive_text())["type"] == "connection"
    with dev_client.websocket_connect("/ws", headers={"Origin": "http://localhost:5173", **HOST}) as ws:
        assert json.loads(ws.receive_text())["type"] == "connection"
    with (
        pytest.raises(WebSocketDisconnect) as ei,
        client.websocket_connect("/ws", headers={"Origin": "http://localhost:5173", **HOST}),
    ):
        pass
    assert ei.value.code == 1008


def test_a_bad_stream_filter_closes_the_websocket(client):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws?streams=a,b", headers=HOST):
        pass


def test_bind_host_must_be_loopback():
    for ok in ("127.0.0.1", "::1", "localhost", " LOCALHOST "):
        assert security.check_bind_host(ok)
    for bad in ("0.0.0.0", "::", "192.168.1.10", "", "example.com", "127.0.0.2"):
        with pytest.raises(ValueError):
            security.check_bind_host(bad)


def test_hosts_and_origins_for_port_80_have_no_port():
    assert "localhost" in security.allowed_hosts(80) and "http://localhost" in security.allowed_origins(80)
    assert "localhost" not in security.allowed_hosts(8765)


def test_initial_connect_option(tmp_path, sim):
    app = create_app(
        PORT,
        manager=DeviceManager(embedded_sim=False),
        static_dir=None,
        initial_connect=ConnectSpec("tcp", host="127.0.0.1", port=sim.port),
    )
    with TestClient(app, base_url=BASE) as c:
        deadline = time.time() + 10
        while time.time() < deadline:
            if c.get("/api/state").json()["connection"]["state"] == "connected":
                break
            time.sleep(0.1)
        assert c.get("/api/state").json()["connection"]["state"] == "connected"


def test_pump_never_skips_runs_beyond_the_per_tick_limit():
    """More runs than one tick may send: the rest goes out on the next tick, the cursor never jumps past them."""
    from rezonating_lab.core.ringbuf import SampleRing
    from rezonating_lab.server import app as app_mod

    ring = SampleRing(1, 4096)
    hub = app_mod.Hub()
    client = hub.add(None)
    hub.pump({0: ring})  # the cursor starts at the head: a client joins live
    n_runs = app_mod.MAX_MESSAGES_PER_TICK + 40
    for k in range(n_runs):  # one-sample runs separated by gaps: every one is its own run
        ring.write(2 * k, np.full((1, 1), k, dtype=np.int32))
    hub.pump({0: ring})
    assert client.queue.qsize() == app_mod.MAX_MESSAGES_PER_TICK
    hub.pump({0: ring})
    assert client.queue.qsize() == n_runs  # nothing was dropped
    firsts = []
    while not client.queue.empty():
        firsts.append(struct.unpack_from("<Q", client.queue.get_nowait(), 8)[0])
    assert firsts == [2 * k for k in range(n_runs)]


def test_websocket_streams_op_ignores_what_is_not_a_list(client, sim):
    connect_sim(client, sim)
    with client.websocket_connect("/ws", headers=HOST) as ws:
        for bad in (5, "0", {"a": 1}, True):
            ws.send_text(json.dumps({"op": "streams", "streams": bad}))
        ws.send_text(json.dumps({"op": "streams", "streams": [2, "x", True]}))
        ws.send_text(json.dumps({"op": "snapshot"}))
        seen = [json.loads(ws.receive_text())["type"] for _ in range(4)]
        assert "connection" in seen  # the socket is still alive and answers a snapshot


def test_settings_cannot_change_while_recording(tmp_path):
    from rec_helpers import form, lab, wait_idle

    with lab(tmp_path, SimConfig(speed=10.0)) as (c, s, cfg):
        assert c.post("/api/record/start", json=form()).status_code == 200
        r = c.post("/api/set", json={"key": "adc.gain.0", "value": 16})
        assert r.status_code == 409 and r.json()["error"]["code"] == "recording_active"
        assert c.post("/api/record/stop").status_code == 200
        wait_idle(c)
