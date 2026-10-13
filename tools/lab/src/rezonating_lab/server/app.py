"""The Lab web app: REST for commands and views, one WebSocket for live data. Contract: ``tools/lab/WEB_API.md``."""

from __future__ import annotations

import asyncio
import contextlib
import json
import struct
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import numpy as np
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, StrictInt
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..core import view
from ..core.ringbuf import SampleRing
from ..recorder.config import LabConfig, load_config
from ..recorder.recording import RecordError, Recorder
from .device import ConnectSpec, DeviceError, DeviceManager, stream_mask_of
from .ports import list_serial_ports
from .bench_routes import register_bench_routes
from .dataset_routes import register_dataset_routes
from .experiment_routes import register_experiment_routes
from .record_routes import register_record_routes
from .rigcheck import RigChecks
from .review_routes import register_review_routes
from .rigcheck_routes import register_rigcheck_routes
from .security import LoopbackGuard

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

# Binary sample frame (WEB_API.md): 20-byte header, then n * n_ch int32, little-endian, frame-major.
MSG_SAMPLES = 1
DTYPE_I32 = 0
HEADER = struct.Struct("<BBBBHHQI")
HEADER_LEN = HEADER.size  # 20
BROADCAST_PERIOD_S = 0.05  # ~20 Hz
MAX_FRAMES_PER_MESSAGE = 8192
MAX_MESSAGES_PER_TICK = 256
CLIENT_QUEUE_MAX = 600

NO_UI_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rezonating Lab</title><style>body{font:16px system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem}
code{background:#8883;padding:.1rem .3rem;border-radius:4px}</style></head><body><h1>Rezonating Lab</h1>
<p>The server is running, but the browser UI has not been built yet.</p>
<p>Run <code>rzlab build-ui</code> (needs Node.js and npm), then reload this page.</p>
<p>The API is up: <a href="/api/state">/api/state</a>, <a href="/api/docs">/api/docs</a>.</p></body></html>"""


def pack_samples(stream_id: int, n_ch: int, epoch: int, first_sample: int, samples: np.ndarray) -> bytes:
    """One binary WebSocket message: header + int32 samples (see WEB_API.md for the byte layout)."""
    n = int(samples.shape[0])
    head = HEADER.pack(MSG_SAMPLES, stream_id, n_ch, DTYPE_I32, epoch & 0xFFFF, 0, first_sample, n)
    return head + np.ascontiguousarray(samples, dtype="<i4").tobytes()


# ------------------------------------------------------------------------------------------------- hub


class _Client:
    def __init__(self, streams: set[int] | None) -> None:
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=CLIENT_QUEUE_MAX)
        self.streams = streams  # None: every stream
        self.dead = False

    def wants(self, stream_id: int) -> bool:
        return self.streams is None or stream_id in self.streams


class _Cursor:
    def __init__(self, ring: SampleRing) -> None:
        self.ring = ring
        self.epoch = ring.epoch
        self.pos = ring.head  # a client joins live: it gets new samples only


class Hub:
    """Fans events and sample frames out to WebSocket clients. Lives on the asyncio loop; never blocks."""

    def __init__(self) -> None:
        self.clients: set[_Client] = set()
        self._cursors: dict[int, _Cursor] = {}
        self.frames_sent = 0
        self.bytes_sent = 0

    def add(self, streams: set[int] | None) -> _Client:
        c = _Client(streams)
        self.clients.add(c)
        return c

    def remove(self, client: _Client) -> None:
        self.clients.discard(client)

    def _put(self, client: _Client, item: Any) -> None:
        if client.dead:
            return
        try:
            client.queue.put_nowait(item)
        except asyncio.QueueFull:
            client.dead = True  # too slow: drop it rather than grow without bound
            while not client.queue.empty():
                client.queue.get_nowait()
            client.queue.put_nowait(None)

    def publish_json(self, event: dict) -> None:
        text = json.dumps(event, separators=(",", ":"), allow_nan=False)
        for c in list(self.clients):
            self._put(c, text)

    def pump(self, rings: dict[int, SampleRing]) -> None:
        """One broadcast tick: new samples of every ring to the clients that want that stream."""
        for sid, ring in rings.items():
            cur = self._cursors.get(sid)
            if cur is None or cur.ring is not ring:
                cur = self._cursors[sid] = _Cursor(ring)
            elif cur.epoch != ring.epoch:
                cur.epoch = ring.epoch
                cur.pos = 0  # runs_since clamps to the oldest index held
            interested = [c for c in self.clients if c.wants(sid) and not c.dead]
            if not interested:
                cur.pos = max(cur.pos, ring.head)
                continue
            runs, cur.pos, epoch = ring.runs_since(cur.pos, MAX_FRAMES_PER_MESSAGE)
            if len(runs) > MAX_MESSAGES_PER_TICK:
                cur.pos = runs[MAX_MESSAGES_PER_TICK][0]  # the rest goes out on the next tick, nothing is skipped
                runs = runs[:MAX_MESSAGES_PER_TICK]
            for first, samples in runs:
                msg = pack_samples(sid, ring.n_ch, epoch, first, samples)
                self.frames_sent += 1
                self.bytes_sent += len(msg)
                for c in interested:
                    self._put(c, msg)


# ----------------------------------------------------------------------------------------- API models


class ConnectBody(BaseModel):
    kind: Literal["sim", "tcp", "serial"]
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    url: str | None = None
    key: str | None = Field(default=None, description="pairing key, 32 hex digits")


class AcquisitionBody(BaseModel):
    action: Literal["start", "stop"]
    streams: list[str | int] | None = Field(default=None, description="names or ids; omitted = every stream")


class SetBody(BaseModel):
    key: Literal["adc.gain.0", "adc.gain.1", "accel.range_g"]
    value: StrictInt


def _error(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=status)


# --------------------------------------------------------------------------------------------- the app


def create_app(
    port: int,
    manager: DeviceManager | None = None,
    static_dir: Path | None = STATIC_DIR,
    initial_connect: ConnectSpec | None = None,
    embedded_sim: bool = True,
    dev_ports: tuple[int, ...] = (),
    lab_config: LabConfig | None = None,
    recorder: Recorder | None = None,
) -> FastAPI:
    """Build the app for a server that listens on loopback ``port`` (the port is needed for the Host/Origin guard).
    ``dev_ports`` lists extra loopback ports (the Vite dev server, ``rzlab serve --dev``) whose Host and Origin pass;
    empty by default.

    ``lab_config`` holds the recorder settings (data root, staging, sidecar copy target); default: read from the
    environment and ``config.toml`` (``recorder/config.py``). Tests pass their own."""
    mgr = manager or DeviceManager(embedded_sim=embedded_sim)
    cfg = lab_config or (recorder.cfg if recorder is not None else load_config())
    rec = recorder or Recorder(mgr, cfg)
    rig = RigChecks(mgr, cfg, recording=lambda: rec.active)
    rec.rig_running = lambda: rig.running
    hub = Hub()

    async def broadcaster() -> None:
        loop = asyncio.get_running_loop()
        nxt = loop.time()
        while True:
            nxt += BROADCAST_PERIOD_S
            delay = nxt - loop.time()
            if delay < -1.0:  # fell far behind (a stall): do not burst to catch up
                nxt = loop.time()
                delay = 0.0
            await asyncio.sleep(max(0.0, delay))
            hub.pump(mgr.rings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()

        def emit(event: dict) -> None:
            with contextlib.suppress(RuntimeError):  # loop already closed during shutdown
                loop.call_soon_threadsafe(hub.publish_json, event)

        mgr.set_emit(emit)
        mgr.start()
        mgr.publish(rec.status())
        mgr.publish(rec.runner_event())
        mgr.publish(rig.view())
        task = loop.create_task(broadcaster())
        auto: asyncio.Task | None = None
        if initial_connect is not None:

            async def first_connect() -> None:
                with contextlib.suppress(Exception):  # the failure is already an `error` event
                    await asyncio.wrap_future(mgr.connect(initial_connect))

            auto = loop.create_task(first_connect())
        try:
            yield
        finally:
            task.cancel()
            if auto is not None:
                auto.cancel()
            await asyncio.to_thread(rig.close)
            await asyncio.to_thread(rec.close)  # finish a running recording before the link goes away
            await asyncio.to_thread(mgr.close)

    app = FastAPI(
        title="Rezonating Lab",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.manager = mgr
    app.state.recorder = rec
    app.state.rigcheck = rig
    app.state.lab_config = cfg
    app.state.hub = hub
    app.state.static_dir = static_dir
    app.add_middleware(LoopbackGuard, port=port, dev_ports=dev_ports)

    # ------------------------------------------------------------------------------- error shapes

    @app.exception_handler(DeviceError)
    async def _device_error(_req, exc: DeviceError):
        return JSONResponse({"error": exc.to_dict()}, status_code=exc.http)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_req, exc: RequestValidationError):
        details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return _error(
            422,
            "invalid_request",
            "invalid request: " + "; ".join(f"{'.'.join(map(str, d['loc']))}: {d['msg']}" for d in details),
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req, exc: StarletteHTTPException):
        return _error(exc.status_code, f"http_{exc.status_code}", str(exc.detail))

    # ---------------------------------------------------------------------------------- commands

    async def run(fut) -> Any:
        return await asyncio.wrap_future(fut)

    def not_while_recording(what: str) -> None:
        if rec.active:
            raise RecordError(
                "recording_active", f"Cannot {what} while a recording runs. Stop the recording first.", http=409
            )
        if rig.running:
            raise DeviceError(
                "rigcheck_running", f"Cannot {what} while rig checks run. Wait for them or cancel them.", http=409
            )

    @app.get("/api/health")
    async def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/state")
    async def state():
        s = mgr.state()
        s["type"] = "state"
        s["clients"] = len(hub.clients)
        return s

    @app.get("/api/ports")
    async def ports():
        return {"ports": await asyncio.to_thread(list_serial_ports)}

    @app.post("/api/connect")
    async def connect(body: ConnectBody):
        not_while_recording("connect")
        try:
            key = bytes.fromhex(body.key) if body.key else None
        except ValueError:
            raise DeviceError("invalid_request", "the key must be 32 hex digits", http=400) from None
        spec = ConnectSpec(body.kind, body.host, body.port, body.url, key)
        return await run(mgr.connect(spec))

    @app.post("/api/disconnect")
    async def disconnect():
        not_while_recording("disconnect")
        return await run(mgr.disconnect())

    @app.post("/api/acquisition")
    async def acquisition(body: AcquisitionBody):
        not_while_recording("start or stop streams")
        names = mgr.stream_names()
        if not names:
            raise DeviceError("not_connected", "no node is connected", http=409)
        mask = stream_mask_of(body.streams, names)
        if body.action == "start":
            return await run(mgr.start_streams(mask))
        return await run(mgr.stop_streams(mask))

    @app.post("/api/set")
    async def set_value(body: SetBody):
        not_while_recording("change settings")
        return await run(mgr.set_value(body.key, body.value))

    @app.get("/api/logs")
    async def logs(limit: int = Query(200, ge=1, le=500)):
        return {"logs": mgr.logs(limit)}

    # --------------------------------------------------------------------------------------- views

    def window(stream: str, window_s: float, end: int | None) -> tuple[dict, SampleRing, int, int]:
        sid = _resolve_stream(mgr, stream)
        info = mgr.stream_info(sid)
        ring = mgr.rings.get(sid)
        if info is None or ring is None:
            raise DeviceError("no_stream", f"no data for stream {stream!r}; connect to a node first", http=404)
        hi = ring.head if end is None else min(end, ring.head)
        n = max(8, int(round(window_s * info["fs_hz"])))
        return info, ring, hi - n, hi

    def compute(fn: Callable[[], Any]) -> Awaitable[Any]:
        return asyncio.to_thread(fn)

    @app.get("/api/view/envelope")
    async def view_envelope(
        stream: str,
        window_s: float = Query(10.0, gt=0.0, le=900.0),
        end: int | None = Query(None, ge=0, description="sample index of the right edge; default newest"),
        columns: int = Query(1000, ge=1, le=4000),
    ):
        info, ring, lo, hi = window(stream, window_s, end)

        def work() -> dict:
            lo_r, data, valid = ring.read(lo, hi)
            env = view.envelope(data, columns, valid)
            gap = (env.n_valid == 0).astype(int).tolist()
            return {
                **_header(info, ring, lo_r, lo_r + len(data)),
                "columns": env.columns,
                "samples_per_column": (len(data) / env.columns) if env.columns else 0,
                "min": _codes(env.vmin),
                "max": _codes(env.vmax),
                "gap": gap,
                "valid_samples": int(valid.sum()),
            }

        return await compute(work)

    @app.get("/api/view/psd")
    async def view_psd(
        stream: str,
        window_s: float = Query(10.0, gt=0.0, le=900.0),
        end: int | None = Query(None, ge=0),
        nperseg: int = Query(1024, ge=64, le=16384),
    ):
        info, ring, lo, hi = window(stream, window_s, end)

        def work() -> dict:
            lo_r, data, valid = ring.read(lo, hi)
            scale = np.array(info["scale"])
            p = view.welch_psd(data * scale[None, :], info["fs_hz"], nperseg=nperseg, valid=valid)
            return {
                **_header(info, ring, lo_r, lo_r + len(data)),
                "nperseg": p.nperseg,
                "n_segments": p.n_segments,
                "freq_hz": [round(float(f), 4) for f in p.freq_hz],
                "psd": [[None if not np.isfinite(v) else float(f"{v:.5g}") for v in row] for row in p.psd],
                "psd_units": [f"{u}^2/Hz" for u in info["units"]],
            }

        return await compute(work)

    @app.get("/api/view/spectrogram")
    async def view_spectrogram(
        stream: str,
        channel: int = Query(0, ge=0, le=7),
        window_s: float = Query(10.0, gt=0.0, le=900.0),
        end: int | None = Query(None, ge=0),
        nfft: int = Query(256, ge=32, le=4096),
        hop: int | None = Query(None, ge=1, le=65536),
        max_columns: int = Query(300, ge=1, le=1000),
        since: int | None = Query(None, ge=0, description="only columns centred after this sample index"),
    ):
        info, ring, lo, hi = window(stream, window_s, end)
        if channel >= info["n_ch"]:
            raise DeviceError("invalid_request", f"stream {info['name']} has {info['n_ch']} channels", http=400)

        def work() -> dict:
            h = hop or max(nfft // 2, -(-(hi - lo) // max_columns))
            start = lo
            if since is not None:
                start = max(start, since - nfft // 2 + h)
            start = -(-max(start, 0) // h) * h  # columns sit on a grid of multiples of hop: stable across requests
            lo_r, data, valid = ring.read(start, hi)
            off = (-lo_r) % h
            lo_r, data, valid = lo_r + off, data[off:], valid[off:]
            x = data[:, channel].astype(np.float64) * info["scale"][channel]
            sp = view.stft_db(x, info["fs_hz"], nfft=nfft, hop=h, valid=valid, first_index=lo_r)
            db = np.round(sp.power_db, 1).astype(object)
            db[np.isnan(sp.power_db)] = None
            db, centers = db[-max_columns:], sp.center_index[-max_columns:]
            return {
                **_header(info, ring, lo_r, lo_r + len(data)),
                "channel": channel,
                "nfft": sp.nfft,
                "hop": h,
                "freq_hz": [round(float(f), 4) for f in sp.freq_hz],
                "center_index": centers.tolist(),
                "db": db.tolist(),
                "db_units": f"dB re {info['units'][channel]}^2/Hz",
            }

        return await compute(work)

    @app.get("/api/view/levels")
    async def view_levels(
        stream: str,
        window_s: float = Query(1.0, gt=0.0, le=900.0),
        end: int | None = Query(None, ge=0),
    ):
        info, ring, lo, hi = window(stream, window_s, end)

        def work() -> dict:
            lo_r, data, valid = ring.read(lo, hi)
            lv = view.channel_levels(data, np.array(info["scale"]), info["full_scale"], valid)
            return {
                **_header(info, ring, lo_r, lo_r + len(data)),
                "channels": [
                    {
                        "n": x.n,
                        "mean": x.mean,
                        "rms": x.rms,
                        "std": x.std,
                        "peak": x.peak,
                        "clipped": x.clipped,
                        "units": info["units"][i],
                    }
                    for i, x in enumerate(lv)
                ],
            }

        return _clean_json(await compute(work))

    register_record_routes(app, mgr, rec, cfg)
    register_rigcheck_routes(app, rig)
    register_review_routes(app, cfg)
    register_dataset_routes(app, cfg)
    register_bench_routes(app, cfg, mgr)
    register_experiment_routes(app, cfg)

    # ----------------------------------------------------------------------------------- WebSocket

    @app.websocket("/ws")
    async def ws(websocket: WebSocket, streams: str | None = None):
        wanted: set[int] | None = None
        if streams is not None:
            try:
                wanted = {int(s) for s in streams.split(",") if s.strip() != ""}
            except ValueError:
                await websocket.close(code=1003, reason="streams must be comma-separated stream ids")
                return
        await websocket.accept()
        client = hub.add(wanted)
        try:
            await _send_snapshot(websocket, mgr)

            async def sender() -> None:
                while True:
                    item = await client.queue.get()
                    if item is None:
                        await websocket.close(code=1013, reason="client too slow")
                        return
                    if isinstance(item, bytes):
                        await websocket.send_bytes(item)
                    else:
                        await websocket.send_text(item)

            async def receiver() -> None:
                while True:
                    text = await websocket.receive_text()
                    try:
                        req = json.loads(text)
                    except ValueError:
                        continue
                    op = req.get("op") if isinstance(req, dict) else None
                    if op == "snapshot":
                        await _send_snapshot(websocket, mgr)
                    elif op == "streams":
                        ids = req.get("streams")
                        if ids is None:
                            client.streams = None
                        elif isinstance(ids, list):
                            client.streams = {i for i in ids if isinstance(i, int) and not isinstance(i, bool)}
                        # anything else is ignored: the filter stays as it was

            tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc is not None and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        except WebSocketDisconnect:
            pass
        finally:
            hub.remove(client)

    # ----------------------------------------------------------------------- static files, SPA

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path == "ws" or full_path == "api" or full_path.startswith("api/"):
            return _error(404, "not_found", f"no such endpoint: /{full_path}")
        root: Path | None = app.state.static_dir
        if root is not None and (root / "index.html").is_file():
            base = root.resolve()
            candidate = (base / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(base):
                return FileResponse(candidate)
            return FileResponse(base / "index.html")
        return HTMLResponse(NO_UI_HTML)

    return app


# --------------------------------------------------------------------------------------------- helpers


async def _send_snapshot(websocket: WebSocket, mgr: DeviceManager) -> None:
    st = mgr.state()
    for kind in ("connection", "hello", "config", "status", "recording", "runner", "rigcheck"):
        if kind in st:
            await websocket.send_text(json.dumps(st[kind], separators=(",", ":"), allow_nan=False))


def _resolve_stream(mgr: DeviceManager, text: str) -> int:
    names = mgr.stream_names()
    if not names:
        raise DeviceError("no_stream", "no stream known yet; connect to a node first", http=404)
    for sid, name in names.items():
        if text == name or text == str(sid):
            return sid
    raise DeviceError("no_stream", f"unknown stream {text!r}; the node has {', '.join(names.values())}", http=404)


def _header(info: dict, ring: SampleRing, lo: int, hi: int) -> dict:
    return {
        "stream": info["id"],
        "name": info["name"],
        "n_ch": info["n_ch"],
        "epoch": ring.epoch,
        "fs_hz": info["fs_hz"],
        "fs_source": info["fs_source"],
        "nominal_hz": info["nominal_hz"],
        "scale": info["scale"],
        "units": info["units"],
        "lo": int(lo),
        "hi": int(hi),
        "head": ring.head,
        "oldest": ring.oldest(),
    }


def _codes(a: np.ndarray) -> list[list[int | None]]:
    """(columns, n_ch) float array of integer codes to [n_ch][columns] with None for NaN (gap columns)."""
    out: list[list[int | None]] = []
    for c in range(a.shape[1] if a.ndim == 2 else 0):
        col = a[:, c]
        out.append([None if np.isnan(v) else int(v) for v in col])
    return out


def _clean_json(obj: Any) -> Any:
    from .device import clean

    return clean(obj)
