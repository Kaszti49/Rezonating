"""Simulated node: follows tools/lab/PROTOCOL.md without hardware.

The node is sans-I/O. A transport (``server.py``, or a test) calls ``SimNode.connect(...)`` for every
client, feeds received bytes to ``Connection.feed`` and calls ``SimNode.tick()`` often. Output leaves
through the ``write`` callback given to ``connect``.

Time: the device clock (``t_dev_us``) runs ``speed`` times faster than the injected wall clock. Samples are
produced in chunks of ``chunk_s`` device seconds (about 25 DATA frames per second per stream), so output
depends only on the seed and the chunk count, not on how often ``tick`` is called. Liveness and the
2 s authentication timeout use wall time. STATUS uses device time.

``adc_dec`` comes from ``rezonating_ml``: one :class:`rezonating_ml.dsp.Decimator2` per channel (the D-016 63-tap
FIR + keep odd raw indices; HELLO reports ``fir_taps = 63``, ``fir_delay = 31``) and
:func:`rezonating_ml.dsp.to_adc_dec_codes`. Device-dropped raw samples go in with ``valid = False``: the FIR holds
the previous good value, and an output whose 63-sample window held a lost sample is ``device_dropped`` and not
sent (PROTOCOL.md 4.3). No signal maths lives in the lab.

EVENT frames (PROTOCOL.md 4.5): the simulator plays the firmware's part for the ``footstep-id`` trigger. It runs
:func:`rezonating_ml.pipeline.build_pipeline` on ADC channel 0 (port 1) of its own ``adc_raw`` samples (with the
device-drop mask, in blocks of ``EVENT_BATCH`` raw samples) and sends one EVENT (``stream`` 1 = ``adc_dec`` index, ``kind`` 0 trigger) per trigger onset.
Until real firmware exists, a firmware-vs-Python compare against the simulator compares Python with Python: it
checks the Lab's plumbing (indices, chunking, loss handling), not a second implementation.

USB rules: the node cannot see the port close. When the client socket goes away inside a live session the
connection is *detached* (``Connection.detach``): the session and the streams keep running, writes go
nowhere, and only the 5 s liveness limit (or REBOOT) ends it. A new connection's ``GET_INFO`` inside that
live session takes it over: HELLO + CONFIG again, seq reset, no extra 0x00.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from rezonating_ml.dsp import DECIM_N_TAPS, Decimator2, to_adc_dec_codes
from rezonating_ml.pipeline import Pipeline, build_pipeline

from ..link import codec
from ..link.codec import (
    Ack,
    Auth,
    ChannelConfig,
    Config,
    Data,
    Err,
    Event,
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
    StreamConfig,
    StreamInfo,
    StreamStatus,
)
from ..link.receiver import FROM_PC, Receiver, Unhandled
from ..link.vectors import HEADS
from .faults import FaultConfig, FaultInjector
from .scenarios import (
    ACCEL_FULL_SCALE,
    ADC_FULL_SCALE,
    ADC_VREF_V,
    AccelSignal,
    AdcSignal,
    GroundTruthLog,
    ScenarioConfig,
)

Clock = Callable[[], float]

ALL_STREAMS_MASK = 0b111
RATE_WINDOW_S = 10.0
VALID_GAINS = (1, 2, 4, 8, 16, 32, 64, 128)
STREAM_TABLE: dict[int, StreamInfo] = {
    codec.STREAM_ADC_RAW: StreamInfo(0, 2, 2000, 24, codec.CLOCK_LTC6903, 0, 0),
    codec.STREAM_ADC_DEC: StreamInfo(
        1, 2, 1000, 24, codec.CLOCK_LTC6903, DECIM_N_TAPS, (DECIM_N_TAPS - 1) // 2
    ),  # D-016 FIR (rezonating_ml)
    codec.STREAM_ACCEL: StreamInfo(2, 3, 2000, 20, codec.CLOCK_ADXL355, 0, 0),
}
MAX_FRAMES_PER_PACKET = {2: 509, 3: 339}
DETACHED_BACKLOG = 10**12  # a detached USB port never drains: every DATA frame counts as a link loss
SIM_TAP_KEY = "sim.tap"  # simulator-only SET key (sim.* is reserved in PROTOCOL.md; real firmware answers ERR 3)
SIM_TAP_LEAD_S = 0.05  # an injected tap starts this long after the last produced sample
EVENT_PACK_ID = "footstep-id"  # the pack whose trigger the simulator runs (EVENT frames, PROTOCOL.md 4.5)
EVENT_KEY = "step"  # footstep-id outputs[]: the per-footstep event
EVENT_CHANNEL = 0  # ADC channel (port 1) the pack runs on
EVENT_BATCH = 512  # raw samples per pipeline call (about 0.25 s): the pack runs in blocks, as firmware would


@dataclass
class SimConfig:
    seed: int = 1
    auth: bool = False  # False: USB session rules, True: TCP rules (AUTH, 2 s timeout, close on end)
    key: bytes = bytes(range(16))
    speed: float = 1.0
    status_period_ms: int = 1000
    chunk_s: float = 0.04  # device seconds per chunk: 25 DATA frames per second per stream
    liveness_s: float = 5.0  # wall seconds without a valid PC frame
    auth_timeout_s: float = 2.0
    boot_offset_s: float = 5.0  # device clock at start
    clock_drift_ppm: float = 0.0  # the device clock runs this much fast (+) or slow (-) against the host clock
    timestamp_jitter_us: float = 0.0  # extra Gaussian noise (std) on every DATA and PONG timestamp
    max_backlog_bytes: int = 256_000  # unsent bytes at which DATA is dropped as a link loss (queue full)
    fw_version: str = "0.1.0-sim"
    node_id: str = "rzn-sim001"
    truth_path: Path | None = None
    record_injections: bool = False  # keep every injected index range (tests); counters are always kept
    # Test hook: called with every control frame (HELLO, CONFIG, STATUS, ACK, ...) before it is written;
    # return True to corrupt that frame on the wire (its seq is spent; the PC counts one bad frame).
    control_fault: Callable[[object], bool] | None = None
    faults: FaultConfig = field(default_factory=FaultConfig)
    scenario: ScenarioConfig = field(default_factory=ScenarioConfig)
    # ADC signal factory ``(scenario, acq_id, shorted=...) -> AdcSignal``; None = the generic footsteps.
    # ``rzlab sim --walkers`` passes ``people.WalkerAdcSignal.factory(...)`` (simulated people walking a protocol).
    adc_signal: Callable[..., AdcSignal] | None = None
    # The footstep-id pack.json whose trigger produces EVENT frames; None = packs/footstep-id/pack.json of the
    # checkout (no checkout found: no EVENT frames). Set ``events=False`` to turn EVENT frames off.
    event_pack: Path | None = None
    events: bool = True


@dataclass
class Injected:
    """What the simulator itself dropped or corrupted for one stream (the ground truth for loss tests).
    Index ranges are half-open and live in the index space of the current acquisition."""

    device: list[tuple[int, int]] = field(default_factory=list)
    link: list[tuple[int, int]] = field(default_factory=list)
    corrupt: list[tuple[int, int]] = field(default_factory=list)
    device_total: int = 0
    link_total: int = 0
    corrupt_total: int = 0
    link_packets: int = 0
    corrupt_packets: int = 0


@dataclass
class StreamState:
    info: StreamInfo
    produced: int = 0
    device_dropped: int = 0
    clipped: int = 0
    sending: bool = False
    win_first: int = 0
    win_end: int = 0
    win_device: int = 0
    win_link: int = 0
    rate_hist: deque = field(default_factory=deque)  # (device seconds, produced)
    injected: Injected = field(default_factory=Injected)

    def reset_acquisition(self) -> None:
        self.produced = self.device_dropped = self.clipped = 0
        self.rate_hist.clear()
        self.injected = Injected()


@dataclass
class Acquisition:
    """One sensor: the ADC (streams 0 and 1) or the accelerometer (stream 2)."""

    name: str
    stream_ids: tuple[int, ...]
    nominal_hz: float
    clock_error: float
    running: bool = False
    acq_id: int = 0
    t0_s: float = 0.0  # device time of index 0
    k: int = 0  # chunks processed
    produced: int = 0  # raw indices assigned
    signal: AdcSignal | AccelSignal | None = None
    decimators: list[Decimator2] = field(default_factory=list)  # ADC only: one per channel (adc_dec)
    pipe: Pipeline | None = None  # ADC only: the footstep-id pipeline behind EVENT frames
    pipe_buf: list[tuple[np.ndarray, np.ndarray]] = field(default_factory=list)  # raw ch0 + valid not yet run

    @property
    def rate_hz(self) -> float:
        return self.nominal_hz * (1.0 + self.clock_error)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Half-open index ranges of the True runs of a boolean array."""
    padded = np.concatenate(([0], mask.astype(np.int8), [0]))
    edges = np.diff(padded)
    return list(zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist(), strict=False))


def decimate(decimators: list[Decimator2], codes: np.ndarray, valid: np.ndarray) -> tuple[int, np.ndarray, np.ndarray]:
    """``adc_dec`` for one block of ``adc_raw`` (``codes: (n, n_ch)`` int32, ``valid: (n,)`` bool, contiguous with
    the previous block): the first decimated index, its int32 codes ``(m, n_ch)`` and their validity ``(m,)``.
    All the maths is ``rezonating_ml.dsp`` (Decimator2 + to_adc_dec_codes)."""
    first = decimators[0].n_out
    cols, ok = [], np.ones(0, dtype=bool)
    for ch, dec in enumerate(decimators):
        y, ok = dec.process_valid(codes[:, ch], valid)
        cols.append(to_adc_dec_codes(y))
    return first, np.stack(cols, axis=1) if cols else np.zeros((0, 0), np.int32), ok


def default_event_pack() -> Path | None:
    """``packs/footstep-id/pack.json`` in the checkout this package runs from, or None."""
    from ..recorder.config import find_repo_root

    repo = find_repo_root()
    p = repo / "packs" / EVENT_PACK_ID / "pack.json" if repo is not None else None
    return p if p is not None and p.is_file() else None


def _us(t_s: float) -> int:
    return int(round(t_s * 1e6))


class SimNode:
    def __init__(self, cfg: SimConfig | None = None, clock: Clock = time.monotonic) -> None:
        self.cfg = cfg or SimConfig()
        if self.cfg.speed <= 0:
            raise ValueError("speed must be positive")
        self.clock = clock
        self._wall0 = clock()
        self.faults = FaultInjector(self.cfg.faults, self.cfg.seed)
        self._jitter = np.random.default_rng(np.random.SeedSequence(self.cfg.seed).spawn(4)[3])
        self.scenario_cfg = replace(self.cfg.scenario, seed=self.cfg.seed)
        self.truth = GroundTruthLog(self.cfg.truth_path)
        self.streams = {sid: StreamState(info) for sid, info in STREAM_TABLE.items()}
        self.adc = Acquisition("adc", (0, 1), 2000.0, self.cfg.faults.clock_error)
        self.accel = Acquisition("accel", (2,), 2000.0, self.cfg.faults.accel_clock_error)
        self.adc_gain = [8, 8]
        self.accel_range_g = 2
        self.status_period_ms = self.cfg.status_period_ms
        self.auth_key = self.cfg.key
        self.sd_mask = 0
        self.sd_session = ""
        self.conns: list[Connection] = []
        self.active: Connection | None = None
        self._next_status_s = 0.0
        self._acq_counter = 0
        self.events_total = 0  # footstep-id trigger onsets (EVENT frames), since start

    # ------------------------------------------------------------------------------- clocks

    def now_dev_s(self) -> float:
        rate = self.cfg.speed * (1.0 + self.cfg.clock_drift_ppm * 1e-6)
        return self.cfg.boot_offset_s + (self.clock() - self._wall0) * rate

    def stamp_noise_us(self) -> int:
        """Timestamp jitter of the firmware (interrupt latency, task scheduling) for one DATA or PONG stamp."""
        if self.cfg.timestamp_jitter_us <= 0:
            return 0
        return int(round(float(self._jitter.normal(0.0, self.cfg.timestamp_jitter_us))))

    def now_dev_us(self) -> int:
        return _us(self.now_dev_s())

    # ------------------------------------------------------------------------- connections

    def connect(
        self,
        write: Callable[[bytes], None],
        backlog: Callable[[], int] = lambda: 0,
        close: Callable[[], None] = lambda: None,
    ) -> Connection:
        conn = Connection(self, write, backlog, close)
        self.conns.append(conn)
        return conn

    def tick(self) -> None:
        """Advance device time: produce chunks, send STATUS when due, check liveness and the auth timeout."""
        now = self.now_dev_s()
        self._advance(now)
        if self.active is not None and now >= self._next_status_s:
            self.active.send_status()
            self._next_status_s = now + self.status_period_ms / 1000.0
        wall = self.clock()
        for conn in list(self.conns):
            conn.check_timers(wall)

    def advance(self) -> None:
        self._advance(self.now_dev_s())

    # ---------------------------------------------------------------------------- acquisition

    def _acq_of(self, stream_id: int) -> Acquisition:
        return self.adc if stream_id in self.adc.stream_ids else self.accel

    def _needed(self, acq: Acquisition) -> bool:
        return any(self.streams[s].sending or self.sd_mask & (1 << s) for s in acq.stream_ids)

    def _ensure_acq(self, acq: Acquisition, now_s: float) -> None:
        """Start acquisition from fully idle: indices restart at 0. Otherwise nothing is reset."""
        if acq.running:
            return
        self._acq_counter += 1
        acq.running = True
        acq.acq_id = self._acq_counter
        acq.t0_s = now_s
        acq.k = 0
        acq.produced = 0
        for sid in acq.stream_ids:
            self.streams[sid].reset_acquisition()
        faults = self.cfg.faults
        if acq is self.adc:
            make_adc = self.cfg.adc_signal or AdcSignal  # --walkers: simulated people (people.WalkerAdcSignal)
            acq.signal = make_adc(self.scenario_cfg, acq.acq_id, shorted=faults.shorted_inputs)
            acq.decimators = [Decimator2() for _ in range(STREAM_TABLE[codec.STREAM_ADC_RAW].n_ch)]
            pack = (self.cfg.event_pack or default_event_pack()) if self.cfg.events else None
            acq.pipe_buf = []
            acq.pipe = (
                build_pipeline(pack, input_fs_hz=float(STREAM_TABLE[codec.STREAM_ADC_RAW].nominal_hz)) if pack else None
            )
        else:
            acq.signal = AccelSignal(self.scenario_cfg, acq.acq_id, gravity=not faults.no_gravity)

    def _release_acq(self, acq: Acquisition) -> None:
        if acq.running and not self._needed(acq):
            acq.running = False

    def _advance(self, now_s: float) -> None:
        for acq in (self.adc, self.accel):
            while acq.running and acq.t0_s + (acq.k + 1) * self.cfg.chunk_s <= now_s:
                self._process_chunk(acq)

    def _process_chunk(self, acq: Acquisition) -> None:
        acq.k += 1
        if acq is self.adc and self.cfg.faults.no_adc:
            return  # the ADC never answers: no DRDY, no samples, nothing counted
        t_end_rel = acq.k * self.cfg.chunk_s
        total = math.ceil(acq.rate_hz * t_end_rel)
        first, n = acq.produced, total - acq.produced
        if n <= 0:
            return
        acq.produced = total
        valid = ~self.faults.device_dropped(n)
        rate = acq.rate_hz
        if acq is self.adc:
            assert isinstance(acq.signal, AdcSignal)
            codes, steps = acq.signal.block(first, n, rate, (self.adc_gain[0], self.adc_gain[1]))
            if self.cfg.faults.swap_channels:
                codes = np.ascontiguousarray(codes[:, ::-1])
            for step in steps:
                idx = int(round(step.t_s * rate))
                self.truth.add(
                    {
                        "acq": acq.acq_id,
                        "kind": "footstep",
                        "step": step.n,
                        "t_dev_us": _us(acq.t0_s + step.t_s),
                        "sample_adc_raw": idx,
                        "sample_adc_dec": idx // 2,
                        "amp_v": round(step.amp_v, 9),
                        **self._accel_index(acq.t0_s + step.t_s),
                        **step.truth_fields(),
                    }
                )
            t0 = acq.t0_s

            def t_raw(j: int, first: int = first, t0: float = t0, rate: float = rate) -> int:
                return _us(t0 + (first + j) / rate) + int(round(float(self._jitter.normal(0.0, 10.0))))

            self._feed_stream(self.streams[0], first, codes, valid, t_raw, acq.t0_s + t_end_rel)
            dec_first, dec_codes, dec_valid = decimate(acq.decimators, codes, valid)
            if len(dec_valid):

                def t_dec(j: int, dec_first: int = dec_first, t0: float = t0, rate: float = rate) -> int:
                    return _us(t0 + (2 * (dec_first + j) + 1) / rate)

                self._feed_stream(self.streams[1], dec_first, dec_codes, dec_valid, t_dec, acq.t0_s + t_end_rel)
            if acq.pipe is not None:
                acq.pipe_buf.append((codes[:, EVENT_CHANNEL].copy(), valid))
                if sum(len(v) for _, v in acq.pipe_buf) >= EVENT_BATCH:
                    x = np.concatenate([c for c, _ in acq.pipe_buf])
                    ok = np.concatenate([v for _, v in acq.pipe_buf])
                    acq.pipe_buf = []
                    self._send_events(acq.pipe, x, ok)
        else:
            assert isinstance(acq.signal, AccelSignal)
            codes = acq.signal.block(first, n, rate, self.accel_range_g)
            t_read = acq.t0_s + t_end_rel + float(self._jitter.normal(0.0, 40e-6))

            def t_acc(j: int, n: int = n, t_read: float = t_read, rate: float = rate) -> int:
                return _us(t_read - (n - 1 - j) / rate)

            self._feed_stream(self.streams[2], first, codes, valid, t_acc, acq.t0_s + t_end_rel)

    def _feed_stream(self, st: StreamState, first: int, codes, valid, t_fn, t_now_s: float) -> None:
        m = len(valid)
        st.produced = first + m
        dropped_runs = _runs(~valid)
        dropped = int(m - valid.sum())
        st.device_dropped += dropped
        full = ADC_FULL_SCALE if st.info.id != codec.STREAM_ACCEL else ACCEL_FULL_SCALE
        clip = ((codes >= full - 1) | (codes <= -full)).any(axis=1) & valid
        st.clipped += int(clip.sum())
        st.rate_hist.append((t_now_s, st.produced))
        while len(st.rate_hist) > 2 and t_now_s - st.rate_hist[1][0] > RATE_WINDOW_S:
            st.rate_hist.popleft()
        inj = st.injected
        inj.device_total += dropped
        if self.cfg.record_injections:
            inj.device += [(first + a, first + b) for a, b in dropped_runs]
        if not st.sending:
            return
        st.win_end = st.produced
        st.win_device += dropped
        max_frames = MAX_FRAMES_PER_PACKET[st.info.n_ch]
        for a, b in _runs(valid):
            for p in range(a, b, max_frames):
                q = min(b, p + max_frames)
                self._send_data(st, Data(st.info.id, first + p, t_fn(p) + self.stamp_noise_us(), codes[p:q]))

    def _send_events(self, pipe: Pipeline, x: np.ndarray, valid: np.ndarray) -> None:
        """Run the footstep-id pipeline (rezonating_ml) on this block; one EVENT per trigger onset (PROTOCOL 4.5).
        The pipeline always runs (it is the node's pack); EVENTs go out only while a connection is attached."""
        out = pipe.process(x, valid)
        if not out.events:
            return
        self.events_total += len(out.events)  # trigger onsets, sent or not
        conn = self.active
        for e in out.events:
            r = float(out.ratio[e.onset - out.start_index]) if out.ratio is not None else None
            if conn is not None:
                conn.send(Event(codec.STREAM_ADC_DEC, e.onset, codec.EVENT_TRIGGER, pipe.pack_id, EVENT_KEY, r, ""))

    def _send_data(self, st: StreamState, data: Data) -> None:
        conn = self.active
        n = data.n
        inj = st.injected
        rng = (data.first_sample, data.first_sample + n)
        if conn is None or self.faults.link_dropped() or conn.backlog() > self.cfg.max_backlog_bytes:
            st.win_link += n
            inj.link_total += n
            inj.link_packets += 1
            if self.cfg.record_injections:
                inj.link.append(rng)
            return
        if conn.send_data(data, self.faults):
            inj.corrupt_total += n
            inj.corrupt_packets += 1
            if self.cfg.record_injections:
                inj.corrupt.append(rng)

    def _accel_index(self, t_dev_s: float) -> dict:
        """``{"sample_accel": i}``: the accel stream's index at device time ``t_dev_s`` (empty when it is not running)."""
        acc = self.accel
        if not acc.running:
            return {}
        return {"sample_accel": int(round((t_dev_s - acc.t0_s) * acc.rate_hz))}

    def inject_tap(self, ch: int) -> int:
        """Simulator only (``SET sim.tap``): a tap on physical ADC channel ``ch`` shortly after the last produced
        sample. Channel faults (``swap_channels``) act on it like on any other signal. Returns its raw index."""
        acq = self.adc
        self._advance(self.now_dev_s())
        assert isinstance(acq.signal, AdcSignal)
        t_s = acq.produced / acq.rate_hz + SIM_TAP_LEAD_S
        acq.signal.add_tap(t_s, ch)
        idx = int(math.ceil(t_s * acq.rate_hz))
        self.truth.add(
            {"acq": acq.acq_id, "kind": "tap", "ch": ch, "t_dev_us": _us(acq.t0_s + t_s), "sample_adc_raw": idx}
        )
        return idx

    def rate_mhz(self, st: StreamState) -> int:
        h = st.rate_hist
        if len(h) < 2 or h[-1][0] - h[0][0] < 0.2:
            return 0
        return int(round((h[-1][1] - h[0][1]) / (h[-1][0] - h[0][0]) * 1000.0))

    # --------------------------------------------------------------------- commands (called by Connection)

    def start_streams(self, mask: int) -> None:
        now = self.now_dev_s()
        self._advance(now)
        for sid, st in self.streams.items():
            if not mask & (1 << sid) or st.sending:
                continue  # starting a running stream is a no-op
            self._ensure_acq(self._acq_of(sid), now)
            st.sending = True
            st.win_first = st.win_end = st.produced
            st.win_device = st.win_link = 0

    def stop_streams(self, mask: int) -> None:
        self._advance(self.now_dev_s())
        for sid, st in self.streams.items():
            if mask & (1 << sid) and st.sending:
                st.win_end = st.produced
                st.sending = False
        for acq in (self.adc, self.accel):
            self._release_acq(acq)

    def sd_record(self, action: int, mask: int, session: str) -> None:
        now = self.now_dev_s()
        self._advance(now)
        if action == 1:
            for acq in (self.adc, self.accel):
                if any(mask & (1 << s) for s in acq.stream_ids):
                    self._ensure_acq(acq, now)
            self.sd_mask |= mask
            self.sd_session = session
        else:
            self.sd_mask &= ~mask if mask else 0
            for acq in (self.adc, self.accel):
                self._release_acq(acq)

    def end_session(self) -> None:
        """Implicit STOP of every stream (no drain), queue cleared. Acquisition keeps running for SD."""
        self._advance(self.now_dev_s())
        for st in self.streams.values():
            if st.sending:
                st.win_end = st.produced
                st.sending = False
        self.active = None
        for acq in (self.adc, self.accel):
            self._release_acq(acq)

    def reboot(self) -> None:
        for conn in list(self.conns):
            conn.close()
        for st in self.streams.values():
            st.reset_acquisition()
            st.sending = False
            st.win_first = st.win_end = st.win_device = st.win_link = 0
        for acq in (self.adc, self.accel):
            acq.running = False
        self.sd_mask = 0
        self._wall0 = self.clock()

    def schedule_status(self) -> None:
        self._next_status_s = self.now_dev_s() + self.status_period_ms / 1000.0

    # ---------------------------------------------------------------------------- reports

    def build_hello(self) -> Hello:
        return Hello(
            proto=0,
            fw_version=self.cfg.fw_version,
            node_id=self.cfg.node_id,
            t_dev_us=self.now_dev_us(),
            streams=[replace(i) for i in STREAM_TABLE.values()],
            heads=list(HEADS),
        )

    def build_config(self) -> Config:
        lsb = codec.UNITS_G
        accel_scale = float(np.float32(1.0 / {2: 256000, 4: 128000, 8: 64000}[self.accel_range_g]))
        adc = [
            ChannelConfig(g, float(np.float32(ADC_VREF_V / g / ADC_FULL_SCALE)), codec.UNITS_V) for g in self.adc_gain
        ]
        return Config(
            streams=[
                StreamConfig(0, list(adc)),
                StreamConfig(1, list(adc)),
                StreamConfig(2, [ChannelConfig(1, accel_scale, lsb)] * 3),
            ],
            accel_range_g=self.accel_range_g,
            status_period_ms=self.status_period_ms,
        )

    def build_status(self, conn: Connection | None) -> Status:
        t = self.now_dev_s()
        backlog = conn.backlog() if conn is not None else 0
        return Status(
            t_dev_us=_us(t),
            queue_fill=min(100, backlog * 100 // max(1, self.cfg.max_backlog_bytes)),
            sd_state=2 if self.sd_mask else 1,
            sd_free_mb=14000,
            rssi_dbm=-58 if self.cfg.auth else 0,
            heap_free=181_204 - 16 * (int(t) % 7),
            temp_c_x10=int(410 + 6 * math.sin(t / 60.0)),
            streams=[
                StreamStatus(
                    id=sid,
                    running=int(st.sending),
                    produced=st.produced,
                    device_dropped=st.device_dropped,
                    rate_mhz=self.rate_mhz(st),
                    clipped=st.clipped,
                    win_first=st.win_first,
                    win_end=st.win_end,
                    win_device=st.win_device,
                    win_link=st.win_link,
                )
                for sid, st in self.streams.items()
            ],
        )

    def close(self) -> None:
        self.truth.close()


class Connection:
    """One client of the node (a TCP connection, or a pyserial ``socket://`` port in USB-rules mode)."""

    def __init__(
        self, node: SimNode, write: Callable[[bytes], None], backlog: Callable[[], int], close: Callable[[], None]
    ):
        self.node = node
        self._write = write
        self.backlog = backlog
        self._close = close
        self.rx = Receiver(FROM_PC, deliver_unhandled=True)
        self.tx_seq = 0
        self.session_live = False
        self.closed = False
        self.detached = False  # USB rules: the client is gone but the session lives on until liveness runs out
        self.auth_attempted = False
        self.t_connect = node.clock()
        self.last_rx = self.t_connect

    # ----------------------------------------------------------------------------------- output

    def send(self, msg) -> None:
        if self.closed or self.detached:
            return
        wire = codec.encode_frame(msg, self.tx_seq)
        self.tx_seq = (self.tx_seq + 1) & 0xFFFF
        hook = self.node.cfg.control_fault
        if hook is not None and hook(msg):
            wire = self.node.faults.corrupt_forced(wire)
        self._write(wire)

    def send_data(self, data: Data, faults: FaultInjector) -> bool:
        """Write a DATA frame, possibly corrupted on the wire. Returns True when it was corrupted."""
        wire = codec.encode_frame(data, self.tx_seq)
        self.tx_seq = (self.tx_seq + 1) & 0xFFFF  # the seq is spent when the frame is written
        bad = faults.corrupt(wire)
        if not self.closed and not self.detached:
            self._write(wire if bad is None else bad)
        return bad is not None

    def send_status(self) -> None:
        self.send(self.node.build_status(self))

    def _send_hello_config(self) -> None:
        self.tx_seq = 0  # the node resets its seq at every HELLO
        self.send(self.node.build_hello())
        self.send(self.node.build_config())

    def _err(self, cmd_seq: int, code: int, text: str) -> None:
        self.send(Err(cmd_seq, code, text))

    # ------------------------------------------------------------------------------------ input

    def feed(self, data: bytes) -> None:
        if self.closed:
            return
        frames = self.rx.feed(data)
        if frames:  # any frame with a good CRC counts for liveness, even one the node answers with ERR
            self.last_rx = self.node.clock()
        for frame in frames:
            if self.closed:
                break
            self._on_frame(frame)

    def _on_frame(self, frame) -> None:
        msg, seq = frame.msg, frame.seq
        if not self.session_live:
            self._before_session(msg, seq)
            return
        node = self.node
        node.advance()
        if isinstance(msg, Unhandled):
            if msg.malformed:
                self._err(seq, codec.ERR_BAD_PAYLOAD, "payload too short")
            else:
                self._err(seq, codec.ERR_UNKNOWN_COMMAND, f"unknown command 0x{msg.type_id:02x}")
        elif isinstance(msg, GetInfo):
            self._send_hello_config()
        elif isinstance(msg, Auth):
            pass  # already in a session: accepted and ignored
        elif isinstance(msg, Ping):
            self.send(Pong(msg.host_t_us, node.now_dev_us() + node.stamp_noise_us()))
        elif isinstance(msg, Start):
            if self._bad_mask(msg.stream_mask):
                self._err(seq, codec.ERR_BAD_VALUE, "bad stream mask")
            else:
                node.start_streams(msg.stream_mask)
                self.send(Ack(seq))
        elif isinstance(msg, Stop):
            if self._bad_mask(msg.stream_mask):
                self._err(seq, codec.ERR_BAD_VALUE, "bad stream mask")
            else:
                node.stop_streams(msg.stream_mask)
                self.send_status()  # the final STATUS, then the ACK
                self.send(Ack(seq))
        elif isinstance(msg, Set):
            self._on_set(msg, seq)
        elif isinstance(msg, SdRecord):
            if msg.action not in (0, 1) or (msg.action == 1 and self._bad_mask(msg.stream_mask)):
                self._err(seq, codec.ERR_BAD_VALUE, "bad SD_RECORD arguments")
            else:
                node.sd_record(msg.action, msg.stream_mask, msg.session)
                self.send(Ack(seq))
        elif isinstance(msg, Reboot):
            self.send(Ack(seq))
            node.reboot()

    @staticmethod
    def _bad_mask(mask: int) -> bool:
        return mask == 0 or bool(mask & ~ALL_STREAMS_MASK)

    def _before_session(self, msg, seq: int) -> None:
        node = self.node
        if node.cfg.auth:
            if not isinstance(msg, Auth):
                return  # waiting for AUTH; the 2 s timeout in check_timers ends it
            self.auth_attempted = True
            if len(msg.key) != 16 or msg.key != node.auth_key:
                self.tx_seq = 0
                self._err(seq, codec.ERR_NOT_AUTHORISED, "not authorised")
                self.close()
                return
            self._begin_session(seq)
        elif isinstance(msg, GetInfo):  # USB: GET_INFO starts the session; AUTH is accepted and ignored
            self._begin_session(seq)

    def _begin_session(self, cmd_seq: int) -> None:
        node = self.node
        old = node.active
        if old is not None and old is not self and old.detached and not node.cfg.auth:
            # USB: the port was opened again inside the live session. The node never saw the close, so the
            # session (and any running stream) simply continues for the new client: HELLO + CONFIG, seq reset,
            # no 0x00 (PROTOCOL.md section 1).
            old.retire()
            node.active = self
            self.session_live = True
            self.last_rx = node.clock()
            self._send_hello_config()
            return
        if old is not None and old is not self:
            self.tx_seq = 0
            self._err(cmd_seq, codec.ERR_BUSY, "session busy")
            if node.cfg.auth:
                self.close()
            return
        node.active = self
        self.session_live = True
        self.last_rx = node.clock()
        self._write(b"\x00")  # separates any boot text from HELLO
        self._send_hello_config()
        node.schedule_status()

    def _on_set(self, msg: Set, seq: int) -> None:
        node = self.node
        key, value = msg.key, msg.value
        tcp = node.cfg.auth
        if key in ("adc.gain.0", "adc.gain.1"):
            if not (isinstance(value, int) and not isinstance(value, bool) and value in VALID_GAINS):
                return self._err(seq, codec.ERR_BAD_VALUE, "gain must be 1, 2, 4, ... 128")
            if node.adc.running:
                return self._err(seq, codec.ERR_BUSY, "ADC acquisition running")
            node.adc_gain[int(key[-1])] = value
        elif key == "accel.range_g":
            if not (isinstance(value, int) and not isinstance(value, bool) and value in (2, 4, 8)):
                return self._err(seq, codec.ERR_BAD_VALUE, "range must be 2, 4 or 8")
            if node.accel.running:
                return self._err(seq, codec.ERR_BUSY, "accel acquisition running")
            node.accel_range_g = value
        elif key in ("wifi.ssid", "wifi.pass"):
            if tcp:
                return self._err(seq, codec.ERR_NOT_AUTHORISED, "USB only")
            if not isinstance(value, str):
                return self._err(seq, codec.ERR_BAD_VALUE, "str8 expected")
        elif key == "pair.key":
            if tcp:
                return self._err(seq, codec.ERR_NOT_AUTHORISED, "USB only")
            if not (isinstance(value, bytes) and len(value) == 16):
                return self._err(seq, codec.ERR_BAD_VALUE, "16-byte blob expected")
            node.auth_key = value
        elif key == SIM_TAP_KEY:
            if not (isinstance(value, int) and not isinstance(value, bool) and value in (0, 1)):
                return self._err(seq, codec.ERR_BAD_VALUE, "sim.tap must be 0 or 1")
            if not node.adc.running:
                return self._err(seq, codec.ERR_BUSY, "ADC acquisition not running")
            node.inject_tap(value)
            return self.send(Ack(seq))  # no CONFIG: nothing in it changed
        elif key == "status.period_ms":
            if not (isinstance(value, int) and not isinstance(value, bool) and 200 <= value <= 10000):
                return self._err(seq, codec.ERR_BAD_VALUE, "status.period_ms must be 200 to 10000")
            node.status_period_ms = value
        else:
            return self._err(seq, codec.ERR_UNKNOWN_KEY, f"unknown key {key}")
        self.send(Ack(seq))
        self.send(node.build_config())

    # ------------------------------------------------------------------------------ lifecycle

    def check_timers(self, wall_s: float) -> None:
        node = self.node
        if self.closed:
            return
        if self.session_live:
            if wall_s - self.last_rx > node.cfg.liveness_s:
                self.end_session()
                if node.cfg.auth or self.detached:
                    self.close()
        elif node.cfg.auth and not self.auth_attempted and wall_s - self.t_connect > node.cfg.auth_timeout_s:
            self.tx_seq = 0
            self._err(0xFFFF, codec.ERR_NOT_AUTHORISED, "authentication timeout")
            self.close()

    def transport_closed(self) -> None:
        """The client's socket is gone. TCP rules: the node sees it and ends the session. USB rules: it can't,
        so a live session is detached and only the liveness timeout (or REBOOT) ends it."""
        if self.node.cfg.auth or not self.session_live:
            self.close()
        else:
            self.detach()

    def detach(self) -> None:
        self.detached = True
        self._write = lambda _data: None
        self.backlog = lambda: DETACHED_BACKLOG
        self._close = lambda: None

    def retire(self) -> None:
        """Forget a detached connection whose session was taken over (the node-wide session goes on)."""
        self.session_live = False
        self.closed = True
        if self in self.node.conns:
            self.node.conns.remove(self)

    def end_session(self) -> None:
        if self.session_live:
            self.session_live = False
            if self.node.active is self:
                self.node.end_session()

    def close(self) -> None:
        if self.closed:
            return
        self.end_session()
        self.closed = True
        if self in self.node.conns:
            self.node.conns.remove(self)
        self._close()
