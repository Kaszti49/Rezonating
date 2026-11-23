"""REST for the Locate page (WEB_API.md section 15). Steps and state go out as WebSocket events."""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .locate import Locator


class CalibrateBody(BaseModel):
    spot: Literal["left", "right"]
    steps: int = Field(5, ge=3, le=20)


class LocateSettingsBody(BaseModel):
    c_mps: float | None = Field(None, ge=10.0, le=2000.0)
    decay_n: float | None = Field(None, ge=0.3, le=2.0)
    spacing_m: float | None = Field(None, ge=0.02, le=5.0)


def register_locate_routes(app: FastAPI, loc: Locator) -> None:
    @app.get("/api/locate")
    async def locate_view():
        return loc.view()

    @app.post("/api/locate/calibrate")
    async def locate_calibrate(body: CalibrateBody):
        return loc.start_calibration(body.spot, body.steps)

    @app.post("/api/locate/calibrate/cancel")
    async def locate_calibrate_cancel():
        return loc.cancel_calibration()

    @app.post("/api/locate/calibrate/reset")
    async def locate_calibrate_reset():
        return loc.reset_calibration()

    @app.post("/api/locate/settings")
    async def locate_settings(body: LocateSettingsBody):
        return loc.set_values(body.c_mps, body.decay_n, body.spacing_m)

    @app.post("/api/locate/clear")
    async def locate_clear():
        return loc.clear()
