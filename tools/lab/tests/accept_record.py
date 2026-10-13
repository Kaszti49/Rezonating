"""Phase 3 acceptance run (not a pytest test: it takes real time). Usage::

    python tools/lab/tests/accept_record.py --minutes 5 --out RESULT.json

Starts the simulator (speed 1), the Lab server on a real loopback port and records one session through the REST
path. Keyboard marks are POSTed to ``/api/record/mark``; phone marks go through the real marker listener over a
WebSocket with injected, asymmetric one-way latency (20-80 ms plus jitter). Ground truth comes from the simulator:
at the instant a "person" presses, the simulator's own device clock gives the true sample index of each stream
(``(now_dev_s - acq.t0_s) * acq.rate_hz``), independent of anything the lab estimates. After the stop it runs
``rzlab validate`` on the data root and ``tools/validate.py`` on a temporary copy of the repository layout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
import websockets
from rezonating_lab.recorder.config import LabConfig, find_repo_root
from rezonating_lab.recorder.validate import run_validate
from rezonating_lab.server.app import create_app
from rezonating_lab.server.device import DeviceManager
from rezonating_lab.sim.node import SimConfig
from rezonating_lab.sim.server import SimThread

FORM = {
    "site": "Accept Lab",
    "room": "Bench",
    "floor": "laminate",
    "surface": "laminate on concrete slab",
    "persons": ["P1"],
    "marker": True,
    "sensors": [
        {"stream": "adc_raw", "ch": 0, "position_m": [0, 0]},
        {"stream": "adc_raw", "ch": 1, "position_m": [2, 0]},
        {"stream": "accel", "position_m": [1, 0]},
    ],
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Truth:
    """True sample index of each stream at this instant, from the simulator's own clock."""

    def __init__(self, sim: SimThread) -> None:
        self.node = sim.node

    def now(self) -> dict[str, float]:
        n = self.node
        t = n.now_dev_s()
        return {
            "adc_raw": (t - n.adc.t0_s) * n.adc.rate_hz,
            "accel": (t - n.accel.t0_s) * n.accel.rate_hz,
        }

    def rates(self) -> dict[str, float]:
        return {"adc_raw": self.node.adc.rate_hz, "accel": self.node.accel.rate_hz}


class Phone:
    """A phone page: pings the marker for its round trip, with one-way latency injected on both directions."""

    def __init__(self, url: str, rng: random.Random) -> None:
        self.url = url.replace("http://", "ws://") + "/ws"
        self.rng = rng
        self.rtts: list[float] = []
        self.waiters: dict[int, asyncio.Future] = {}
        self.acks: asyncio.Queue = asyncio.Queue()
        self.ws = None
        self._id = 0

    def delay(self) -> float:
        base = self.rng.uniform(0.020, 0.080)  # asymmetric: up and down drawn independently
        return max(0.0, base + self.rng.gauss(0, 0.005))

    async def run(self) -> None:
        self.ws = await websockets.connect(self.url, max_size=4096)
        asyncio.create_task(self._reader())
        asyncio.create_task(self._pinger())

    async def _reader(self) -> None:
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                if m["op"] == "pong":
                    fut = self.waiters.pop(m["id"], None)
                    if fut:
                        fut.set_result(time.perf_counter())
                elif m["op"] == "ack":
                    await self.acks.put(m)
        except websockets.ConnectionClosed:
            pass  # the marker listener closes with the recording

    async def _pinger(self) -> None:
        while True:
            self._id += 1
            pid = self._id
            up, down = self.delay(), self.delay()
            t0 = time.perf_counter()
            await asyncio.sleep(up)
            fut = asyncio.get_running_loop().create_future()
            self.waiters[pid] = fut
            await self.ws.send(json.dumps({"op": "ping", "id": pid}))
            t_recv = await fut
            self.rtts.append(((t_recv - t0) + down) * 1000.0)
            self.rtts = self.rtts[-7:]
            await asyncio.sleep(1.0)

    async def tap(self, edge: str) -> dict:
        """The user taps now; the message reaches the server after the (injected) uplink delay."""
        await asyncio.sleep(self.delay())
        rtt = statistics.median(self.rtts)
        await self.ws.send(json.dumps({"op": "mark", "edge": edge, "rtt_ms": rtt}))
        return await asyncio.wait_for(self.acks.get(), 5)


async def drive(base: str, sim: SimThread, minutes: float, rng: random.Random) -> dict:
    truth = Truth(sim)
    key_truth: list[dict] = []
    phone_truth: list[dict] = []
    async with httpx.AsyncClient(base_url=base, timeout=30) as http:
        r = await http.post("/api/connect", json={"kind": "tcp", "host": "127.0.0.1", "port": sim.port})
        r.raise_for_status()
        r = await http.post("/api/record/start", json=FORM)
        assert r.status_code == 200, r.text
        info = (await http.get("/api/record/marker")).json()
        phone = Phone(info["url"], rng)
        await phone.run()
        while len(phone.rtts) < 3:
            await asyncio.sleep(0.2)
        t_start = time.perf_counter()
        end_at = t_start + minutes * 60.0 - 12.0
        cycle = 10.0
        n = 0
        await asyncio.sleep(5.0)
        while time.perf_counter() + cycle < end_at + 12.0 and time.perf_counter() < end_at:
            t_cycle = time.perf_counter()
            # keyboard mark: 2 s long
            key_truth.append(truth.now())
            r = await http.post("/api/record/mark", json={"edge": "start", "person": "P1"})
            assert r.status_code == 200, r.text
            await asyncio.sleep(2.0)
            key_truth.append(truth.now())
            r = await http.post("/api/record/mark", json={"edge": "end"})
            assert r.status_code == 200, r.text
            await asyncio.sleep(max(0.0, t_cycle + 5.0 - time.perf_counter()))
            # phone mark: 2 s long
            phone_truth.append(truth.now())
            ack = await phone.tap("start")
            assert ack["ok"], ack
            await asyncio.sleep(2.0)
            phone_truth.append(truth.now())
            ack = await phone.tap("end")
            assert ack["ok"], ack
            n += 1
            await asyncio.sleep(max(0.0, t_cycle + cycle - time.perf_counter()))
        remaining = t_start + minutes * 60.0 - time.perf_counter()
        if remaining > 0:
            await asyncio.sleep(remaining)
        t_stop = time.perf_counter()
        r = await http.post("/api/record/stop")
        result = r.json()
        return {
            "stop": result,
            "key_truth": key_truth,
            "phone_truth": phone_truth,
            "rates": truth.rates(),
            "cycles": n,
            "rtts_last": phone.rtts,
            "wall_record_s": t_stop - t_start,
        }


def errors_ms(sidecar: dict, truth: list[dict], rates: dict[str, float], src: str, stream: str) -> list[float]:
    labels = [x for x in sidecar["labels"] if x["src"] == src]
    base = sidecar["first_sample"]
    edges = []
    for lab in labels:
        edges += [base + lab["i0"], base + lab["i1"]]
    assert len(edges) == len(truth), (src, stream, len(edges), len(truth))
    return [(e - t[stream]) / rates[stream] * 1000.0 for e, t in zip(edges, truth, strict=True)]


def stats(v: list[float]) -> dict:
    a = [abs(x) for x in v]
    q = statistics.quantiles(a, n=20, method="inclusive") if len(a) >= 2 else a  # q[18] is the 95th percentile
    return {
        "n": len(a),
        "max_abs_ms": round(max(a), 2),
        "p50_abs_ms": round(statistics.median(a), 2),
        "p95_abs_ms": round(q[18] if len(a) >= 2 else a[0], 2),
        "mean_abs_ms": round(statistics.mean(a), 2),
        "mean_signed_ms": round(statistics.mean(v), 2),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--drift-ppm", type=float, default=60.0, help="simulated device clock drift against the host")
    ap.add_argument("--jitter-us", type=float, default=150.0, help="simulated noise on DATA and PONG timestamps")
    ap.add_argument("--keep", action="store_true", help="keep the temporary folder with the WAV files and sidecars")
    args = ap.parse_args(argv)
    repo = find_repo_root()
    assert repo is not None
    tmp = Path(tempfile.mkdtemp(prefix="rz-accept-"))
    try:
        return run(args, repo, tmp)
    finally:
        if args.keep:
            print("kept:", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)  # the recordings (WAV) of a throwaway run must not stay behind


def run(args: argparse.Namespace, repo: Path, tmp: Path) -> int:
    root, staging, sidecars = tmp / "dataroot", tmp / "staging", tmp / "repo-copy" / "data"
    root.mkdir()
    cfg = LabConfig(
        data_root=root,
        data_root_source="env",
        staging_dir=staging,
        sidecar_dir=sidecars,
        copy_sim_sidecars=True,
        repo_root=repo,
        schema_path=repo / "schemas" / "sidecar.schema.json",
        marker_bind="127.0.0.1",
    )
    port = free_port()
    t_wall = time.perf_counter()
    with SimThread(
        SimConfig(speed=1.0, seed=args.seed, clock_drift_ppm=args.drift_ppm, timestamp_jitter_us=args.jitter_us)
    ) as sim:
        app = create_app(port, manager=DeviceManager(embedded_sim=False), static_dir=tmp / "nostatic", lab_config=cfg)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        th = threading.Thread(target=server.run, daemon=True)
        th.start()
        while not server.started:
            time.sleep(0.05)
        try:
            out = asyncio.run(drive(f"http://127.0.0.1:{port}", sim, args.minutes, random.Random(args.seed)))
        finally:
            server.should_exit = True
            th.join(20)
    wall = time.perf_counter() - t_wall
    stop = out["stop"]
    print("stop ok:", stop.get("ok"), "problems:", stop.get("problems"))
    session = stop["session"]
    folder = root / session
    report: dict = {
        "session": session,
        "wall_total_s": round(wall, 1),
        "wall_record_s": round(out["wall_record_s"], 1),
        "data_root": str(root),
        "streams": {},
    }
    for s in stop["streams"]:
        report["streams"][s["stream"]] = {
            k: s[k] for k in ("frames", "duration_s", "sample_rate", "sample_rate_measured", "loss", "labels")
        }
    rates = out["rates"]
    label_err: dict = {}
    for stream, suffix in (("adc_raw", "adc"), ("accel", "accel")):
        sc = json.loads((folder / f"{session}.{suffix}.json").read_text(encoding="utf-8"))
        for src, key in (("key", "key_truth"), ("phone", "phone_truth")):
            e = errors_ms(sc, out[key], rates, src, stream)
            label_err[f"{src}/{stream}"] = stats(e)
            unc = [x["unc_ms"] for x in sc["labels"] if x["src"] == src]
            label_err[f"{src}/{stream}"]["unc_ms_mean"] = round(statistics.mean(unc), 1)
            ed = []
            for lab in [x for x in sc["labels"] if x["src"] == src]:
                ed += [lab["unc_ms"], lab["unc_ms"]]
            n_in = sum(abs(x) <= u for x, u in zip(e, ed, strict=True))
            label_err[f"{src}/{stream}"]["within_unc"] = n_in
            label_err[f"{src}/{stream}"]["within_unc_fraction"] = round(n_in / len(e), 3)
    report["label_error_ms"] = label_err
    report["sim"] = {"seed": args.seed, "clock_drift_ppm": args.drift_ppm, "timestamp_jitter_us": args.jitter_us}
    report.pop("data_root", None)  # a local path with the user name: not for a report that gets pasted around
    print("\n--- rzlab validate", root)
    rc_lab = run_validate(root, cfg.schema_path)
    print("exit code:", rc_lab)
    # tools/validate.py on a temporary copy of the repository layout (the real data/ is not touched)
    copy = tmp / "repo-copy"
    for name in ("schemas", "packs"):
        shutil.copytree(repo / name, copy / name)
    (copy / "tools").mkdir()
    shutil.copy(repo / "tools" / "validate.py", copy / "tools" / "validate.py")
    print("\n--- tools/validate.py on", copy)
    p = subprocess.run([sys.executable, str(copy / "tools" / "validate.py")], capture_output=True, text=True)
    print(p.stdout.strip(), p.stderr.strip())
    print("exit code:", p.returncode)
    report["rzlab_validate_exit"] = rc_lab
    report["tools_validate_exit"] = p.returncode
    report["sidecars_in_copy"] = sorted(str(x.relative_to(copy)) for x in (copy / "data").rglob("*") if x.is_file())
    print("\n" + json.dumps(report, indent=1))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    # unc_ms is an estimate aimed at 95 % coverage (WEB_API.md 9.5): the run fails below that, and on the hard limits
    covered = all(e["within_unc_fraction"] >= 0.95 for e in label_err.values())
    limits = all(e["max_abs_ms"] < (20.0 if k.startswith("key") else 150.0) for k, e in label_err.items())
    print(f"unc_ms covers >= 95 % of the edges: {covered}; key < 20 ms and phone < 150 ms: {limits}")
    ok = stop.get("ok") and rc_lab == 0 and p.returncode == 0 and covered and limits
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
