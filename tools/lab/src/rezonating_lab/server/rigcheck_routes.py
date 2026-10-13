"""REST for the rig checks (WEB_API.md section 11). Progress goes out as the cached ``rigcheck`` WebSocket event."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .device import DeviceError
from .rigcheck import RigChecks


class RigRunBody(BaseModel):
    checks: list[str] | None = None  # None: all of them, in order (a new report)
    rate_s: float | None = Field(None, ge=1.0, le=600.0)  # rate check duration (device seconds); default 60


def register_rigcheck_routes(app: FastAPI, rig: RigChecks) -> None:
    @app.get("/api/rigcheck")
    async def rigcheck_view():
        return rig.view()

    @app.post("/api/rigcheck/run")
    async def rigcheck_run(body: RigRunBody):
        return await asyncio.to_thread(rig.run, body.checks, body.rate_s)

    @app.post("/api/rigcheck/confirm")
    async def rigcheck_confirm():
        return rig.confirm()

    @app.post("/api/rigcheck/cancel")
    async def rigcheck_cancel():
        return rig.cancel()

    @app.get("/api/rigcheck/report")
    async def rigcheck_report():
        if rig.session_started is None:
            raise DeviceError("no_results", "No rig check has run yet.", http=404)
        name = rig.report_filename()
        return Response(
            rig.report_markdown(),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )
