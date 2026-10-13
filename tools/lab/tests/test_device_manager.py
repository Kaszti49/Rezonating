"""DeviceManager against the simulator: TCP, pyserial socket:// URLs, commands, errors, transport switching."""

import socket
import time

import pytest
from rezonating_lab.server.device import ConnectSpec, DeviceError, DeviceManager, parse_connect_arg, stream_mask_of
from rezonating_lab.sim.faults import FaultConfig
from rezonating_lab.sim.node import SimConfig
from rezonating_lab.sim.server import SimThread

ALL = 0b111


class Events:
    """Thread-safe collector for the manager's events."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def __call__(self, ev: dict) -> None:
        self.items.append(ev)

    def of(self, kind: str) -> list[dict]:
        return [e for e in list(self.items) if e["type"] == kind]


@pytest.fixture
def events():
    return Events()


@pytest.fixture
def sim():
    with SimThread(SimConfig(speed=10.0)) as s:
        yield s


@pytest.fixture
def manager(events):
    m = DeviceManager(emit=events, embedded_sim=False)
    m.start()
    yield m
    m.close()


def tcp(sim):
    return ConnectSpec("tcp", host="127.0.0.1", port=sim.port)


def serial_url(sim):
    return ConnectSpec("serial", url=f"socket://127.0.0.1:{sim.port}")


def last_status(events):
    return events.of("status")[-1]


def stream_of(status, name):
    return next(s for s in status["streams"] if s["name"] == name)


def run_for(manager, seconds):
    time.sleep(seconds)
    manager.submit(lambda: None).result(5)  # a round trip through the worker: everything received so far is handled


def finish(manager, events):
    """STOP everything and return the final status event."""
    manager.stop_streams(ALL).result(10)
    return last_status(events)


# ------------------------------------------------------------------------------------------ connecting


def test_connect_over_tcp_start_stop_with_exact_accounting(manager, sim, events):
    assert manager.connect(tcp(sim)).result(10)["state"] == "connected"
    assert [e["state"] for e in events.of("connection")][-1] == "connected"
    hello, config = events.of("hello")[0], events.of("config")[0]
    assert hello["node_id"] == "rzn-sim001" and [s["name"] for s in hello["streams"]] == ["adc_raw", "adc_dec", "accel"]
    assert config["streams"][0]["channels"][0] == {
        "gain": 8,
        "scale": pytest.approx(1.2 / 8 / 2**23, rel=1e-6),
        "units": "V",
    }
    assert hello["heads"] and hello["heads"][0]["descriptor"] is not None

    manager.start_streams(ALL).result(10)
    run_for(manager, 1.5)
    st = finish(manager, events)
    assert st["acquiring"] is False and st["recording"] is False
    for name in ("adc_raw", "adc_dec", "accel"):
        s = stream_of(st, name)
        loss = s["loss"]
        assert loss["host"] == 0 and loss["device"] == 0 and loss["link"] == 0
        assert loss["final"] is True and loss["incomplete"] is False and loss["window"] > 1000
        assert loss["received"] == loss["window"]
        assert manager.rings[s["id"]].written == loss["received"]  # every sample is in the ring, at its own index
    assert st["link"]["bad_frames"] == 0 and st["link"]["lost_frames"] == 0
    assert st["link"]["rtt_ms"] is not None and st["link"]["type"] == "tcp"


def test_connect_over_a_pyserial_socket_url(manager, sim, events):
    manager.connect(serial_url(sim)).result(10)
    assert events.of("connection")[-1]["link"] == "serial"
    manager.start_streams(0b100).result(10)
    run_for(manager, 1.0)
    st = finish(manager, events)
    accel = stream_of(st, "accel")
    assert accel["loss"]["host"] == 0 and accel["loss"]["final"] and accel["loss"]["window"] > 500
    assert st["link"]["type"] == "serial" and st["link"]["target"].startswith("socket://")


def test_status_event_carries_rates_offsets_levels_and_health(manager, sim, events):
    manager.connect(tcp(sim)).result(10)
    manager.start_streams(ALL).result(10)
    time.sleep(2.2)
    st = last_status(events)
    s = stream_of(st, "adc_raw")
    assert s["running"] is True
    assert s["rate_hz_status"] == pytest.approx(2016.0, rel=0.002)
    assert s["offset_pct_status"] == pytest.approx(0.8, abs=0.05) and s["offset_pct_fit"] == pytest.approx(0.8, abs=0.1)
    assert s["levels"] and s["levels"][0]["units"] == "V" and s["levels"][0]["peak"] > 0
    assert st["health"]["temp_c"] == pytest.approx(41.0, abs=1) and 0 <= st["health"]["queue_fill"] < 50
    assert st["acquiring"] is True and st["link"]["rx_bytes_per_s"] > 10_000
    accel = stream_of(st, "accel")
    assert accel["levels"][2]["mean"] == pytest.approx(1.0, abs=0.05) and accel["levels"][2]["units"] == "g"
    manager.stop_streams(ALL).result(10)


def test_status_events_arrive_about_once_per_second(manager, sim, events):
    manager.connect(tcp(sim)).result(10)
    n0 = len(events.of("status"))
    time.sleep(3.3)
    assert 2 <= len(events.of("status")) - n0 <= 5


def test_connect_failure_is_a_clear_error_and_leaves_the_manager_usable(manager, sim, events):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead_port = s.getsockname()[1]
    with pytest.raises(DeviceError) as ei:
        manager.connect(ConnectSpec("tcp", host="127.0.0.1", port=dead_port)).result(10)
    assert ei.value.code == "connect_failed" and str(dead_port) in ei.value.message
    assert events.of("connection")[-1]["state"] == "disconnected" and events.of("connection")[-1]["error"]
    assert events.of("error")[-1]["code"] == "connect_failed"
    manager.connect(tcp(sim)).result(10)  # still works afterwards


def test_commands_need_a_connection(manager):
    with pytest.raises(DeviceError) as ei:
        manager.start_streams(ALL).result(5)
    assert ei.value.code == "not_connected"


def test_liveness_ping_keeps_the_session_alive(events):
    with SimThread(SimConfig(speed=1.0, liveness_s=1.0)) as sim:
        m = DeviceManager(emit=events, embedded_sim=False)
        m.start()
        try:
            m.connect(tcp(sim)).result(10)
            time.sleep(3.5)  # three liveness periods with nothing to do but PING
            assert sim.node.active is not None
            assert events.of("connection")[-1]["state"] == "connected"
        finally:
            m.close()


def test_embedded_simulator_starts_when_none_is_listening(events):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    m = DeviceManager(emit=events, embedded_sim=True)
    m.start()
    try:
        m.connect(ConnectSpec("sim", port=free)).result(15)
        c = events.of("connection")[-1]
        assert c["state"] == "connected" and c["embedded_sim"] is True and c["target"] == f"127.0.0.1:{free}"
        assert any("embedded" in e["msg"] for e in events.of("log"))
        m.start_streams(0b001).result(10)
        run_for(m, 0.6)
        m.stop_streams(0b001).result(10)
        assert stream_of(last_status(events), "adc_raw")["loss"]["host"] == 0
    finally:
        m.close()
    with pytest.raises(OSError), socket.create_connection(("127.0.0.1", free), timeout=1):
        pass  # the embedded simulator is gone after close()


def test_embedded_simulator_can_be_disabled(events):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    m = DeviceManager(emit=events, embedded_sim=False)
    m.start()
    try:
        with pytest.raises(DeviceError) as ei:
            m.connect(ConnectSpec("sim", port=free)).result(10)
        assert ei.value.code == "connect_failed"
    finally:
        m.close()


# ---------------------------------------------------------------------------------- commands and errors


def test_set_gain_while_idle_updates_the_config_event(manager, sim, events):
    manager.connect(tcp(sim)).result(10)
    manager.set_value("adc.gain.0", 32).result(10)
    cfg = events.of("config")[-1]
    assert cfg["streams"][0]["channels"][0]["gain"] == 32
    assert cfg["streams"][0]["channels"][0]["scale"] == pytest.approx(1.2 / 32 / 2**23, rel=1e-6)
    assert cfg["streams"][0]["channels"][1]["gain"] == 8
    manager.set_value("accel.range_g", 8).result(10)
    assert events.of("config")[-1]["accel_range_g"] == 8
    info = manager.stream_info(0)
    assert info["gain"] == [32, 8] and info["scale"][0] == pytest.approx(1.2 / 32 / 2**23, rel=1e-6)


def test_err_5_while_acquiring_reaches_the_ui_as_a_clear_error(manager, sim, events):
    manager.connect(tcp(sim)).result(10)
    manager.start_streams(0b001).result(10)
    with pytest.raises(DeviceError) as ei:
        manager.set_value("adc.gain.1", 16).result(10)
    err = ei.value
    assert err.code == "busy" and err.node_code == 5 and err.http == 409
    assert "acquiring" in err.message and "Stop acquisition" in err.message and "adc.gain.1" in err.message
    ev = events.of("error")[-1]
    assert (
        ev["code"] == "busy" and ev["node_code"] == 5 and ev["id"] == err.event_id and ev["command"] == "set adc.gain.1"
    )
    # accel is a different sensor: its range may change while only the ADC runs
    manager.set_value("accel.range_g", 4).result(10)
    manager.stop_streams(0b001).result(10)
    manager.set_value("adc.gain.1", 16).result(10)  # allowed again once idle


def test_bad_values_and_keys(manager, sim):
    manager.connect(tcp(sim)).result(10)
    with pytest.raises(DeviceError) as ei:
        manager.set_value("adc.gain.0", 3).result(10)
    assert ei.value.code == "bad_value" and ei.value.node_code == 4
    with pytest.raises(DeviceError) as ei:
        manager.set_value("wifi.ssid", 1).result(10)
    assert ei.value.code == "unknown_key" and ei.value.http == 400  # not settable from the UI
    with pytest.raises(DeviceError):
        manager.start_streams(0).result(10)
    with pytest.raises(DeviceError):
        manager.stop_streams(0b1000).result(10)


def test_disconnect_stops_the_streams_politely(manager, sim, events):
    manager.connect(tcp(sim)).result(10)
    manager.start_streams(ALL).result(10)
    run_for(manager, 0.5)
    manager.disconnect().result(10)
    assert events.of("connection")[-1]["state"] == "disconnected"
    assert not any(st.sending for st in sim.node.streams.values())  # the node saw the STOP
    final = last_status(events)
    assert all(s["loss"]["final"] and s["loss"]["host"] == 0 for s in final["streams"])
    assert manager.rings[0].written > 0  # the data stays viewable after disconnect


def test_device_and_link_losses_are_reported_separately(events):
    cfg = SimConfig(speed=10.0, faults=FaultConfig(device_drop_rate=0.002, link_drop_rate=0.05), seed=3)
    with SimThread(cfg) as sim:
        m = DeviceManager(emit=events, embedded_sim=False)
        m.start()
        try:
            m.connect(tcp(sim)).result(10)
            m.start_streams(0b001).result(10)
            run_for(m, 2.0)
            m.stop_streams(0b001).result(10)
            loss = stream_of(last_status(events), "adc_raw")["loss"]
            assert loss["device"] > 0 and loss["link"] > 0 and loss["host"] == 0 and loss["final"]
            ring = m.rings[0]
            lo, data, valid = ring.read(0, ring.head)
            assert int((~valid).sum()) == loss["device"] + loss["link"]  # gaps in the ring = counted losses
        finally:
            m.close()


# ------------------------------------------------------------------------------------ transport switch


def test_switching_transport_gives_fresh_accounting(manager, sim, events):
    manager.connect(tcp(sim)).result(10)
    manager.start_streams(ALL).result(10)
    run_for(manager, 1.2)
    epoch_before = manager.rings[0].epoch
    # switch to the same node over a pyserial URL while streaming: no explicit disconnect
    manager.connect(serial_url(sim)).result(15)
    assert events.of("connection")[-1]["link"] == "serial"
    assert all(ring.head == 0 and ring.epoch > epoch_before - 1 for ring in manager.rings.values())
    assert manager.rings[0].epoch != epoch_before
    st = last_status(events)
    assert all(s["loss"] is None and not s["running"] for s in st["streams"])  # nothing carried over
    manager.start_streams(ALL).result(10)
    run_for(manager, 1.2)
    st = finish(manager, events)
    for s in st["streams"]:
        loss = s["loss"]
        assert loss["win_first"] == 0 and loss["host"] == 0 and loss["final"]  # the old window is gone
        assert loss["received"] == loss["window"] == manager.rings[s["id"]].written
        assert manager.rings[s["id"]].base == 0


def test_cable_pull_then_reconnect_does_not_count_the_left_over_window(manager, sim, events):
    """Abrupt switch (no STOP, like a killed PC): the sim keeps the old session and streams running."""
    manager.connect(serial_url(sim)).result(10)
    manager.start_streams(ALL).result(10)
    run_for(manager, 1.0)
    old_window_end = stream_of(last_status(events), "adc_raw")["loss"]["win_end"]
    assert old_window_end > 1000
    manager.submit(lambda: manager._client.transport.close()).result(5)  # pull the cable
    deadline = time.time() + 5
    while events.of("connection")[-1]["state"] != "disconnected" and time.time() < deadline:
        time.sleep(0.05)
    assert events.of("connection")[-1]["state"] == "disconnected" and "lost" in events.of("connection")[-1]["error"]
    assert events.of("error")[-1]["code"] == "link_lost"
    assert any(st.sending for st in sim.node.streams.values())  # the node never saw the close (USB rules)
    # the last window is still viewable and marked incomplete
    lost = stream_of(last_status(events), "adc_raw")["loss"]
    assert lost["incomplete"] is True and manager.rings[0].written > 0

    manager.connect(tcp(sim)).result(15)  # the other way, to the same node, inside its 5 s liveness window
    assert not any(st.sending for st in sim.node.streams.values())  # the clean-up STOP ran
    manager.start_streams(ALL).result(10)
    run_for(manager, 0.5)
    st = finish(manager, events)
    for s in st["streams"]:
        loss = s["loss"]
        assert loss["host"] == 0 and loss["final"] and not loss["incomplete"]
        assert loss["win_first"] == 0 and loss["window"] < old_window_end  # a new window, not the stale one
        assert loss["received"] == loss["window"]


def test_lost_clean_up_stop_ack_after_connect_forces_the_next_start(events, monkeypatch):
    """If the clean-up STOP cannot be confirmed the first START is forced and the log says so."""
    from rezonating_lab.link.codec import Ack
    from rezonating_lab.server import device

    state = {"drop": False}

    def fault(msg) -> bool:
        if state["drop"] and isinstance(msg, Ack):
            state["drop"] = False
            return True  # corrupt the clean-up STOP's ACK on the wire
        return False

    real_clean_stop = device.session.clean_stop

    def arming_clean_stop(*args, **kwargs):
        state["drop"] = True
        return real_clean_stop(*args, **kwargs)

    monkeypatch.setattr(device.session, "clean_stop", arming_clean_stop)
    monkeypatch.setattr(device.session, "CLEAN_STOP_TIMEOUT_S", 0.3)
    with SimThread(SimConfig(speed=10.0, control_fault=fault)) as sim:
        m = DeviceManager(emit=events, embedded_sim=False)
        m.start()
        try:
            m.connect(tcp(sim)).result(10)
            assert any("not acknowledged" in e["msg"] for e in events.of("log"))
            m.start_streams(0b001).result(10)
            run_for(m, 1.0)
            m.stop_streams(0b001).result(10)
            loss = stream_of(last_status(events), "adc_raw")["loss"]
            assert loss["host"] == 0 and loss["final"]
        finally:
            m.close()


# ---------------------------------------------------------------------------------------------- helpers


def test_parse_connect_arg():
    assert parse_connect_arg("sim").kind == "sim"
    s = parse_connect_arg("tcp:192.168.1.7:7350")
    assert (s.kind, s.host, s.port) == ("tcp", "192.168.1.7", 7350)
    assert parse_connect_arg("serial:COM5").url == "COM5"
    assert parse_connect_arg("serial:socket://127.0.0.1:7350").url == "socket://127.0.0.1:7350"
    for bad in ("", "tcp", "usb:COM5", "sim:foo"):
        with pytest.raises(ValueError):
            parse_connect_arg(bad)


def test_connect_spec_validation_refuses_odd_serial_urls():
    for url in ("file:///etc/passwd", "rfc2217://host:1", "loop://", "COM5; rm -rf /"):
        with pytest.raises(DeviceError):
            ConnectSpec("serial", url=url).validate()
    ConnectSpec("serial", url="COM12").validate()
    ConnectSpec("serial", url="/dev/ttyACM0").validate()
    ConnectSpec("serial", url="socket://127.0.0.1:7350").validate()
    with pytest.raises(DeviceError):
        ConnectSpec("tcp").validate()
    with pytest.raises(DeviceError):
        ConnectSpec("tcp", host="x", key=b"short").validate()


def test_stream_mask_of():
    names = {0: "adc_raw", 1: "adc_dec", 2: "accel"}
    assert stream_mask_of(None, names) == 0b111 and stream_mask_of([], names) == 0b111
    assert stream_mask_of(["accel", 0], names) == 0b101
    assert stream_mask_of(["1"], names) == 0b010
    for bad in (["nope"], [7], [True]):
        with pytest.raises(DeviceError):
            stream_mask_of(bad, names)
