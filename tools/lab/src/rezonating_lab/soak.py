"""``rzlab soak``: run the whole chain for a while and check that nothing is lost or leaks.

It starts ``rzlab sim --speed N`` and ``rzlab serve`` as separate processes (so CPU and memory belong to the
server alone), STARTs all streams, and consumes the WebSocket like the browser would: every binary frame is
parsed and its sample indices checked for continuity, and (unless ``--no-ui-load``) the view endpoints are polled
like a UI would. Every ``--sample-period`` seconds it records the server's CPU % (of one core) and RSS, and the
WebSocket frame and byte rates.

Exit code 0 only if there is no host gap on any stream, the server's memory does not grow, its CPU stays under the
limits (median 50 % and peak 100 % of one core), the WebSocket delivered about 20 frames per
second per stream, and nothing died.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HEADER = struct.Struct("<BBBBHHQI")
MIN_FRAME_RATE_HZ = 15.0  # nominal is 20 Hz per stream
MAX_RSS_GROWTH_MB = 10.0
MAX_RSS_GROWTH_FRACTION = 0.05
MAX_CPU_MEDIAN_PCT = 50.0  # server CPU, percent of one core: median over the run
MAX_CPU_PEAK_PCT = 100.0  # ... and no sample above one full core


@dataclass
class StreamTally:
    frames: int = 0
    bytes: int = 0
    samples: int = 0
    skipped: int = 0  # indices jumped over inside one epoch (client-side gap count)
    epochs: set = field(default_factory=set)
    next_index: int | None = None
    epoch: int | None = None


def free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method: str, url: str, body: dict | None = None, timeout: float = 15.0) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


def wait_for(fn, timeout_s: float, what: str) -> None:
    deadline = time.time() + timeout_s
    last: Exception | None = None
    while time.time() < deadline:
        try:
            if fn():
                return
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(0.2)
    raise RuntimeError(f"timeout waiting for {what}" + (f" ({last})" if last else ""))


def _median(xs: list[float]) -> float:
    return statistics.median(xs) if xs else float("nan")


def rss_growth(samples: list[dict], duration_s: float) -> dict:
    """RSS of the middle quarter (25-50 % of the run) against the last quarter. The first quarter is warm-up."""
    mid = [s["srv_rss_mb"] for s in samples if 0.25 * duration_s <= s["t"] < 0.5 * duration_s]
    last = [s["srv_rss_mb"] for s in samples if s["t"] >= 0.75 * duration_s]
    a, b = _median(mid), _median(last)
    growth = b - a
    limit = max(MAX_RSS_GROWTH_MB, MAX_RSS_GROWTH_FRACTION * a) if a == a else MAX_RSS_GROWTH_MB
    # slope over the whole post warm-up run, MB per minute
    post = [(s["t"], s["srv_rss_mb"]) for s in samples if s["t"] >= 0.25 * duration_s]
    slope = 0.0
    if len(post) >= 3:
        mean_t = statistics.fmean(t for t, _ in post)
        mean_r = statistics.fmean(r for _, r in post)
        den = sum((t - mean_t) ** 2 for t, _ in post)
        slope = sum((t - mean_t) * (r - mean_r) for t, r in post) / den * 60.0 if den > 0 else 0.0
    return {
        "mid_mb": a,
        "last_mb": b,
        "growth_mb": growth,
        "limit_mb": limit,
        "slope_mb_per_min": slope,
        "ok": growth <= limit,
    }


async def _consume(url: str, tallies: dict[int, StreamTally], counters: dict, stop: asyncio.Event) -> None:
    import websockets

    async with websockets.connect(url, max_size=None, open_timeout=10) as ws:
        counters["ws_connected"] = True
        while not stop.is_set():
            try:
                msg = await asyncio.wait_for(ws.recv(), 2.0)
            except asyncio.TimeoutError:
                counters["ws_stalls"] += 1
                continue
            if isinstance(msg, bytes):
                typ, sid, n_ch, dtype, epoch, _flags, first, n = HEADER.unpack_from(msg)
                t = tallies.setdefault(sid, StreamTally())
                t.frames += 1
                t.bytes += len(msg)
                t.samples += n
                t.epochs.add(epoch)
                if t.epoch == epoch and t.next_index is not None and first > t.next_index:
                    t.skipped += first - t.next_index
                t.epoch = epoch
                t.next_index = first + n
                if len(msg) != HEADER.size + 4 * n * n_ch:
                    counters["bad_frames"] += 1
            else:
                ev = json.loads(msg)
                counters["events"][ev["type"]] = counters["events"].get(ev["type"], 0) + 1
                if ev["type"] == "status":
                    counters["last_status"] = ev


async def _ui_load(base: str, stop: asyncio.Event, lat: list[float]) -> None:
    """Poll the view endpoints about the way the browser would."""
    paths = [
        "/api/view/envelope?stream=adc_raw&window_s=10&columns=1000",
        "/api/view/envelope?stream=accel&window_s=60&columns=1000",
        "/api/view/psd?stream=adc_raw&window_s=10",
        "/api/view/spectrogram?stream=adc_dec&window_s=10",
    ]
    i = 0
    while not stop.is_set():
        t0 = time.perf_counter()
        try:
            await asyncio.to_thread(http, "GET", base + paths[i % len(paths)])
            lat.append(time.perf_counter() - t0)
        except Exception:  # noqa: BLE001
            lat.append(float("inf"))
        i += 1
        try:
            await asyncio.wait_for(stop.wait(), 0.5)
        except asyncio.TimeoutError:
            pass


async def _sampler(
    srv_ps,
    sim_ps,
    tallies: dict[int, StreamTally],
    counters: dict,
    stop: asyncio.Event,
    period_s: float,
    samples: list[dict],
    t_start: float,
) -> None:
    srv_ps.cpu_percent(None)
    sim_ps.cpu_percent(None)
    last = (time.perf_counter(), {k: (v.frames, v.bytes) for k, v in tallies.items()})
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), period_s)
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            break  # the run ended: a partial period would only add a bogus sample
        now = time.perf_counter()
        dt = now - last[0]
        cur = {k: (v.frames, v.bytes) for k, v in tallies.items()}
        fps = {k: (cur[k][0] - last[1].get(k, (0, 0))[0]) / dt for k in cur}
        bps = sum(cur[k][1] - last[1].get(k, (0, 0))[1] for k in cur) / dt
        last = (now, cur)
        status = counters.get("last_status") or {}
        host_gaps = {s["name"]: (s.get("loss") or {}).get("host", 0) for s in status.get("streams", [])}
        samples.append(
            {
                "t": now - t_start,
                "srv_cpu": srv_ps.cpu_percent(None),
                "srv_rss_mb": srv_ps.memory_info().rss / 2**20,
                "sim_cpu": sim_ps.cpu_percent(None),
                "sim_rss_mb": sim_ps.memory_info().rss / 2**20,
                "ws_fps": fps,
                "ws_kBps": bps / 1000.0,
                "host_gaps": host_gaps,
            }
        )
        line = samples[-1]
        print(
            f"  t={line['t']:6.1f}s  server cpu {line['srv_cpu']:5.1f}%  rss {line['srv_rss_mb']:6.1f} MB  "
            f"sim cpu {line['sim_cpu']:5.1f}%  ws {sum(fps.values()):5.1f} frames/s {line['ws_kBps']:6.1f} kB/s  host gaps {host_gaps}",
            flush=True,
        )


async def _run(minutes: float, base: str, ws_url: str, srv_ps, sim_ps, period_s: float, ui_load: bool) -> dict:
    tallies: dict[int, StreamTally] = {}
    counters: dict[str, Any] = {
        "ws_connected": False,
        "ws_stalls": 0,
        "bad_frames": 0,
        "events": {},
        "last_status": None,
    }
    stop = asyncio.Event()
    samples: list[dict] = []
    lat: list[float] = []
    t_start = time.perf_counter()
    tasks = [
        asyncio.create_task(_consume(ws_url, tallies, counters, stop)),
        asyncio.create_task(_sampler(srv_ps, sim_ps, tallies, counters, stop, period_s, samples, t_start)),
    ]
    if ui_load:
        tasks.append(asyncio.create_task(_ui_load(base, stop, lat)))
    duration = minutes * 60.0
    try:
        deadline = t_start + duration
        while time.perf_counter() < deadline:
            await asyncio.sleep(0.5)
            for t in tasks:
                if t.done() and t.exception() is not None:
                    raise t.exception()
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.perf_counter() - t_start
    return {"tallies": tallies, "counters": counters, "samples": samples, "latency": lat, "elapsed": elapsed}


def run_soak(minutes: float, speed: float, sample_period_s: float, json_path: Path | None, ui_load: bool = True) -> int:
    try:
        import psutil
    except ImportError:
        print('rzlab soak needs psutil: pip install -e "tools/lab[dev]"', file=sys.stderr)
        return 2
    sim_port, srv_port = free_port(), free_port()
    base = f"http://127.0.0.1:{srv_port}"
    log_dir = Path(tempfile.mkdtemp(prefix="rzlab-soak-"))
    procs: list[subprocess.Popen] = []

    def spawn(name: str, args: list[str]) -> subprocess.Popen:
        log = open(log_dir / f"{name}.log", "w")  # noqa: SIM115 - lives as long as the process
        p = subprocess.Popen([sys.executable, "-m", "rezonating_lab.cli", *args], stdout=log, stderr=subprocess.STDOUT)
        procs.append(p)
        return p

    print(
        f"rzlab soak: {minutes:g} min, sim speed {speed:g}x, sim :{sim_port}, server :{srv_port}, logs in {log_dir}",
        flush=True,
    )
    try:
        sim = spawn("sim", ["sim", "--port", str(sim_port), "--speed", str(speed)])
        srv = spawn("serve", ["serve", "--port", str(srv_port), "--connect", f"tcp:127.0.0.1:{sim_port}"])

        def connected() -> bool:
            return http("GET", base + "/api/state", timeout=3).get("connection", {}).get("state") == "connected"

        wait_for(connected, 30, "the server to connect to the simulator")
        started = http("POST", base + "/api/acquisition", {"action": "start"})
        if "error" in started:
            raise RuntimeError(f"START failed: {started}")
        srv_ps, sim_ps = psutil.Process(srv.pid), psutil.Process(sim.pid)
        result = asyncio.run(
            _run(minutes, base, f"ws://127.0.0.1:{srv_port}/ws", srv_ps, sim_ps, sample_period_s, ui_load)
        )
        alive = {"sim": sim.poll() is None, "server": srv.poll() is None}
        stopped = http("POST", base + "/api/acquisition", {"action": "stop"}, timeout=20)
        final = http("GET", base + "/api/state")["status"]
    except Exception as exc:  # noqa: BLE001
        print(f"rzlab soak: FAILED to run: {exc}", file=sys.stderr)
        return 3
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()

    return _report(minutes, speed, result, alive, stopped, final, json_path)


def _stat(vals: list[float]) -> dict:
    if not vals:
        return {"start": None, "min": None, "max": None, "end": None}
    return {"start": vals[0], "min": min(vals), "max": max(vals), "end": vals[-1]}


def _report(
    minutes: float, speed: float, result: dict, alive: dict, stopped: dict, final: dict, json_path: Path | None
) -> int:
    samples, tallies, counters, elapsed = result["samples"], result["tallies"], result["counters"], result["elapsed"]
    problems: list[str] = []
    streams_report = {}
    for s in final["streams"]:
        loss = s.get("loss") or {}
        t = tallies.get(s["id"], StreamTally())
        fps = t.frames / elapsed
        streams_report[s["name"]] = {
            "device": loss.get("device"),
            "link": loss.get("link"),
            "host": loss.get("host"),
            "final": loss.get("final"),
            "received": loss.get("received"),
            "window": loss.get("window"),
            "ws_frames_per_s": fps,
            "ws_kB_per_s": t.bytes / elapsed / 1000.0,
            "ws_samples": t.samples,
            "ws_index_skips": t.skipped,
            "epochs_seen": sorted(t.epochs),
        }
        if loss.get("host") != 0:
            problems.append(f"{s['name']}: host gap {loss.get('host')}")
        if not loss.get("final"):
            problems.append(f"{s['name']}: the loss numbers are not final (STOP not confirmed)")
        if fps < MIN_FRAME_RATE_HZ:
            problems.append(f"{s['name']}: only {fps:.1f} WebSocket frames/s (expected about 20)")
        if len(t.epochs) != 1:
            problems.append(f"{s['name']}: sample epoch changed during the run: {sorted(t.epochs)}")
    worst_host = max((v["host"] or 0 for v in streams_report.values()), default=0)
    seen_gap = max((max(smp["host_gaps"].values(), default=0) for smp in samples), default=0)
    if seen_gap:
        problems.append(f"host gap showed up during the run (max {seen_gap}); the final number is {worst_host}")
    growth = rss_growth(samples, elapsed)
    if not growth["ok"]:
        problems.append(f"server RSS grew {growth['growth_mb']:.1f} MB (limit {growth['limit_mb']:.1f} MB)")
    srv_cpu_all = [s["srv_cpu"] for s in samples]
    cpu_median, cpu_peak = _median(srv_cpu_all), max(srv_cpu_all, default=float("nan"))
    if srv_cpu_all and cpu_median > MAX_CPU_MEDIAN_PCT:
        problems.append(f"server CPU median {cpu_median:.1f} % of one core (limit {MAX_CPU_MEDIAN_PCT:g} %)")
    if srv_cpu_all and cpu_peak > MAX_CPU_PEAK_PCT:
        problems.append(f"server CPU peak {cpu_peak:.1f} % of one core (limit {MAX_CPU_PEAK_PCT:g} %)")
    if not srv_cpu_all:
        problems.append("no CPU samples were taken (run longer than one sample period)")
    for name, ok in alive.items():
        if not ok:
            problems.append(f"the {name} process died during the run")
    if counters["bad_frames"]:
        problems.append(f"{counters['bad_frames']} malformed WebSocket frames")
    link = final.get("link", {})
    if link.get("bad_frames") or link.get("lost_frames"):
        problems.append(
            f"link counters not clean: bad_frames {link.get('bad_frames')}, lost_frames {link.get('lost_frames')}"
        )
    if "error" in stopped:
        problems.append(f"STOP failed: {stopped}")

    srv_cpu, srv_rss = [s["srv_cpu"] for s in samples], [s["srv_rss_mb"] for s in samples]
    sim_cpu, sim_rss = [s["sim_cpu"] for s in samples], [s["sim_rss_mb"] for s in samples]
    lat = [x for x in result["latency"] if x != float("inf")]
    report = {
        "minutes": elapsed / 60.0,
        "speed": speed,
        "streams": streams_report,
        "server_cpu_pct": _stat(srv_cpu),
        "server_rss_mb": _stat(srv_rss),
        "sim_cpu_pct": _stat(sim_cpu),
        "sim_rss_mb": _stat(sim_rss),
        "rss_growth": growth,
        "cpu_limits_pct": {"median": MAX_CPU_MEDIAN_PCT, "peak": MAX_CPU_PEAK_PCT},
        "server_cpu_median_pct": cpu_median,
        "ws_events": counters["events"],
        "ws_stalls": counters["ws_stalls"],
        "ui_requests": {
            "count": len(result["latency"]),
            "failed": len(result["latency"]) - len(lat),
            "mean_s": statistics.fmean(lat) if lat else None,
            "max_s": max(lat) if lat else None,
        },
        "link": link,
        "problems": problems,
        "pass": not problems,
    }
    print("\n=== soak report ===")
    print(f"duration {elapsed:.0f} s at sim speed {speed:g}x")
    for name, r in streams_report.items():
        print(
            f"  {name:<8} device {r['device']}  link {r['link']}  host {r['host']}  received {r['received']}  "
            f"ws {r['ws_frames_per_s']:.1f} frames/s {r['ws_kB_per_s']:.1f} kB/s  ws index skips {r['ws_index_skips']}"
        )
    for label, key in (
        ("server CPU % (one core)", "server_cpu_pct"),
        ("server RSS MB", "server_rss_mb"),
        ("sim CPU %", "sim_cpu_pct"),
        ("sim RSS MB", "sim_rss_mb"),
    ):
        v = report[key]
        print(f"  {label:<24} start {v['start']:.1f}  min {v['min']:.1f}  max {v['max']:.1f}  end {v['end']:.1f}")
    print(
        f"  server CPU median {cpu_median:.1f} %, peak {cpu_peak:.1f} % (limits {MAX_CPU_MEDIAN_PCT:g} / {MAX_CPU_PEAK_PCT:g})"
    )
    print(
        f"  RSS growth: {growth['growth_mb']:+.2f} MB (middle quarter {growth['mid_mb']:.1f} -> last quarter {growth['last_mb']:.1f}), "
        f"slope {growth['slope_mb_per_min']:+.2f} MB/min, limit {growth['limit_mb']:.1f} MB"
    )
    print(
        f"  link: {link.get('frames_ok')} frames ok, bad_frames {link.get('bad_frames')}, lost_frames {link.get('lost_frames')}, rtt {link.get('rtt_ms')} ms"
    )
    if report["ui_requests"]["count"]:
        u = report["ui_requests"]
        print(
            f"  UI-like requests: {u['count']} (failed {u['failed']}), mean {u['mean_s'] * 1000:.0f} ms, max {u['max_s'] * 1000:.0f} ms"
        )
    print("  ws events:", counters["events"])
    if problems:
        print("\nFAIL")
        for p in problems:
            print("  -", p)
    else:
        print("\nPASS: no host gap, memory flat, CPU within limits, WebSocket rate as expected")
    if json_path:
        json_path.write_text(json.dumps(report, indent=2, default=str))
        print(f"report written to {json_path}")
    return 0 if not problems else 1
