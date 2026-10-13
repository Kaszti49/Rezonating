"""The phone marker listener: token handling, identical 404s, nothing but /m/<token> on the LAN port."""

from __future__ import annotations

import asyncio
import hmac
import json
import socket
import time

import httpx
import pytest
import websockets
from rec_helpers import FORM, PORT, form, lab, wait_idle
from rezonating_lab.recorder import marker as mk
from rezonating_lab.recorder.marker import MarkerApp, MarkerServer, MarkRefused, TokenStore, parse_marker_path
from rezonating_lab.recorder.recording import Recorder
from rezonating_lab.sim.node import SimConfig
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


class FakeSink:
    def __init__(self) -> None:
        self.marks: list[tuple[str, float, float]] = []
        self.listeners: list = []
        self.refuse = False

    def mark_from_phone(self, edge, arrival_us, rtt_ms):
        if self.refuse:
            raise MarkRefused("mark_open", "A mark is already open; end it first.")
        self.marks.append((edge, arrival_us, rtt_ms))
        return {"id": len(self.marks)}

    def marker_state(self):
        return {"recording": True, "marking": bool(self.marks and self.marks[-1][0] == "start"), "n_labels": 0}

    def add_state_listener(self, fn):
        self.listeners.append(fn)

    def remove_state_listener(self, fn):
        self.listeners.remove(fn)


@pytest.fixture
def parts():
    tokens, sink = TokenStore(), FakeSink()
    app = MarkerApp(tokens, sink, lambda: time.perf_counter() * 1e6)
    return tokens, sink, app


def signature(r: httpx.Response) -> tuple:
    return r.status_code, r.content, tuple(sorted((k, v) for k, v in r.headers.items() if k != "date"))


# -------------------------------------------------------------------------------- token and paths


def test_token_has_at_least_128_bits_and_is_unique_and_compared_in_constant_time(monkeypatch):
    a, b = TokenStore(), TokenStore()
    assert mk.TOKEN_BYTES * 8 >= 128 and a.token != b.token and len(a.token) >= 22
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(mk.hmac, "compare_digest", lambda x, y: calls.append(1) or real(x, y))
    assert a.matches(a.token) and not a.matches(b.token) and not a.matches("x" * 500) and not a.matches("")
    assert len(calls) == 4  # every guess goes through compare_digest
    a.revoke()
    assert not a.matches(a.token) and not a.alive


@pytest.mark.parametrize(
    "path,expect",
    [
        ("/m/abc", ("abc", False)),
        ("/m/abc/ws", ("abc", True)),
        ("/m/abc/", None),
        ("/m/abc/ws/x", None),
        ("/m//ws", None),
        ("/", None),
        ("/api/state", None),
        ("/m/a b", None),
        ("/M/abc", None),
        ("/m/" + "a" * 65, None),
    ],
)
def test_path_parsing(path, expect):
    assert parse_marker_path(path) == expect


# ----------------------------------------------------------------------------- identical 404s (HTTP)


def test_every_failure_is_the_same_404_and_the_page_needs_the_token(parts):
    tokens, sink, app = parts
    with TestClient(app, base_url="http://testserver") as c:
        good = c.get(f"/m/{tokens.token}")
        assert good.status_code == 200 and "text/html" in good.headers["content-type"]
        assert (
            "frame-ancestors 'none'" in good.headers["content-security-policy"]
            and good.headers["cache-control"] == "no-store"
        )
        bad_paths = [
            "/m/not-the-token",
            f"/m/{tokens.token[:-1]}",
            f"/m/{tokens.token}x",
            "/m/",
            "/",
            "/api/state",
            "/api/record/marker",
            "/ws",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/static/index.html",
            "/assets/app.js",
            f"/m/{tokens.token}/api/state",
            f"/m/{tokens.token}/",
            f"/m/{tokens.token}/ws",  # a plain GET on the WebSocket path
            "/m/%00",
            "/m/../api/state",
            "//m/" + tokens.token,
        ]
        sigs = {signature(c.get(p)) for p in bad_paths}
        assert len(sigs) == 1, "bad token, unknown path and wrong route must look exactly alike"
        status, body, _ = next(iter(sigs))
        assert status == 404 and body == b"Not Found"
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
            r = c.request(method, f"/m/{tokens.token}")
            assert r.status_code == 404 and r.content in (b"Not Found", b""), method


def test_expired_token_gets_the_same_404_as_a_wrong_one(parts):
    tokens, _, app = parts
    token = tokens.token
    with TestClient(app, base_url="http://testserver") as c:
        assert c.get(f"/m/{token}").status_code == 200
        tokens.revoke()  # what the end of the recording does
        expired = c.get(f"/m/{token}")
        wrong = c.get("/m/never-valid")
        assert signature(expired) == signature(wrong) and expired.status_code == 404
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(f"/m/{token}/ws"):
                pass


# ---------------------------------------------------------------------------------------- WebSocket


def test_websocket_requires_token_and_same_origin(parts):
    tokens, _, app = parts
    with TestClient(app, base_url="http://testserver") as c:
        for path in ("/m/wrong/ws", "/ws", "/api/ws", f"/m/{tokens.token}/other"):
            with pytest.raises(WebSocketDisconnect):
                with c.websocket_connect(path):
                    pass
        with pytest.raises(WebSocketDisconnect):  # right token, page from another origin
            with c.websocket_connect(f"/m/{tokens.token}/ws", headers={"Origin": "http://evil.example"}):
                pass
        with c.websocket_connect(f"/m/{tokens.token}/ws", headers={"Origin": "http://testserver"}) as ws:
            assert ws.receive_json()["op"] == "state"


def test_websocket_ping_mark_and_input_checks(parts):
    tokens, sink, app = parts
    with TestClient(app, base_url="http://testserver") as c, c.websocket_connect(f"/m/{tokens.token}/ws") as ws:
        assert ws.receive_json() == {"op": "state", "recording": True, "marking": False, "n_labels": 0}
        ws.send_json({"op": "ping", "id": 5})
        assert ws.receive_json() == {"op": "pong", "id": 5}
        ws.send_json({"op": "mark", "edge": "start", "rtt_ms": 42.5})
        ack = ws.receive_json()
        assert ack["ok"] and ack["id"] == 1 and sink.marks[0][0] == "start" and sink.marks[0][2] == 42.5
        for bad in (
            {"op": "mark", "edge": "start"},
            {"op": "mark", "edge": "start", "rtt_ms": -1},
            {"op": "mark", "edge": "start", "rtt_ms": 99999},
            {"op": "mark", "edge": "start", "rtt_ms": "5"},
            {"op": "mark", "edge": "nope", "rtt_ms": 5},
        ):
            ws.send_json(bad)
            r = ws.receive_json()
            assert r["ok"] is False and r["code"] in ("rtt_required", "bad_edge")
        assert len(sink.marks) == 1
        sink.refuse = True
        ws.send_json({"op": "mark", "edge": "start", "rtt_ms": 10})
        assert ws.receive_json()["code"] == "mark_open"
        ws.send_text("not json")
        ws.send_json(["list"])
        ws.send_json({"op": "ping", "id": 6})
        assert ws.receive_json() == {"op": "pong", "id": 6}


def test_websocket_state_is_pushed_and_message_flood_is_cut(parts):
    tokens, sink, app = parts
    with TestClient(app, base_url="http://testserver") as c, c.websocket_connect(f"/m/{tokens.token}/ws") as ws:
        ws.receive_json()
        sink.listeners[0]({"recording": True, "marking": True, "n_labels": 3})
        assert ws.receive_json() == {"op": "state", "recording": True, "marking": True, "n_labels": 3}
        with pytest.raises(WebSocketDisconnect):
            for i in range(mk.MAX_MESSAGES_PER_S + 30):
                ws.send_json({"op": "ping", "id": i})
            for _ in range(mk.MAX_MESSAGES_PER_S + 30):
                ws.receive_json()
    assert sink.listeners == []


# ------------------------------------------------------------------------ a real listener on a port


def test_real_listener_serves_only_the_marker_and_stops_with_the_token(parts):
    tokens, sink, app = parts
    server = MarkerServer(app, "127.0.0.1", 0)
    port = server.start()
    base = f"http://127.0.0.1:{port}"
    try:
        assert httpx.get(f"{base}/m/{tokens.token}").status_code == 200
        probes = ["/api/state", "/api/record/marker", "/ws", "/docs", "/openapi.json", "/", "/m/wrong", "/assets/x.js"]
        assert len({signature(httpx.get(base + p)) for p in probes}) == 1
        assert all(httpx.get(base + p).status_code == 404 for p in probes)

        async def probes_ws() -> list[str]:
            out = []
            for p in ("/ws", "/api/state", "/m/wrong/ws"):
                with pytest.raises(websockets.exceptions.InvalidStatus) as exc:
                    async with websockets.connect(f"ws://127.0.0.1:{port}{p}"):
                        pass
                out.append(str(exc.value.response.status_code))
            async with websockets.connect(f"ws://127.0.0.1:{port}/m/{tokens.token}/ws") as ws:
                assert json.loads(await ws.recv())["op"] == "state"
                await ws.send(json.dumps({"op": "mark", "edge": "end", "rtt_ms": 20}))
                assert json.loads(await ws.recv())["ok"] is True
            return out

        assert asyncio.run(probes_ws()) == ["404", "404", "404"]
    finally:
        server.stop()
    assert not tokens.alive
    with pytest.raises(httpx.TransportError):
        httpx.get(f"{base}/m/{tokens.token}", timeout=2)  # the port is closed with the recording


# ----------------------------------------------------------- through the recorder, on the Lab server


def test_marker_lives_and_dies_with_the_recording_and_exposes_no_lab_endpoints(tmp_path):
    with lab(tmp_path, SimConfig(speed=10.0)) as (client, sim, cfg):
        assert client.get("/api/record/marker").json()["active"] is False
        assert client.get("/api/record/marker/qr.svg").status_code == 404
        r = client.post("/api/record/start", json=form(marker=True))
        assert r.status_code == 200, r.text
        info = client.get("/api/record/marker").json()
        assert info["active"] and "/m/" in info["url"] and info["url"].startswith("http://")
        assert info["qr_svg"].startswith("<svg") and info["hosts"] is not None
        qr = client.get("/api/record/marker/qr.svg")
        assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml")
        other = client.get("/api/record/marker", params={"host": "203.0.113.9"})
        assert other.status_code == 400 and other.json()["error"]["code"] == "bad_marker_host"
        assert info["hosts"] == [info["host"]]  # one bound address, so one address to offer
        base = f"http://127.0.0.1:{info['port']}"
        token = info["url"].rsplit("/", 1)[1]
        assert httpx.get(f"{base}/m/{token}").status_code == 200
        for p in ("/api/state", "/api/record/state", "/api/record/marker", "/api/health", "/ws", "/api/docs", "/"):
            r = httpx.get(base + p)
            assert r.status_code == 404 and r.content == b"Not Found", p
        # the Lab server itself still refuses the marker's port in its Host check (and is not on that port)
        assert info["port"] != PORT
        client.post("/api/record/stop")
        wait_idle(client)
        with pytest.raises(httpx.TransportError):
            httpx.get(f"{base}/m/{token}", timeout=2)
        assert client.get("/api/record/marker").json()["active"] is False


def test_phone_mark_is_corrected_by_half_the_round_trip_and_gets_unc():
    rec = Recorder.__new__(Recorder)
    e = Recorder._edge(rec, "phone", 10_000_000.0, 100.0)
    assert e.host_us == 10_000_000.0 - 50_000.0 and e.rtt_ms == 100.0 and e.allowance_ms == 10.0
    k = Recorder._edge(rec, "key", 10_000_000.0, None)
    assert k.host_us == 10_000_000.0 and k.rtt_ms is None
    from rezonating_lab.recorder.labels import edge_unc_ms

    assert edge_unc_ms(e, clock_unc_us=400.0, sample_rate_hz=2000.0) == pytest.approx(0.4 + 50.0 + 10.0 + 0.25)
    assert FORM["marker"] is False


def test_phone_page_marks_on_the_touch_not_on_the_release():
    from rezonating_lab.recorder.marker import PAGE

    assert "addEventListener('pointerdown'" in PAGE
    assert "addEventListener('click',function(ev){if(ev.detail===0)fire()})" in PAGE  # only keyboard clicks (detail 0)


# ----------------------------------------------- one bound address: the URL names exactly what is listening

LAN = ["127.0.0.2", "127.0.0.3"]  # stand-ins for two interfaces (Ethernet and a VPN); both bind on loopback


@pytest.fixture
def two_interfaces(monkeypatch):
    monkeypatch.setattr(mk, "lan_addresses", lambda: list(LAN))
    for addr in LAN:  # the whole 127/8 is loopback on Windows and Linux; skip where it is not
        probe = socket.socket()
        try:
            probe.bind((addr, 0))
        except OSError:
            pytest.skip(f"cannot bind {addr} here")
        finally:
            probe.close()
    return LAN


def reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def test_describe_marker_only_ever_names_the_bound_address(two_interfaces):
    d = mk.describe_marker("TOK", 5000, "127.0.0.2", None)
    assert d["host"] == "127.0.0.2" and d["hosts"] == ["127.0.0.2"] and d["url"] == "http://127.0.0.2:5000/m/TOK"
    # the config's marker_host (advertised) cannot override the bound address either
    assert mk.describe_marker("TOK", 5000, "127.0.0.2", "192.168.99.99", None)["url"] == d["url"]
    assert mk.describe_marker("TOK", 5000, "127.0.0.2", None, "127.0.0.2")["url"] == d["url"]
    for bad in ("127.0.0.3", "192.168.99.99"):  # another interface of this PC is as wrong as a foreign address
        with pytest.raises(mk.MarkerHostError):
            mk.describe_marker("TOK", 5000, "127.0.0.2", None, bad)


def test_describe_marker_offers_the_candidates_only_when_every_interface_is_bound(two_interfaces):
    d = mk.describe_marker("TOK", 5000, "0.0.0.0", None)
    assert d["hosts"] == LAN and d["host"] == LAN[0]
    assert mk.describe_marker("TOK", 5000, "0.0.0.0", None, LAN[1])["url"] == "http://127.0.0.3:5000/m/TOK"
    assert mk.describe_marker("TOK", 5000, "0.0.0.0", "10.1.1.1")["host"] == "10.1.1.1"  # config marker_host
    with pytest.raises(mk.MarkerHostError):
        mk.describe_marker("TOK", 5000, "0.0.0.0", None, "203.0.113.9")


def test_choose_bind_takes_one_current_address_and_never_a_wildcard_from_the_form(two_interfaces):
    assert mk.choose_bind("auto", None) == LAN[0]  # the default route's pick
    assert mk.choose_bind("auto", LAN[1]) == LAN[1]
    assert mk.choose_bind("auto", "127.0.0.1") == "127.0.0.1"
    assert mk.choose_bind("0.0.0.0", None) == "0.0.0.0"  # only when the config says so
    assert mk.choose_bind("0.0.0.0", LAN[1]) == LAN[1]  # and a person may narrow it to one interface
    for bad in ("203.0.113.9", "0.0.0.0", "::", "example.org", "10.0.0.1/8"):
        for cfg_bind in ("auto", "0.0.0.0", "127.0.0.1"):
            with pytest.raises(mk.MarkerHostError):
                mk.choose_bind(cfg_bind, bad)
    assert mk.marker_hosts("auto") == LAN and mk.marker_hosts("0.0.0.0") == LAN
    assert mk.marker_hosts("127.0.0.1") == [*LAN, "127.0.0.1"]


def test_options_list_the_interfaces_and_start_binds_the_chosen_one(tmp_path, two_interfaces):
    with lab(tmp_path, SimConfig(speed=10.0), marker_bind="auto") as (client, sim, cfg):
        opt = client.get("/api/record/options").json()["marker"]
        assert opt["hosts"] == LAN and opt["bind"] == LAN[0]
        bad = client.post("/api/record/start", json=form(marker=True, marker_host="203.0.113.9"))
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "bad_marker_host"
        assert bad.json()["error"]["details"][0]["loc"] == ["marker_host"]
        assert list(cfg.data_root.iterdir()) == [] and client.get("/api/record/state").json()["state"] == "idle"
        r = client.post("/api/record/start", json=form(marker=True, marker_host=LAN[1]))
        assert r.status_code == 200, r.text
        info = client.get("/api/record/marker").json()
        assert info["host"] == LAN[1] and info["hosts"] == [LAN[1]]
        assert info["url"].startswith(f"http://{LAN[1]}:{info['port']}/m/")
        assert reachable(LAN[1], info["port"]) and not reachable(LAN[0], info["port"])  # bound = URL, nothing else
        assert httpx.get(info["url"]).status_code == 200
        for path in ("/api/record/marker", "/api/record/marker/qr.svg"):
            refused = client.get(path, params={"host": LAN[0]})  # a real address of this PC, but not the bound one
            assert refused.status_code == 400 and refused.json()["error"]["code"] == "bad_marker_host", path
            assert LAN[1] in refused.json()["error"]["message"]
        assert client.get("/api/record/marker", params={"host": LAN[1]}).json()["url"] == info["url"]
        assert "Marker address refused" in json.dumps(client.get("/api/logs").json())
        client.post("/api/record/stop")
        wait_idle(client)


def test_start_without_marker_host_binds_the_default_route_address(tmp_path, two_interfaces):
    with lab(tmp_path, SimConfig(speed=10.0), marker_bind="auto") as (client, sim, cfg):
        assert client.post("/api/record/start", json=form(marker=True)).status_code == 200
        info = client.get("/api/record/marker").json()
        assert info["host"] == LAN[0] and info["hosts"] == [LAN[0]]
        assert reachable(LAN[0], info["port"]) and not reachable(LAN[1], info["port"])
        client.post("/api/record/stop")
        wait_idle(client)


def test_a_config_marker_host_cannot_point_the_qr_at_an_unbound_address(tmp_path, two_interfaces):
    with lab(tmp_path, SimConfig(speed=10.0), marker_bind="auto", marker_host="192.168.99.99") as (client, sim, cfg):
        assert client.post("/api/record/start", json=form(marker=True)).status_code == 200
        info = client.get("/api/record/marker").json()
        assert info["host"] == LAN[0] and "192.168.99.99" not in info["url"]
        client.post("/api/record/stop")
        wait_idle(client)


def test_explicit_wildcard_bind_keeps_offering_every_address(tmp_path, two_interfaces):
    with lab(tmp_path, SimConfig(speed=10.0), marker_bind="0.0.0.0") as (client, sim, cfg):
        assert client.get("/api/record/options").json()["marker"]["hosts"] == LAN
        assert client.post("/api/record/start", json=form(marker=True)).status_code == 200
        info = client.get("/api/record/marker").json()
        assert info["hosts"] == LAN and info["host"] == LAN[0]
        assert reachable("127.0.0.1", info["port"])  # genuinely listens on all
        other = client.get("/api/record/marker", params={"host": LAN[1]}).json()
        assert other["url"].startswith(f"http://{LAN[1]}:")
        assert client.get("/api/record/marker", params={"host": "203.0.113.9"}).status_code == 400
        client.post("/api/record/stop")
        wait_idle(client)
