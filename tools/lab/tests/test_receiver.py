import random

import numpy as np
from rezonating_lab.link import codec
from rezonating_lab.link.codec import Ack, Data, Log, Ping
from rezonating_lab.link.receiver import FROM_NODE, FROM_PC, Receiver, Unhandled
from rezonating_lab.link.vectors import CONFIG, HELLO


def acks(n, start=0):
    return [(Ack(i), (start + i) & 0xFFFF) for i in range(n)]


def wire_of(items):
    return b"".join(codec.encode_frame(m, s) for m, s in items)


def test_clean_stream():
    items = acks(20)
    rx = Receiver()
    frames = rx.feed(wire_of(items))
    assert [(f.msg, f.seq) for f in frames] == items
    assert (rx.bad_frames, rx.lost_frames, rx.unknown_types) == (0, 0, 0)


def test_any_chunking_gives_the_same_result():
    rng = random.Random(3)
    items = acks(30)
    wire = wire_of(items)
    for piece in (1, 2, 7, 64, 1000):
        rx = Receiver()
        got = []
        for i in range(0, len(wire), piece):
            got += rx.feed(wire[i : i + piece])
        assert [(f.msg, f.seq) for f in got] == items
    rx = Receiver()
    got = []
    i = 0
    while i < len(wire):
        step = rng.randrange(1, 50)
        got += rx.feed(wire[i : i + step])
        i += step
    assert len(got) == 30


def test_resync_after_corrupted_bytes():
    rng = random.Random(5)
    items = acks(200)
    wires = [codec.encode_frame(m, s) for m, s in items]
    corrupted = set(rng.sample(range(200), 25))
    for i in corrupted:
        w = bytearray(wires[i])
        pos = rng.randrange(0, len(w) - 1)  # never the delimiter
        w[pos] = (w[pos] ^ rng.randrange(1, 256)) or 1
        wires[i] = bytes(w)
    rx = Receiver()
    frames = rx.feed(b"".join(wires))
    survivors = [items[i] for i in range(200) if i not in corrupted]
    assert [(f.msg, f.seq) for f in frames] == survivors
    assert rx.bad_frames == 25
    # every corrupted frame leaves a seq jump (unless it is the very last frame, which nothing follows)
    assert rx.lost_frames == 25 - (1 if 199 in corrupted else 0)


def test_leading_boot_text_then_hello():
    boot = b"ESP-ROM:esp32s3-20210327\r\nBuild:Mar 27 2021\r\nrst:0x1 (POWERON)\r\n"
    rx = Receiver()
    frames = rx.feed(boot + b"\x00" + codec.encode_frame(HELLO, 0) + codec.encode_frame(CONFIG, 1))
    assert [f.msg for f in frames] == [HELLO, CONFIG]
    assert rx.bad_frames == 1 and rx.lost_frames == 0


def test_garbage_without_zero_does_not_grow_the_buffer():
    rx = Receiver()
    for _ in range(10):
        rx.feed(b"A" * 1000)
    assert len(rx._buf) <= codec.MAX_ENCODED_LEN
    assert rx.bad_frames == 1  # 10 kB without a 0x00 is one bad frame, not one per 4120 bytes
    frames = rx.feed(b"\x00" + codec.encode_frame(Ack(1), 0))
    assert [f.msg for f in frames] == [Ack(1)]
    assert rx.bad_frames == 1


def test_oversize_chunk_is_one_bad_frame_then_recovery():
    rx = Receiver()
    frames = rx.feed(b"A" * 4120 + b"\x00" + codec.encode_frame(Ack(1), 0))
    assert [f.msg for f in frames] == [Ack(1)]
    assert rx.bad_frames == 1


def test_oversize_4121_is_one_bad_frame_for_any_chunking():
    wire = b"A" * 4121 + b"\x00" + codec.encode_frame(Ack(1), 0)
    for piece in (len(wire), 1, 7, 4096):
        rx = Receiver()
        frames = []
        for i in range(0, len(wire), piece):
            frames += rx.feed(wire[i : i + piece])
        assert [f.msg for f in frames] == [Ack(1)] and rx.bad_frames == 1, piece


def test_a_lost_hello_is_a_resync_not_65k_lost_frames():
    # mid-session: expected seq is 5000, HELLO (seq 0) is lost, CONFIG (seq 1) arrives
    rx = Receiver()
    rx.feed(wire_of([(Ack(0), 4999)]))
    rx.feed(wire_of([(CONFIG, 1), (Ack(1), 2)]))
    assert (rx.lost_frames, rx.resyncs) == (0, 1)
    # in a short session too (expected 20)
    rx = Receiver()
    rx.feed(wire_of([(Ack(0), 19), (CONFIG, 1)]))
    assert (rx.lost_frames, rx.resyncs) == (0, 1)
    # a numbering that fell back to the start while the expected seq was past half the range
    rx = Receiver()
    rx.feed(wire_of([(Ack(0), 40000), (CONFIG, 1)]))
    assert (rx.lost_frames, rx.resyncs) == (0, 1)


def test_ordinary_loss_and_wrap_are_still_lost_frames():
    rx = Receiver()
    rx.feed(wire_of([(Ack(0), 100), (Ack(1), 1100)]))  # 999 lost: well under the resync limits
    assert (rx.lost_frames, rx.resyncs) == (999, 0)
    rx = Receiver()
    rx.feed(wire_of([(Ack(0), 65530), (Ack(1), 4)]))  # 10 lost across the wrap, seq < 16 but a short jump
    assert (rx.lost_frames, rx.resyncs) == (9, 0)


def test_a_repeated_seq_is_a_resync():
    rx = Receiver()
    rx.feed(wire_of([(Ack(0), 10), (Ack(1), 10)]))  # same seq twice: jump of 65535
    assert (rx.lost_frames, rx.resyncs) == (0, 1)


def test_a_4119_byte_chunk_is_still_accepted():
    from rezonating_lab.link.vectors import _largest_set

    msg = _largest_set()
    wire = codec.encode_frame(msg, 0x0101)
    assert len(wire) == 4120  # 4119 + delimiter
    rx = Receiver(FROM_PC)  # SET is a PC to node frame
    frames = rx.feed(wire)
    assert [f.msg for f in frames] == [msg] and rx.bad_frames == 0


def test_empty_chunks_are_ignored():
    rx = Receiver()
    frames = rx.feed(b"\x00\x00\x00" + codec.encode_frame(Ack(1), 0) + b"\x00\x00")
    assert len(frames) == 1 and rx.bad_frames == 0


def test_lost_frames_counts_seq_jumps_and_wraps():
    rx = Receiver()
    rx.feed(wire_of([(Ack(0), 65534), (Ack(1), 65535), (Ack(2), 0)]))
    assert rx.lost_frames == 0
    rx.feed(wire_of([(Ack(3), 4)]))  # 1, 2, 3 missing
    assert rx.lost_frames == 3


def test_hello_resets_the_expected_seq():
    rx = Receiver()
    rx.feed(wire_of([(Ack(0), 100), (Ack(1), 101), (HELLO, 0), (CONFIG, 1)]))
    assert rx.lost_frames == 0
    rx.feed(wire_of([(Ack(2), 5)]))  # after CONFIG seq 1 we expected 2
    assert rx.lost_frames == 3


def test_unknown_types_are_counted_and_not_delivered():
    raw = codec.encode_raw_frame(0x55, 1, b"abc")
    rx = Receiver()
    frames = rx.feed(codec.encode_frame(Ack(0), 0) + codec.to_wire(raw) + codec.encode_frame(Ack(2), 2))
    assert [f.msg for f in frames] == [Ack(0), Ack(2)]
    assert rx.unknown_types == 1 and rx.lost_frames == 0  # the unknown frame's seq still counts


def test_a_pc_type_arriving_from_the_node_is_unknown():
    rx = Receiver(FROM_NODE)
    assert rx.feed(codec.encode_frame(Ping(1), 0)) == []
    assert rx.unknown_types == 1


def test_deliver_unhandled_keeps_order():
    unknown = codec.to_wire(codec.encode_raw_frame(0x55, 1, b""))
    short_start = codec.to_wire(codec.encode_raw_frame(0x82, 2, b""))  # START without its mask byte
    rx = Receiver(FROM_PC, deliver_unhandled=True)
    frames = rx.feed(codec.encode_frame(Ping(1), 0) + unknown + short_start + codec.encode_frame(Ping(2), 3))
    kinds = [type(f.msg).__name__ for f in frames]
    assert kinds == ["Ping", "Unhandled", "Unhandled", "Ping"]
    assert isinstance(frames[1].msg, Unhandled) and not frames[1].msg.malformed
    assert frames[2].msg.malformed
    assert rx.unknown_types == 1 and rx.bad_frames == 1


def test_trailing_payload_bytes_are_ignored():
    raw = codec.encode_raw_frame(Ack.TYPE_ID, 0, Ack(77).to_payload() + b"\x01\x02")
    rx = Receiver()
    frames = rx.feed(codec.to_wire(raw))
    assert frames[0].msg == Ack(77) and rx.bad_frames == 0


def test_data_and_log_survive_a_realistic_mix():
    data = Data(0, 10, 99, np.arange(-10, 10, dtype=np.int32).reshape(10, 2))
    stream = wire_of([(HELLO, 0), (CONFIG, 1), (data, 2), (Log(3, 1, "t", "m"), 3)])
    rx = Receiver()
    got = rx.feed(stream)
    assert got[2].msg == data
