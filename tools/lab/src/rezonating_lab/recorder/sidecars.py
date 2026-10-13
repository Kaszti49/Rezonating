"""Builds the v1 sidecar of one stream (D-019, D-020) from what the node and the form said and what was recorded.

Pure functions: no I/O, no clocks. The schema (``schemas/sidecar.schema.json``, Tier 1) has no place for the floor,
the session's people, the frame count or recorder bookkeeping, so those go into ``notes`` as ``rzlab: key=value; ...``
lines (see ``rezonating_ml.io.parse_rzlab_notes``). The schema is not changed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
from rezonating_ml.io import STREAM_FILE_SUFFIX, format_rzlab_notes

from ..core.accounting import LOSS_INCOMPLETE_NOTE
from ..core.timing import fit_stream_rate
from .forms import SessionForm

LINK_BY_KIND = {"serial": "usb", "sim": "usb", "tcp": "wifi"}
RECORDER_TAG = "rzlab"


class SensorProblem(Exception):
    """The form does not say where every recorded channel is. ``details`` are ``{loc, msg}`` for the UI."""

    def __init__(self, details: list[dict]) -> None:
        super().__init__("; ".join(d["msg"] for d in details))
        self.details = details


def file_stem(stream_name: str, session: str) -> str:
    """``<session>.adc`` for adc_raw, ``<session>.accel`` for accel."""
    return f"{session}.{STREAM_FILE_SUFFIX[stream_name]}"


def head_defaults(stream: dict, ch: int, heads: list[dict]) -> dict[str, Any]:
    """Port, head name, serial and mount that the node's head descriptors suggest for one channel."""
    descriptors = {h["port"]: h["descriptor"] for h in heads if isinstance(h.get("descriptor"), dict)}
    desc: dict | None = None
    port: int | None = None
    if stream["name"] == "adc_raw":
        port = ch + 1  # ADC input n sits on head port n + 1
        desc = descriptors.get(port)
    else:
        for p, d in descriptors.items():
            if d.get("type") == "accelerometer":
                desc, port = d, p
                break
    out: dict[str, Any] = {"head": "unknown", "serial": "unknown"}
    if port is not None and desc is not None:
        out["port"] = port
    if desc is not None:
        out["head"] = f"{desc.get('type', 'unknown')}/{desc.get('model', 'unknown')}"
        out["serial"] = str(desc.get("serial", "unknown"))
        if desc.get("mount"):
            out["mount"] = desc["mount"]
    return out


def channel_entries(stream: dict, form: SessionForm, heads: list[dict]) -> list[dict[str, Any]]:
    """``channels[]`` of the sidecar: node (units, scale, gain) plus form (positions, overrides).

    Every channel needs a position (walk-pass-v1: sensor positions are measured and written down). A form entry
    without ``ch`` covers all channels of its stream that have no entry of their own."""
    name = stream["name"]
    listed = [s for s in form.sensors if s.stream == name]
    per_ch = {s.ch: s for s in listed if s.ch is not None}
    wildcard = next((s for s in listed if s.ch is None), None)
    out: list[dict[str, Any]] = []
    problems: list[dict] = []
    for ch in range(stream["n_ch"]):
        sensor = per_ch.get(ch, wildcard)
        if sensor is None:
            problems.append({"loc": ["sensors"], "msg": f"{name} channel {ch}: say where it is (position_m)"})
            continue
        node_ch = (
            stream["channels"][ch] if ch < len(stream["channels"]) else {"gain": 1, "scale": 1.0, "units": "counts"}
        )
        entry: dict[str, Any] = {"ch": ch}
        defaults = head_defaults(stream, ch, heads)
        entry["head"] = sensor.head or defaults["head"]
        entry["serial"] = sensor.serial or defaults["serial"]
        entry["units"] = node_ch["units"]
        entry["scale"] = node_ch["scale"]
        entry["gain"] = node_ch["gain"]
        port = sensor.port if sensor.port is not None else defaults.get("port")
        if port is not None:
            entry["port"] = port
        mount = sensor.mount or defaults.get("mount")
        if mount:
            entry["mount"] = mount
        if form.surface:
            entry["surface"] = form.surface
        entry["position_m"] = list(sensor.position_m)
        out.append(entry)
    if problems:
        raise SensorProblem(problems)
    return out


def measured_rate(
    first_samples: np.ndarray,
    t_dev_us: np.ndarray,
    status_rate_hz: float | None,
    nominal_hz: float,
    base: int,
) -> tuple[float, str, int]:
    """``(rate_hz, source, t_dev_us of index base)``. The fit of the DATA timestamps wins; then the node's own
    measurement; then the nominal rate."""
    fit = fit_stream_rate(first_samples, t_dev_us)
    if fit is not None:
        rate, t_first = fit
        source = "fit"
        anchor_idx = int(first_samples[0])
    else:
        rate = status_rate_hz if status_rate_hz else nominal_hz
        source = "status" if status_rate_hz else "nominal"
        t_first = float(t_dev_us[0]) if len(t_dev_us) else 0.0
        anchor_idx = int(first_samples[0]) if len(first_samples) else base
    t_base = t_first + (base - anchor_idx) * 1e6 / rate
    return float(rate), source, max(0, int(round(t_base)))


def utc_string(epoch_s: float) -> str:
    return (
        datetime.fromtimestamp(epoch_s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{int(epoch_s * 1000) % 1000:03d}Z"
    )


def notes_text(
    form: SessionForm,
    *,
    frames: int,
    rate_source: str,
    incomplete: bool,
    extra: dict[str, str],
) -> str:
    """The sidecar ``notes``: the loss marker, one ``rzlab:`` line of values, then the person's own text."""
    values: dict[str, str] = {"frames": str(frames), "rate_source": rate_source}
    if form.floor:
        values["floor"] = form.floor.strip()
    if form.persons:
        values["persons"] = ",".join(form.persons)
    values.update(extra)
    lines = []
    if incomplete:
        lines.append(LOSS_INCOMPLETE_NOTE)
    lines.append(format_rzlab_notes(values))
    if form.notes and form.notes.strip():
        lines.append(form.notes.strip())
    return "\n".join(lines)


def build_sidecar(
    *,
    session: str,
    node: str,
    firmware: str,
    start_utc: str,
    stream: dict,
    link: str,
    channels: list[dict[str, Any]],
    protocol: str,
    base: int,
    t_dev_us: int,
    rate_hz: float,
    loss: dict[str, int],
    notes: str,
    labels: list[dict[str, Any]],
) -> dict[str, Any]:
    measured = round(rate_hz, 4)
    doc: dict[str, Any] = {
        "schema": 1,
        "session": session,
        "node": node,
        "firmware": firmware,
        "start_utc": start_utc,
        "sample_rate": max(1, round(measured)),
        "sample_rate_nominal": int(stream["nominal_hz"]),
        "sample_rate_measured": measured,
        "stream": stream["name"],
        "clock": stream["clock"],
        "first_sample": int(base),
        "t_dev_us": int(t_dev_us),
        "loss": loss,
        "link": link,
        "kind": "continuous",
        "channels": channels,
        "protocol": protocol,
        "notes": notes,
        "labels": labels,
    }
    return doc
