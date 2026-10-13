"""REST endpoints of the Review page and the SD import (``/api/review/...``). Contract: ``tools/lab/WEB_API.md`` 12."""

from __future__ import annotations

import asyncio
from pathlib import Path as FsPath
from typing import Any, Literal

from fastapi import FastAPI, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from ..recorder.config import ConfigError, LabConfig, check_data_root
from ..recorder.recording import RecordError
from ..recorder.review import (
    ReviewError,
    WavCache,
    apply_edit,
    check_allowed,
    envelope_view,
    list_sessions,
    normalise_labels,
    open_session,
    save_labels,
    session_folder,
    spectrogram_view,
    stream_data,
    stream_paths,
)
from ..recorder.sdimport import import_sd, summary

Stream = Literal["adc_raw", "accel"]
SessionName = Path(max_length=80)


class EditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream: Stream
    labels: list[dict[str, Any]] = Field(max_length=20000)
    op: dict[str, Any]


class CheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream: Stream
    labels: list[dict[str, Any]] = Field(max_length=20000)
    version: str | None = Field(default=None, max_length=64)  # accepted for symmetry with a save; not used


class SaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream: Stream
    labels: list[dict[str, Any]] = Field(max_length=20000)
    version: str = Field(min_length=1, max_length=64)
    peer_version: str | None = Field(default=None, max_length=64)  # required when the session has both streams


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)


def register_review_routes(app: FastAPI, cfg: LabConfig) -> None:
    cache = WavCache()

    def root() -> FsPath:
        st = check_data_root(cfg, probe_write=False)
        if not st.ok or cfg.data_root is None:
            raise RecordError(st.error_code or "no_data_root", st.message or "No usable data root.", http=409)
        return cfg.data_root

    async def call(fn, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except ReviewError as exc:
            raise RecordError(exc.code, exc.message, http=exc.http) from exc

    @app.get("/api/review/sessions")
    async def sessions():
        r = root()
        return {"root": str(r), "sessions": await call(list_sessions, r, cfg.sidecar_dir)}

    @app.get("/api/review/sessions/{name}")
    async def session(name: str = SessionName):
        return await call(open_session, root(), name, cfg.sidecar_dir, cfg.repo_root)

    @app.get("/api/review/sessions/{name}/envelope")
    async def envelope(
        name: str = SessionName,
        stream: Stream = "adc_raw",
        i0: int | None = Query(None, ge=0),
        i1: int | None = Query(None, ge=1),
        columns: int = Query(1200, ge=1, le=4000),
    ):
        def run():
            return envelope_view(stream_data(root(), name, stream, cache), i0, i1, columns)

        return await call(run)

    @app.get("/api/review/sessions/{name}/spectrogram")
    async def spectrogram(
        name: str = SessionName,
        stream: Stream = "adc_raw",
        ch: int = Query(0, ge=0, le=7),
        i0: int | None = Query(None, ge=0),
        i1: int | None = Query(None, ge=1),
        columns: int = Query(600, ge=1, le=2000),
        nfft: int = Query(256, ge=16, le=4096),
    ):
        def run():
            return spectrogram_view(stream_data(root(), name, stream, cache), ch, i0, i1, columns, nfft)

        return await call(run)

    @app.post("/api/review/sessions/{name}/edit")
    async def edit(body: EditBody, name: str = SessionName):
        def run():
            opened = open_session(root(), name, cfg.sidecar_dir, cfg.repo_root)
            s = opened["streams"].get(body.stream)
            if s is None or s["frames"] is None:
                raise ReviewError("no_stream", f"Session {name} has no {body.stream} recording.", 404)
            labels = apply_edit(
                body.labels,
                body.op,
                s["frames"],
                int(s["sample_rate"] or 0),
                opened["persons"],
                opened["labels_allowed"],
            )
            return {"labels": labels}

        return await call(run)

    @app.post("/api/review/sessions/{name}/check")
    async def check(body: CheckBody, name: str = SessionName):
        """Check a label list without saving (the page calls it before Save is offered)."""

        def run():
            opened = open_session(root(), name, cfg.sidecar_dir, cfg.repo_root)
            s = opened["streams"].get(body.stream)
            if s is None or s["frames"] is None:
                raise ReviewError("no_stream", f"Session {name} has no {body.stream} recording.", 404)
            labels = normalise_labels(body.labels, s["frames"], int(s["sample_rate"] or 0), opened["persons"])
            check_allowed(labels, opened["labels_allowed"])
            return {"labels": labels}

        return await call(run)

    @app.put("/api/review/sessions/{name}/labels")
    async def save(body: SaveBody, name: str = SessionName):
        def run():
            try:
                schema = cfg.require_schema()
            except ConfigError as exc:
                raise ReviewError(exc.code, exc.message, 409) from exc
            r = root()
            session_folder(r, name)
            stream_paths(r / name, body.stream)
            return save_labels(
                r,
                name,
                body.stream,
                body.labels,
                body.version,
                schema,
                cfg.repo_root,
                cfg.sidecar_dir,
                body.peer_version,
            )

        return await call(run)

    @app.post("/api/review/import-sd")
    async def import_from_sd(body: ImportBody):
        rec = getattr(app.state, "recorder", None)
        if rec is not None and rec.state != "idle":
            raise RecordError(
                "recording_active", "A recording is running; import from the SD card after it has stopped.", http=409
            )

        def run():
            try:
                schema = cfg.require_schema()
            except ConfigError as exc:
                raise ReviewError(exc.code, exc.message, 409) from exc
            src = FsPath(body.path.strip())
            if not src.is_absolute():
                raise ReviewError("invalid_request", "Give the full path of the SD card's folder.")
            try:
                results = import_sd(
                    src,
                    root(),
                    cfg.staging_dir,
                    schema,
                    cfg.sidecar_dir,
                    copy_sim=cfg.copy_sim_sidecars,
                    repo_root=cfg.repo_root,
                )
            except FileNotFoundError as exc:
                raise ReviewError("not_found", str(exc), 404) from exc
            except ValueError as exc:
                raise ReviewError("invalid_request", str(exc)) from exc
            return {"results": [x.to_dict() for x in results], "summary": summary(results)}

        return await call(run)
