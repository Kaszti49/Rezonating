"""REST endpoints of the recorder (``/api/record/...``). Contract: ``tools/lab/WEB_API.md`` section 9."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import FastAPI, Path, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from ..recorder.config import ConfigError, LabConfig, check_data_root, save_data_root
from ..recorder.forms import LabelOverrides, LabelState, SessionForm, list_protocols
from ..recorder.protocol import ProtocolError, load_named
from ..recorder.recording import RecordError, Recorder
from .device import DeviceManager


class MarkBody(LabelOverrides):
    """A mark edge from the keyboard. The browser sends no time: the server stamps the arrival.

    It extends ``LabelOverrides`` so the label and pseudonym checks run during request validation: a refused name is
    a 422 that is not echoed, and never an unhandled error that a server log could print.
    """

    edge: Literal["start", "end", "toggle"] = "toggle"


class RunnerStartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: str | None = None  # omit = the session's protocol


class RunnerGotoBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int


class DataRootBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


def register_record_routes(app: FastAPI, mgr: DeviceManager, rec: Recorder, cfg: LabConfig) -> None:
    @app.get("/api/record/options")
    async def options():
        return await asyncio.to_thread(rec.options)

    @app.get("/api/record/state")
    async def state():
        return rec.status()

    @app.get("/api/record/data-root")
    async def data_root():
        return (await asyncio.to_thread(check_data_root, cfg)).to_dict()

    @app.put("/api/record/data-root")
    async def set_data_root(body: DataRootBody):
        if rec.active:
            raise RecordError("recording_active", "Stop the recording before changing the data root.")
        if cfg.data_root_source == "env":
            raise RecordError(
                "data_root_from_env",
                "The data root is set by the RZ_DATA_ROOT environment variable, which wins over the config file. "
                "Change or remove the variable and restart the server.",
            )
        try:
            await asyncio.to_thread(save_data_root, cfg, body.path)
        except ConfigError as exc:
            raise RecordError(exc.code, exc.message, http=409) from exc
        return (await asyncio.to_thread(check_data_root, cfg)).to_dict()

    @app.post("/api/record/start")
    async def start(form: SessionForm):
        await asyncio.to_thread(rec.start, form)
        return rec.status()

    @app.post("/api/record/stop")
    async def stop():
        return await asyncio.to_thread(rec.stop)

    @app.get("/api/record/current-label")
    async def get_label_state():
        return rec.label_state.model_dump()

    @app.put("/api/record/current-label")
    async def put_label_state(body: LabelState):
        return rec.set_label_state(body).model_dump()

    @app.post("/api/record/mark")
    async def mark(body: MarkBody):
        arrival_us = mgr.host_us()  # the server's own clock, taken first thing; the browser sends no time
        overrides = LabelOverrides(label=body.label, person=body.person, pace=body.pace, shoes=body.shoes)  # validated
        return rec.mark(body.edge, "key", arrival_us, None, overrides)

    @app.get("/api/record/labels")
    async def labels():
        return {"labels": rec.labels_list(), "marking": rec.labels.open_mark() is not None}

    @app.delete("/api/record/labels/{label_id}")
    async def delete_label(label_id: int):
        return rec.delete_label(label_id)

    @app.get("/api/record/marker")
    async def marker(
        host: str | None = Query(
            None, description="omit, or the bound address (`hosts[0]`); another one is refused with 400"
        ),
    ):
        info = rec.marker_info(host)
        if info is None:
            reason = rec.marker_error or "The marker runs while a recording runs, and only if the form asked for it."
            return {"active": False, "reason": reason}
        return {"active": True, **info}

    @app.get("/api/record/marker/qr.svg")
    async def marker_qr(host: str | None = Query(None)):
        info = rec.marker_info(host)
        if info is None:
            return JSONResponse(
                {"error": {"code": "no_marker", "message": "No phone marker is running."}}, status_code=404
            )
        return Response(info["qr_svg"], media_type="image/svg+xml", headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------------- protocols and the runner (WEB_API.md 10)

    @app.get("/api/record/protocols/{name}")
    async def protocol(name: str = Path(max_length=64)):
        if name not in list_protocols(cfg.repo_root):
            raise RecordError("not_found", f"No protocol {name!r}; see options.protocols.", http=404)
        try:
            proto = await asyncio.to_thread(load_named, cfg.repo_root, name)
        except ProtocolError as exc:
            raise RecordError(
                "bad_protocol",
                f"docs/protocols/{name}.yaml cannot be used: " + "; ".join(exc.problems),
                http=422,
                details=[{"loc": ["protocol"], "msg": p} for p in exc.problems],
            ) from exc
        return proto.to_dict()

    @app.get("/api/record/runner")
    async def runner_state():
        return rec.runner_view()

    @app.post("/api/record/runner/start")
    async def runner_start(body: RunnerStartBody | None = None):
        return await asyncio.to_thread(rec.runner_start, body.protocol if body else None)

    @app.post("/api/record/runner/stop")
    async def runner_stop():
        return rec.runner_stop()

    @app.post("/api/record/runner/next")
    async def runner_next():
        return rec.runner_move("next")

    @app.post("/api/record/runner/back")
    async def runner_back():
        return rec.runner_move("back")

    @app.post("/api/record/runner/skip")
    async def runner_skip():
        return rec.runner_move("skip")

    @app.post("/api/record/runner/goto")
    async def runner_goto(body: RunnerGotoBody):
        return rec.runner_move("goto", body.index)

    @app.post("/api/record/runner/cancel")
    async def runner_cancel():
        return rec.runner_cancel()
