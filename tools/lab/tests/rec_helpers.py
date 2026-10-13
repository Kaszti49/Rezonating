"""Shared setup for the recorder tests: a LabConfig in tmp_path, the form, and a running app against a simulator."""

from __future__ import annotations

import copy
import dataclasses
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from rezonating_lab.recorder.config import LabConfig, find_repo_root
from rezonating_lab.server.app import create_app
from rezonating_lab.server.device import DeviceManager
from rezonating_lab.sim.node import SimConfig
from rezonating_lab.sim.server import SimThread

PORT = 8765
REPO = find_repo_root()
assert REPO is not None

FORM = {
    "site": "Home A",
    "room": "Kitchen",
    "floor": "laminate",
    "surface": "laminate on concrete slab",
    "persons": ["P1", "P2"],
    "marker": False,
    "sensors": [
        {"stream": "adc_raw", "ch": 0, "position_m": [0, 0]},
        {"stream": "adc_raw", "ch": 1, "position_m": [2, 0]},
        {"stream": "accel", "position_m": [1, 0]},
    ],
}


def form(**over) -> dict:
    f = copy.deepcopy(FORM)
    f.update(over)
    return f


def make_cfg(tmp_path: Path, **over) -> LabConfig:
    root = tmp_path / "dataroot"
    root.mkdir(parents=True, exist_ok=True)
    kw = {
        "data_root": root,
        "data_root_source": "env",
        "staging_dir": tmp_path / "staging",
        "sidecar_dir": tmp_path / "repo-data",
        "copy_sim_sidecars": True,
        "repo_root": REPO,
        "schema_path": REPO / "schemas" / "sidecar.schema.json",
        "marker_bind": "127.0.0.1",
        "config_path": tmp_path / "config.toml",
    }
    kw.update(over)
    return LabConfig(**kw)


@contextmanager
def lab(tmp_path: Path, sim_cfg: SimConfig | None = None, **cfg_over):
    """``(client, sim, cfg)``: the app on a TestClient, connected to a fresh simulator."""
    cfg = make_cfg(tmp_path, **cfg_over)
    sim_cfg = sim_cfg or SimConfig(speed=10.0)
    if sim_cfg.max_backlog_bytes == SimConfig().max_backlog_bytes:
        # These tests run the simulator 10x faster than real time. On a busy PC a stall of a second would overflow the
        # simulated 256 kB transmit queue and show up as link loss that has nothing to do with the recorder.
        sim_cfg = dataclasses.replace(sim_cfg, max_backlog_bytes=16_000_000)
    with SimThread(sim_cfg) as sim:
        app = create_app(
            PORT, manager=DeviceManager(embedded_sim=False), static_dir=tmp_path / "nostatic", lab_config=cfg
        )
        with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as client:
            r = client.post("/api/connect", json={"kind": "tcp", "host": "127.0.0.1", "port": sim.port})
            assert r.status_code == 200, r.text
            yield client, sim, cfg


def wait_idle(client: TestClient, timeout_s: float = 30.0) -> dict:
    end = time.time() + timeout_s
    while time.time() < end:
        st = client.get("/api/record/state").json()
        if st["state"] == "idle":
            return st
        time.sleep(0.1)
    raise AssertionError("the recorder did not become idle")
