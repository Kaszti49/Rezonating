"""Synthetic sessions for the Review and SD-import tests, written with ``rezonating_ml.io`` (no recorder, no node)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
from rec_helpers import REPO
from rezonating_ml import io

SCHEMA = REPO / "schemas" / "sidecar.schema.json"
EXAMPLE = json.loads((REPO / "schemas" / "examples" / "sidecar.walk-pass-v1.json").read_text(encoding="utf-8"))
RATE = 2000
FRAMES = 8000  # 4 s
NAME = "2026-10-12_home-a_kitchen_01"


def base_labels(rate: int = RATE) -> list[dict]:
    def lab(i0: int, i1: int, **tags) -> dict:
        return {"t0": i0 / rate, "t1": i1 / rate, "i0": i0, "i1": i1, **tags}

    return [
        lab(0, 2000, src="key", unc_ms=14.2, label="silence"),
        lab(3000, 4000, src="key", unc_ms=13.0, label="walk", person="P1", pace="normal", shoes=True),
        lab(5000, 6000, src="phone", unc_ms=40.0, label="walk", person="P2", pace="slow", shoes=False),
    ]


def sidecar(name: str, stream: str = "adc_raw", frames: int = FRAMES, labels: list[dict] | None = None) -> dict:
    doc = copy.deepcopy(EXAMPLE)
    doc.update(
        session=name,
        stream=stream,
        clock="ltc6903" if stream == "adc_raw" else "adxl355",
        sample_rate=RATE,
        sample_rate_nominal=RATE,
        sample_rate_measured=float(RATE),
        notes=io.format_rzlab_notes({"frames": str(frames), "persons": "P1,P2", "floor": "laminate"}),
        labels=base_labels() if labels is None else labels,
    )
    if stream == "accel":
        doc["channels"] = [{"ch": c, "head": "accelerometer/adxl355", "serial": "x", "units": "g"} for c in range(3)]
    return doc


def write_session(parent: Path, name: str = NAME, accel: bool = False, frames: int = FRAMES, seed: int = 1) -> Path:
    """``<parent>/<name>/`` with an adc stream (2 channels: a 50 Hz sine and noise) and optionally an accel one."""
    folder = parent / name
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t = np.arange(frames) / RATE
    adc = np.stack([np.sin(2 * np.pi * 50 * t) * 1e6, rng.normal(0, 1e4, frames)], axis=1).astype(np.int32)
    io.write_wav(folder / f"{name}.adc.wav", adc, RATE)
    io.save_sidecar(folder / f"{name}.adc.json", sidecar(name, frames=frames), SCHEMA)
    if accel:
        acc = rng.integers(-1000, 1000, (frames, 3)).astype(np.int32)
        io.write_wav(folder / f"{name}.accel.wav", acc, RATE)
        io.save_sidecar(folder / f"{name}.accel.json", sidecar(name, "accel", frames=frames), SCHEMA)
    return folder
