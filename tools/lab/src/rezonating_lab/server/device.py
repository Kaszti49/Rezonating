"""Device manager: the one owner of the link connection (D-017, D-018).

A single worker thread owns the transport, the ``LinkClient`` and the ``SessionMonitor``. Everything that
touches the link (connect, START, STOP, SET, PING, reading) runs on that thread, so link I/O never blocks the
asyncio loop of the web server. Other threads talk to it through ``submit`` (a command queue returning
``concurrent.futures.Future``) and read results through events (``emit``), the sample rings and ``state()``.

Accounting after a (re)connect is always fresh: a new ``LinkClient`` and ``SessionMonitor``, the ring buffers
reset, then the clean-up STOP of PROTOCOL.md section 1 before anything is started. So switching from Wi-Fi to
USB (or the simulator) never counts a stale window; a window left over on the node shows up as host gap if the
clean-up STOP could not be confirmed.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import queue
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from .. import session
from ..core.monitor import SessionMonitor, offset_pct
from ..core.ringbuf import SampleRing
from ..core.timing import ClockMap
from ..core.view import channel_levels
from ..link import codec
from ..link.client import LinkClient
from ..link.codec import Ack, Config, Data, Err, Hello, Log, Ping, Pong, Set, Start, Status, Stop
from ..link.transport_serial import SerialTransport
from ..link.transport_tcp import DEFAULT_PORT, TcpTransport, TransportClosed, parse_host_port

LOOP_POLL_S = 0.02  # how long one read waits for bytes
PING_PERIOD_S = 0.5  # liveness PING (PROTOCOL.md section 1 asks for at least 1 Hz)
STATUS_EVENT_PERIOD_S = 1.0
HANDSHAKE_TIMEOUT_S = 3.0
START_TIMEOUT_S = 2.0
STOP_TIMEOUT_S = 3.0
SET_TIMEOUT_S = 2.0
POLITE_STOP_TIMEOUT_S = 1.5
STALE_AFTER_S = 3.0  # no frame from the node for this long: the link looks dead
RING_SECONDS = 600.0
RING_MARGIN = 1.02  # a fast clock (up to +1.65 % over temperature) must still hold the full 10 minutes
LOG_KEEP = 500
UNIT_NAMES = {codec.UNITS_COUNTS: "counts", codec.UNITS_V: "V", codec.UNITS_G: "g"}
LEVEL_WINDOW_S = 1.0
SETTABLE_KEYS = ("adc.gain.0", "adc.gain.1", "accel.range_g")
LOG_LEVEL_NAMES = {1: "error", 2: "warn", 3: "info", 4: "debug", 5: "verbose"}
CLOCK_NAMES = {codec.CLOCK_LTC6903: "ltc6903", codec.CLOCK_ADXL355: "adxl355", codec.CLOCK_CRYSTAL: "crystal"}

SERIAL_URL_RE = re.compile(r"^(COM\d+|/dev/[\w./-]+|socket://[\w.\-\[\]:]+)$", re.IGNORECASE)

Emit = Callable[[dict], None]
CACHED_EVENTS = ("connection", "hello", "config", "status", "recording")  # the snapshot a new client gets


class RecordTap(Protocol):
    """Receives the node's DATA while a recording runs. All three methods are called on the device thread and must
    not block (no disk, no long-held locks): ``on_data`` only queues, the writer is another thread."""

    def on_data(self, d: Data) -> None: ...
    def on_status(self, mon: SessionMonitor) -> None: ...
    def on_link_lost(self, snapshot: dict[int, dict], reason: str) -> None: ...


class DeviceError(Exception):
    """A command failed. ``code`` is a short machine word, ``http`` the status the REST layer answers with."""

    def __init__(self, code: str, message: str, node_code: int | None = None, http: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.node_code = node_code
        self.http = http
        self.event_id: int | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.node_code is not None:
            d["node_code"] = self.node_code
        if self.event_id is not None:
            d["event_id"] = self.event_id
        return d


@dataclass
class ConnectSpec:
    kind: str  # "sim" | "tcp" | "serial"
    host: str | None = None
    port: int | None = None
    url: str | None = None
    key: bytes | None = None

    def validate(self) -> None:
        if self.kind not in ("sim", "tcp", "serial"):
            raise DeviceError("invalid_request", f"unknown kind {self.kind!r}; use sim, tcp or serial", http=400)
        if self.key is not None and len(self.key) != 16:
            raise DeviceError("invalid_request", "the pairing key must be 16 bytes (32 hex digits)", http=400)
        if self.kind == "tcp" and not self.host:
            raise DeviceError("invalid_request", "tcp needs a host", http=400)
        if self.kind == "serial":
            if not self.url or not SERIAL_URL_RE.match(self.url):
                raise DeviceError(
                    "invalid_request",
                    "serial needs a port such as COM5, /dev/ttyACM0 or socket://127.0.0.1:7350",
                    http=400,
                )

    def link(self) -> str:
        return self.kind

    def target(self) -> str:
        if self.kind == "serial":
            return self.url or ""
        host = self.host or "127.0.0.1"
        return f"{host}:{self.port or DEFAULT_PORT}"


def parse_connect_arg(text: str) -> ConnectSpec:
    """``sim``, ``tcp:HOST[:PORT]`` or ``serial:URL`` (the ``--connect`` option of ``rzlab serve``)."""
    kind, _, rest = text.partition(":")
    if kind == "sim" and not rest:
        return ConnectSpec("sim")
    if kind == "tcp" and rest:
        host, port = parse_host_port(rest)
        return ConnectSpec("tcp", host=host, port=port)
    if kind == "serial" and rest:
        return ConnectSpec("serial", url=rest)
    raise ValueError(f"bad --connect value {text!r}; use sim, tcp:HOST:PORT or serial:URL")


def stream_mask_of(streams: list[str | int] | None, known: dict[int, str]) -> int:
    """Stream names or ids to a mask. ``None`` or an empty list means every stream the node has."""
    if not streams:
        mask = 0
        for sid in known:
            mask |= 1 << sid
        return mask
    by_name = {v: k for k, v in known.items()}
    mask = 0
    for s in streams:
        if isinstance(s, str) and s in by_name:
            sid = by_name[s]
        elif isinstance(s, int) and not isinstance(s, bool) and s in known:
            sid = s
        elif isinstance(s, str) and s.isdigit() and int(s) in known:
            sid = int(s)
        else:
            raise DeviceError(
                "invalid_request", f"unknown stream {s!r}; the node has {', '.join(known.values())}", http=400
            )
        mask |= 1 << sid
    return mask


def _num(v: Any) -> Any:
    """JSON-safe number: NaN and infinity become None."""
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def clean(obj: Any) -> Any:
    """Recursively make a structure JSON-safe (non-finite floats to None, numpy scalars to Python)."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.generic):
        return clean(obj.item())
    return _num(obj)


class DeviceManager:
    def __init__(
        self,
        emit: Emit | None = None,
        ring_seconds: float = RING_SECONDS,
        embedded_sim: bool = True,
        wall: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._emit_cb: Emit = emit or (lambda ev: None)
        self.ring_seconds = ring_seconds
        self.embedded_sim_enabled = embedded_sim
        self._wall = wall
        self._cmd_q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="rzlab-device", daemon=True)
        self._lock = threading.Lock()
        self._latest: dict[str, dict] = {}
        self._logs: deque[dict] = deque(maxlen=LOG_KEEP)
        self._event_id = 0
        # session state: only the worker thread writes these
        self._state = "disconnected"
        self._spec: ConnectSpec | None = None
        self._error: str | None = None
        self._client: LinkClient | None = None
        self._mon = SessionMonitor()
        self._replies: dict[int, Ack | Err] = {}
        self._force_start = False
        self._session_alive = False
        self._next_ping = 0.0
        self._next_status = 0.0
        self._last_rx = 0.0
        self._bytes_mark: tuple[float, int] = (0.0, 0)
        self._rx_bytes_per_s = 0.0
        self._embedded: Any = None
        self._embedded_started_here = False
        self.rings: dict[int, SampleRing] = {}
        self._tap: RecordTap | None = None
        self.clock_map = ClockMap()  # host clock -> node clock, from every PING/PONG pair of this connection

    # --------------------------------------------------------------------------------- lifecycle

    def set_emit(self, emit: Emit) -> None:
        self._emit_cb = emit

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()
        self._publish(self._connection_event())

    def close(self) -> None:
        """Politely stop and disconnect, end the worker thread, stop an embedded simulator."""
        if self._thread.is_alive():
            try:
                self.submit(lambda: self._do_disconnect(polite=True)).result(timeout=10)
            except Exception:  # noqa: BLE001
                pass
            self._stop.set()
            self._cmd_q.put(None)
            self._thread.join(timeout=10)
        if self._embedded is not None:
            self._embedded.stop()
            self._embedded = None

    def submit(self, fn: Callable[[], Any]) -> concurrent.futures.Future:
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._cmd_q.put((fn, fut))
        return fut

    # ------------------------------------------------------------------------------ public commands

    def connect(self, spec: ConnectSpec) -> concurrent.futures.Future:
        spec.validate()
        return self.submit(lambda: self._do_connect(spec))

    def disconnect(self) -> concurrent.futures.Future:
        return self.submit(lambda: self._do_disconnect(polite=True))

    def start_streams(self, mask: int) -> concurrent.futures.Future:
        return self.submit(lambda: self._do_start(mask))

    def stop_streams(self, mask: int) -> concurrent.futures.Future:
        return self.submit(lambda: self._do_stop(mask))

    def set_value(self, key: str, value: int) -> concurrent.futures.Future:
        return self.submit(lambda: self._do_set(key, value))

    def stream_names(self) -> dict[int, str]:
        hello = self._mon.hello
        if hello is None:
            return {}
        return {s.id: codec.STREAM_NAMES.get(s.id, f"stream{s.id}") for s in hello.streams}

    def record_start(self, tap: RecordTap, mask: int) -> concurrent.futures.Future:
        """STOP everything (clean slate), install ``tap``, START ``mask``. The tap sees only the new window."""
        return self.submit(lambda: self._do_record_start(tap, mask))

    def record_stop(self, mask: int) -> concurrent.futures.Future:
        """STOP ``mask``, wait for the drain, detach the tap. Resolves to ``{"snapshot": ..., "stop_error": ...}``."""
        return self.submit(lambda: self._do_record_stop(mask))

    @property
    def recording(self) -> bool:
        return self._tap is not None

    def host_us(self) -> int:
        """The server clock in microseconds (the clock of the PING frames); thread-safe."""
        return self._host_us()

    def publish(self, event: dict) -> None:
        """Emit an event from any thread (the recorder's progress and label events)."""
        self._publish(event)

    def record_context(self) -> dict | None:
        """What a sidecar needs from the connected node (HELLO, CONFIG, the connection kind); None if not connected."""
        mon, spec = self._mon, self._spec
        hello, cfg = mon.hello, mon.config
        if hello is None or cfg is None or self._client is None or self._state != "connected" or spec is None:
            return None
        streams: dict[int, dict] = {}
        for s in hello.streams:
            sc = next((c for c in cfg.streams if c.id == s.id), None)
            streams[s.id] = {
                "id": s.id,
                "name": codec.STREAM_NAMES.get(s.id, f"stream{s.id}"),
                "n_ch": s.n_ch,
                "nominal_hz": s.nominal_hz,
                "bits": s.bits,
                "clock": CLOCK_NAMES.get(s.clock, str(s.clock)),
                "channels": [
                    {"gain": c.gain, "scale": float(c.scale), "units": UNIT_NAMES.get(c.units, "counts")}
                    for c in (sc.channels if sc else [])
                ],
            }
        heads = []
        for h in hello.heads:
            try:
                desc: Any = json.loads(h.descriptor.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                desc = None
            heads.append({"port": h.port, "descriptor": desc})
        return {
            "node_id": hello.node_id,
            "fw_version": hello.fw_version,
            "link_kind": spec.kind,
            "streams": streams,
            "heads": heads,
        }

    # ----------------------------------------------------------------------------------- read side

    def state(self) -> dict:
        """The latest connection, hello, config and status events (a snapshot for a new client)."""
        with self._lock:
            return {k: dict(v) for k, v in self._latest.items()}

    def logs(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return list(self._logs)[-limit:]

    @property
    def connected(self) -> bool:
        return self._state == "connected"

    def stream_info(self, stream_id: int) -> dict | None:
        """What a view needs about one stream: n_ch, scale, units, full scale and the best known rate."""
        mon = self._mon
        sm = mon.streams.get(stream_id)
        if sm is None or sm.info is None:
            return None
        n_ch = sm.info.n_ch
        scale = [1.0] * n_ch
        units = ["counts"] * n_ch
        gain: list[int | None] = [None] * n_ch
        cfg = mon.config
        if cfg is not None:
            for sc in cfg.streams:
                if sc.id == stream_id:
                    scale = [float(c.scale) for c in sc.channels][:n_ch]
                    units = [UNIT_NAMES.get(c.units, "counts") for c in sc.channels][:n_ch]
                    gain = [c.gain for c in sc.channels][:n_ch]
        rate = sm.rate_fit_hz
        source = "fit"
        if rate is None:
            rate = sm.rate_status_hz
            source = "status"
        if rate is None:
            rate = float(sm.info.nominal_hz)
            source = "nominal"
        return {
            "id": stream_id,
            "name": sm.name,
            "n_ch": n_ch,
            "nominal_hz": sm.info.nominal_hz,
            "bits": sm.info.bits,
            "full_scale": 2 ** (sm.info.bits - 1),
            "scale": scale,
            "units": units,
            "gain": gain,
            "fs_hz": float(rate),
            "fs_source": source,
        }

    # ------------------------------------------------------------------------------------ events

    def _emit(self, event: dict) -> None:
        event.setdefault("t", time.time())
        try:
            self._emit_cb(clean(event))
        except Exception:  # noqa: BLE001 - a broken listener must not kill the link thread
            pass

    def _publish(self, event: dict) -> None:
        event.setdefault("t", time.time())
        event = clean(event)
        if event["type"] in CACHED_EVENTS:
            with self._lock:
                self._latest[event["type"]] = event
        elif event["type"] == "log":
            with self._lock:
                self._logs.append(event)
        try:
            self._emit_cb(event)
        except Exception:  # noqa: BLE001
            pass

    def host_log(self, msg: str, level: int = 3) -> None:
        self._publish(
            {
                "type": "log",
                "source": "host",
                "level": level,
                "level_name": LOG_LEVEL_NAMES[level],
                "t_dev_us": None,
                "tag": "lab",
                "msg": msg,
            }
        )

    def _error_event(self, err: DeviceError, command: str) -> DeviceError:
        self._event_id += 1
        err.event_id = self._event_id
        self._publish({"type": "error", "id": self._event_id, "command": command, **err.to_dict()})
        return err

    def _connection_event(self) -> dict:
        spec = self._spec
        return {
            "type": "connection",
            "state": self._state,
            "link": spec.link() if spec else None,
            "target": spec.target() if spec else None,
            "embedded_sim": self._embedded is not None and spec is not None and spec.kind == "sim",
            "error": self._error,
        }

    def _set_state(self, state: str, error: str | None = None) -> None:
        self._state = state
        self._error = error
        self._publish(self._connection_event())

    # ------------------------------------------------------------------------------- worker loop

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                cmd = self._cmd_q.get(timeout=0.0 if self._client is not None else 0.1)
            except queue.Empty:
                cmd = None
            if cmd is not None:
                fn, fut = cmd
                if not fut.set_running_or_notify_cancel():
                    continue
                try:
                    fut.set_result(fn())
                except DeviceError as exc:
                    fut.set_exception(exc)
                except TransportClosed as exc:
                    self._link_lost(str(exc))
                    fut.set_exception(
                        self._error_event(DeviceError("link_lost", f"connection lost: {exc}", http=502), "command")
                    )
                except Exception as exc:  # noqa: BLE001
                    fut.set_exception(exc)
                continue
            if self._client is None:
                continue
            try:
                self._handle(self._client.poll(LOOP_POLL_S))
            except TransportClosed as exc:
                self._link_lost(str(exc))
            except Exception as exc:  # noqa: BLE001
                self._link_lost(f"internal error: {exc!r}")

    # ----------------------------------------------------------------------------------- frames

    def _host_us(self) -> int:
        return int(self._wall() * 1e6)

    def _handle(self, frames: list) -> None:
        mon = self._mon
        if frames:
            self._last_rx = self._wall()
        for fr in frames:
            msg = fr.msg
            mon.on_frame(fr, self._host_us())
            if isinstance(msg, Data):
                ring = self.rings.get(msg.stream)
                if ring is not None:
                    ring.write(msg.first_sample, msg.samples)
                self._tap_call("on_data", msg)
            elif isinstance(msg, Pong):
                self.clock_map.add(msg.host_t_us, self._host_us(), msg.t_dev_us)
            elif isinstance(msg, Status):
                self._tap_call("on_status", mon)
            elif isinstance(msg, (Ack, Err)):
                self._replies[msg.cmd_seq] = msg
                if isinstance(msg, Err):
                    self._unsolicited_err(msg)
            elif isinstance(msg, Log):
                self._publish(
                    {
                        "type": "log",
                        "source": "node",
                        "level": msg.level,
                        "level_name": LOG_LEVEL_NAMES.get(msg.level, str(msg.level)),
                        "t_dev_us": msg.t_dev_us,
                        "tag": msg.tag,
                        "msg": msg.msg,
                    }
                )
            elif isinstance(msg, Config):
                self._publish(self._config_event())
        self._tick()

    def _tap_call(self, method: str, *args: Any) -> None:
        tap = self._tap
        if tap is None:
            return
        try:
            getattr(tap, method)(*args)
        except Exception as exc:  # noqa: BLE001 - a broken recorder must not kill the link thread
            self.host_log(f"recorder error in {method}: {exc!r}", 1)

    def _unsolicited_err(self, err: Err) -> None:
        """ERR frames are reported by the command that waits for them; a stray one (no command waiting) is logged."""
        # A command waiting on this cmd_seq raises its own DeviceError; here only note it in the log.
        self.host_log(f"node ERR {err.code} for command seq {err.cmd_seq}: {err.msg}", level=2)

    def _tick(self) -> None:
        """Housekeeping that must run whenever the link is polled: PING and the 1 Hz status event."""
        client = self._client
        if client is None or self._mon.hello is None:
            return
        now = self._wall()
        if now >= self._next_ping:
            client.send(Ping(self._host_us()))
            self._next_ping = now + PING_PERIOD_S
        if now >= self._next_status:
            self._next_status = now + STATUS_EVENT_PERIOD_S
            self._publish(self._status_event())

    def _wait_reply(self, seq: int, timeout_s: float) -> Ack | Err | None:
        assert self._client is not None
        deadline = self._wall() + timeout_s
        while self._wall() < deadline:
            reply = self._replies.pop(seq, None)
            if reply is not None:
                return reply
            self._handle(self._client.poll(LOOP_POLL_S))
        return self._replies.pop(seq, None)

    # --------------------------------------------------------------------------------- connect

    def _open_transport(self, spec: ConnectSpec):
        try:
            if spec.kind == "serial":
                return SerialTransport(spec.url or "")
            if spec.kind == "tcp":
                return TcpTransport(spec.host or "127.0.0.1", spec.port or DEFAULT_PORT)
            port = spec.port or DEFAULT_PORT
            try:
                return TcpTransport("127.0.0.1", port)
            except OSError:
                if not self.embedded_sim_enabled:
                    raise
            self._start_embedded_sim(port)
            return TcpTransport("127.0.0.1", self._embedded.port)
        except DeviceError:
            raise
        except Exception as exc:  # noqa: BLE001 - OSError, pyserial's SerialException, ...
            raise DeviceError("connect_failed", f"cannot connect to {spec.target()}: {exc}", http=502) from exc

    def _start_embedded_sim(self, port: int) -> None:
        if self._embedded is not None:
            return
        from ..sim.node import SimConfig
        from ..sim.server import SimThread

        try:
            sim = SimThread(SimConfig(), "127.0.0.1", port).start()
        except OSError:
            sim = SimThread(SimConfig(), "127.0.0.1", 0).start()
        self._embedded = sim
        self.host_log(f"no simulator was listening: started an embedded one on 127.0.0.1:{sim.port}")

    def _setup_rings(self, hello: Hello) -> None:
        rings: dict[int, SampleRing] = {}
        for s in hello.streams:
            cap = int(self.ring_seconds * s.nominal_hz * RING_MARGIN)
            old = self.rings.get(s.id)
            if old is not None and old.n_ch == s.n_ch and old.capacity == cap:
                epoch = old.reset()
                rings[s.id] = old
                self._publish(
                    {
                        "type": "stream_reset",
                        "stream": s.id,
                        "name": codec.STREAM_NAMES.get(s.id, f"stream{s.id}"),
                        "epoch": epoch,
                    }
                )
            else:
                rings[s.id] = SampleRing(s.n_ch, cap)
        self.rings = rings

    def _do_connect(self, spec: ConnectSpec) -> dict:
        if self._client is not None:
            self._do_disconnect(polite=True)
        self._spec = spec
        self._set_state("connecting")
        self._mon = SessionMonitor()
        self.clock_map = ClockMap()
        self._replies.clear()
        self._session_alive = False
        try:
            transport = self._open_transport(spec)
        except DeviceError as exc:
            self._set_state("disconnected", exc.message)
            raise self._error_event(exc, "connect") from exc
        client = LinkClient(transport)
        self._client = client
        self._next_ping = self._wall()
        self._next_status = self._wall() + STATUS_EVENT_PERIOD_S
        self._last_rx = self._wall()
        self._bytes_mark = (self._wall(), 0)
        try:
            session.open_session(client, self._mon, spec.key, self._handle, self._wall, HANDSHAKE_TIMEOUT_S)
            hello = self._mon.hello
            assert hello is not None
            self._setup_rings(hello)
            self._session_alive = True
            self._publish(self._hello_event())
            self._publish(self._config_event())
            acked = session.clean_stop(client, self._mon, self._handle, self._wall)
            self._force_start = not acked
            if not acked:
                self.host_log(
                    "the clean-up STOP was not acknowledged: the first START will count any stale window as loss", 2
                )
        except session.SessionError as exc:
            hint = ""
            if spec.kind == "tcp" and spec.key is None and "no HELLO" in str(exc):
                hint = " A Wi-Fi node needs its pairing key."
            self._drop_client()
            self._set_state("disconnected", str(exc) + hint)
            raise self._error_event(DeviceError("session_failed", str(exc) + hint, http=502), "connect") from exc
        except TransportClosed as exc:
            self._drop_client()
            self._set_state("disconnected", f"connection lost: {exc}")
            raise self._error_event(
                DeviceError("link_lost", f"connection lost during start-up: {exc}", http=502), "connect"
            ) from exc
        self._set_state("connected")
        self._publish(self._status_event())
        return {"state": "connected", "node_id": hello.node_id}

    def _drop_client(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass

    def _do_disconnect(self, polite: bool) -> dict:
        client = self._client
        if client is None:
            return {"state": self._state}
        self._end_tap("disconnected")
        self._set_state("disconnecting")
        if polite and self._mon.hello is not None:
            try:
                if any(sm.running for sm in self._mon.streams.values()):
                    seq = client.send(Stop(session.all_streams_mask(self._mon)))
                    self._mon.expect_stop_ack(seq, session.all_streams_mask(self._mon))
                    self._wait_reply(seq, POLITE_STOP_TIMEOUT_S)
            except Exception:  # noqa: BLE001 - the link may already be dead; closing is what matters
                pass
        self._publish(self._status_event())
        self._drop_client()
        self._set_state("disconnected")
        return {"state": "disconnected"}

    def _link_lost(self, reason: str) -> None:
        """The transport died under us. Keep the rings and the monitor (the last window stays viewable)."""
        self._end_tap(reason)
        self._drop_client()
        self._session_alive = False
        self._error = f"connection lost: {reason}"
        self._state = "disconnected"
        self.host_log(self._error, 1)
        self._publish(self._status_event())
        self._publish(self._connection_event())
        self._error_event(DeviceError("link_lost", self._error, http=502), "link")

    def _snapshot(self, mask: int) -> dict[int, dict]:
        """Loss numbers of the streams in ``mask`` for a recording that ends now: exact when the final STATUS and
        the STOP's ACK arrived, otherwise 'incomplete' (everything unattributed counts as host loss)."""
        out: dict[int, dict] = {}
        for sid, sm in self._mon.streams.items():
            if mask & (1 << sid):
                out[sid] = {
                    "report": sm.acct.report("final" if sm.finalized else "incomplete"),
                    "final": sm.finalized,
                    "rate_status_hz": sm.rate_status_hz,
                    "rate_fit_hz": sm.rate_fit_hz,
                    "timing_flags": sm.timing_flags,
                }
        return out

    def _end_tap(self, reason: str) -> None:
        """The recording cannot continue (link lost, disconnect): hand the recorder what we know and detach it."""
        tap, self._tap = self._tap, None
        if tap is None:
            return
        try:
            tap.on_link_lost(self._snapshot(self.stream_mask_all()), reason)
        except Exception as exc:  # noqa: BLE001
            self.host_log(f"recorder error ending the recording: {exc!r}", 1)

    # ---------------------------------------------------------------------------------- commands

    def _do_record_start(self, tap: RecordTap, mask: int) -> dict:
        client = self._require_connected()
        mon = self._mon
        if self._tap is not None:
            raise DeviceError("recording_active", "a recording is already running", http=409)
        if mask == 0 or mask & ~self.stream_mask_all():
            raise self._error_event(DeviceError("invalid_request", "bad stream mask", http=400), "record")
        # Clean slate: a window left over from the Live page (or a dead PC) must not leak into the recording.
        acked = session.clean_stop(client, mon, self._handle, self._wall)
        if not acked:
            self.host_log("the clean-up STOP was not acknowledged: a stale window will show up as loss", 2)
        for sid, sm in mon.streams.items():
            if mask & (1 << sid):
                ring = self.rings.get(sid)
                if ring is not None:
                    epoch = ring.reset()
                    self._publish({"type": "stream_reset", "stream": sid, "name": sm.name, "epoch": epoch})
        self._tap = tap  # after the STOP's ACK: nothing before it can belong to the new window
        seq = client.send(Start(mask))
        mon.start_sent(seq, mask, force=not acked)
        self._force_start = False
        reply = self._wait_reply(seq, START_TIMEOUT_S)
        if isinstance(reply, Err) or reply is None:
            self._tap = None
            if isinstance(reply, Err):
                raise self._error_event(self._err_to_device_error(reply, "START"), "start")
            raise self._error_event(
                DeviceError("timeout", "no ACK for START within 2 s; the recording was not started", http=504),
                "start",
            )
        self._publish(self._status_event())
        return {"started": mask, "clean_stop_acked": acked}

    def _do_record_stop(self, mask: int) -> dict:
        client = self._require_connected()
        seq = client.send(Stop(mask))
        self._mon.expect_stop_ack(seq, mask)
        reply = self._wait_reply(seq, STOP_TIMEOUT_S)
        stop_error = None
        if isinstance(reply, Err):
            stop_error = f"STOP refused: ERR {reply.code} {reply.msg}"
        elif reply is None:
            stop_error = "no ACK for STOP within 3 s"
        snapshot = self._snapshot(mask)
        self._tap = None
        self._publish(self._status_event())
        return {"snapshot": snapshot, "stop_error": stop_error}

    def _require_connected(self) -> LinkClient:
        if self._client is None or self._state != "connected":
            raise DeviceError("not_connected", "no node is connected", http=409)
        return self._client

    def _err_to_device_error(self, err: Err, what: str, key: str | None = None) -> DeviceError:
        code = err.code
        text = err.msg or "no detail"
        if code == codec.ERR_BUSY:
            hint = "Stop acquisition first."
            if key and key.startswith("adc.gain"):
                hint = "Stop acquisition on adc_raw and adc_dec first, then change the gain."
            elif key == "accel.range_g":
                hint = "Stop acquisition on accel first, then change the range."
            return DeviceError(
                "busy", f"The node is busy (ERR 5): {what} is not allowed while it is acquiring. {hint}", 5, 409
            )
        if code == codec.ERR_BAD_VALUE:
            return DeviceError("bad_value", f"The node rejected the value for {what} (ERR 4): {text}", 4, 400)
        if code == codec.ERR_UNKNOWN_KEY:
            return DeviceError("unknown_key", f"The node does not know {what} (ERR 3): {text}", 3, 400)
        if code == codec.ERR_NOT_AUTHORISED:
            return DeviceError("not_authorised", f"The node refused {what} (ERR 6): {text}", 6, 403)
        return DeviceError("node_error", f"The node answered {what} with ERR {code}: {text}", code, 502)

    def _do_start(self, mask: int) -> dict:
        client = self._require_connected()
        mon = self._mon
        valid = self.stream_mask_all()
        if mask == 0 or mask & ~valid:
            raise self._error_event(DeviceError("invalid_request", "bad stream mask", http=400), "start")
        force = self._force_start
        # Streams that start from idle restart their sample indices at 0 (PROTOCOL.md 4.3): new ring epoch.
        for sid, sm in mon.streams.items():
            if mask & (1 << sid) and (force or not sm.running):
                ring = self.rings.get(sid)
                if ring is not None:
                    epoch = ring.reset()
                    self._publish({"type": "stream_reset", "stream": sid, "name": sm.name, "epoch": epoch})
        seq = client.send(Start(mask))
        mon.start_sent(seq, mask, force=force)
        self._force_start = False
        reply = self._wait_reply(seq, START_TIMEOUT_S)
        if isinstance(reply, Err):
            raise self._error_event(self._err_to_device_error(reply, "START"), "start")
        if reply is None:
            raise self._error_event(
                DeviceError("timeout", "no ACK for START within 2 s; the stream may still have started", http=504),
                "start",
            )
        self._publish(self._status_event())
        return {"started": mask}

    def stream_mask_all(self) -> int:
        mask = 0
        for sid in self._mon.streams:
            mask |= 1 << sid
        return mask

    def _do_stop(self, mask: int) -> dict:
        client = self._require_connected()
        if mask == 0 or mask & ~self.stream_mask_all():
            raise self._error_event(DeviceError("invalid_request", "bad stream mask", http=400), "stop")
        seq = client.send(Stop(mask))
        self._mon.expect_stop_ack(seq, mask)
        reply = self._wait_reply(seq, STOP_TIMEOUT_S)
        self._publish(self._status_event())
        if isinstance(reply, Err):
            raise self._error_event(self._err_to_device_error(reply, "STOP"), "stop")
        if reply is None:
            raise self._error_event(
                DeviceError("timeout", "no ACK for STOP within 3 s; the loss numbers stay 'incomplete'", http=504),
                "stop",
            )
        return {"stopped": mask}

    def _do_set(self, key: str, value: int) -> dict:
        client = self._require_connected()
        if key not in SETTABLE_KEYS:
            raise self._error_event(
                DeviceError(
                    "unknown_key", f"{key!r} cannot be set from the UI; use one of {', '.join(SETTABLE_KEYS)}", http=400
                ),
                "set",
            )
        if isinstance(value, bool) or not isinstance(value, int):
            raise self._error_event(DeviceError("bad_value", "the value must be an integer", http=400), "set")
        before = self._mon.config
        seq = client.send(Set(key, value))
        reply = self._wait_reply(seq, SET_TIMEOUT_S)
        if isinstance(reply, Err):
            raise self._error_event(self._err_to_device_error(reply, key, key), f"set {key}")
        if reply is None:
            raise self._error_event(
                DeviceError("timeout", f"no answer to SET {key} within 2 s", http=504), f"set {key}"
            )
        # ACK is followed by a new CONFIG; wait briefly so the caller sees the new numbers
        deadline = self._wall() + 0.5
        while self._mon.config is before and self._wall() < deadline:
            self._handle(client.poll(LOOP_POLL_S))
        return {"set": key, "value": value}

    # ------------------------------------------------------------------------------- event bodies

    def _hello_event(self) -> dict:
        hello = self._mon.hello
        assert hello is not None
        heads = []
        for h in hello.heads:
            try:
                desc: Any = json.loads(h.descriptor.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                desc = None
            heads.append({"port": h.port, "descriptor": desc})
        return {
            "type": "hello",
            "proto": hello.proto,
            "fw_version": hello.fw_version,
            "node_id": hello.node_id,
            "t_dev_us": hello.t_dev_us,
            "streams": [
                {
                    "id": s.id,
                    "name": codec.STREAM_NAMES.get(s.id, f"stream{s.id}"),
                    "n_ch": s.n_ch,
                    "nominal_hz": s.nominal_hz,
                    "bits": s.bits,
                    "full_scale": 2 ** (s.bits - 1),
                    "clock": CLOCK_NAMES.get(s.clock, str(s.clock)),
                    "fir_taps": s.fir_taps,
                    "fir_delay": s.fir_delay,
                }
                for s in hello.streams
            ],
            "heads": heads,
        }

    def _config_event(self) -> dict:
        cfg = self._mon.config
        assert cfg is not None
        return {
            "type": "config",
            "streams": [
                {
                    "id": sc.id,
                    "name": codec.STREAM_NAMES.get(sc.id, f"stream{sc.id}"),
                    "channels": [
                        {"gain": c.gain, "scale": c.scale, "units": UNIT_NAMES.get(c.units, "counts")}
                        for c in sc.channels
                    ],
                }
                for sc in cfg.streams
            ],
            "accel_range_g": cfg.accel_range_g,
            "status_period_ms": cfg.status_period_ms,
        }

    def _levels(self, stream_id: int) -> list[dict] | None:
        ring = self.rings.get(stream_id)
        info = self.stream_info(stream_id)
        if ring is None or info is None or ring.head == 0:
            return None
        n = max(8, int(info["fs_hz"] * LEVEL_WINDOW_S))
        _lo, data, valid = ring.read_last(n)
        lv = channel_levels(data, np.array(info["scale"]), info["full_scale"], valid)
        return [
            {
                "mean": x.mean,
                "rms": x.rms,
                "std": x.std,
                "peak": x.peak,
                "clipped": x.clipped,
                "n": x.n,
                "units": info["units"][i],
            }
            for i, x in enumerate(lv)
        ]

    def _status_event(self) -> dict:
        mon = self._mon
        now = self._wall()
        client = self._client
        alive = self._session_alive and client is not None
        st = mon.last_status
        streams = []
        for sid, sm in sorted(mon.streams.items()):
            loss = sm.loss(alive)
            rs, rf = sm.rate_status_hz, sm.rate_fit_hz
            nominal = float(sm.info.nominal_hz)
            ring = self.rings.get(sid)
            loss_d = None
            if loss is not None:
                loss_d = {
                    "device": loss.device,
                    "link": loss.link,
                    "host": loss.host_gap,
                    "host_exact": loss.host_gap_exact,
                    "host_max": loss.host_gap_max,
                    "pending": loss.pending,
                    "received": loss.received,
                    "missing": loss.missing,
                    "window": loss.window,
                    "win_first": loss.win_first,
                    "win_end": loss.win_end,
                    "final": sm.finalized,
                    "incomplete": loss.incomplete,
                    "protocol_bug": loss.protocol_bug,
                }
            streams.append(
                {
                    "id": sid,
                    "name": sm.name,
                    "n_ch": sm.info.n_ch,
                    "nominal_hz": sm.info.nominal_hz,
                    "running": sm.running,
                    "rate_hz_status": rs,
                    "rate_hz_fit": rf,
                    "offset_pct_status": offset_pct(rs, nominal),
                    "offset_pct_fit": offset_pct(rf, nominal),
                    "produced": sm.status.produced if sm.status else None,
                    "node_device_dropped": sm.status.device_dropped if sm.status else None,
                    "node_clipped": sm.status.clipped if sm.status else None,
                    "packets": sm.packets,
                    "samples": sm.samples,
                    "timing_flags": sm.timing_flags,
                    "loss": loss_d,
                    "levels": self._levels(sid),
                    "epoch": ring.epoch if ring else 0,
                    "head": ring.head if ring else 0,
                }
            )
        link: dict[str, Any] = {
            "type": self._spec.link() if self._spec else None,
            "target": self._spec.target() if self._spec else None,
        }
        if client is not None:
            rx = client.rx
            t0, b0 = self._bytes_mark
            if now - t0 >= 0.5:
                self._rx_bytes_per_s = (rx.bytes_in - b0) / (now - t0)
                self._bytes_mark = (now, rx.bytes_in)
            age = now - self._last_rx
            link.update(
                {
                    "rtt_ms": mon.rtt_us / 1000.0 if mon.rtt_us is not None else None,
                    "bad_frames": rx.bad_frames,
                    "lost_frames": rx.lost_frames,
                    "resyncs": rx.resyncs,
                    "unknown_types": rx.unknown_types,
                    "frames_ok": rx.frames_ok,
                    "bytes_in": rx.bytes_in,
                    "rx_bytes_per_s": self._rx_bytes_per_s,
                    "last_rx_age_s": age,
                    "stale": age > STALE_AFTER_S,
                }
            )
        health = None
        if st is not None:
            health = {
                "queue_fill": st.queue_fill,
                "heap_free": st.heap_free,
                "temp_c": st.temp_c_x10 / 10.0,
                "rssi_dbm": st.rssi_dbm if st.rssi_dbm != 0 else None,
                "sd_state": st.sd_state,
                "sd_free_mb": st.sd_free_mb,
                "t_dev_us": st.t_dev_us,
            }
        hello = mon.hello
        return {
            "type": "status",
            "state": self._state,
            "node": {"node_id": hello.node_id, "fw_version": hello.fw_version, "proto": hello.proto} if hello else None,
            "link": link,
            "health": health,
            "streams": streams,
            "acquiring": any(s["running"] for s in streams),
            "recording": self._tap is not None,
        }
