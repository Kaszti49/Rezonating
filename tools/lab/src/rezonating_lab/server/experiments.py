"""Experiments page (Lab phase 7): build a labelled window dataset from sessions, evaluate it with a group split
next to a baseline, save the run, and draft an EXP note in ``50 Experiments/``.

Every number here comes from ``rezonating_ml``: :func:`rezonating_ml.pipeline.run_pipeline` (features per event
window), :func:`rezonating_ml.pipeline.zero_fill_mask` (the lost-frame mask from the WAV and the sidecar's ``loss``
total), :func:`rezonating_ml.baseline.split_by_group` and :func:`rezonating_ml.baseline.evaluate` (model and
majority-class baseline on the same split, with its flags). This module only selects, labels, checks and stores.

Label rule. A feature window takes the sidecar label whose ``[i0, i1)`` holds its **onset**, mapped back to the
input stream with :meth:`rezonating_ml.pipeline.Pipeline.to_input_index` (``2k - 30`` when the pipeline decimates).
Windows outside every label, in a ``silence`` label, or in a label without the target field are dropped and counted
by reason; nothing is dropped silently.

Refusals (:class:`ExperimentError`): an unknown, invalid or WAV-less session; a split by person for the target
``person`` (every test person would be unseen in training); any session on both sides of the split (for a split by
person this also catches a session shared by a train person and a test person); test labels never seen in
training (``evaluate``). A result never exists without its baseline (``EvalResult`` enforces it).

Caches and runs stay out of the repository: features per session and pack hash go to a cache folder (default next
to the Datasets index, in the user's cache folder), runs to ``tools/lab/runs/`` (gitignored) or ``RZ_RUNS_DIR``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import rezonating_ml
from rezonating_ml import baseline as rzb
from rezonating_ml import io as rzio
from rezonating_ml import pipeline as rzp
from rezonating_ml.features import FEATURE_NAMES

TARGETS = ("person", "pace", "shoes")
SPLITS = tuple(rzb.SPLITS)  # ("session", "person")
MODELS = tuple(rzb.MODELS)  # ("logreg", "rf")
SILENCE = "silence"
CACHE_VERSION = 1  # bump when what a cache file holds changes
SIMULATED_MARK = "SIMULATED DATA"
PSEUDONYM_RE = re.compile(r"^P\d+$")
RUN_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_[a-z0-9-]+_(session|person)(_\d+)?$")
EXP_ID_RE = re.compile(r"EXP-(\d{3})")
BAD_NAME_CHARS = re.compile(r'[/\\:*?"<>|\[\]#^\n\r\t]')
PERSON_SPLIT_FOR_PERSON = (
    "A split by person cannot evaluate person identification: every test person would be a label the model never "
    "saw in training. Split by session for target 'person', or choose target 'pace' or 'shoes' for a person split."
)
DROP_REASONS = ("outside_labels", "silence", "no_target")


class ExperimentError(Exception):
    """A request the runner refuses. ``code`` is the API error code, ``message`` is fit for a toast."""

    def __init__(self, code: str, message: str, http: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http = http


# ------------------------------------------------------------------------------------------------ config


@dataclass
class ExperimentConfig:
    pack: str
    sessions: list[str]
    split: str = "session"  # "session" | "person"
    target: str = "person"  # "person" | "pace" | "shoes"
    model: str = "logreg"  # "logreg" | "rf"
    seed: int = 0
    test_groups: list[str] | None = None  # explicit test sessions (split by session) or persons (split by person)
    fraction: float | None = None  # else this share of the groups; neither = 0.25

    def check(self) -> None:
        if self.target not in TARGETS:
            raise ExperimentError("bad_target", f"target must be one of {TARGETS}, got {self.target!r}", 422)
        if self.split not in SPLITS:
            raise ExperimentError("bad_split", f"split must be one of {SPLITS}, got {self.split!r}", 422)
        if self.model not in MODELS:
            raise ExperimentError("bad_model", f"model must be one of {MODELS}, got {self.model!r}", 422)
        if self.split == "person" and self.target == "person":
            raise ExperimentError("person_split_for_person", PERSON_SPLIT_FOR_PERSON, 422)
        if len(set(self.sessions)) != len(self.sessions) or len(self.sessions) < 2:
            raise ExperimentError("bad_sessions", "Choose at least two different sessions.", 422)
        if self.test_groups is not None and self.fraction is not None:
            raise ExperimentError("bad_test", "Give test groups or a fraction, not both.", 422)
        if self.test_groups is not None and not self.test_groups:
            raise ExperimentError("bad_test", "The list of test groups is empty.", 422)


@dataclass
class SessionSource:
    """One session's ``adc_raw`` recording, resolved from a Datasets index row."""

    session: str
    wav: Path
    sidecar: Path
    simulated: bool
    people: list[str]
    protocol: str | None
    floor: str | None


def resolve_sessions(
    rows: Sequence[Mapping[str, Any]], names: Sequence[str], data_root: Path | None, sidecar_root: Path | None
) -> list[SessionSource]:
    """The ``adc_raw`` WAV and sidecar of each named session (Datasets index rows). Refuses an unknown or invalid
    session and one without its WAV or ``adc_raw`` stream."""
    if data_root is None:
        raise ExperimentError("no_data_root", "No usable data root: the recordings (WAVs) live there.")
    by_name = {r["session"]: r for r in rows}
    out: list[SessionSource] = []
    for name in names:
        row = by_name.get(name)
        if row is None:
            raise ExperimentError("not_found", f"No session {name!r} in the dataset index.", 404)
        if not row["valid"]:
            raise ExperimentError(
                "invalid_session", f"Session {name} is not valid ({'; '.join(row['errors'][:2])}); fix it first."
            )
        adc = [e for e in row["streams"] if e["stream"] in ("adc_raw", None)]
        if not adc:
            raise ExperimentError("no_adc", f"Session {name} has no adc_raw recording.")
        e = adc[0]
        if not e["wav_present"]:
            raise ExperimentError("wav_missing", f"Session {name}: the WAV is missing on the data root.")
        sc_name = Path(e["sidecar"]).name
        if row["sidecar_source"] == "data_root" or sidecar_root is None:
            sidecar = data_root / name / sc_name
        else:
            sidecar = sidecar_root / name / sc_name
        out.append(
            SessionSource(
                session=name,
                wav=data_root / e["wav"],
                sidecar=sidecar,
                simulated=bool(row["simulated"]),
                people=list(row["people"]),
                protocol=row["protocol"],
                floor=row["floor"],
            )
        )
    return out


# ------------------------------------------------------------------------------------------------ packs


def load_pack(packs_dir: Path, pack_id: str) -> tuple[dict[str, Any], str]:
    """``(pack.json, sha256 of its bytes)`` for ``packs/<pack_id>/pack.json``."""
    if not re.fullmatch(r"[a-z0-9-]+", pack_id):
        raise ExperimentError("bad_pack", f"Not a pack id: {pack_id!r}", 422)
    path = packs_dir / pack_id / "pack.json"
    if not path.is_file():
        raise ExperimentError("no_pack", f"No pack {pack_id!r} in {packs_dir.name}/.", 404)
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def list_packs(packs_dir: Path) -> list[dict[str, Any]]:
    out = []
    for p in sorted(packs_dir.glob("*/pack.json")) if packs_dir.is_dir() else []:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({"id": doc.get("id", p.parent.name), "name": doc.get("name"), "features": doc.get("features")})
    return out


# ------------------------------------------------------------------------------------------------ features


@dataclass
class SessionFeatures:
    """Pipeline output of one session that the dataset needs (cached per session and pack hash)."""

    features: np.ndarray  # (k, N_FEATURES) float32, one row per feature window
    onset_in: np.ndarray  # (k,) int64, window onset in input-stream (sidecar) indices
    n_events: int
    n_windows_invalid: int  # windows skipped by the pipeline (lost samples inside)
    channel: int
    mask_covers_all_lost: bool
    mask_n_marked: int


def _head_channel(sidecar: Mapping[str, Any], pack: Mapping[str, Any]) -> int:
    """The first WAV channel whose head is of the pack's first required type (else channel 0)."""
    want = [h.get("type") for h in pack.get("requires", {}).get("heads", []) if isinstance(h, dict)]
    for i, ch in enumerate(sidecar.get("channels") or []):
        if isinstance(ch, dict) and want and str(ch.get("head", "")).split("/")[0] == want[0]:
            return i
    return 0


def _cache_key(src: SessionSource, pack_hash: str) -> str:
    h = hashlib.sha256()
    for part in (str(CACHE_VERSION), rezonating_ml.__version__, pack_hash, src.session):
        h.update(part.encode() + b"\0")
    for p in (src.wav, src.sidecar):
        st = p.stat()
        h.update(f"{st.st_mtime_ns}:{st.st_size}".encode() + b"\0")
    return h.hexdigest()[:24]


def session_features(
    src: SessionSource, pack: Mapping[str, Any], pack_hash: str, cache_dir: Path | None
) -> tuple[SessionFeatures, dict[str, Any], bool]:
    """``(features, sidecar, from_cache)`` for one session: the whole ``adc_raw`` WAV through ``run_pipeline`` with
    the ``zero_fill_mask`` valid mask (sidecar ``loss`` total; a mismatch refuses the session)."""
    sidecar = rzio.load_sidecar(src.sidecar)
    cache = cache_dir / f"{src.session}_{_cache_key(src, pack_hash)}.npz" if cache_dir is not None else None
    if cache is not None and cache.is_file():
        try:
            with np.load(cache) as z:
                meta = json.loads(str(z["meta"]))
                feats = SessionFeatures(features=z["features"], onset_in=z["onset_in"], **meta)
            return feats, sidecar, True
        except (OSError, ValueError, KeyError, TypeError):
            pass  # a damaged cache file is rebuilt
    codes, _fs = rzio.read_wav(src.wav)
    codes = codes if codes.ndim == 2 else codes[:, None]
    try:
        mask = rzp.zero_fill_mask(codes, expected_lost=rzp.sidecar_lost_total(sidecar["loss"]))
    except rzp.LostSampleMismatch as exc:
        raise ExperimentError("loss_mismatch", f"Session {src.session}: {exc}") from exc
    except (KeyError, TypeError) as exc:
        raise ExperimentError("no_loss", f"Session {src.session}: the sidecar has no loss counters.") from exc
    ch = _head_channel(sidecar, pack)
    scale = np.float32((sidecar.get("channels") or [{}])[ch].get("scale", 1.0))
    x = codes[:, ch].astype(np.float32) * scale  # volts, float32 as on the node
    fs_in = float(sidecar.get("sample_rate_nominal") or sidecar.get("sample_rate"))
    out = rzp.run_pipeline(pack, x, input_fs_hz=fs_in, valid=mask.valid)
    if out.features is None or out.feature_windows is None:
        st = {s.name: s.status for s in out.stages}
        raise ExperimentError("no_features", f"Pack {pack.get('id')!r}: no features from the pipeline ({st}).")
    onsets = np.asarray([w.onset for w in out.feature_windows], dtype=np.int64)
    pipe = rzp.build_pipeline(pack, input_fs_hz=fs_in)
    onset_in = np.asarray(pipe.to_input_index(onsets), dtype=np.int64).reshape(-1)
    feats = SessionFeatures(
        features=np.asarray(out.features, dtype=np.float32).reshape(-1, len(FEATURE_NAMES)),
        onset_in=onset_in,
        n_events=len(out.windows or ()),
        n_windows_invalid=sum(1 for w in out.windows or () if w.n_invalid),
        channel=ch,
        mask_covers_all_lost=bool(mask.covers_all_lost),
        mask_n_marked=int(mask.n_marked),
    )
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        meta = {k: v for k, v in asdict(feats).items() if k not in ("features", "onset_in")}
        tmp = cache.with_name(cache.name + ".tmp.npz")
        np.savez(tmp, features=feats.features, onset_in=feats.onset_in, meta=json.dumps(meta))
        os.replace(tmp, cache)
    return feats, sidecar, False


# ------------------------------------------------------------------------------------------------ labels


def target_value(label: Mapping[str, Any], target: str) -> str | None:
    """The class of a label for ``target`` (``None``: the label has no such field). Shoes: ``shoes``/``no_shoes``."""
    v = label.get(target)
    if v is None:
        return None
    if target == "shoes":
        return "shoes" if bool(v) else "no_shoes"
    if target == "person" and not PSEUDONYM_RE.match(str(v)):
        return None  # only pseudonyms ever leave this function
    return str(v)


def assign_labels(
    onset_in: np.ndarray, labels: Sequence[Mapping[str, Any]], target: str
) -> tuple[list[dict[str, Any] | None], Counter]:
    """For each window onset (input-stream index), the label holding it (``i0 <= onset < i1``), or ``None`` when it
    is dropped; and the drops counted by reason (``outside_labels``, ``silence``, ``no_target``). When labels
    overlap, a non-silence label wins over silence, then the earliest-starting one."""
    spans = sorted(
        (int(lab["i0"]), int(lab["i1"]), lab)
        for lab in labels
        if isinstance(lab, Mapping) and isinstance(lab.get("i0"), int) and isinstance(lab.get("i1"), int)
    )
    out: list[dict[str, Any] | None] = []
    dropped: Counter = Counter()
    for t in np.asarray(onset_in).tolist():
        hits = [lab for i0, i1, lab in spans if i0 <= t < i1]
        if not hits:
            dropped["outside_labels"] += 1
            out.append(None)
            continue
        lab = next((h for h in hits if h.get("label") != SILENCE), hits[0])
        if lab.get("label") == SILENCE:
            dropped["silence"] += 1
            out.append(None)
            continue
        value = target_value(lab, target)
        if value is None:
            dropped["no_target"] += 1
            out.append(None)
            continue
        person = lab.get("person")
        out.append(
            {
                "y": value,
                "person": str(person) if person is not None and PSEUDONYM_RE.match(str(person)) else "-",
                "pace": str(lab.get("pace")) if lab.get("pace") is not None else "-",
                "shoes": target_value(lab, "shoes") or "-",
            }
        )
    return out, dropped


@dataclass
class WindowSet:
    X: np.ndarray  # (n, N_FEATURES) float32
    y: np.ndarray  # (n,) str
    session: np.ndarray  # (n,) str
    person: np.ndarray  # (n,) str ("-" = unknown)
    pace: np.ndarray
    shoes: np.ndarray
    per_session: list[dict[str, Any]] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def build_windows(
    sources: Sequence[SessionSource],
    pack: Mapping[str, Any],
    pack_hash: str,
    target: str,
    cache_dir: Path | None,
    progress: Callable[[int, int, str], None] | None = None,
) -> WindowSet:
    """The labelled feature windows of every session (see the module docstring for the label rule)."""
    rows: list[np.ndarray] = []
    cols: dict[str, list[str]] = {"y": [], "session": [], "person": [], "pace": [], "shoes": []}
    per_session: list[dict[str, Any]] = []
    dropped: Counter = Counter()
    warnings: list[str] = []
    for i, src in enumerate(sources):
        if progress:
            progress(i, len(sources), src.session)
        feats, sidecar, cached = session_features(src, pack, pack_hash, cache_dir)
        assigned, drop = assign_labels(feats.onset_in, sidecar.get("labels") or [], target)
        keep = [j for j, a in enumerate(assigned) if a is not None]
        rows.append(feats.features[keep])
        for j in keep:
            a = assigned[j]
            assert a is not None
            cols["y"].append(a["y"])
            cols["session"].append(src.session)
            for k in ("person", "pace", "shoes"):
                cols[k].append(a[k])
        dropped.update(drop)
        if not feats.mask_covers_all_lost:
            warnings.append(f"{src.session}: the lost-frame mask is backed by the count only (not proven)")
        per_session.append(
            {
                "session": src.session,
                "simulated": src.simulated,
                "people": src.people,
                "protocol": src.protocol,
                "floor": src.floor,
                "channel": feats.channel,
                "events": feats.n_events,
                "windows_invalid": feats.n_windows_invalid,
                "windows": int(feats.features.shape[0]),
                "kept": len(keep),
                "dropped": {r: int(drop.get(r, 0)) for r in DROP_REASONS},
                "classes": dict(sorted(Counter(cols["y"][len(cols["y"]) - len(keep) :]).items())),
                "cached": cached,
            }
        )
    if progress:
        progress(len(sources), len(sources), "evaluating")
    X = np.concatenate(rows) if rows else np.zeros((0, len(FEATURE_NAMES)), np.float32)
    return WindowSet(
        X=X.astype(np.float32),
        **{k: np.asarray(v, dtype=str) for k, v in cols.items()},
        per_session=per_session,
        dropped={r: int(dropped.get(r, 0)) for r in DROP_REASONS},
        warnings=warnings,
    )


# ------------------------------------------------------------------------------------------------ evaluation


def check_split(ws: WindowSet, cfg: ExperimentConfig) -> dict[str, list[str]]:
    """Train and test sessions and persons of the split ``cfg`` names (``split_by_group``). Refuses any session on
    both sides (for a split by person: a session that holds a train person and a test person)."""
    groups = ws.session if cfg.split == "session" else ws.person
    if cfg.split == "person" and np.any(ws.person == "-"):
        raise ExperimentError("no_person", "A split by person needs a person on every window's label.")
    fraction = cfg.fraction if cfg.test_groups is None else None
    if cfg.test_groups is None and fraction is None:
        fraction = 0.25
    try:
        tr, te = rzb.split_by_group(groups, test_groups=cfg.test_groups, fraction=fraction, seed=cfg.seed)
    except ValueError as exc:
        raise ExperimentError("bad_split", f"Split refused: {exc}", 422) from exc
    s_tr, s_te = set(ws.session[tr].tolist()), set(ws.session[te].tolist())
    both = sorted(s_tr & s_te)
    if both:
        raise ExperimentError(
            "overlap",
            f"Sessions on both sides of the split: {', '.join(both)}. A split by person may not share a session "
            "between a train person and a test person (same floor, day and clock): choose test persons whose "
            "sessions hold no train person, or split by session.",
        )
    p_tr, p_te = set(ws.person[tr].tolist()), set(ws.person[te].tolist())
    if cfg.split == "person" and p_tr & p_te:  # split_by_group already refuses it; kept as the page's own check
        raise ExperimentError("overlap", f"Persons on both sides of the split: {sorted(p_tr & p_te)}")
    return {
        "train_groups": sorted(set(groups[tr].tolist())),
        "test_groups": sorted(set(groups[te].tolist())),
        "train_sessions": sorted(s_tr),
        "test_sessions": sorted(s_te),
        "train_people": sorted(p_tr - {"-"}),
        "test_people": sorted(p_te - {"-"}),
    }


def _per_person(ws: WindowSet, cfg: ExperimentConfig, ev: dict[str, Any], test_sessions: list[str]) -> dict:
    """Per-person test results where ``evaluate`` gives them: for target person, each person's class row (recall =
    share of that person's test windows named correctly); for a split by person, the per-group scores."""
    if cfg.target == "person":
        return {
            p: {"accuracy": v["recall"], "n": v["support"], "source": "per_class recall"}
            for p, v in ev["scores"]["per_class"].items()
            if v["support"] > 0
        }
    if cfg.split == "person":
        return {p: {**v, "source": "per_group"} for p, v in ev["scores"]["per_group"].items()}
    return {}


def run_experiment(
    cfg: ExperimentConfig,
    sources: Sequence[SessionSource],
    pack: Mapping[str, Any],
    pack_hash: str,
    cache_dir: Path | None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Build the windows, check the split and evaluate (model and majority baseline). Returns the results JSON."""
    cfg.check()
    if [s.session for s in sources] != list(cfg.sessions):
        raise ExperimentError("bad_sessions", "Sessions and their sources disagree.", 500)
    t0 = time.monotonic()
    ws = build_windows(sources, pack, pack_hash, cfg.target, cache_dir, progress)
    if ws.y.size == 0:
        raise ExperimentError("no_windows", "No labelled feature windows in these sessions.")
    split = check_split(ws, cfg)
    try:
        res = rzb.evaluate(
            ws.X,
            ws.y,
            {"session": ws.session, "person": ws.person},
            split=cfg.split,
            seed=cfg.seed,
            model=cfg.model,
            test_groups=split["test_groups"],
        )
    except ValueError as exc:
        raise ExperimentError("eval_refused", f"Evaluation refused: {exc}", 422) from exc
    ev = res.as_dict()
    if ev.get("baseline") is None:  # EvalResult cannot exist without it; this page never shows a result without it
        raise ExperimentError("no_baseline", "The evaluation returned no baseline.", 500)
    simulated = any(s.simulated for s in sources)
    flags = list(res.flags)
    if simulated:
        flags.insert(0, f"{SIMULATED_MARK}: {sum(s.simulated for s in sources)} of {len(sources)} sessions")
    flags += ws.warnings
    return {
        "format": 1,
        "created": datetime.now().isoformat(timespec="seconds"),
        "config": asdict(cfg),
        "pack": {"id": pack.get("id"), "version": pack.get("version"), "sha256": pack_hash},
        "rezonating_ml": rezonating_ml.__version__,
        "features": list(FEATURE_NAMES),
        "simulated": simulated,
        "sessions": ws.per_session,
        "dataset": {
            "windows": int(ws.y.size),
            "dropped": ws.dropped,
            "classes": dict(sorted(Counter(ws.y.tolist()).items())),
            "people": sorted(set(ws.person.tolist()) - {"-"}),
        },
        "split": split,
        "result": ev,
        "beats_baseline": bool(res.beats_baseline),
        "per_person": _per_person(ws, cfg, ev, split["test_sessions"]),
        "flags": flags,
        "summary": res.summary(),
        "elapsed_s": round(time.monotonic() - t0, 3),
    }


# ------------------------------------------------------------------------------------------------ runs


def confusion_svg(labels: Sequence[str], matrix: Sequence[Sequence[int]], title: str = "") -> str:
    """A small confusion-matrix heatmap (rows = true, columns = predicted)."""
    n = len(labels)
    cell, left, top = 44, 90, 40
    w, h = left + n * cell + 10, top + n * cell + 30
    peak = max((v for row in matrix for v in row), default=0) or 1
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" font-family="sans-serif" font-size="11">',
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        f'<text x="{left}" y="14">{esc(title)}</text>',
        f'<text x="{left}" y="30" fill="#555">predicted</text>',
    ]
    for j, lab in enumerate(labels):
        out.append(f'<text x="{left + j * cell + cell / 2}" y="{top - 2}" text-anchor="middle">{esc(lab)}</text>')
    for i, lab in enumerate(labels):
        y = top + i * cell
        out.append(f'<text x="{left - 6}" y="{y + cell / 2 + 4}" text-anchor="end">{esc(lab)}</text>')
        for j in range(n):
            v = matrix[i][j]
            a = v / peak
            out.append(
                f'<rect x="{left + j * cell}" y="{y}" width="{cell - 2}" height="{cell - 2}" '
                f'fill="rgb({int(255 - 200 * a)},{int(255 - 140 * a)},255)"/>'
                f'<text x="{left + j * cell + cell / 2 - 1}" y="{y + cell / 2 + 4}" text-anchor="middle" '
                f'fill="{"#fff" if a > 0.6 else "#111"}">{v}</text>'
            )
    out.append(f'<text x="4" y="{top + n * cell + 20}" fill="#555">rows: true class</text></svg>')
    return "".join(out)


def save_run(runs_root: Path, results: Mapping[str, Any], now: datetime | None = None) -> str:
    """Write ``<runs_root>/<YYYY-MM-DD_HHMMSS>_<pack>_<split>/`` with config.json, results.json and confusion.svg.
    Returns the run id (the folder name)."""
    now = now or datetime.now()
    cfg = results["config"]
    base = f"{now:%Y-%m-%d_%H%M%S}_{cfg['pack']}_{cfg['split']}"
    runs_root.mkdir(parents=True, exist_ok=True)
    run_id, k = base, 1
    while (runs_root / run_id).exists():
        k += 1
        run_id = f"{base}_{k}"
    folder = runs_root / run_id
    folder.mkdir()
    (folder / "config.json").write_text(json.dumps(cfg, indent=1) + "\n", encoding="utf-8")
    (folder / "results.json").write_text(json.dumps({**results, "run_id": run_id}, indent=1) + "\n", encoding="utf-8")
    ev = results["result"]
    title = f"{cfg['model']} | target {cfg['target']} | split by {cfg['split']}"
    if results.get("simulated"):
        title = f"{SIMULATED_MARK} | {title}"
    (folder / "confusion.svg").write_text(confusion_svg(ev["labels"], ev["scores"]["confusion"], title), "utf-8")
    return run_id


def run_folder(runs_root: Path, run_id: str) -> Path:
    if not RUN_ID_RE.match(run_id):
        raise ExperimentError("bad_run", f"Not a run id: {run_id!r}", 422)
    folder = runs_root / run_id
    if not (folder / "results.json").is_file():
        raise ExperimentError("not_found", f"No run {run_id!r}.", 404)
    return folder


def load_run(runs_root: Path, run_id: str) -> dict[str, Any]:
    return json.loads((run_folder(runs_root, run_id) / "results.json").read_text(encoding="utf-8"))


def list_runs(runs_root: Path) -> list[dict[str, Any]]:
    """Every saved run, newest first, as a one-line summary."""
    out = []
    for d in sorted(runs_root.iterdir(), reverse=True) if runs_root.is_dir() else []:
        if not RUN_ID_RE.match(d.name) or not (d / "results.json").is_file():
            continue
        try:
            r = json.loads((d / "results.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ev = r["result"]
        out.append(
            {
                "run_id": d.name,
                "created": r.get("created"),
                "pack": r["config"]["pack"],
                "split": r["config"]["split"],
                "target": r["config"]["target"],
                "model": r["config"]["model"],
                "sessions": len(r["config"]["sessions"]),
                "simulated": r.get("simulated", False),
                "balanced_accuracy": ev["scores"]["balanced_accuracy"],
                "baseline_balanced_accuracy": ev["baseline"]["balanced_accuracy"],
                "beats_baseline": r.get("beats_baseline"),
                "flags": len(r.get("flags", [])),
                "draft": r.get("draft"),
            }
        )
    return out


# ------------------------------------------------------------------------------------------------ EXP draft


def next_exp_id(vault_root: Path) -> str:
    """The next ``EXP-###`` after the highest one in ``50 Experiments/`` and ``00 Inbox/`` (names and ``id:``)."""
    best = 0
    for folder in ("50 Experiments", "00 Inbox"):
        d = vault_root / folder
        for p in d.rglob("*.md") if d.is_dir() else []:
            ids = EXP_ID_RE.findall(p.name)
            try:
                head = p.read_text(encoding="utf-8")[:2000]
            except (OSError, UnicodeDecodeError):
                head = ""
            ids += re.findall(r"^id:\s*EXP-(\d{3})\s*$", head, flags=re.M)
            best = max([best, *(int(i) for i in ids)])
    if best >= 999:
        raise ExperimentError("exp_full", "EXP-999 is taken; ids have three digits.")
    return f"EXP-{best + 1:03d}"


def _one(values: Sequence[str | None]) -> str:
    vals = {v for v in values if v}
    return vals.pop() if len(vals) == 1 else ""


def _fmt(v: float) -> str:
    return f"{v:.3f}"


def exp_note_text(run: Mapping[str, Any], exp_id: str, title: str, run_rel: str, today: str) -> str:
    """The draft note: the exact ``experiment`` frontmatter of the vault-conventions skill, then the body."""
    cfg, ev, ds, sp = run["config"], run["result"], run["dataset"], run["split"]
    sessions = run["sessions"]
    sim = run.get("simulated", False)
    protocol = _one([s.get("protocol") for s in sessions])
    floor = _one([s.get("floor") for s in sessions])
    fm = [
        "---",
        "type: experiment",
        f"id: {exp_id}",
        "status: running",
        f"date: {today}",
        "owner: claude",
        f'pack: "[[{cfg["pack"]}]]"',
        f"protocol: {protocol}".rstrip(),
        f"floor: {floor}".rstrip(),
        f"people: {len(ds['people'])}",
        "sessions:",
        *[f"  - {s['session']}" for s in sessions],
        "metric: balanced_accuracy",
        f"metric_value: {ev['scores']['balanced_accuracy']:.3f}",
        "result:",
        "---",
    ]
    labels = ev["labels"]
    conf = ev["scores"]["confusion"]
    body = [f"# {exp_id} {title}", ""]
    if sim:
        body += ["> [!warning] SIMULATED DATA", "> Every number below comes from simulated sessions, not a floor.", ""]
    body += [
        f"**Question:** how well does `{cfg['model']}` on `{run['pack']['id']}` features tell **{cfg['target']}** "
        f"apart, split by {cfg['split']}, compared with the majority-class baseline?",
        "",
        "## Data",
        f"- Sessions ({len(sessions)}, {'simulated' if sim else 'real'}): "
        + ", ".join(f"{s['session']}{' (sim)' if s['simulated'] else ''}" for s in sessions),
        f"- Feature windows kept: {ds['windows']}; dropped: " + ", ".join(f"{k} {v}" for k, v in ds["dropped"].items()),
        "- Classes: " + ", ".join(f"{k} {v}" for k, v in ds["classes"].items()),
        f"- Pack {run['pack']['id']} {run['pack']['version']} (sha256 {run['pack']['sha256'][:12]}), "
        f"rezonating_ml {run['rezonating_ml']}",
        "",
        "## Split",
        f"- By **{cfg['split']}**, seed {cfg['seed']}, model `{cfg['model']}`",
        f"- Train sessions: {', '.join(sp['train_sessions'])} ({ev['n_train']} windows)",
        f"- Test sessions: {', '.join(sp['test_sessions'])} ({ev['n_test']} windows)",
        f"- Train people: {', '.join(sp['train_people']) or '-'}; test people: {', '.join(sp['test_people']) or '-'}",
        "",
        "## Results",
        "| | Accuracy | Balanced accuracy |",
        "| --- | --- | --- |",
        f"| Model ({cfg['model']}) | {_fmt(ev['scores']['accuracy'])} | {_fmt(ev['scores']['balanced_accuracy'])} |",
        f"| Majority baseline | {_fmt(ev['baseline']['accuracy'])} | {_fmt(ev['baseline']['balanced_accuracy'])} |",
        "",
        "Confusion matrix (rows true, columns predicted):",
        "",
        "| true \\ pred | " + " | ".join(labels) + " |",
        "| --- |" + " --- |" * len(labels),
        *[f"| {lab} | " + " | ".join(str(v) for v in conf[i]) + " |" for i, lab in enumerate(labels)],
        "",
        "## Flags",
        *([f"- {f}" for f in run["flags"]] or ["- none"]),
        "",
        "## What the number does not show",
        "- One split and one seed; no spread across seeds or folds.",
        "- " + ("Simulated sessions: says nothing about a real floor." if sim else "Only the floors listed above."),
        "",
        "## Run",
        f"- `{run_rel}`",
        "",
        "## Log",
        f"- {today} drafted by the Lab Experiments page; a person reviews it and sets `result`.",
        "",
    ]
    return "\n".join(fm) + "\n" + "\n".join(body)


EXP_FOLDER = "50 Experiments"


def check_draft(note: Path, vault_root: Path, script: Path) -> dict[str, Any]:
    """Run ``python .claude/scripts/vault_schema.py <note>`` with the vault root as project root. The draft passes
    only when the note was checked and the script reports no error at all (exit 0); warnings are shown."""
    if not script.is_file():
        return {"ok": False, "cli": "", "cli_rc": None, "errors": [f"{script} not found"]}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(vault_root), "PYTHONIOENCODING": "utf-8"}
    cli = subprocess.run(
        [sys.executable, str(script), str(note)], capture_output=True, text=True, env=env, timeout=60, check=False
    )
    errors = [ln for ln in cli.stdout.splitlines() if ": error: " in ln]
    if cli.returncode != 0 and not errors:
        errors.append(f"vault_schema exited {cli.returncode}: {cli.stderr.strip()[-300:]}")
    if "1 notes checked" not in cli.stdout:
        errors.append("vault_schema did not check the note (is the vault root a vault?)")
    return {
        "ok": cli.returncode == 0 and not errors,
        "cli": cli.stdout.strip(),
        "cli_rc": cli.returncode,
        "errors": errors,
    }


def draft_exp_note(
    run: Mapping[str, Any],
    run_dir: Path,
    vault_root: Path,
    repo_root: Path,
    title: str,
    script: Path | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Write ``<vault_root>/50 Experiments/EXP-### <title>.md`` (the id after the highest in ``50 Experiments/``
    and ``00 Inbox/``) and check it with ``vault_schema.py`` (:func:`check_draft`); on any error the note is
    deleted and the errors returned. Writes nowhere else in the vault."""
    title = re.sub(r"\s+", " ", BAD_NAME_CHARS.sub(" ", title)).strip()[:60].strip()
    if not title:
        raise ExperimentError("bad_title", "Give the note a short title.", 422)
    folder = vault_root / EXP_FOLDER
    if not folder.is_dir():
        raise ExperimentError("no_exp_folder", f"No '{EXP_FOLDER}' folder in the vault root {vault_root}.")
    exp_id = next_exp_id(vault_root)
    note = folder / f"{exp_id} {title}.md"
    try:
        run_rel = run_dir.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        run_rel = run_dir.name  # runs outside the repository: the folder name only
    text = exp_note_text(run, exp_id, title, run_rel, today or datetime.now().strftime("%Y-%m-%d"))
    with open(note, "x", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    check = check_draft(note, vault_root, script or repo_root / ".claude" / "scripts" / "vault_schema.py")
    rel = f"{EXP_FOLDER}/{note.name}"
    if not check["ok"]:
        note.unlink()
        return {"ok": False, "id": exp_id, "path": None, "deleted": rel, "check": check}
    return {"ok": True, "id": exp_id, "path": rel, "check": check}


def record_draft(run_dir: Path, draft: Mapping[str, Any]) -> None:
    """Note the drafted EXP id and path in the run's results.json (the runs list shows it)."""
    path = run_dir / "results.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["draft"] = {"id": draft["id"], "path": draft["path"]}
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
