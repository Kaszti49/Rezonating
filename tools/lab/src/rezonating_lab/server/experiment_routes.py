"""REST endpoints of the Experiments page (``/api/experiments/...``, Lab phase 7). Logic: :mod:`.experiments`.

One run at a time, in a worker thread: ``POST /api/experiments/run`` starts it and returns a job id,
``GET /api/experiments/jobs/{id}`` reports progress and, at the end, the saved run (or the refusal).

Folders (none in the repository except the gitignored runs folder):

- runs: ``RZ_RUNS_DIR``, else ``<repo>/tools/lab/runs`` (gitignored);
- feature cache: ``RZ_FEATURE_CACHE``, else ``features/`` next to the Datasets index (the user's cache folder);
  refused inside the repository;
- vault root (Draft EXP note): ``RZ_VAULT_ROOT``, else the repository root (repo root = vault root).
"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from pathlib import Path as FsPath
from typing import Any, Literal

from fastapi import FastAPI, Path
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from ..datasets import DatasetError, DatasetIndex
from ..recorder.config import LabConfig, check_data_root, default_index_db, is_inside
from ..recorder.recording import RecordError
from . import experiments as ex

RunId = Path(max_length=80, pattern=ex.RUN_ID_RE.pattern)


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pack: str = Field("footstep-id", pattern=r"^[a-z0-9-]+$", max_length=40)
    sessions: list[str] = Field(..., min_length=2, max_length=2000)
    split: Literal["session", "person"] = "session"
    target: Literal["person", "pace", "shoes"] = "person"
    model: Literal["logreg", "rf"] = "logreg"
    seed: int = Field(0, ge=0, le=2**31 - 1)
    test_groups: list[str] | None = Field(None, max_length=2000)
    fraction: float | None = Field(None, gt=0, lt=1)


class DraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=80)


def register_experiment_routes(
    app: FastAPI,
    cfg: LabConfig,
    runs_root: FsPath | None = None,
    cache_dir: FsPath | None = None,
    vault_root: FsPath | None = None,
) -> None:
    env = os.environ
    repo = cfg.repo_root
    runs = runs_root or (
        FsPath(env["RZ_RUNS_DIR"]) if env.get("RZ_RUNS_DIR") else (repo / "tools" / "lab" / "runs" if repo else None)
    )
    cache = cache_dir or (
        FsPath(env["RZ_FEATURE_CACHE"])
        if env.get("RZ_FEATURE_CACHE")
        else (cfg.index_db or default_index_db(env)).parent / "features"
    )
    vault = vault_root or (FsPath(env["RZ_VAULT_ROOT"]) if env.get("RZ_VAULT_ROOT") else repo)
    jobs: dict[str, dict[str, Any]] = {}
    lock = threading.Lock()
    holder: dict[str, Any] = {}

    def fail(code: str, message: str, http: int = 409) -> RecordError:
        return RecordError(code, message, http=http)

    def need_runs() -> FsPath:
        if runs is None:
            raise ex.ExperimentError("no_runs_dir", "No runs folder: set RZ_RUNS_DIR or run from the repository.")
        return runs

    def packs_dir() -> FsPath:
        if repo is None:
            raise ex.ExperimentError("no_repo", "The repository (packs/) was not found.")
        return repo / "packs"

    def index() -> DatasetIndex:
        if cfg.schema_path is None or cfg.sidecar_dir is None:
            raise ex.ExperimentError("no_index", "The dataset index needs the sidecar schema and the data folder.")
        db = cfg.index_db or default_index_db({})
        with lock:
            if holder.get("db") != db:
                holder["ix"] = DatasetIndex(db, cfg.sidecar_dir, cfg.schema_path, "data", cfg.repo_root)
                holder["db"] = db
            return holder["ix"]

    def data_root() -> FsPath | None:
        return cfg.data_root if check_data_root(cfg, probe_write=False).ok else None

    async def call(fn, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except ex.ExperimentError as exc:
            raise fail(exc.code, exc.message, exc.http) from exc
        except DatasetError as exc:
            raise fail(exc.code, exc.message, exc.http) from exc

    @app.get("/api/experiments/options")
    async def options():
        def run():
            try:
                packs = ex.list_packs(packs_dir())
            except ex.ExperimentError:
                packs = []
            return {
                "packs": packs,
                "splits": list(ex.SPLITS),
                "targets": list(ex.TARGETS),
                "models": list(ex.MODELS),
                "runs_dir": str(runs) if runs else None,
                "vault_root_set": vault is not None,
                "busy": any(j["state"] == "running" for j in jobs.values()),
            }

        return await call(run)

    def work(job: dict[str, Any], body: RunBody) -> None:
        def progress(i: int, n: int, what: str) -> None:
            job.update(done=i, total=n, stage=what)

        try:
            if cache is not None and repo is not None and is_inside(cache, repo):
                raise ex.ExperimentError("cache_in_repo", f"The feature cache {cache} is inside the repository.")
            ecfg = ex.ExperimentConfig(**body.model_dump())
            ecfg.check()
            root = data_root()
            ix = index()
            ix.refresh(root)
            sources = ex.resolve_sessions(ix.rows(root), ecfg.sessions, root, cfg.sidecar_dir)
            pack, pack_hash = ex.load_pack(packs_dir(), ecfg.pack)
            results = ex.run_experiment(ecfg, sources, pack, pack_hash, cache, progress)
            run_id = ex.save_run(need_runs(), results)
            job.update(state="done", run_id=run_id, result=ex.load_run(need_runs(), run_id))
        except (ex.ExperimentError, DatasetError) as exc:
            job.update(state="error", error={"code": exc.code, "message": exc.message})
        except Exception as exc:  # noqa: BLE001 - reported to the page, never swallowed
            job.update(state="error", error={"code": "internal", "message": f"{type(exc).__name__}: {exc}"})

    @app.post("/api/experiments/run")
    async def start(body: RunBody):
        try:
            ex.ExperimentConfig(**body.model_dump()).check()
        except ex.ExperimentError as exc:
            raise fail(exc.code, exc.message, exc.http) from exc
        with lock:
            if any(j["state"] == "running" for j in jobs.values()):
                raise fail("busy", "An experiment is already running.")
            job_id = uuid.uuid4().hex[:12]
            job = {"id": job_id, "state": "running", "done": 0, "total": len(body.sessions), "stage": "starting"}
            jobs[job_id] = job
        threading.Thread(target=work, args=(job, body), daemon=True, name=f"exp-{job_id}").start()
        return {"job": job_id}

    @app.get("/api/experiments/jobs/{job_id}")
    async def job_status(job_id: str = Path(max_length=12, pattern=r"^[0-9a-f]{12}$")):
        job = jobs.get(job_id)
        if job is None:
            raise fail("not_found", "No such experiment job.", 404)
        return dict(job)

    @app.get("/api/experiments/runs")
    async def runs_list():
        return await call(lambda: {"runs": ex.list_runs(need_runs())})

    @app.get("/api/experiments/runs/{run_id}")
    async def run_detail(run_id: str = RunId):
        return await call(lambda: ex.load_run(need_runs(), run_id))

    @app.get("/api/experiments/runs/{run_id}/confusion.svg")
    async def run_svg(run_id: str = RunId):
        folder = await call(ex.run_folder, need_runs(), run_id)
        return Response((folder / "confusion.svg").read_text(encoding="utf-8"), media_type="image/svg+xml")

    @app.post("/api/experiments/runs/{run_id}/draft")
    async def draft(body: DraftBody, run_id: str = RunId):
        def run():
            if vault is None or repo is None:
                raise ex.ExperimentError("no_vault", "No vault root: set RZ_VAULT_ROOT or run from the repository.")
            folder = ex.run_folder(need_runs(), run_id)
            out = ex.draft_exp_note(ex.load_run(need_runs(), run_id), folder, vault, repo, body.title)
            if out["ok"]:
                ex.record_draft(folder, out)
            return out

        return await call(run)
