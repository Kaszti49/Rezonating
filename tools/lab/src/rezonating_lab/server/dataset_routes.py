"""REST endpoints of the Datasets page (``/api/datasets/...``). Contract: ``tools/lab/WEB_API.md`` section 13."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path as FsPath
from typing import Any, Literal

from fastapi import FastAPI, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from ..datasets import DatasetError, DatasetIndex, Filters, facets, totals
from ..recorder.config import LabConfig, check_data_root, default_index_db, is_inside
from ..recorder.recording import RecordError

SessionName = Path(max_length=80, pattern=r"^\d{4}-\d{2}-\d{2}_[a-z0-9-]+_[a-z0-9-]+_\d{2}$")
DATE = r"^\d{4}-\d{2}-\d{2}$"


class FilterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: str | None = Field(None, max_length=80)
    floor: str | None = Field(None, max_length=80)
    person: str | None = Field(None, pattern=r"^P\d+$")
    valid: bool | None = None
    wav: Literal["present", "missing"] | None = None
    simulated: bool | None = None
    date_from: str | None = Field(None, pattern=DATE)
    date_to: str | None = Field(None, pattern=DATE)


class ManifestBody(BaseModel):
    """Either ``sessions`` (names) or ``filters``; neither = every session. Simulated and invalid sessions are left
    out unless asked for."""

    model_config = ConfigDict(extra="forbid")

    sessions: list[str] | None = Field(None, max_length=10000)
    filters: FilterBody | None = None
    include_simulated: bool = False
    include_invalid: bool = False


def _sidecar_prefix(cfg: LabConfig) -> str:
    """How ``sidecar_dir`` is written in manifest paths: relative to the repository, else ``data``."""
    if cfg.sidecar_dir is not None and cfg.repo_root is not None and is_inside(cfg.sidecar_dir, cfg.repo_root):
        try:
            return cfg.sidecar_dir.resolve().relative_to(cfg.repo_root.resolve()).as_posix() or "data"
        except ValueError:
            pass
    return "data"


def register_dataset_routes(app: FastAPI, cfg: LabConfig) -> None:
    holder: dict[str, Any] = {}
    holder_lock = threading.Lock()  # requests run in worker threads: one DatasetIndex per key, never two

    def index() -> DatasetIndex:
        schema = cfg.schema_path
        if schema is None or not schema.is_file():
            raise DatasetError("no_schema", "schemas/sidecar.schema.json was not found.")
        if cfg.sidecar_dir is None:
            raise DatasetError("no_sidecar_dir", "No repository data folder is known (sidecar_dir, RZ_SIDECAR_DIR).")
        db = cfg.index_db or default_index_db({})
        key = (str(db), str(cfg.sidecar_dir), str(schema))
        with holder_lock:
            if holder.get("key") != key:
                holder["index"] = DatasetIndex(db, cfg.sidecar_dir, schema, _sidecar_prefix(cfg), cfg.repo_root)
                holder["key"] = key
            return holder["index"]

    def root_status() -> tuple[FsPath | None, dict]:
        st = check_data_root(cfg, probe_write=False)
        return (cfg.data_root if st.ok else None), st.to_dict()

    def need_root() -> FsPath:
        root, st = root_status()
        if root is None:
            err = st["error"] or {}
            raise DatasetError(err.get("code") or "no_data_root", err.get("message") or "No usable data root.")
        return root

    async def call(fn, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except DatasetError as exc:
            raise RecordError(exc.code, exc.message, http=exc.http) from exc

    def index_info(ix: DatasetIndex, st: dict) -> dict:
        return {"db": str(ix.db_path), "refresh": ix.last_refresh, "data_root": st, "manifest": _manifest_info(ix)}

    def _manifest_info(ix: DatasetIndex) -> dict:
        path = ix.sidecar_root / "manifest.json"
        return {"path": f"{ix.sidecar_prefix}/manifest.json", "exists": path.is_file()}

    @app.get("/api/datasets/sessions")
    async def sessions(
        protocol: str | None = Query(None, max_length=80),
        floor: str | None = Query(None, max_length=80),
        person: str | None = Query(None, pattern=r"^P\d+$"),
        valid: bool | None = None,
        wav: Literal["present", "missing"] | None = None,
        simulated: bool | None = None,
        date_from: str | None = Query(None, pattern=DATE),
        date_to: str | None = Query(None, pattern=DATE),
    ):
        f = Filters(protocol, floor, person, valid, wav, simulated, date_from, date_to)

        def run():
            ix = index()
            root, st = root_status()
            ix.refresh(root)
            rows = ix.rows(root)
            shown = [r for r in rows if f.match(r)]
            return {
                "index": index_info(ix, st),
                "facets": facets(rows),
                "all": len(rows),
                "totals": totals(shown),
                "sessions": shown,
            }

        return await call(run)

    @app.get("/api/datasets/sessions/{name}")
    async def session(name: str = SessionName):
        def run():
            ix = index()
            root, _st = root_status()
            ix.refresh(root)
            return ix.session(root, name)

        return await call(run)

    @app.post("/api/datasets/sessions/{name}/hash")
    async def hash_session(name: str = SessionName):
        def run():
            ix = index()
            root = need_root()
            ix.refresh(root)
            return {"session": name, "wavs": ix.hash_session(root, name)}

        return await call(run)

    @app.post("/api/datasets/rebuild")
    async def rebuild():
        def run():
            ix = index()
            root, st = root_status()
            return {"refresh": ix.refresh(root, force=True), "index": index_info(ix, st)}

        return await call(run)

    def _args(body: ManifestBody) -> tuple:
        filters = Filters.from_dict(body.filters.model_dump()) if body.filters else None
        return body.sessions, filters, body.include_simulated, body.include_invalid

    @app.post("/api/datasets/manifest/preview")
    async def manifest_preview(body: ManifestBody):
        def run():
            ix = index()
            root = need_root()
            ix.refresh(root)
            return ix.plan_manifest(root, *_args(body))

        return await call(run)

    @app.post("/api/datasets/manifest")
    async def manifest_build(body: ManifestBody):
        def run():
            ix = index()
            root = need_root()
            ix.refresh(root)
            return ix.build_manifest(root, *_args(body))

        return await call(run)
