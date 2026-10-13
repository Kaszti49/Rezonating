"""``rzlab sim-dataset``: complete, labelled simulated sessions in the recorder's layout, without the link.

Each session is ``<out>/<session>/<session>.adc.wav|json`` and ``<session>.accel.wav|json`` (v1 sidecars written
through ``rezonating_ml.io`` and built by the recorder's own ``build_sidecar``), plus the ground truth next to the
folder in ``<out>/<session>.truth.jsonl`` (outside the session folder, so ``rzlab validate`` stays clean).

Every session walks the whole protocol with all its persons (order shuffled per session), on its own work day
(Monday or Tuesday) and floor, with its own LTC6903 clock error (the measured rate is the true simulated rate).
Every person walks with a small drift of their own in every session (``people.session_drift``), so a split by
session is harder than a split by window, as with real people.
Labels are one per protocol pass (``src: auto``, person, pace, shoes) plus the timed steps (silence). Notes carry
``rzlab: source=sim`` so the Datasets page and the manifest builder leave the sessions out of real data.

Vectorised: a 3-person walk-pass-v1 session (about 33 min of signal) takes a few seconds.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from rezonating_ml import io

from ..recorder.config import find_repo_root, is_inside
from ..recorder.naming import session_name, slugify
from ..recorder.protocol import Protocol
from ..recorder.sidecars import build_sidecar, file_stem, utc_string
from ..recorder.validate import validate_session_folder
from .people import (
    DEFAULT_DIFFICULTY,
    SENSOR_X_M,
    SiteEffect,
    build_schedule,
    make_profile,
    person_number,
    render_steps,
    session_drift,
)
from .scenarios import ACCEL_LSB_PER_G, ADC_FULL_SCALE, ADC_VREF_V, AccelSignal, ScenarioConfig

NODE_ID = "rzn-sim001"
FIRMWARE = "0.1.0-sim"
SITE = "sim"
ADC_GAIN = 8
ACCEL_RANGE_G = 2
NOMINAL_HZ = 2000
ADC_CLOCK_ERR_STD = 0.005  # LTC6903: 0.5 % typical ...
ADC_CLOCK_ERR_MAX = 0.011  # ... 1.1 % max at 25 degC
ACCEL_CLOCK_ERR_STD = 0.001
LEAD_S = 2.0  # recording starts this long before the protocol's first step
TAIL_S = 2.0
DEFAULT_START = date(2026, 11, 2)  # a Monday
_DRIFT_SALT = 0xD21F


@dataclass
class DatasetConfig:
    sessions: int
    persons: list[str]
    seed: int = 1
    days: int | None = None  # distinct work days; None = one per session
    floors: list[str] = field(default_factory=lambda: ["lab"])
    difficulty: float = DEFAULT_DIFFICULTY
    passes_scale: float = 1.0  # scales every passes step (tests use < 1); timed steps keep their length
    start: date = DEFAULT_START


@dataclass
class SessionResult:
    name: str
    folder: Path
    day: date
    floor: str
    persons: list[str]
    duration_s: float
    adc_rate_hz: float
    accel_rate_hz: float
    n_passes: int
    n_steps: int


def work_days(start: date, n: int) -> list[date]:
    """The first ``n`` Mondays and Tuesdays on or after ``start`` (the team's work days)."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() in (0, 1):
            out.append(d)
        d += timedelta(days=1)
    return out


def _adc_channels(floor: str) -> list[dict]:
    scale = ADC_VREF_V / (ADC_GAIN * ADC_FULL_SCALE)
    return [
        {
            "ch": ch,
            "port": ch + 1,
            "head": "geophone/sim",
            "serial": f"SIM-G{ch + 1}",
            "units": "V",
            "scale": scale,
            "gain": ADC_GAIN,
            "surface": floor,
            "position_m": [SENSOR_X_M[ch], 0.0],
        }
        for ch in range(2)
    ]


def _accel_channels(floor: str) -> list[dict]:
    return [
        {
            "ch": ch,
            "port": 3,
            "head": "accelerometer/sim",
            "serial": "SIM-A1",
            "units": "g",
            "scale": 1.0 / ACCEL_LSB_PER_G[ACCEL_RANGE_G],
            "surface": floor,
            "position_m": [1.0, 0.0],
        }
        for ch in range(3)
    ]


def _labels(marks: Sequence, rate_hz: float, fs_header: int, t_shift_s: float, n_frames: int) -> list[dict]:
    out = []
    for m in marks:
        i0 = min(n_frames, max(0, int(round((m.t0_s - t_shift_s) * rate_hz))))
        i1 = min(n_frames, max(i0, int(round((m.t1_s - t_shift_s) * rate_hz))))
        lab: dict = {"t0": i0 / fs_header, "t1": i1 / fs_header, "i0": i0, "i1": i1, "src": "auto", "label": m.label}
        if m.person is not None:
            lab.update(person=m.person, pace=m.pace, shoes=m.shoes)
        out.append(lab)
    return out


def generate_session(
    cfg: DatasetConfig, protocol: Protocol, index: int, day_index: int, day: date, nn: int, out: Path, schema: Path
) -> SessionResult:
    floor = cfg.floors[index % len(cfg.floors)]
    name = session_name(day, SITE, slugify(floor), nn)
    ss = np.random.SeedSequence([cfg.seed, 0x5E55, index])
    rng = np.random.default_rng(ss)
    order = list(cfg.persons)
    rng.shuffle(order)
    adc_err = float(np.clip(rng.normal(0.0, ADC_CLOCK_ERR_STD), -ADC_CLOCK_ERR_MAX, ADC_CLOCK_ERR_MAX))
    acc_err = float(rng.normal(0.0, ACCEL_CLOCK_ERR_STD))
    adc_rate = NOMINAL_HZ * (1.0 + adc_err)
    acc_rate = NOMINAL_HZ * (1.0 + acc_err)
    acc_offset_s = float(rng.uniform(0.0, 0.002))  # the accel stream's index 0 is this much later
    site = SiteEffect.make(floor, day_index, cfg.seed)
    centres = {p: make_profile(p, cfg.seed, cfg.difficulty) for p in cfg.persons}
    # per (person, session): its own generator, so the drift does not move any other draw of the session
    profiles = {
        p: session_drift(
            c, np.random.default_rng(np.random.SeedSequence([cfg.seed, _DRIFT_SALT, index, person_number(p)]))
        )
        for p, c in centres.items()
    }
    sched = build_schedule(
        protocol.expand(order),
        profiles,
        int(rng.integers(2**31)),
        start_s=LEAD_S,
        site=site,
        passes_scale=cfg.passes_scale,
    )
    duration_s = sched.end_s + TAIL_S
    scen = ScenarioConfig(seed=int(rng.integers(2**31)))

    # ADC (adc_raw): noise floor + offset + the walkers, in codes at the gain
    n_adc = int(math.ceil(duration_s * adc_rate))
    noise_rng = np.random.default_rng(ss.spawn(1)[0])
    volts = scen.adc_offset_v + scen.adc_noise_v * noise_rng.standard_normal((n_adc, 2))
    render_steps(volts, adc_rate, sched.steps)
    adc_codes = np.clip(np.rint(volts * ADC_GAIN / ADC_VREF_V * ADC_FULL_SCALE), -ADC_FULL_SCALE, ADC_FULL_SCALE - 1)
    adc_codes = adc_codes.astype(np.int32)
    del volts
    n_acc = int(math.ceil((duration_s - acc_offset_s) * acc_rate))
    acc_codes = AccelSignal(scen, 1).block(0, n_acc, acc_rate, ACCEL_RANGE_G)

    folder = out / name
    folder.mkdir(parents=True, exist_ok=False)
    t0_utc = datetime(day.year, day.month, day.day, 8, 30, tzinfo=timezone.utc).timestamp() + 600 * nn
    t_dev_us = 5_000_000 + int(rng.integers(0, 10**9))
    notes_base = {
        "rate_source": "fit",
        "floor": floor,
        "persons": ",".join(order),
        "ended": "protocol",
        "source": "sim",
        "sim_seed": str(cfg.seed),
        "sim_difficulty": f"{cfg.difficulty:g}",
        "sim_passes_scale": f"{cfg.passes_scale:g}",
    }
    for stream, codes, rate, shift_s, channels, clock in (
        ("adc_raw", adc_codes, adc_rate, 0.0, _adc_channels(floor), "ltc6903"),
        ("accel", acc_codes, acc_rate, acc_offset_s, _accel_channels(floor), "adxl355"),
    ):
        measured = round(rate, 4)
        fs_header = max(1, round(measured))
        stem = file_stem(stream, name)
        io.write_wav(folder / f"{stem}.wav", codes, fs_header)
        doc = build_sidecar(
            session=name,
            node=NODE_ID,
            firmware=FIRMWARE,
            start_utc=utc_string(t0_utc + shift_s),
            stream={"name": stream, "nominal_hz": NOMINAL_HZ, "clock": clock},
            link="usb",
            channels=channels,
            protocol=protocol.name,
            base=0,
            t_dev_us=t_dev_us + int(round(shift_s * 1e6)),
            rate_hz=rate,
            loss={"device": 0, "link": 0, "host": 0},
            notes=io.format_rzlab_notes({"frames": str(len(codes)), **notes_base}),
            labels=_labels(sched.marks, measured, fs_header, shift_s, len(codes)),
        )
        io.save_sidecar(folder / f"{stem}.json", doc, schema)

    with (out / f"{name}.truth.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        head = {
            "kind": "session",
            "session": name,
            "seed": cfg.seed,
            "difficulty": cfg.difficulty,
            "floor": floor,
            "day": day.isoformat(),
            "site_effect": site.__dict__,
            "adc_rate_hz": adc_rate,
            "accel_rate_hz": acc_rate,
            "accel_offset_s": acc_offset_s,
            "persons": order,
            "profiles": {p: profiles[p].as_dict() for p in order},  # as walked in this session (drift included)
            "centres": {p: centres[p].as_dict() for p in order},  # the person's centre for this seed
        }
        fh.write(json.dumps(head) + "\n")
        for st in sched.steps:
            i = int(round(st.t_s * adc_rate))
            ev = {"kind": "footstep", "step": st.n, "t_s": round(st.t_s, 6), "sample_adc_raw": i}
            ev.update(sample_adc_dec=i // 2, sample_accel=int(round((st.t_s - acc_offset_s) * acc_rate)))
            ev.update(st.truth_fields(), x_m=round(st.x_m, 3), amp_v=round(st.amp_v, 9), f1_hz=round(st.f1_hz, 3))
            fh.write(json.dumps(ev) + "\n")

    report = validate_session_folder(folder, schema)
    if not report.ok:
        raise RuntimeError(f"generated session {name} does not validate: " + "; ".join(report.problems))
    return SessionResult(
        name=name,
        folder=folder,
        day=day,
        floor=floor,
        persons=order,
        duration_s=duration_s,
        adc_rate_hz=adc_rate,
        accel_rate_hz=acc_rate,
        n_passes=len(sched.passes()),
        n_steps=len(sched.steps),
    )


def check_out_dir(
    out: Path,
    *,
    repo_root: Path | None,
    data_root: Path | None = None,
    sidecar_dir: Path | None = None,
    into_data_root: bool = False,
) -> None:
    """Refuse an output folder where simulated sessions could pass for real data (raises ``ValueError``): inside the
    repository (only ``*.wav`` is ignored there, so truth files and sidecars could be committed), inside the
    sidecar folder, or inside the configured data root unless ``into_data_root``. Paths are resolved first, so a
    relative path or a link into the repository is caught too."""
    out = out.expanduser().resolve()
    if repo_root is not None and is_inside(out, repo_root):
        raise ValueError(f"--out {out} is inside the repository {repo_root}: write simulated sessions elsewhere")
    if sidecar_dir is not None and is_inside(out, sidecar_dir):
        raise ValueError(f"--out {out} is inside the sidecar folder {sidecar_dir}: write simulated sessions elsewhere")
    if data_root is not None and not into_data_root and is_inside(out, data_root):
        raise ValueError(
            f"--out {out} is inside the data root {data_root}: choose another folder, or pass --into-data-root"
        )


def generate_dataset(cfg: DatasetConfig, protocol: Protocol, out: Path, schema: Path) -> list[SessionResult]:
    """Write ``cfg.sessions`` sessions into ``out`` (created if missing; existing session folders are refused).
    ``out`` inside the repository is refused (``ValueError``); the CLI also checks the data root and sidecar folder."""
    check_out_dir(out, repo_root=find_repo_root())
    if cfg.sessions < 1:
        raise ValueError("sessions must be at least 1")
    if not cfg.persons:
        raise ValueError("at least one person (P1, P2, ...)")
    if not cfg.floors:
        raise ValueError("at least one floor")
    n_days = cfg.days or cfg.sessions
    if n_days < 1:
        raise ValueError("days must be at least 1")
    days = work_days(cfg.start, n_days)
    out.mkdir(parents=True, exist_ok=True)
    used: dict[tuple[date, str], int] = {}
    results = []
    for i in range(cfg.sessions):
        d_idx = i * n_days // cfg.sessions
        floor = cfg.floors[i % len(cfg.floors)]
        key = (days[d_idx], slugify(floor))
        used[key] = used.get(key, 0) + 1
        results.append(generate_session(cfg, protocol, i, d_idx, days[d_idx], used[key], out, schema))
    return results
