"""The simulated node against PROTOCOL.md, driven without any transport (fake wall clock)."""

import json

import numpy as np
import pytest
from helpers import Pc, datas, make_node, of_type, run
from rezonating_lab.link import codec
from rezonating_lab.link.codec import (
    Ack,
    Auth,
    Config,
    Err,
    GetInfo,
    Hello,
    Ping,
    Pong,
    Reboot,
    SdRecord,
    Set,
    Start,
    Status,
    Stop,
)
from rezonating_lab.sim.faults import FaultConfig
from rezonating_lab.sim.node import SimConfig, SimNode

KEY = bytes(range(16))


def started(node, clock, **kw):
    pc = Pc(node)
    pc.send(GetInfo())
    pc.frames()
    return pc


def errs(frames):
    return [f.msg for f in frames if isinstance(f.msg, Err)]


# ------------------------------------------------------------------------------- session rules


def test_session_start_sequence_bytes():
    node, _ = make_node()
    pc = Pc(node)  # the PC writes one 0x00 first, then GET_INFO
    assert pc.take_bytes() == b""
    pc.send(GetInfo())
    data = pc.take_bytes()
    expected = b"\x00" + codec.encode_frame(node.build_hello(), 0) + codec.encode_frame(node.build_config(), 1)
    assert data == expected
    assert data[0] == 0x00 and data[1] != 0x00  # exactly one 0x00, then HELLO


def test_hello_and_config_contents():
    node, _ = make_node()
    pc = Pc(node)
    pc.send(GetInfo())
    hello, config = (f.msg for f in pc.frames())
    assert isinstance(hello, Hello) and isinstance(config, Config)
    assert hello.proto == 0
    by_id = {s.id: s for s in hello.streams}
    assert [(s.n_ch, s.nominal_hz, s.bits, s.clock) for s in by_id.values()] == [
        (2, 2000, 24, 0),
        (2, 1000, 24, 0),
        (3, 2000, 20, 1),
    ]
    assert by_id[0].fir_taps == by_id[0].fir_delay == 0 and by_id[2].fir_taps == 0
    assert by_id[1].fir_taps % 2 == 1  # PROTOCOL.md: fir_taps must be odd
    assert by_id[1].fir_delay == (by_id[1].fir_taps - 1) // 2
    assert [h.port for h in hello.heads] == [1, 2, 3]
    assert all(len(h.descriptor) <= 900 for h in hello.heads)
    scale = float(np.float32(1.2 / 8 / 2**23))
    assert config.streams[0].channels[0].scale == scale and config.streams[0].channels[0].units == codec.UNITS_V
    assert config.streams[2].channels[0].units == codec.UNITS_G
    assert config.accel_range_g == 2 and config.status_period_ms == 1000


def test_head_descriptors_pass_the_schema():
    jsonschema = pytest.importorskip("jsonschema")
    from pathlib import Path

    schema_path = Path(__file__).resolve().parents[3] / "schemas" / "head-descriptor.schema.json"
    if not schema_path.exists():
        pytest.skip("schemas/ not in this checkout")
    schema = json.loads(schema_path.read_text())
    node, _ = make_node()
    for head in node.build_hello().heads:
        jsonschema.validate(json.loads(head.descriptor), schema)


def test_usb_rules_ignore_everything_before_get_info():
    node, _ = make_node()
    pc = Pc(node)
    pc.send(Ping(5))
    pc.send(Start(1))
    pc.send(Auth(KEY))  # on USB, AUTH is accepted and ignored: it does not start a session
    assert pc.take_bytes() == b""


def test_status_every_period_with_continuing_seq():
    node, clock = make_node()
    pc = started(node, clock)
    run(node, clock, 3.05)
    frames = pc.frames()
    statuses = of_type(frames, Status)
    assert len(statuses) == 3
    assert [f.seq for f in frames] == [2, 3, 4]
    t = [f.msg.t_dev_us for f in statuses]
    assert all(abs((b - a) - 1_000_000) < 20_000 for a, b in zip(t, t[1:], strict=False))
    assert statuses[0].msg.rssi_dbm == 0  # Wi-Fi off in USB mode
    assert all(s.win_first == s.win_end == s.win_device == s.win_link == 0 for s in statuses[0].msg.streams)


def test_get_info_again_resets_the_seq_at_hello():
    node, clock = make_node()
    pc = started(node, clock)
    run(node, clock, 1.1)
    pc.frames()
    pc.send(GetInfo())
    frames = pc.frames()
    assert [type(f.msg).__name__ for f in frames] == ["Hello", "Config"] and [f.seq for f in frames] == [0, 1]
    assert not pc.raw.endswith(b"\x00\x00")  # no extra 0x00 in a live session


def test_ping_pong_echoes_host_time():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(Ping(123456789))
    (pong,) = of_type(pc.frames(), Pong)
    assert pong.msg.host_t_us == 123456789 and pong.msg.t_dev_us == node.now_dev_us()


def test_unknown_command_and_short_payload():
    node, clock = make_node()
    pc = started(node, clock)
    seq = pc.tx_seq
    pc.conn.feed(codec.to_wire(codec.encode_raw_frame(0x55, seq, b"")))
    pc.conn.feed(codec.to_wire(codec.encode_raw_frame(Start.TYPE_ID, seq + 1, b"")))
    e1, e2 = errs(pc.frames())
    assert (e1.cmd_seq, e1.code) == (seq, codec.ERR_UNKNOWN_COMMAND)
    assert (e2.cmd_seq, e2.code) == (seq + 1, codec.ERR_BAD_PAYLOAD)


def test_bad_stream_masks():
    node, clock = make_node()
    pc = started(node, clock)
    for msg in (Start(0), Start(0b1000), Stop(0), SdRecord(1, 0, "x")):
        seq = pc.send(msg)
        (e,) = errs(pc.frames())
        assert (e.cmd_seq, e.code) == (seq, codec.ERR_BAD_VALUE)


# ---------------------------------------------------------------------------- acquisition


def test_start_data_stop_with_final_status_before_ack():
    node, clock = make_node()
    pc = started(node, clock)
    seq = pc.send(Start(0b001))
    assert [f.msg for f in pc.frames()] == [Ack(seq)]
    run(node, clock, 2.0)
    frames = pc.frames()
    d = datas(frames, 0)
    assert not datas(frames, 1) and not datas(frames, 2)
    assert 45 <= len(d) <= 55  # about 25 DATA frames per second
    assert all(60 <= x.n <= 100 for x in d)
    assert d[0].first_sample == 0
    assert all(b.first_sample == a.first_sample + a.n for a, b in zip(d, d[1:], strict=False))  # contiguous, no drops
    assert d[0].samples.dtype == np.int32 and d[0].samples.shape[1] == 2
    # measured rate from the timestamps: nominal 2000 Hz plus the default +0.8 % clock error
    t = np.array([x.t_dev_us for x in d], float)
    idx = np.array([x.first_sample for x in d], float)
    rate = 1e6 / np.polyfit(idx, t, 1)[0]
    assert abs(rate - 2016.0) < 0.5

    stop_seq = pc.send(Stop(0b001))
    tail = pc.frames()
    assert [type(f.msg).__name__ for f in tail][-2:] == ["Status", "Ack"]
    final, ack = tail[-2].msg, tail[-1].msg
    assert ack == Ack(stop_seq)
    s0 = final.stream(0)
    received = sum(x.n for x in d) + sum(x.n for x in datas(tail, 0))
    assert s0.running == 0 and s0.win_first == 0 and s0.win_end == s0.produced == received
    assert s0.win_device == 0 and s0.win_link == 0
    run(node, clock, 0.5)
    assert not datas(pc.frames(), 0)  # nothing after STOP


def test_status_window_fields_and_rate():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(Start(0b111))
    run(node, clock, 3.05)
    last = of_type(pc.frames(), Status)[-1].msg
    for sid, nominal in ((0, 2000), (1, 1000), (2, 2000)):
        s = last.stream(sid)
        assert s.running == 1 and s.win_first == 0 and 0 < s.win_end <= s.produced
        expected = nominal * (1.008 if sid < 2 else 0.998)
        assert abs(s.rate_mhz / 1000 - expected) < 1.0
    # adc_dec reports the raw rate divided by 2
    assert abs(last.stream(1).rate_mhz * 2 - last.stream(0).rate_mhz) < 3000


def test_clock_error_option():
    node, clock = make_node(faults=FaultConfig(clock_error=0.0))
    pc = started(node, clock)
    pc.send(Start(0b001))
    run(node, clock, 2.05)
    s = of_type(pc.frames(), Status)[-1].msg.stream(0)
    assert abs(s.rate_mhz - 2_000_000) < 1000


def test_speed_option_scales_device_time():
    node, clock = make_node(speed=5.0)
    pc = started(node, clock)
    pc.send(Start(0b001))
    run(node, clock, 1.0)
    frames = pc.frames()
    assert len(of_type(frames, Status)) in (4, 5)  # STATUS follows the device clock: 5 device seconds
    s = of_type(frames, Status)[-1].msg.stream(0)
    assert s.produced > 8000
    assert 9500 < node.streams[0].produced < 10600  # 5 device seconds at about 2016 Hz


def test_indices_reset_only_from_fully_idle():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(Start(0b001))
    run(node, clock, 1.0)
    pc.frames()
    produced = node.streams[0].produced
    assert produced > 1900
    # starting adc_dec while adc_raw runs only turns sending on
    pc.send(Start(0b010))
    assert node.streams[0].produced >= produced
    assert node.streams[1].win_first == node.streams[1].produced > 0
    # stopping adc_raw keeps the ADC running for adc_dec
    pc.send(Stop(0b001))
    run(node, clock, 0.5)
    assert node.adc.running and node.streams[0].produced > produced
    # stopping the last consumer makes the ADC idle; the next START restarts the indices at 0
    pc.send(Stop(0b010))
    assert not node.adc.running
    pc.frames()
    pc.send(Start(0b001))
    st = of_type(pc.frames(), Ack)
    assert st and node.streams[0].produced == 0 and node.streams[0].win_first == 0
    run(node, clock, 0.2)
    assert datas(pc.frames(), 0)[0].first_sample == 0


def test_start_of_a_running_stream_is_a_no_op():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(Start(0b001))
    run(node, clock, 1.0)
    pc.frames()
    before = (node.streams[0].win_first, node.streams[0].produced)
    seq = pc.send(Start(0b001))
    assert [f.msg for f in pc.frames()] == [Ack(seq)]
    assert node.streams[0].win_first == before[0] and node.streams[0].produced >= before[1]


def test_sd_record_keeps_acquisition_running_after_link_stop_and_session_end():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(SdRecord(1, 0b001, "s1"))
    pc.send(Start(0b001))
    run(node, clock, 1.0)
    pc.frames()
    pc.send(Stop(0b001))
    assert node.adc.running  # SD_RECORD still needs it
    produced = node.streams[0].produced
    run(node, clock, 0.5)
    assert node.streams[0].produced > produced
    assert of_type(pc.frames(), Status)[-1].msg.sd_state == 2
    pc.send(SdRecord(0, 0b001, ""))
    assert not node.adc.running


def test_session_end_stops_link_streams():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(Start(0b111))
    run(node, clock, 1.0)
    pc.frames()
    clock.advance(5.1)
    node.tick()
    assert not node.active and not pc.conn.session_live
    assert not any(st.sending for st in node.streams.values())
    assert not node.adc.running and not node.accel.running
    # win_end frozen at produced, not lost
    assert all(st.win_end == st.produced for st in node.streams.values())


# --------------------------------------------------------------------------------------- SET


def test_set_gain_idle_then_busy():
    node, clock = make_node()
    pc = started(node, clock)
    seq = pc.send(Set("adc.gain.0", 16))
    ack, config = pc.frames()
    assert ack.msg == Ack(seq) and isinstance(config.msg, Config)
    assert config.msg.streams[0].channels[0].gain == 16
    assert config.msg.streams[0].channels[0].scale == float(np.float32(1.2 / 16 / 2**23))
    assert config.msg.streams[0].channels[1].gain == 8
    pc.send(Start(0b001))
    pc.frames()
    seq = pc.send(Set("adc.gain.1", 4))
    (e,) = pc.frames()
    assert e.msg == Err(seq, codec.ERR_BUSY, e.msg.msg)  # ERR only, no CONFIG
    seq = pc.send(Set("accel.range_g", 4))  # the accelerometer is idle
    assert [type(f.msg).__name__ for f in pc.frames()] == ["Ack", "Config"]


def test_set_errors():
    node, clock = make_node()
    pc = started(node, clock)
    for msg, code in (
        (Set("nope", 1), codec.ERR_UNKNOWN_KEY),
        (Set("adc.gain.0", 3), codec.ERR_BAD_VALUE),
        (Set("adc.gain.0", "8"), codec.ERR_BAD_VALUE),
        (Set("accel.range_g", 16), codec.ERR_BAD_VALUE),
        (Set("status.period_ms", 100), codec.ERR_BAD_VALUE),
        (Set("status.period_ms", 20000), codec.ERR_BAD_VALUE),
        (Set("pair.key", b"short"), codec.ERR_BAD_VALUE),
    ):
        seq = pc.send(msg)
        (e,) = pc.frames()
        assert (e.msg.cmd_seq, e.msg.code) == (seq, code), msg


def test_set_status_period_changes_the_status_rate():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(Set("status.period_ms", 500))
    cfg = of_type(pc.frames(), Config)[-1].msg
    assert cfg.status_period_ms == 500
    run(node, clock, 2.05)
    assert len(of_type(pc.frames(), Status)) in (3, 4)


def test_wifi_and_pair_key_set_on_usb():
    node, clock = make_node()
    pc = started(node, clock)
    for msg in (Set("wifi.ssid", "lab"), Set("wifi.pass", "secret"), Set("pair.key", KEY[::-1])):
        pc.send(msg)
        assert [type(f.msg).__name__ for f in pc.frames()] == ["Ack", "Config"]
    assert node.auth_key == KEY[::-1]


# ---------------------------------------------------------------------------- TCP rules (--auth)


def test_auth_rules():
    node, clock = make_node(auth=True, key=KEY)
    pc = Pc(node)
    pc.send(GetInfo())  # not AUTH: ignored
    assert pc.take_bytes() == b""
    pc.send(Auth(KEY))
    data = pc.take_bytes()
    assert data == b"\x00" + codec.encode_frame(node.build_hello(), 0) + codec.encode_frame(node.build_config(), 1)
    assert node.build_status(None).rssi_dbm == -58
    # wifi.* and pair.key over TCP: ERR 6
    for msg in (Set("wifi.ssid", "x"), Set("pair.key", KEY)):
        pc.send(msg)
        (e,) = pc.frames()
        assert e.msg.code == codec.ERR_NOT_AUTHORISED


def test_wrong_key_gets_err_6_with_seq_0_and_the_connection_closes():
    node, _ = make_node(auth=True, key=KEY)
    pc = Pc(node)
    pc.send(GetInfo())
    cmd = pc.send(Auth(b"\xff" * 16))
    (f,) = pc.frames()
    assert f.seq == 0 and f.msg == Err(cmd, codec.ERR_NOT_AUTHORISED, f.msg.msg)
    assert pc.closed and pc.conn.closed and node.active is None


def test_auth_timeout_after_2_seconds():
    node, clock = make_node(auth=True, key=KEY)
    pc = Pc(node)
    run(node, clock, 1.9)
    assert pc.take_bytes() == b"" and not pc.closed
    run(node, clock, 0.2)
    (f,) = pc.frames()
    assert f.seq == 0 and f.msg.cmd_seq == 0xFFFF and f.msg.code == codec.ERR_NOT_AUTHORISED
    assert pc.closed


def test_one_session_at_a_time():
    node, clock = make_node(auth=True, key=KEY)
    a, b = Pc(node), Pc(node)
    a.send(Auth(KEY))
    a.frames()
    cmd = b.send(Auth(KEY))
    (f,) = b.frames()
    assert f.seq == 0 and f.msg == Err(cmd, codec.ERR_BUSY, f.msg.msg)
    assert b.closed and not a.closed
    # in USB mode the second client is refused but not disconnected
    node2, _ = make_node()
    a2, b2 = Pc(node2), Pc(node2)
    a2.send(GetInfo())
    cmd = b2.send(GetInfo())
    (f,) = b2.frames()
    assert f.msg.code == codec.ERR_BUSY and not b2.closed


def test_liveness_5_seconds_and_pings_keep_the_session_alive():
    node, clock = make_node(auth=True, key=KEY)
    pc = Pc(node)
    pc.send(Auth(KEY))
    for _ in range(8):  # 8 s, with a PING each second
        run(node, clock, 1.0)
        pc.send(Ping(1))
    assert node.active is pc.conn and not pc.closed
    run(node, clock, 5.2)  # silence
    assert node.active is None and pc.closed  # TCP: the socket is closed too


def test_usb_liveness_ends_the_session_but_keeps_the_port():
    node, clock = make_node()
    pc = started(node, clock)
    run(node, clock, 5.2)
    assert node.active is None and not pc.closed
    pc.frames()
    run(node, clock, 2.0)
    assert pc.take_bytes() == b""  # no STATUS without a session
    pc.send(GetInfo())  # a new session on the same port
    assert [f.seq for f in pc.frames()] == [0, 1]


def test_reboot_acks_then_drops_the_connection():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(Start(0b001))
    run(node, clock, 0.5)
    seq = pc.send(Reboot())
    frames = pc.frames()
    assert frames[-1].msg == Ack(seq) and pc.closed
    assert not node.adc.running and node.streams[0].produced == 0


# ------------------------------------------------------------------- faults and ground truth


def test_runs_are_deterministic_for_a_seed():
    def capture(seed):
        node, clock = make_node(
            seed=seed, faults=FaultConfig(device_drop_rate=0.01, link_drop_rate=0.1, corrupt_rate=0.1)
        )
        pc = started(node, clock)
        pc.send(Start(0b111))
        run(node, clock, 2.0)
        pc.send(Stop(0b111))
        pc.frames()
        return bytes(pc.raw)

    assert capture(3) == capture(3)
    assert capture(3) != capture(4)


def test_device_drops_split_packets_and_are_counted():
    node, clock = make_node(record_injections=True, faults=FaultConfig(device_drop_rate=0.02))
    pc = started(node, clock)
    pc.send(Start(0b001))
    run(node, clock, 3.0)
    pc.send(Stop(0b001))
    frames = pc.frames()
    d = datas(frames, 0)
    final = of_type(frames, Status)[-1].msg.stream(0)
    got = set()
    for x in d:
        got |= set(range(x.first_sample, x.first_sample + x.n))
    injected = {i for a, b in node.streams[0].injected.device for i in range(a, b)}
    assert injected and final.win_device == len(injected) == final.device_dropped
    assert got.isdisjoint(injected)  # a lost sample is never sent, not even as a placeholder
    assert got | injected == set(range(final.win_first, final.win_end))
    assert final.win_link == 0


def test_link_drops_use_no_seq_and_corruption_does():
    node, clock = make_node(record_injections=True, faults=FaultConfig(link_drop_rate=0.3))
    pc = started(node, clock)
    pc.send(Start(0b001))
    run(node, clock, 3.0)
    pc.send(Stop(0b001))
    frames = pc.frames()
    assert pc.rx.lost_frames == 0 and pc.rx.bad_frames == 0  # dropped before the transport: no seq gap
    final = of_type(frames, Status)[-1].msg.stream(0)
    inj = node.streams[0].injected
    assert final.win_link == inj.link_total > 0 and final.win_device == 0

    node, clock = make_node(record_injections=True, faults=FaultConfig(corrupt_rate=0.2))
    pc = started(node, clock)
    pc.send(Start(0b001))
    run(node, clock, 3.0)
    pc.send(Stop(0b001))
    pc.frames()
    inj = node.streams[0].injected
    assert inj.corrupt_packets > 0
    assert pc.rx.bad_frames == pc.rx.lost_frames == inj.corrupt_packets


def test_adc_dec_placeholder_takes_every_second_raw_sample():
    node, clock = make_node(faults=FaultConfig())
    pc = started(node, clock)
    pc.send(Start(0b011))
    run(node, clock, 2.0)
    pc.send(Stop(0b011))
    frames = pc.frames()

    def rebuild(stream):
        parts = datas(frames, stream)
        out = np.zeros((parts[-1].first_sample + parts[-1].n, parts[0].n_ch), np.int32)
        for p in parts:
            out[p.first_sample : p.first_sample + p.n] = p.samples
        return out

    raw, dec = rebuild(0), rebuild(1)
    assert len(dec) == len(raw) // 2 or len(dec) == len(raw) // 2 + 0
    n = min(len(dec), len(raw) // 2)
    assert np.array_equal(dec[:n], raw[1 : 2 * n : 2])
    # dec timestamps are the raw sample's DRDY time
    d1 = datas(frames, 1)[0]
    d0 = datas(frames, 0)[0]
    period_us = 1e6 / 2016.0
    assert abs(d1.t_dev_us - (d0.t_dev_us + period_us)) < 60  # raw sample 1 (jitter 10 us rms on the raw one)


def test_accel_is_about_one_g_on_z():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(Start(0b100))
    run(node, clock, 1.0)
    d = datas(pc.frames(), 2)
    z = np.concatenate([x.samples[:, 2] for x in d]) / 256000.0
    assert d[0].samples.shape[1] == 3 and abs(z.mean() - 1.0) < 0.02


def test_ground_truth_events_in_memory_and_jsonl(tmp_path):
    path = tmp_path / "truth.jsonl"
    node = SimNode(SimConfig(truth_path=path), clock := make_node()[1])
    pc = Pc(node)
    pc.send(GetInfo())
    pc.send(Start(0b011))
    run(node, clock, 6.0)
    node.close()
    ev = node.truth.events
    assert len(ev) >= 8
    assert all(e["kind"] == "footstep" for e in ev)
    t = [e["t_dev_us"] for e in ev]
    assert t == sorted(t) and 0.4 < np.diff(t).mean() / 1e6 < 0.8
    assert all(e["sample_adc_dec"] == e["sample_adc_raw"] // 2 for e in ev)
    assert [json.loads(line) for line in path.read_text().splitlines()] == ev


def test_signals_are_in_raw_codes_with_footsteps():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(Start(0b001))
    run(node, clock, 6.0)
    d = datas(pc.frames(), 0)
    ch0 = np.concatenate([x.samples[:, 0] for x in d]).astype(float)
    noise = np.median(np.abs(ch0 - np.median(ch0))) * 1.4826
    assert np.abs(ch0).max() > 20 * noise
    assert np.abs(ch0).max() < 2**23


def test_speed_must_be_positive():
    with pytest.raises(ValueError):
        SimNode(SimConfig(speed=0))


# ------------------------------------------------- USB: the node cannot see the port close (finding 2)


def test_usb_port_close_does_not_end_the_session_or_the_streams():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(Start(0b111))
    run(node, clock, 1.0)
    pc.conn.transport_closed()  # the client process died: the node sees nothing
    assert node.active is pc.conn and pc.conn.session_live and pc.conn.detached
    produced = node.streams[0].produced
    run(node, clock, 3.0)  # under the 5 s liveness limit
    assert node.active is pc.conn and all(st.sending for st in node.streams.values())
    assert node.streams[0].produced > produced + 5000
    assert node.streams[0].win_link > 0  # nobody reads the port: DATA counts as link loss, never hidden
    run(node, clock, 2.3)  # now 5 s without a PC frame
    assert node.active is None and not any(st.sending for st in node.streams.values())
    assert pc.conn not in node.conns  # a detached connection is dropped when its session ends


def test_a_new_get_info_inside_the_live_usb_session_resends_hello_and_config_without_a_zero_byte():
    node, clock = make_node()
    old = started(node, clock)
    old.send(Start(0b001))
    run(node, clock, 1.0)
    old.conn.transport_closed()
    run(node, clock, 1.0)
    new = Pc(node)  # the PC opens the port again and writes its flushing 0x00
    assert new.take_bytes() == b""
    new.send(GetInfo())
    data = new.take_bytes()
    assert data == codec.encode_frame(node.build_hello(), 0) + codec.encode_frame(node.build_config(), 1)
    assert data[0] != 0x00  # no session-start 0x00 inside a live session
    assert node.active is new.conn and node.streams[0].sending and node.adc.running
    assert old.conn not in node.conns
    run(node, clock, 1.1)
    frames = new.frames()
    assert of_type(frames, Status)
    # the old window is still there: the PC must STOP before it STARTs (PROTOCOL.md section 1)
    stop = new.send(Stop(0b111))
    tail = new.frames()
    assert [type(f.msg).__name__ for f in tail][-2:] == ["Status", "Ack"] and tail[-1].msg == Ack(stop)
    assert not node.adc.running


def test_liveness_counts_from_the_last_frame_of_the_new_client():
    node, clock = make_node()
    old = started(node, clock)
    run(node, clock, 3.0)
    old.conn.transport_closed()
    run(node, clock, 1.0)
    new = Pc(node)
    new.send(GetInfo())
    for _ in range(8):  # 8 s of pings from the new client keep the taken-over session alive
        run(node, clock, 1.0)
        new.send(Ping(1))
    assert node.active is new.conn
    run(node, clock, 5.2)
    assert node.active is None


def test_tcp_rules_still_end_the_session_when_the_socket_closes():
    node, clock = make_node(auth=True, key=KEY)
    pc = Pc(node)
    pc.send(Auth(KEY))
    pc.conn.transport_closed()
    assert node.active is None and pc.conn.closed


def test_a_second_open_client_is_still_refused_in_usb_mode():
    node, clock = make_node()
    a = started(node, clock)
    b = Pc(node)
    cmd = b.send(GetInfo())  # the first client is still connected: busy, not a take-over
    (f,) = b.frames()
    assert f.msg == Err(cmd, codec.ERR_BUSY, f.msg.msg) and node.active is a.conn


# --------------------------------------------------------------- section 5 error rules (finding 4)


def test_every_known_pc_frame_with_a_short_payload_gets_err_2():
    node, clock = make_node()
    pc = started(node, clock)
    for type_id in (0x82, 0x83, 0x84, 0x85, 0x86, 0x88):  # START, STOP, SET, SD_RECORD, PING, AUTH
        seq = pc.tx_seq
        pc.tx_seq += 1
        pc.conn.feed(codec.to_wire(codec.encode_raw_frame(type_id, seq, b"")))
        (e,) = errs(pc.frames())
        assert (e.cmd_seq, e.code) == (seq, codec.ERR_BAD_PAYLOAD), hex(type_id)


def test_a_frame_with_a_bad_crc_gets_no_reply_and_does_not_keep_the_session_alive():
    node, clock = make_node()
    pc = started(node, clock)
    wire = bytearray(codec.encode_frame(Ping(1), pc.tx_seq))
    wire[-2] ^= 0x01  # flip a CRC bit
    run(node, clock, 4.0)
    pc.frames()
    pc.conn.feed(bytes(wire))
    assert pc.take_bytes() == b"" and pc.conn.rx.bad_frames == 1  # no PONG, no ERR
    run(node, clock, 1.2)  # 5.2 s since the last valid frame
    assert node.active is None


def test_a_crc_valid_frame_with_a_short_payload_counts_for_liveness():
    node, clock = make_node()
    pc = started(node, clock)
    run(node, clock, 4.0)
    pc.frames()
    pc.conn.feed(codec.to_wire(codec.encode_raw_frame(0x86, pc.tx_seq, b"")))  # PING without its payload: ERR 2
    run(node, clock, 3.0)
    assert node.active is pc.conn


def test_sd_record_stop_with_mask_0_stops_everything():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(SdRecord(1, 0b101, "s1"))
    assert node.sd_mask == 0b101 and node.adc.running and node.accel.running
    pc.frames()
    seq = pc.send(SdRecord(0, 0, ""))
    assert [f.msg for f in pc.frames()] == [Ack(seq)]
    assert node.sd_mask == 0 and not node.adc.running and not node.accel.running
    # a stop with a mask only stops those streams
    pc.send(SdRecord(1, 0b101, "s2"))
    pc.send(SdRecord(0, 0b001, ""))
    assert node.sd_mask == 0b100 and not node.adc.running and node.accel.running


def test_start_stop_and_sd_start_reject_unknown_mask_bits_but_sd_stop_does_not():
    node, clock = make_node()
    pc = started(node, clock)
    for msg in (Start(0b1000), Stop(0b10000), SdRecord(1, 0b1001, "x")):
        seq = pc.send(msg)
        (e,) = errs(pc.frames())
        assert (e.cmd_seq, e.code) == (seq, codec.ERR_BAD_VALUE)
    seq = pc.send(SdRecord(0, 0, ""))
    assert [f.msg for f in pc.frames()] == [Ack(seq)]


def test_set_check_order_unknown_key_then_tcp_only_then_value_then_busy():
    # TCP-only key over TCP with a bad value type: ERR 6 comes before ERR 4
    node, clock = make_node(auth=True, key=KEY)
    pc = Pc(node)
    pc.send(Auth(KEY))
    pc.frames()
    for msg in (Set("wifi.ssid", 5), Set("pair.key", "short")):
        seq = pc.send(msg)
        (e,) = pc.frames()
        assert (e.msg.cmd_seq, e.msg.code) == (seq, codec.ERR_NOT_AUTHORISED)
    pc.send(Set("nope.nope", 1))  # unknown key beats everything
    (e,) = pc.frames()
    assert e.msg.code == codec.ERR_UNKNOWN_KEY
    # bad value beats busy
    pc.send(Start(0b001))
    pc.frames()
    seq = pc.send(Set("adc.gain.0", 3))  # not a power of two, and the ADC runs
    (e,) = pc.frames()
    assert (e.msg.cmd_seq, e.msg.code) == (seq, codec.ERR_BAD_VALUE)
    seq = pc.send(Set("adc.gain.0", 4))  # a good value, but busy
    (e,) = pc.frames()
    assert (e.msg.cmd_seq, e.msg.code) == (seq, codec.ERR_BUSY)


# ------------------------------------------------------------- adc_dec placeholder (finding 5)


def test_decimate_placeholder_depends_only_on_raw_sample_2k_plus_1():
    from rezonating_lab.sim.node import decimate_placeholder

    codes = np.arange(12, dtype=np.int32).reshape(6, 2)  # raw indices 10..15
    valid = np.ones(6, bool)
    first_k, dec, ok = decimate_placeholder(10, codes, valid)
    assert first_k == 5 and ok.all() and dec[:, 0].tolist() == [2, 6, 10]  # raw 11, 13, 15 -> k = 5, 6, 7
    valid[0] = False  # raw 10 = 2k for k = 5: does not matter
    assert decimate_placeholder(10, codes, valid)[2].all()
    valid[:] = True
    valid[1] = False  # raw 11 = 2k + 1 for k = 5: output 5 is lost
    assert decimate_placeholder(10, codes, valid)[2].tolist() == [False, True, True]
    # a block that starts on an odd raw index
    first_k, dec, ok = decimate_placeholder(11, codes[:5], np.ones(5, bool))
    assert first_k == 5 and dec[:, 0].tolist() == [0, 4, 8]  # raw 11, 13, 15 -> codes rows 0, 2, 4
    # a one-sample block that starts on an even index has no output
    assert len(decimate_placeholder(10, codes[:1], np.ones(1, bool))[2]) == 0


def test_adc_dec_device_drops_are_exactly_the_lost_odd_raw_samples():
    node, clock = make_node(record_injections=True, faults=FaultConfig(device_drop_rate=0.01))
    pc = started(node, clock)
    pc.send(Start(0b011))
    run(node, clock, 4.0)
    pc.send(Stop(0b011))
    frames = pc.frames()
    raw_lost = {i for a, b in node.streams[0].injected.device for i in range(a, b)}
    dec_lost = {i for a, b in node.streams[1].injected.device for i in range(a, b)}
    final = of_type(frames, Status)[-1].msg
    n_dec = final.stream(1).win_end
    assert raw_lost and dec_lost
    assert dec_lost == {(i - 1) // 2 for i in raw_lost if i % 2 == 1 and (i - 1) // 2 < n_dec}
    assert final.stream(1).win_device == len(dec_lost)
    got = set()
    for x in datas(frames, 1):
        got |= set(range(x.first_sample, x.first_sample + x.n))
    assert got.isdisjoint(dec_lost) and got | dec_lost == set(range(n_dec))


# ----------------------------------------------------------- control-frame fault hook (finding 1)


def test_control_fault_hook_corrupts_the_chosen_frame_on_the_wire():
    node, clock = make_node()
    pc = started(node, clock)
    pc.send(Start(0b001))
    run(node, clock, 0.3)
    pc.frames()
    node.cfg.control_fault = lambda m: isinstance(m, Status)
    pc.send(Stop(0b001))
    frames = pc.frames()
    assert [type(f.msg).__name__ for f in frames if not isinstance(f.msg, codec.Data)] == ["Ack"]
    assert pc.rx.bad_frames == 1 and pc.rx.lost_frames == 1  # one bad frame and the seq hole it left
    node.cfg.control_fault = None
    pc.send(Ping(1))
    assert of_type(pc.frames(), Pong)
