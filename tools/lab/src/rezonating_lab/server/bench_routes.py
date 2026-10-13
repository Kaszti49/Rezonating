"""REST for the pack bench (WEB_API.md section "Pack bench"). All maths comes from ``rezonating_ml`` (D-017);
:mod:`.bench` holds the plumbing."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI
from rezonating_ml.baseline import train_baseline_model
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..link import codec
from ..recorder.config import LabConfig, check_data_root
from . import bench as B
from .device import DeviceManager

ADC_RAW = 0


class SourceBody(BaseModel):
    kind: Literal["recording", "sim", "live"]
    session: str | None = None
    root: str | None = None  # a sim-dataset folder (``rzlab sim-dataset --out``); default: the data root
    channel: int = Field(0, ge=0, le=3)


class RunBody(BaseModel):
    pack: str
    source: SourceBody
    trigger: dict[str, float] | None = None  # slider values (sta_ms, lta_ms, ratio, pre_ms, post_ms)
    k0: int | None = None
    k1: int | None = None
    columns: int = Field(1200, ge=10, le=8000)
    use_model: bool = True


class TrainBody(BaseModel):
    pack: str
    sources: list[SourceBody]
    trigger: dict[str, float] | None = None
    seed: int = 0


class TriggerBody(BaseModel):
    pack: str
    trigger: dict[str, float]


class CompareBody(BaseModel):
    pack: str = "footstep-id"
    channel: int = Field(0, ge=0, le=3)


class VectorBody(BaseModel):
    pack: str
    source: SourceBody
    trigger: dict[str, float] | None = None
    k0: int
    k1: int
    folder: str | None = None  # default: <data root>/bench-vectors
    filename: str = Field("sta_lta_clip.json", pattern=r"^[A-Za-z0-9_.-]+\.json$")


class CheckBody(BaseModel):
    path: str


class Bench:
    """The bench's state: the in-memory model, a cache of the last loaded recording and the live run."""

    def __init__(self, cfg: LabConfig, mgr: DeviceManager | None, packs_dir: Path | None = None) -> None:
        self.cfg = cfg
        self.mgr = mgr
        repo = cfg.repo_root
        self.packs_dir = packs_dir or (repo / "packs" if repo is not None else Path("packs"))
        self.model: Any = None
        self.model_info: dict[str, Any] | None = None
        self.live: B.LiveRun | None = None
        self._cache: tuple[tuple, B.SourceData] | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------------------------ helpers

    def data_root(self) -> Path:
        st = check_data_root(self.cfg, probe_write=False)
        if not st.ok or self.cfg.data_root is None:
            raise B.BenchError(st.error_code or "no_data_root", st.message or "No usable data root.", 409)
        return self.cfg.data_root

    def source_root(self, s: SourceBody) -> Path:
        return Path(s.root).expanduser().resolve() if s.root else self.data_root()

    def pack(self, pack_id: str, trigger: dict[str, float] | None) -> dict[str, Any]:
        return B.with_trigger(B.load_pack(self.packs_dir, pack_id), trigger)

    def load(self, s: SourceBody) -> B.SourceData:
        if s.kind == "live":
            raise B.BenchError("bad_source", "the live source is not a recording")
        if not s.session:
            raise B.BenchError("bad_source", "pick a session")
        root = self.source_root(s)
        key = (s.kind, str(root), s.session, s.channel)
        with self._lock:
            if self._cache is not None and self._cache[0] == key:
                return self._cache[1]
        src = B.load_recording(root, s.session, s.channel, kind=s.kind)
        with self._lock:
            self._cache = (key, src)
        return src

    def _model_for(self, pack_id: str, use: bool) -> Any:
        if use and self.model is not None and self.model_info and self.model_info.get("pack") == pack_id:
            return self.model
        return None

    def _ring(self) -> Any:
        if self.mgr is None or not self.mgr.connected:
            raise B.BenchError("not_connected", "Connect a node (or the simulator) for the live source.", 409)
        ring = self.mgr.rings.get(ADC_RAW)
        if ring is None:
            raise B.BenchError("no_stream", "the node has no adc_raw stream", 409)
        return ring

    def live_run(self, pack: dict[str, Any], channel: int, model: Any) -> B.LiveRun:
        key = (json.dumps(pack, sort_keys=True), channel, id(model))
        if self.live is None or self.live.key != key:
            self.live = B.LiveRun(pack, channel, model, key)
        self.live.poll(self._ring())
        return self.live

    # ------------------------------------------------------------------------------------- actions

    def run(self, body: RunBody) -> dict[str, Any]:
        pack = self.pack(body.pack, body.trigger)
        model = self._model_for(body.pack, body.use_model)
        if body.source.kind == "live":
            lr = self.live_run(pack, body.source.channel, model)
            if lr.out is None:
                return {"pack": body.pack, "empty": True, "message": "no adc_raw samples yet: start adc_raw"}
            return B.build_view(lr.pipe, lr.out, lr.source(), pack, body.k0, body.k1, body.columns, self.model_info)
        src = self.load(body.source)
        pipe, out = B.run_chunked(pack, src.x, src.valid, src.input_fs_hz, model)
        return B.build_view(pipe, out, src, pack, body.k0, body.k1, body.columns, self.model_info)

    def train(self, body: TrainBody) -> dict[str, Any]:
        pack = self.pack(body.pack, body.trigger)
        sources = [self.load(s) for s in body.sources]
        X, y, per = B.training_set(pack, sources)
        classes = sorted(set(y))
        if len(classes) < 2:
            raise B.BenchError("too_few_classes", f"the selected sessions give {len(y)} labelled windows of {classes}")
        self.model = train_baseline_model(X, y, seed=body.seed)
        self.model_info = {
            "pack": body.pack,
            "kind": "logreg (rezonating_ml.baseline.train_baseline_model)",
            "sessions": per,
            "n_windows": len(y),
            "classes": {c: y.count(c) for c in classes},
            "seed": body.seed,
            "note": "in memory only; scores on these sessions are in-sample, not a result (use baseline.evaluate)",
        }
        return self.model_info

    def forget_model(self) -> dict[str, Any]:
        self.model, self.model_info = None, None
        return {"ok": True}

    def preview(self, body: TriggerBody) -> dict[str, Any]:
        ch = B.trigger_change(B.pack_path(self.packs_dir, body.pack), body.trigger)
        ch.pop("_old_text")
        ch.pop("_new_text")
        return ch

    def save(self, body: TriggerBody) -> dict[str, Any]:
        repo = self.cfg.repo_root
        if repo is None:
            raise B.BenchError("no_repo", "no repository checkout: tools/validate.py is needed to save", 409)
        return B.save_trigger(
            B.pack_path(self.packs_dir, body.pack), body.trigger, lambda p: B.validate_pack_file(p, repo)
        )

    def compare(self, body: CompareBody) -> dict[str, Any]:
        """Node EVENT frames vs Python on the same ``adc_dec`` indices (the live ``adc_raw`` ring, pack as saved)."""
        pack = self.pack(body.pack, None)
        lr = self.live_run(pack, body.channel, None)
        ring = self._ring()
        if lr.out is None or lr.first is None:
            raise B.BenchError("no_data", "no adc_raw samples yet: start adc_raw", 409)
        k_off = lr.first // 2  # node adc_dec index = pipeline index + first / 2 (first is even)
        py_end = k_off + int(lr.out.decimated.size)
        hi = py_end - B.COMPARE_MARGIN
        py = [e.onset + k_off for e in lr.out.events or () if e.onset + k_off < hi]
        assert self.mgr is not None
        fw = [
            ev.sample
            for epoch, ev in list(self.mgr.node_events)
            if epoch == ring.epoch
            and ev.stream == codec.STREAM_ADC_DEC
            and ev.kind == codec.EVENT_TRIGGER
            and ev.pack == body.pack
            and k_off <= ev.sample < hi
        ]
        res = B.compare_events(fw, py)
        res.update(
            {
                "range": [k_off, max(k_off, hi)],
                "starts_at_acquisition_start": lr.first == 0,
                "note": "until real firmware exists, the simulator's EVENTs come from rezonating_ml too: this "
                "compares Python with Python (indices, chunking, loss), not two implementations",
            }
        )
        return res

    def make_vector(self, body: VectorBody) -> dict[str, Any]:
        pack = self.pack(body.pack, body.trigger)
        src = self.load(body.source)
        ref = self.cfg.repo_root / "ml" / "tests" / "vectors" / "sta_lta.json" if self.cfg.repo_root else None
        tol = json.loads(ref.read_text(encoding="utf-8"))["tolerance"]["rel"] if ref and ref.is_file() else None
        vec = B.make_vector(pack, src, body.k0, body.k1, tol)
        folder = Path(body.folder).expanduser() if body.folder else self.data_root() / "bench-vectors"
        if self.cfg.repo_root is not None and folder.resolve().is_relative_to(self.cfg.repo_root.resolve()):
            raise B.BenchError(
                "reserved",
                "vectors are never written inside the repository (packs/, schemas/ and ml/tests/vectors are managed "
                "elsewhere); pick a folder outside it",
            )
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / body.filename
        if path.exists():
            raise B.BenchError("exists", f"{path} already exists; choose another file name", 409)
        path.write_text(json.dumps(vec, indent=1) + "\n", encoding="utf-8", newline="\n")
        return {"path": str(path), "n": len(vec["input"]), "events": len(vec["expected"]["events"]),
                "masked": "masked" in vec, "warning": vec.get("warning")}  # fmt: skip

    def check_vector(self, body: CheckBody) -> dict[str, Any]:
        path = Path(body.path).expanduser()
        if not path.is_file():
            raise B.BenchError("not_found", f"no file {path}", 404)
        try:
            problems = B.check_vector(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, KeyError, TypeError) as exc:
            raise B.BenchError("bad_vector", f"not a test vector file: {exc}", 400) from exc
        return {"path": str(path), "ok": not problems, "problems": problems}


def register_bench_routes(app: FastAPI, cfg: LabConfig, mgr: DeviceManager | None) -> Bench:
    bench = Bench(cfg, mgr)
    app.state.bench = bench

    @app.exception_handler(B.BenchError)
    async def _bench_error(_req, exc: B.BenchError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.http)

    async def call(fn, *args):
        return await asyncio.to_thread(fn, *args)

    @app.get("/api/bench/packs")
    async def packs():
        return {"packs_dir": str(bench.packs_dir), "packs": B.list_packs(bench.packs_dir)}

    @app.get("/api/bench/sessions")
    async def sessions(root: str | None = None):
        r = Path(root).expanduser().resolve() if root else bench.data_root()
        return {"root": str(r), "sessions": await call(B.list_bench_sessions, r)}

    @app.post("/api/bench/run")
    async def run(body: RunBody):
        return await call(bench.run, body)

    @app.post("/api/bench/train")
    async def train(body: TrainBody):
        return await call(bench.train, body)

    @app.delete("/api/bench/model")
    async def forget():
        return bench.forget_model()

    @app.post("/api/bench/trigger/preview")
    async def preview(body: TriggerBody):
        return await call(bench.preview, body)

    @app.post("/api/bench/trigger/save")
    async def save(body: TriggerBody):
        return await call(bench.save, body)

    @app.post("/api/bench/compare")
    async def compare(body: CompareBody):
        return await call(bench.compare, body)

    @app.post("/api/bench/vector/create")
    async def vector_create(body: VectorBody):
        return await call(bench.make_vector, body)

    @app.post("/api/bench/vector/check")
    async def vector_check(body: CheckBody):
        return await call(bench.check_vector, body)

    return bench
