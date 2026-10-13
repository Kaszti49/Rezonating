"""Pack bench (Lab phase 5): run a pack stage by stage on live, recorded or simulated data.

D-017: the Lab holds no signal maths. Every number a stage shows comes from ``rezonating_ml`` (D-021):
:func:`rezonating_ml.pipeline.build_pipeline` (decimate, dsp, trigger, features, model), ``zero_fill_mask`` for a
recording's lost frames, ``baseline.train_baseline_model`` for the in-memory model. What lives here is plumbing:
loading sources, feeding the pipeline in chunks, matching event indices against ground truth or the node's EVENT
frames, rewriting the ``trigger`` block of a ``pack.json``, and the display envelopes of ``core.view``.

Index spaces: the pipeline reports pack-rate indices from the start of what it was fed. ``Pipeline.to_input_index``
maps them back to the input (``2k - 30`` when decimating); ``SourceData.first_index`` is the input index of the
first fed sample (0 for a recording, the ring's first index for the live source).

Scoring (:func:`score_events`): an event matches a ground-truth step when its onset, mapped to the input stream,
lies within ``MATCH_TOL_MS`` (50 ms; 50 samples at the 1 kHz pack rate, 100 at the 2 kHz input) of the step's
onset. Each truth step and each event is used at most once (nearest first). The onset error is event minus truth,
in ms of input samples at the nominal rate. The STA/LTA onset is where the ratio crosses the threshold, so it lags
the physical step start by a few ms; the error's mean shows that lag.
"""

from __future__ import annotations

import copy
import difflib
import importlib.util
import json
import math
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from rezonating_ml import io
from rezonating_ml.features import FEATURE_NAMES
from rezonating_ml.pipeline import (
    NOT_AVAILABLE,
    Pipeline,
    PipelineOutput,
    build_pipeline,
    concat_outputs,
    run_pipeline,
    sidecar_lost_total,
    zero_fill_mask,
)
from rezonating_ml.trigger import Event

from ..core import view
from ..recorder.review import stream_paths

MATCH_TOL_MS = 50.0
TUNABLE = ("sta_ms", "lta_ms", "ratio", "pre_ms", "post_ms")
DEFAULT_CHUNK = 4096  # input samples per process() call for recordings (any size gives the same result)
VECTOR_PACK = "footstep-id"
FOOTSTEP_VECTORS_WARNING = (
    "changing footstep-id's trigger invalidates ml/tests/vectors: regenerate them "
    "(python -m rezonating_ml.vectors --write) and tell firmware"
)
COMPARE_MARGIN = 1000  # pack-rate samples at the live end left out of a compare (the node sends EVENTs in blocks)
MAX_LIST = 5000  # events / features / diffs returned to the UI at most (counts are always complete)


class BenchError(Exception):
    def __init__(self, code: str, message: str, http: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


# ----------------------------------------------------------------------------------------------- packs


def list_packs(packs_dir: Path) -> list[dict[str, Any]]:
    out = []
    for p in sorted(packs_dir.glob("*/pack.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            out.append({"id": p.parent.name, "error": str(exc)})
            continue
        out.append(
            {
                "id": doc.get("id", p.parent.name),
                "name": doc.get("name", ""),
                "sample_rate_hz": doc.get("requires", {}).get("sample_rate_hz"),
                "trigger": doc.get("trigger"),
                "features": doc.get("features"),
                "model": doc.get("model"),
                "tunable": (doc.get("trigger") or {}).get("type") == "sta_lta",
            }
        )
    return out


def pack_path(packs_dir: Path, pack_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", pack_id or ""):
        raise BenchError("bad_pack", f"{pack_id!r} is not a pack id")
    p = packs_dir / pack_id / "pack.json"
    if not p.is_file():
        raise BenchError("not_found", f"no pack {pack_id} in {packs_dir}", 404)
    return p


def load_pack(packs_dir: Path, pack_id: str) -> dict[str, Any]:
    return json.loads(pack_path(packs_dir, pack_id).read_text(encoding="utf-8"))


def _num(v: Any) -> int | float:
    f = float(v)
    if not math.isfinite(f):
        raise BenchError("bad_trigger", f"{v!r} is not a finite number")
    return int(f) if f.is_integer() else f


def with_trigger(pack: Mapping[str, Any], overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    """A copy of ``pack`` with the STA/LTA trigger values in ``overrides`` (only ``TUNABLE`` keys)."""
    doc = copy.deepcopy(dict(pack))
    if not overrides:
        return doc
    trig = doc.get("trigger") or {}
    if trig.get("type") != "sta_lta":
        raise BenchError("not_tunable", f"pack {doc.get('id')} has no sta_lta trigger to tune")
    bad = set(overrides) - set(TUNABLE)
    if bad:
        raise BenchError("bad_trigger", f"not tunable: {sorted(bad)}")
    doc["trigger"] = {**trig, **{k: _num(v) for k, v in overrides.items()}}
    return doc


# --------------------------------------------------------------------------------------------- sources


@dataclass
class SourceData:
    kind: str  # "recording" | "sim" | "live"
    name: str
    x: np.ndarray  # (n,) int32: one channel of adc_raw codes
    valid: np.ndarray | None  # (n,) bool, False = lost; None = all good
    input_fs_hz: float  # nominal rate (the pipeline's filters are designed for it, as on the node)
    first_index: int = 0  # input-stream index of x[0]
    labels: list[dict[str, Any]] = field(default_factory=list)  # sidecar labels (i0/i1 in input frames)
    truth: list[int] | None = None  # ground-truth step onsets (input indices), sim sessions only
    info: dict[str, Any] = field(default_factory=dict)


def session_dir(root: Path, name: str) -> Path:
    if not io.SESSION_RE.match(name or ""):
        raise BenchError("not_found", f"{name!r} is not a session name", 404)
    folder = root / name
    if not folder.is_dir() or folder.resolve().parent != root.resolve():
        raise BenchError("not_found", f"no session {name} in {root}", 404)
    return folder


def truth_path(root: Path, name: str) -> Path:
    return root / f"{name}.truth.jsonl"


def list_bench_sessions(root: Path) -> list[dict[str, Any]]:
    """Sessions with an ``adc_raw`` stream in ``root``, and whether a ground-truth file sits next to them."""
    out = []
    if not root.is_dir():
        return out
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and io.SESSION_RE.match(p.name)):
        wav, js = stream_paths(folder, "adc_raw")
        if wav.is_file() and js.is_file():
            out.append({"name": folder.name, "truth": truth_path(root, folder.name).is_file()})
    return out


def read_truth(path: Path) -> list[int]:
    """Footstep onsets (``sample_adc_raw``) from a ``rzlab sim-dataset`` truth file."""
    steps = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                if rec.get("kind") == "footstep":
                    steps.append(int(rec["sample_adc_raw"]))
    return sorted(steps)


def load_recording(root: Path, name: str, channel: int = 0, kind: str = "recording") -> SourceData:
    """One ``adc_raw`` channel of a session, read through ``rezonating_ml.io``, with the lost-frame mask from
    ``zero_fill_mask`` and the sidecar's loss total (README "Pack pipeline (D-021)")."""
    folder = session_dir(root, name)
    wav, js = stream_paths(folder, "adc_raw")
    frames, fs_header = io.read_wav(wav)
    sidecar = json.loads(js.read_text(encoding="utf-8"))
    if not 0 <= channel < frames.shape[1]:
        raise BenchError("bad_channel", f"{name} has {frames.shape[1]} channels; channel {channel} does not exist")
    lost = sidecar_lost_total(sidecar["loss"])
    m = zero_fill_mask(frames, expected_lost=lost)
    tp = truth_path(root, name)
    return SourceData(
        kind=kind,
        name=name,
        x=np.ascontiguousarray(frames[:, channel]),
        valid=m.valid,
        input_fs_hz=float(sidecar["sample_rate_nominal"]),
        labels=list(sidecar.get("labels") or []),
        truth=read_truth(tp) if tp.is_file() else None,
        info={
            "frames": int(frames.shape[0]),
            "channel": channel,
            "fs_header_hz": int(fs_header),
            "rate_measured_hz": sidecar.get("sample_rate_measured"),
            "loss_total": lost,
            "n_marked_lost": int((~m.valid).sum()),
            "mask_covers_all_lost": bool(m.covers_all_lost),
            "mask_surplus": int(m.n_surplus),
        },
    )


# ------------------------------------------------------------------------------------------- pipeline


def run_chunked(
    pack: Mapping[str, Any],
    x: np.ndarray,
    valid: np.ndarray | None,
    input_fs_hz: float,
    model: Any = None,
    chunk: int = DEFAULT_CHUNK,
) -> tuple[Pipeline, PipelineOutput]:
    """Feed ``x`` through ``build_pipeline`` in chunks, then ``finish()``; the joined output equals
    ``run_pipeline`` on the same samples (D-021)."""
    pipe = build_pipeline(pack, input_fs_hz=input_fs_hz, model=model)
    outs = []
    for a in range(0, max(len(x), 1), chunk):
        outs.append(pipe.process(x[a : a + chunk], None if valid is None else valid[a : a + chunk]))
    outs.append(pipe.finish())
    return pipe, concat_outputs(outs)


def _ev(e: Event, pipe: Pipeline, first_index: int) -> dict[str, Any]:
    d: dict[str, Any] = e.as_dict()
    d["input_index"] = int(pipe.to_input_index(e.onset)) + first_index
    return d


def events_input_index(events: Sequence[Event], pipe: Pipeline, first_index: int = 0) -> list[int]:
    return [int(pipe.to_input_index(e.onset)) + first_index for e in events]


# -------------------------------------------------------------------------------------------- scoring


def _tol_samples(tol_ms: float, fs_hz: float) -> int:
    return int(round(tol_ms * fs_hz / 1000.0))


def _match(a: Sequence[int], b: Sequence[int], tol: int) -> list[tuple[int, int]]:
    """Pairs ``(i, j)`` of ``a[i]`` and ``b[j]`` within ``tol``, closest pairs first, each item used once."""
    cand = []
    bs = np.asarray(b, dtype=np.int64)
    for i, v in enumerate(a):
        lo, hi = np.searchsorted(bs, v - tol, "left"), np.searchsorted(bs, v + tol, "right")
        cand += [(abs(int(bs[j]) - v), i, int(j)) for j in range(lo, hi)]
    cand.sort()
    used_a, used_b, pairs = set(), set(), []
    for _, i, j in cand:
        if i not in used_a and j not in used_b:
            used_a.add(i)
            used_b.add(j)
            pairs.append((i, j))
    return sorted(pairs)


def score_events(
    event_idx: Sequence[int], truth_idx: Sequence[int], fs_hz: float, tol_ms: float = MATCH_TOL_MS
) -> dict[str, Any]:
    """Precision, recall and onset error of detected events against ground-truth onsets (input indices)."""
    ev, tr = sorted(event_idx), sorted(truth_idx)
    pairs = _match(ev, tr, _tol_samples(tol_ms, fs_hz))
    err_ms = [(ev[i] - tr[j]) * 1000.0 / fs_hz for i, j in pairs]
    tp = len(pairs)

    def stat(f: Callable[[np.ndarray], float]) -> float | None:
        return round(float(f(np.asarray(err_ms))), 3) if err_ms else None

    return {
        "tolerance_ms": tol_ms,
        "n_truth": len(tr),
        "n_events": len(ev),
        "true_positives": tp,
        "false_positives": len(ev) - tp,
        "false_negatives": len(tr) - tp,
        "precision": round(tp / len(ev), 4) if ev else None,
        "recall": round(tp / len(tr), 4) if tr else None,
        "onset_error_ms": {
            "mean": stat(np.mean),
            "median": stat(np.median),
            "abs_p95": stat(lambda a: np.percentile(np.abs(a), 95)),
            "min": stat(np.min),
            "max": stat(np.max),
        },
    }


def compare_events(fw: Sequence[int], py: Sequence[int], tol: int = 50) -> dict[str, Any]:
    """Node EVENT samples vs Python onsets on the same index space. Exact index equality is a match; for the rest,
    the nearest partner within ``tol`` samples is shown with its index difference (``py - fw``)."""
    fw_s, py_s = sorted(set(fw)), sorted(set(py))
    same = sorted(set(fw_s) & set(py_s))
    missing = [v for v in fw_s if v not in set(same)]  # the node has it, Python does not
    extra = [v for v in py_s if v not in set(same)]  # Python has it, the node does not
    diffs = [{"fw": missing[i], "py": extra[j], "diff": extra[j] - missing[i]} for i, j in _match(missing, extra, tol)]
    return {
        "n_fw": len(fw_s),
        "n_py": len(py_s),
        "matched": len(same),
        "missing": len(missing),
        "extra": len(extra),
        "missing_idx": missing[:MAX_LIST],
        "extra_idx": extra[:MAX_LIST],
        "diffs": diffs[:MAX_LIST],
    }


# --------------------------------------------------------------------------------------------- display


def _env(x: np.ndarray | None, valid: np.ndarray | None, k0: int, k1: int, columns: int) -> dict[str, Any] | None:
    """Display envelope (core.view, display only) of ``x[k0:k1]``."""
    if x is None:
        return None
    seg = x[k0:k1]
    v = None if valid is None else valid[k0:k1]
    if seg.size == 0:
        return {"k": [], "min": [], "max": []}
    e = view.envelope(seg.astype(np.float64), columns, v)

    def lst(a: np.ndarray) -> list[float | None]:
        return [None if not math.isfinite(float(t)) else round(float(t), 6) for t in a]

    return {"k": [int(k0 + t) for t in e.edges[:-1]], "min": lst(e.vmin[:, 0]), "max": lst(e.vmax[:, 0])}


def build_view(
    pipe: Pipeline,
    out: PipelineOutput,
    src: SourceData,
    pack: Mapping[str, Any],
    k0: int | None = None,
    k1: int | None = None,
    columns: int = 1200,
    model_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    n = int(out.filtered.size)
    k0 = 0 if k0 is None else max(0, min(int(k0), n))
    k1 = n if k1 is None else max(k0, min(int(k1), n))
    stages = {s.name: {"status": s.status, "detail": s.detail} for s in out.stages}
    trig = pack.get("trigger") or {}
    events = out.events or ()
    windows = out.windows or ()
    fwin = out.feature_windows or ()
    res: dict[str, Any] = {
        "pack": pack.get("id"),
        "trigger": trig,
        "source": {"kind": src.kind, "name": src.name, "first_index": src.first_index, **src.info},
        "fs_hz": pipe.fs_hz,
        "input_fs_hz": pipe.input_fs_hz,
        "n": n,
        "range": [k0, k1],
        "stage_order": [s.name for s in out.stages],
        "stages": stages,
        "decimated": _env(out.decimated, out.valid, k0, k1, columns),
        "filtered": _env(out.filtered, out.valid, k0, k1, columns),
        "ratio": _env(out.ratio, None, k0, k1, columns),
        "threshold": trig.get("ratio") if trig.get("type") == "sta_lta" else None,
        "n_invalid_out": int((~out.valid).sum()),
        "counts": {
            "events": len(events),
            "windows": len(windows),
            "windows_invalid": pipe.n_windows_invalid,
            "windows_cut": pipe.n_windows_cut,
            "windows_featured": pipe.n_windows_featured,
            "windows_skipped_invalid": pipe.n_windows_skipped_invalid,
        },
        "events": [_ev(e, pipe, src.first_index) for e in events][:MAX_LIST],
        "windows": [w.as_dict() for w in windows][:MAX_LIST],
        "feature_names": list(FEATURE_NAMES),
        "features": None,
        "model": None,
        "model_info": model_info,
        "score": None,
    }
    if out.features is not None:
        res["features"] = [
            {"onset": w.onset, "values": [float(v) for v in row]} for w, row in zip(fwin, out.features, strict=True)
        ][:MAX_LIST]
    if out.model is not None:
        res["model"] = {
            "classes": list(out.model.classes),
            "rows": [
                {"onset": w.onset, "label": lab, "proba": [round(float(p), 5) for p in pr]}
                for w, lab, pr in zip(fwin, out.model.labels, out.model.proba, strict=True)
            ][:MAX_LIST],
        }
    if src.truth is not None and stages.get("trigger", {}).get("status") != NOT_AVAILABLE:
        res["score"] = score_events(
            events_input_index(events, pipe, src.first_index), src.truth, pipe.input_fs_hz, MATCH_TOL_MS
        )
    return res


# ------------------------------------------------------------------------------------ baseline training


def window_labels(
    windows: Sequence[Event], pipe: Pipeline, labels: Sequence[Mapping[str, Any]], first_index: int = 0
) -> list[str | None]:
    """The ``person`` of the sidecar label (``[i0, i1)``, input frames) holding each window's onset, else None."""
    spans = [(int(lab["i0"]), int(lab["i1"]), str(lab["person"])) for lab in labels if lab.get("person")]
    out: list[str | None] = []
    for w in windows:
        i = int(pipe.to_input_index(w.onset)) + first_index
        out.append(next((p for a, b, p in spans if a <= i < b), None))
    return out


def training_set(pack: Mapping[str, Any], sources: Sequence[SourceData]) -> tuple[np.ndarray, list[str], dict]:
    xs, ys, per = [], [], {}
    for src in sources:
        pipe, out = run_chunked(pack, src.x, src.valid, src.input_fs_hz)
        if out.features is None:
            raise BenchError("no_features", f"pack {pack.get('id')} has no features stage to train on")
        labs = window_labels(out.feature_windows or (), pipe, src.labels, src.first_index)
        keep = [i for i, lab in enumerate(labs) if lab is not None]
        xs.append(out.features[keep])
        ys += [labs[i] for i in keep]  # type: ignore[misc]
        per[src.name] = len(keep)
    X = np.concatenate(xs) if xs else np.zeros((0, len(FEATURE_NAMES)), np.float32)
    return X, ys, per


# --------------------------------------------------------------------------------------- pack.json edit


def _find_value_span(text: str, key: str) -> tuple[int, int]:
    """``[start, end)`` of the object value of top-level ``key`` in a pack.json text (2-space indent)."""
    m = re.search(r'^  "' + re.escape(key) + r'"\s*:\s*', text, re.M)
    if m is None or text[m.end()] != "{":
        raise BenchError("no_trigger", f'no top-level "{key}" object in pack.json')
    depth, i, in_str = 0, m.end(), False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return m.end(), i + 1
        i += 1
    raise BenchError("bad_json", "unbalanced braces in pack.json")


def _format_obj(obj: Mapping[str, Any], one_line: bool) -> str:
    if one_line:
        return "{ " + ", ".join(f"{json.dumps(k)}: {json.dumps(v)}" for k, v in obj.items()) + " }"
    return json.dumps(obj, indent=2).replace("\n", "\n  ")


def replace_trigger_text(text: str, trigger: Mapping[str, Any]) -> str:
    """``text`` with only the top-level ``trigger`` object replaced (layout of everything else kept byte for byte,
    the block keeps its one-line or multi-line style and key order)."""
    a, b = _find_value_span(text, "trigger")
    new = text[:a] + _format_obj(trigger, "\n" not in text[a:b]) + text[b:]
    old_doc, new_doc = json.loads(text), json.loads(new)
    if list(new_doc) != list(old_doc) or {**old_doc, "trigger": new_doc["trigger"]} != new_doc:
        raise BenchError("edit_failed", "rewriting the trigger block changed something else; nothing was written")
    if new_doc["trigger"] != dict(trigger):
        raise BenchError("edit_failed", "the rewritten trigger block does not read back as the new values")
    return new


def _load_validate_module(repo_root: Path) -> Any:
    path = repo_root / "tools" / "validate.py"
    spec = importlib.util.spec_from_file_location("rz_tools_validate", path)
    if spec is None or spec.loader is None:
        raise BenchError("no_validate", f"cannot load {path}", 500)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def validate_pack_file(path: Path, repo_root: Path) -> list[str]:
    """The pack checks of ``tools/validate.py`` (its ``validator_for("pack-manifest")`` and the id rule) on one
    pack.json, wherever it lies (a temp copy in tests)."""
    mod = _load_validate_module(repo_root)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path.name}: invalid JSON: {exc}"]
    v = mod.validator_for("pack-manifest")
    errs = [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in v.iter_errors(doc)]
    if doc.get("id") != path.parent.name:
        errs.append(f"id '{doc.get('id')}' must match folder name '{path.parent.name}'")
    return errs


def trigger_change(path: Path, overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Preview: the new text, the unified diff and the warnings of saving ``overrides`` into ``path``."""
    text = path.read_text(encoding="utf-8")
    doc = json.loads(text)
    new_trigger = with_trigger(doc, overrides)["trigger"]
    new_text = replace_trigger_text(text, new_trigger)
    diff = "".join(
        difflib.unified_diff(
            text.splitlines(keepends=True), new_text.splitlines(keepends=True), f"a/{path.name}", f"b/{path.name}"
        )
    )
    warnings = [FOOTSTEP_VECTORS_WARNING] if doc.get("id") == VECTOR_PACK and new_text != text else []
    return {"pack": doc.get("id"), "trigger": new_trigger, "diff": diff, "changed": new_text != text,
            "warnings": warnings, "_new_text": new_text, "_old_text": text}  # fmt: skip


def save_trigger(path: Path, overrides: Mapping[str, Any], validate: Callable[[Path], list[str]]) -> dict[str, Any]:
    """Write only the trigger block, then validate; on any validation error the old file is put back."""
    ch = trigger_change(path, overrides)
    old, new = ch.pop("_old_text"), ch.pop("_new_text")
    if not ch["changed"]:
        return {**ch, "saved": False, "errors": []}
    try:  # rezonating_ml must accept the new trigger (e.g. sta_ms < lta_ms), not only the schema
        build_pipeline(json.loads(new))
    except ValueError as exc:
        return {**ch, "saved": False, "errors": [f"rezonating_ml refuses this trigger: {exc}"]}
    path.write_text(new, encoding="utf-8", newline="\n")
    try:
        errors = validate(path)
    except Exception as exc:  # noqa: BLE001 - a validator crash is a failed validation
        errors = [f"validation crashed: {exc!r}"]
    if errors:
        path.write_text(old, encoding="utf-8", newline="\n")
        raise BenchError("invalid_pack", "validation failed, pack.json was restored: " + "; ".join(errors), 422)
    return {**ch, "saved": True, "errors": []}


# --------------------------------------------------------------------------------------------- vectors


def _f32_list(a: np.ndarray) -> list[float]:
    return [float(v) for v in np.asarray(a, dtype=np.float32)]


def _trigger_only_pack(fs_hz: float, trigger: Mapping[str, Any]) -> dict[str, Any]:
    """A pack with no dsp and no features: run_pipeline on it is the STA/LTA stage alone at the pack rate."""
    return {"id": "bench-vector", "requires": {"sample_rate_hz": fs_hz}, "dsp": [], "trigger": dict(trigger)}


def make_vector(
    pack: Mapping[str, Any], src: SourceData, k0: int, k1: int, reference_tol_rel: float | None
) -> dict[str, Any]:
    """An ``sta_lta.json``-format vector (ml/tests/vectors) from pack-rate samples ``[k0, k1)`` of the source.

    ``input`` is the decimated + filtered clip (as in ``rezonating_ml.vectors``); ``expected`` is what the
    STA/LTA stage of ``rezonating_ml`` gives on it from a fresh state, with ``windows`` when the clip holds lost
    samples (then under ``masked``, as in the generated file).
    """
    trig = pack.get("trigger") or {}
    if trig.get("type") != "sta_lta":
        raise BenchError("not_tunable", f"pack {pack.get('id')} has no sta_lta trigger")
    pipe, out = run_chunked(pack, src.x, src.valid, src.input_fs_hz)
    k0, k1 = max(0, int(k0)), min(int(k1), out.filtered.size)
    if k1 - k0 < 2:
        raise BenchError("bad_clip", "the clip holds fewer than 2 pack-rate samples")
    x = out.filtered[k0:k1]
    ok = out.valid[k0:k1]
    fs = pipe.fs_hz
    tp = _trigger_only_pack(fs, trig)
    res = run_pipeline(tp, x, input_fs_hz=fs)
    ratio_thr = float(trig["ratio"])
    tol = reference_tol_rel if reference_tol_rel is not None else 1e-5

    def margin(r: np.ndarray) -> float:
        return float(np.min(np.abs(r.astype(np.float64) - ratio_thr) / max(ratio_thr, 1.0))) if r.size else 1.0

    vec: dict[str, Any] = {
        "name": "sta_lta",
        "decisions": ["D-021"],
        "description": (
            "Bench clip: STA/LTA on the decimated, filtered clip, from a fresh trigger state; same contract as "
            "ml/tests/vectors/sta_lta.json (rezonating_ml.vectors). Expected values are rezonating_ml's own output."
        ),
        "generator": "rzlab bench: create test vector from clip",
        "clip": {
            "source": src.kind,
            "name": src.name,
            "pack": pack.get("id"),
            "k0": k0,
            "k1": k1,
            "input_index0": int(pipe.to_input_index(k0)) + src.first_index,
        },  # fmt: skip
        "fs_hz": fs,
        "trigger": dict(trig),
        "samples": {
            "n_sta": int(round(trig["sta_ms"] * fs / 1000)),
            "n_lta": int(round(trig["lta_ms"] * fs / 1000)),
            "n_pre": int(round(trig["pre_ms"] * fs / 1000)),
            "n_post": int(round(trig["post_ms"] * fs / 1000)),
        },
        "tolerance": {
            "rel": tol,
            "note": "on ratio, relative to max(|ratio|, 1); taken from ml/tests/vectors/sta_lta.json when present. "
            "Events and windows must match exactly.",
        },
        "threshold_margin_rel": margin(res.ratio if res.ratio is not None else np.zeros(0)),
        "input": _f32_list(x),
        "expected": {
            "ratio": _f32_list(res.ratio if res.ratio is not None else np.zeros(0)),
            "events": [e.as_dict() for e in res.events or ()],
        },
    }
    if not ok.all():
        m = run_pipeline(tp, x, input_fs_hz=fs, valid=ok)
        vec["masked"] = {
            "valid": [bool(v) for v in ok],
            "threshold_margin_rel": margin(m.ratio[ok] if m.ratio is not None else np.zeros(0)),
            "expected": {
                "ratio": _f32_list(m.ratio if m.ratio is not None else np.zeros(0)),
                "events": [e.as_dict() for e in m.events or ()],
                "windows": [w.as_dict() for w in m.windows or ()],
            },
        }
    if vec["threshold_margin_rel"] < tol:
        vec["warning"] = "a ratio sample lies within the tolerance of the threshold: events may differ in firmware"
    return vec


def check_vector(vec: Mapping[str, Any]) -> list[str]:
    """Compare an sta_lta-format vector with the current rezonating_ml STA/LTA stage. ``[]`` = passes."""
    problems: list[str] = []
    fs, trig, tol = float(vec["fs_hz"]), vec["trigger"], float(vec["tolerance"]["rel"])
    tp = _trigger_only_pack(fs, trig)
    x = np.asarray(vec["input"], dtype=np.float32)
    cases = [("unmasked", x, None, vec["expected"])]
    if "masked" in vec:
        v = np.asarray(vec["masked"]["valid"], dtype=bool)
        cases.append(("masked", x[: v.size], v, vec["masked"]["expected"]))
    for name, xi, vi, exp in cases:
        out = run_pipeline(tp, xi, input_fs_hz=fs, valid=vi)
        got = out.ratio if out.ratio is not None else np.zeros(0, np.float32)
        want = np.asarray(exp["ratio"], dtype=np.float32)
        if got.shape != want.shape:
            problems.append(f"{name}: ratio has {got.size} samples, expected {want.size}")
        else:
            rel = np.abs(got.astype(np.float64) - want) / np.maximum(np.abs(want), 1.0)
            if rel.size and float(rel.max()) > tol:
                problems.append(f"{name}: ratio differs by {float(rel.max()):.3g} (relative) > {tol:.3g}")
        ev = [e.as_dict() for e in out.events or ()]
        if ev != list(exp["events"]):
            problems.append(f"{name}: events differ: got {ev[:5]}, expected {list(exp['events'])[:5]}")
        if "windows" in exp:
            wins = [w.as_dict() for w in out.windows or ()]
            if wins != list(exp["windows"]):
                problems.append(f"{name}: windows differ: got {wins[:5]}, expected {list(exp['windows'])[:5]}")
    return problems


# ------------------------------------------------------------------------------------------- live source


class LiveRun:
    """The live source: the connected node's ``adc_raw`` ring, fed to one pipeline chunk by chunk as it arrives.

    The pipeline starts at the ring's oldest held index, rounded up to an even index so its decimator keeps the
    same raw samples as the node's (odd raw indices). A new ring epoch (restarted indices), a ring overrun past
    the cursor, or another pack / trigger / channel starts it again.
    """

    def __init__(self, pack: Mapping[str, Any], channel: int, model: Any, key: tuple) -> None:
        self.pack = dict(pack)
        self.channel = channel
        self.key = key
        self.pipe = build_pipeline(self.pack, input_fs_hz=2000.0, model=model)
        self.epoch: int | None = None
        self.first: int | None = None  # input index of the first fed sample
        self.cursor = 0
        self.out: PipelineOutput | None = None
        self.lock = threading.Lock()

    def poll(self, ring: Any) -> None:
        with self.lock:
            oldest = ring.oldest()
            if oldest is None:
                return
            if self.epoch != ring.epoch or self.first is None or oldest > self.cursor:
                self.pipe.reset()
                self.epoch, self.out = ring.epoch, None
                self.first = self.cursor = oldest + (oldest % 2)
            head = ring.head
            if head <= self.cursor:
                return
            lo, data, valid = ring.read(self.cursor, head)
            if lo != self.cursor:  # overrun between oldest() and read(): start again next poll
                self.first = None
                return
            o = self.pipe.process(data[:, self.channel], valid)
            self.out = o if self.out is None else concat_outputs([self.out, o])
            self.cursor = head

    def source(self) -> SourceData:
        n = 0 if self.out is None else int(self.out.decimated.size)
        return SourceData(
            kind="live",
            name="adc_raw ring",
            x=np.zeros(0, np.int32),
            valid=None,
            input_fs_hz=self.pipe.input_fs_hz,
            first_index=self.first or 0,
            info={"channel": self.channel, "epoch": self.epoch, "cursor": self.cursor, "n_out": n},
        )
