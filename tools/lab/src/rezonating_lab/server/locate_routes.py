"""REST for the Locate page (WEB_API.md section 15). Steps and state go out as WebSocket events."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from ..recorder.recording import RecordError
from .locate import Locator


class LocateSettingsBody(BaseModel):
    swap_sides: bool


def register_locate_routes(app: FastAPI, loc: Locator) -> None:
    @app.get("/api/locate")
    async def locate_view():
        return loc.view()

    @app.post("/api/locate/settings")
    async def locate_settings(body: LocateSettingsBody):
        return loc.set_swap(body.swap_sides)

    @app.post("/api/locate/baseline")
    async def locate_baseline():
        v = loc.save_baseline()
        if v is None:
            raise RecordError("no_signal", "No signal yet: connect the node first.", http=409)
        return v

    @app.post("/api/locate/clear")
    async def locate_clear():
        return loc.clear()
