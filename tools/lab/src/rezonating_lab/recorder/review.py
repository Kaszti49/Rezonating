"""The Review page's backend (WEB_API.md section 12): list and open recorded sessions, draw them, edit their labels.

Labels are edited in **sample indices** (``i0``/``i1`` within one stream's WAV); ``t0``/``t1`` are always recomputed as
``index / sample_rate``, the rule ``rezonating_ml.io.check_pair`` checks. Every edit is a pure function of the label
list (:func:`apply_edit`), so the browser keeps the undo history and the server keeps one implementation of the rules.

Source of an edited label: the sidecar schema v1 allows ``src`` ``key``, ``phone``, ``review`` and ``auto``; there is
no ``edit``. A label added on the Review page gets ``review``. A live label that is edited by hand **keeps its src**
(it still started as a key or phone mark); when one of its indices moves (move, split, merge) its ``unc_ms`` is
dropped, because it described the live mark's timing and no longer applies. A retag keeps both.

Both streams stay in sync (decision of 2026-10-13): the page edits the labels of one stream, and a save writes them
into **both** sidecars. The other stream's indices come through the shared device clock: a sidecar's frame ``i`` lies
at device time ``t_dev_us + i * 1e6 / sample_rate_measured`` (``first_sample``/``t_dev_us`` and the measured rate the
recorder wrote; the same clock it used to put each live mark into both files). For a label that was not edited, a label
of the other stream within :data:`SYNC_TOL_S` of the mapped place with the same tags is kept as it is (its own
``unc_ms``); an edited label is always mapped afresh. A label entirely outside the other file is not copied there.

Saving (:func:`save_labels`) checks both new sidecars first (``rezonating_ml.io.check_pair`` plus the schema check of
``tools/validate.py``); nothing is written unless both pass. Then each previous version is kept as ``<sidecar>.bak``,
both are written through ``rezonating_ml.io.save_sidecar`` as a pair (a failed second write puts the first back from its
``.bak``: ``write_failed``), the session folder is re-validated (the ``rzlab
validate`` checks) and both copies in the repository's ``data/<session>/`` are replaced (temp file and
``os.replace``) only when the folder is valid.

Label texts come from the session protocol's fixed list (``labels`` in ``docs/protocols/<protocol>.yaml``, plus
``noise``, ``other``, ``bad``; only those three for a protocol without a YAML): an add, a retag or a save with any
other label is refused (422). Labels outside the list (older sessions) are listed in ``labels_off_list``.

Recordings are read only through ``rezonating_ml.io``; the display maths is ``core/view.py``.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import os
import shutil
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from rezonating_ml import io

from ..core.view import envelope, stft_db
from .forms import check_label, check_pseudonym
from .protocol import SHARED_LABELS, ProtocolError, check_listed, load_named
from .validate import STREAM_BY_SUFFIX, validate_session_folder

SUFFIX_BY_STREAM = {v: k for k, v in STREAM_BY_SUFFIX.items()}
PACES = ("slow", "normal", "fast")
TAG_KEYS = ("label", "person", "pace", "shoes")
SRC_REVIEW = "review"
MAX_LABELS = 20000
BACKUP_SUFFIX = ".bak"
SYNC_TOL_S = 0.010  # a label of the other stream this close to the mapped place is the same label


class ReviewError(Exception):
    """A Review request was refused; ``code`` and ``http`` follow the API's error envelope."""

    def __init__(self, code: str, message: str, http: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http = http


# ---------------------------------------------------------------------------------------------- sessions


def session_folder(root: Path, name: str) -> Path:
    """The folder of session ``name`` in the data root; refuses anything that is not a session name in it."""
    if not io.SESSION_RE.match(name):
        raise ReviewError("not_found", f"{name!r} is not a session name (YYYY-MM-DD_<site>_<room>_<nn>).", 404)
    folder = root / name
    if not folder.is_dir():
        raise ReviewError("not_found", f"No session {name} in the data root.", 404)
    if folder.is_symlink() or folder.resolve().parent != root.resolve():
        raise ReviewError("not_found", f"{name} is a link or lies outside the data root; it is not opened.", 404)
    return folder


def load_doc(js: Path) -> dict[str, Any]:
    """A sidecar through ``rezonating_ml.io``; an unreadable or corrupt one is a 422, not a server error."""
    try:
        return io.load_sidecar(js)
    except (OSError, ValueError) as exc:
        raise ReviewError("invalid_sidecar", f"{js.name} cannot be read: {exc}") from exc


def labels_allowed(repo_root: Path | None, protocol: Any) -> tuple[list[str] | None, str | None]:
    """``(labels, None)`` of the session's protocol; ``(SHARED_LABELS, why)`` when the protocol has no usable YAML
    (an older session such as ``kill-test-phone``); ``(None, why)`` only when the sidecar names no protocol."""
    if not isinstance(protocol, str):
        return None, "the sidecar names no protocol"
    try:
        return list(load_named(repo_root, protocol).labels), None
    except ProtocolError as exc:
        return list(SHARED_LABELS), (
            f"protocol {protocol} gives no label list ({'; '.join(exc.problems)}); only the shared labels "
            f"{', '.join(SHARED_LABELS)} can be set"
        )


def off_list(labels: list[Any], allowed: list[str] | None) -> list[int]:
    """Positions of the labels whose text is not in ``allowed`` (all of them when there is no list)."""
    return [
        n
        for n, lab in enumerate(labels)
        if allowed is None or not isinstance(lab, dict) or lab.get("label") not in allowed
    ]


def stream_paths(folder: Path, stream: str) -> tuple[Path, Path]:
    suffix = SUFFIX_BY_STREAM.get(stream)
    if suffix is None:
        raise ReviewError("no_stream", f"Unknown stream {stream!r}; a session holds adc_raw and/or accel.", 404)
    return folder / f"{folder.name}.{suffix}.wav", folder / f"{folder.name}.{suffix}.json"


def file_version(path: Path) -> str:
    """A short hash of the sidecar's bytes: a save names the version it edited, so a change on disk is not lost."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def list_sessions(root: Path, sidecar_dir: Path | None) -> list[dict[str, Any]]:
    """Every session folder of the data root that holds at least one sidecar, newest name first. Reads only sidecars."""
    out: list[dict[str, Any]] = []
    folders = (p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and io.SESSION_RE.match(p.name))
    for folder in sorted(folders, reverse=True):
        streams: list[dict[str, Any]] = []
        for stream in STREAM_BY_SUFFIX.values():
            wav, js = stream_paths(folder, stream)
            if not js.is_file():
                continue
            entry: dict[str, Any] = {"stream": stream, "wav": wav.is_file()}
            try:
                doc = io.load_sidecar(js)
                frames = io.parse_rzlab_notes(doc.get("notes")).get("frames")
                rate = doc.get("sample_rate")
                entry["labels"] = len(doc.get("labels") or [])
                entry["sample_rate"] = rate
                entry["duration_s"] = (
                    round(int(frames) / rate, 3) if frames and frames.isdigit() and isinstance(rate, int) else None
                )
            except (OSError, ValueError) as exc:
                entry["error"] = f"cannot read the sidecar: {exc}"
            streams.append(entry)
        if streams:
            out.append({"name": folder.name, "streams": streams, "repo_copy": _repo_copy(sidecar_dir, folder.name)})
    return out


def _repo_copy(sidecar_dir: Path | None, name: str) -> bool:
    return sidecar_dir is not None and (sidecar_dir / name).is_dir()


def open_session(root: Path, name: str, sidecar_dir: Path | None, repo_root: Path | None = None) -> dict[str, Any]:
    """What the Review page needs to show a session: per stream the WAV shape, channel units and the labels."""
    folder = session_folder(root, name)
    streams: dict[str, Any] = {}
    persons: list[str] = []
    protocol = None
    for stream in STREAM_BY_SUFFIX.values():
        wav, js = stream_paths(folder, stream)
        if not js.is_file():
            continue
        doc = load_doc(js)
        notes = io.parse_rzlab_notes(doc.get("notes"))
        if notes.get("persons") and not persons:
            persons = [p for p in notes["persons"].split(",") if p]
        protocol = protocol or doc.get("protocol")
        info = io.wav_info(wav) if wav.is_file() else None
        streams[stream] = {
            "stream": stream,
            "sidecar": js.name,
            "wav": wav.name if info else None,
            "frames": info.frames if info else None,
            "sample_rate": doc.get("sample_rate"),
            "n_ch": len(doc.get("channels") or []),
            "channels": [
                {"ch": c.get("ch"), "units": c.get("units"), "scale": c.get("scale"), "head": c.get("head")}
                for c in doc.get("channels") or []
            ],
            "labels": doc.get("labels") or [],
            "version": file_version(js),
            "backup": (js.parent / (js.name + BACKUP_SUFFIX)).is_file(),
        }
    if not streams:
        raise ReviewError("not_found", f"Session {name} holds no sidecar.", 404)
    allowed, why = labels_allowed(repo_root, protocol)
    for st in streams.values():
        st["labels_off_list"] = off_list(st["labels"], allowed)
    return {
        "name": name,
        "streams": streams,
        "persons": persons,
        "protocol": protocol,
        "labels_allowed": allowed,
        "labels_note": why,
        "repo_copy": _repo_copy(sidecar_dir, name),
    }


# ------------------------------------------------------------------------------------------- the signal


class WavCache:
    """The last few WAVs read for display, keyed by path, size and modification time (a rewrite is noticed)."""

    def __init__(self, max_items: int = 2) -> None:
        self._lock = threading.Lock()
        self._items: OrderedDict[tuple[str, int, int], np.ndarray] = OrderedDict()
        self._max = max_items

    def get(self, path: Path) -> np.ndarray:
        st = path.stat()
        key = (str(path.resolve()), st.st_size, st.st_mtime_ns)
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        codes, _fs = io.read_wav(path)
        with self._lock:
            self._items[key] = codes
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return codes


@dataclass
class StreamData:
    codes: np.ndarray  # (frames, n_ch) int32 codes
    scale: np.ndarray  # (n_ch,) float64: units per code
    units: list[str]
    rate_hz: int


def stream_data(root: Path, name: str, stream: str, cache: WavCache) -> StreamData:
    folder = session_folder(root, name)
    wav, js = stream_paths(folder, stream)
    if not wav.is_file() or not js.is_file():
        raise ReviewError("no_stream", f"Session {name} has no {stream} recording with a sidecar.", 404)
    doc = load_doc(js)
    codes = cache.get(wav)
    chans = doc.get("channels") or []
    scale = np.array([float(c.get("scale", 1.0)) for c in chans] or [1.0] * codes.shape[1], np.float64)
    if len(scale) != codes.shape[1]:
        scale = np.ones(codes.shape[1])
    units = [str(c.get("units", "counts")) for c in chans] or ["counts"] * codes.shape[1]
    return StreamData(codes, scale, units, int(doc.get("sample_rate") or 1))


def _range(frames: int, i0: int | None, i1: int | None) -> tuple[int, int]:
    a = 0 if i0 is None else i0
    b = frames if i1 is None else i1
    if not 0 <= a < b <= frames:
        raise ReviewError("out_of_bounds", f"The range must satisfy 0 <= i0 < i1 <= {frames} (the file's frames).")
    return a, b


def _nan_list(a: np.ndarray, digits: int = 6) -> list:
    return [None if not np.isfinite(v) else round(float(v), digits) for v in a]


def envelope_view(data: StreamData, i0: int | None, i1: int | None, columns: int) -> dict[str, Any]:
    """Min/max per pixel column of ``[i0, i1)`` in the channels' units (whole file by default)."""
    frames = data.codes.shape[0]
    a, b = _range(frames, i0, i1)
    env = envelope(data.codes[a:b], columns)
    lo = env.vmin * data.scale[None, :]
    hi = env.vmax * data.scale[None, :]
    vmin, vmax = np.minimum(lo, hi), np.maximum(lo, hi)  # a negative scale swaps them
    return {
        "frames": frames,
        "sample_rate": data.rate_hz,
        "i0": a,
        "i1": b,
        "edges": (env.edges + a).tolist(),
        "units": data.units,
        "min": [_nan_list(vmin[:, c], 9) for c in range(vmin.shape[1])],
        "max": [_nan_list(vmax[:, c], 9) for c in range(vmax.shape[1])],
    }


def spectrogram_view(
    data: StreamData, ch: int, i0: int | None, i1: int | None, columns: int, nfft: int
) -> dict[str, Any]:
    """STFT columns of one channel over ``[i0, i1)``; the hop grows so at most ``columns`` columns come back."""
    frames, n_ch = data.codes.shape
    if not 0 <= ch < n_ch:
        raise ReviewError("invalid_request", f"Channel {ch} does not exist; the stream has {n_ch}.")
    a, b = _range(frames, i0, i1)
    x = data.codes[a:b, ch].astype(np.float64) * data.scale[ch]
    sg = stft_db(x, float(data.rate_hz), nfft=nfft, first_index=a, max_columns=columns)
    return {
        "frames": frames,
        "sample_rate": data.rate_hz,
        "i0": a,
        "i1": b,
        "ch": ch,
        "units": data.units[ch] if ch < len(data.units) else "counts",
        "nfft": sg.nfft,
        "hop": sg.hop,
        "freq_hz": [round(float(f), 3) for f in sg.freq_hz],
        "center_index": sg.center_index.tolist(),
        "power_db": [_nan_list(row, 1) for row in sg.power_db],
    }


# -------------------------------------------------------------------------------------------- label edits


def _check_tags(lab: dict[str, Any], where: str, persons: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    label = lab.get("label")
    if not isinstance(label, str):
        raise ReviewError("invalid_label", f"{where}: label must be text.")
    try:
        out["label"] = check_label(label)
    except ValueError as exc:
        raise ReviewError("invalid_label", f"{where}: {exc}") from exc
    person = lab.get("person")
    if person is not None:
        try:
            out["person"] = check_pseudonym(str(person))
        except ValueError as exc:
            raise ReviewError("invalid_label", f"{where}: {exc}") from exc
        if persons and person not in persons:
            raise ReviewError("invalid_label", f"{where}: {person} is not one of this session's persons.")
    pace = lab.get("pace")
    if pace is not None:
        if pace not in PACES:
            raise ReviewError("invalid_label", f"{where}: pace is slow, normal or fast.")
        out["pace"] = pace
    shoes = lab.get("shoes")
    if shoes is not None:
        if not isinstance(shoes, bool):
            raise ReviewError("invalid_label", f"{where}: shoes is true or false.")
        out["shoes"] = shoes
    return out


def _index(v: Any, where: str, name: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise ReviewError("invalid_label", f"{where}: {name} must be a whole sample index.")
    return v


def normalise_labels(labels: Any, frames: int, rate_hz: int, persons: list[str] | None = None) -> list[dict[str, Any]]:
    """Check a label list from the browser and rebuild it in the sidecar's shape, sorted by ``(i0, i1)``.

    Refuses (``ReviewError``) an index outside ``0 <= i0 <= i1 <= frames``, a bad tag or an unknown field."""
    if not isinstance(labels, list):
        raise ReviewError("invalid_request", "labels must be a list.")
    if len(labels) > MAX_LABELS:
        raise ReviewError("invalid_request", f"At most {MAX_LABELS} labels.")
    if rate_hz <= 0:
        raise ReviewError("invalid_request", "The sidecar has no usable sample_rate.")
    allowed = {"t0", "t1", "i0", "i1", "src", "unc_ms", *TAG_KEYS}
    out: list[dict[str, Any]] = []
    for n, lab in enumerate(labels):
        where = f"labels[{n}]"
        if not isinstance(lab, dict):
            raise ReviewError("invalid_label", f"{where}: must be an object.")
        extra = set(lab) - allowed
        if extra:
            raise ReviewError("invalid_label", f"{where}: unknown field(s) {', '.join(sorted(extra))}.")
        i0, i1 = _index(lab.get("i0"), where, "i0"), _index(lab.get("i1"), where, "i1")
        if not 0 <= i0 <= i1 <= frames:
            raise ReviewError(
                "out_of_bounds", f"{where}: [{i0}, {i1}] is outside the file: 0 <= i0 <= i1 <= {frames} is needed."
            )
        entry: dict[str, Any] = {"t0": i0 / rate_hz, "t1": i1 / rate_hz, "i0": i0, "i1": i1}
        src = lab.get("src")
        if src is not None:
            if src not in ("key", "phone", "review", "auto"):
                raise ReviewError("invalid_label", f"{where}: src must be key, phone, review or auto.")
            entry["src"] = src
        unc = lab.get("unc_ms")
        if unc is not None:
            if isinstance(unc, bool) or not isinstance(unc, (int, float)) or unc < 0:
                raise ReviewError("invalid_label", f"{where}: unc_ms must be a number >= 0.")
            entry["unc_ms"] = unc
        entry.update(_check_tags(lab, where, persons or []))
        out.append(entry)
    out.sort(key=lambda d: (d["i0"], d["i1"]))
    return out


def check_allowed(labels: list[dict[str, Any]], allowed: list[str] | None, only: list[int] | None = None) -> None:
    """Refuse (422) a label text outside the protocol's list; ``only`` limits the check to those positions."""
    for n in range(len(labels)) if only is None else only:
        text = labels[n].get("label")
        if allowed is None:
            raise ReviewError(
                "no_label_list",
                "This session's protocol gives no label list (labels: in docs/protocols/<protocol>.yaml), so no "
                "label can be set or saved.",
            )
        try:
            check_listed(str(text), allowed, None)
        except ValueError:
            raise ReviewError(
                "invalid_label", f"labels[{n}]: {text!r} is not one of this protocol's labels: {', '.join(allowed)}."
            ) from None


def _moved(lab: dict[str, Any], i0: int, i1: int) -> dict[str, Any]:
    """A copy of ``lab`` with new indices; ``unc_ms`` (a live mark's timing) no longer applies."""
    new = {k: v for k, v in lab.items() if k not in ("unc_ms", "t0", "t1")}
    new["i0"], new["i1"] = i0, i1
    return new


def apply_edit(
    labels: list[dict[str, Any]],
    op: dict[str, Any],
    frames: int,
    rate_hz: int,
    persons: list[str] | None = None,
    allowed: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Apply one edit to a (checked) label list and return the new, checked list. ``op["kind"]``:

    * ``move`` ``{n, edge: "start"|"end", i}``: move one edge to sample ``i`` (it may not pass the other edge);
    * ``split`` ``{n, i}``: two labels ``[i0, i)`` and ``[i, i1)`` with the same tags (``i0 < i < i1``);
    * ``merge`` ``{n}``: label ``n`` and the next one become one, from the first start to the later end, with the
      tags and src of label ``n``;
    * ``retag`` ``{n, set: {label?, person?, pace?, shoes?}}``: a ``null`` value removes that field (not ``label``);
    * ``delete`` ``{n}``;
    * ``add`` ``{i0, i1, label, person?, pace?, shoes?}``: a new label with src ``review``.

    The label text of an add or a retag must be one of ``allowed`` (the protocol's list)."""
    cur = normalise_labels(labels, frames, rate_hz, persons)
    kind = op.get("kind")

    def pick(key: str = "n") -> int:
        n = op.get(key)
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n < len(cur):
            raise ReviewError("bad_edit", f"No label {n!r}; there are {len(cur)}.")
        return n

    def sample(key: str = "i") -> int:
        i = _index(op.get(key), "edit", key)
        if not 0 <= i <= frames:
            raise ReviewError("out_of_bounds", f"Sample {i} is outside the file (0 to {frames}).")
        return i

    if kind == "move":
        n, i = pick(), sample()
        lab = cur[n]
        if op.get("edge") == "start":
            if i > lab["i1"]:
                raise ReviewError("bad_edit", "The start cannot move past the end of the label.")
            cur[n] = _moved(lab, i, lab["i1"])
        elif op.get("edge") == "end":
            if i < lab["i0"]:
                raise ReviewError("bad_edit", "The end cannot move before the start of the label.")
            cur[n] = _moved(lab, lab["i0"], i)
        else:
            raise ReviewError("bad_edit", "edge is start or end.")
    elif kind == "split":
        n, i = pick(), sample()
        lab = cur[n]
        if not lab["i0"] < i < lab["i1"]:
            raise ReviewError("bad_edit", "Put the cursor inside the label to split it.")
        cur[n : n + 1] = [_moved(lab, lab["i0"], i), _moved(lab, i, lab["i1"])]
    elif kind == "merge":
        n = pick()
        if n + 1 >= len(cur):
            raise ReviewError("bad_edit", "The last label has no next neighbour to merge with.")
        a, b = cur[n], cur[n + 1]
        cur[n : n + 2] = [_moved(a, min(a["i0"], b["i0"]), max(a["i1"], b["i1"]))]
    elif kind == "retag":
        n = pick()
        changes = op.get("set")
        if not isinstance(changes, dict) or not changes or set(changes) - set(TAG_KEYS):
            raise ReviewError("bad_edit", "retag needs set: {label?, person?, pace?, shoes?}.")
        lab = dict(cur[n])
        for k, v in changes.items():
            if v is None:
                if k == "label":
                    raise ReviewError("invalid_label", "Every label needs a label text.")
                lab.pop(k, None)
            else:
                lab[k] = v
        cur[n] = lab
        if "label" in changes:
            cur[n]["label"] = _tag_label(lab, allowed)
    elif kind == "delete":
        del cur[pick()]
    elif kind == "add":
        i0, i1 = sample("i0"), sample("i1")
        if i1 < i0:
            raise ReviewError("bad_edit", "A label ends after it starts.")
        new = {"i0": i0, "i1": i1, "src": SRC_REVIEW}
        new.update({k: op[k] for k in TAG_KEYS if op.get(k) is not None})
        new["label"] = _tag_label(new, allowed)
        cur.append(new)
    else:
        raise ReviewError("bad_edit", "kind is move, split, merge, retag, delete or add.")
    return normalise_labels(cur, frames, rate_hz, persons)


def _tag_label(lab: dict[str, Any], allowed: list[str] | None) -> str:
    text = lab.get("label")
    if not isinstance(text, str):
        raise ReviewError("invalid_label", "A label needs a label text.")
    try:
        text = check_label(text)
    except ValueError as exc:
        raise ReviewError("invalid_label", str(exc)) from exc
    probe = [{"label": text}]
    try:
        check_allowed(probe, allowed)
    except ReviewError as exc:
        raise ReviewError(exc.code, exc.message.replace("labels[0]: ", ""), exc.http) from None
    return text


# --------------------------------------------------------------------------------------- the other stream


def _clock(doc: dict[str, Any]) -> tuple[float, float]:
    """``(t_dev_us of frame 0, frames per device second)`` of a sidecar (WEB_API.md 12.5)."""
    rate = doc.get("sample_rate_measured")
    t0 = doc.get("t_dev_us")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or rate <= 0:
        raise ReviewError(
            "invalid_sidecar", "A sidecar has no usable sample_rate_measured; the streams cannot be synced."
        )
    if isinstance(t0, bool) or not isinstance(t0, (int, float)):
        raise ReviewError("invalid_sidecar", "A sidecar has no t_dev_us; the streams cannot be synced.")
    return float(t0), float(rate)


def _map_raw(i: int, src_doc: dict[str, Any], dst_doc: dict[str, Any]) -> int:
    t_src, r_src = _clock(src_doc)
    t_dst, r_dst = _clock(dst_doc)
    t_dev = t_src + i * 1e6 / r_src
    return int(round((t_dev - t_dst) * r_dst / 1e6))


def map_index(i: int, src_doc: dict[str, Any], dst_doc: dict[str, Any], dst_frames: int) -> int:
    """Frame ``i`` of one stream as a frame of the other, through the device clock; kept inside ``[0, dst_frames]``."""
    return min(max(_map_raw(i, src_doc, dst_doc), 0), dst_frames)


def _signature(lab: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(lab.get(k) for k in ("i0", "i1", "src", "unc_ms", *TAG_KEYS))


def _same_tags(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all(a.get(k) == b.get(k) for k in (*TAG_KEYS, "src"))


def mirror_labels(
    labels: list[dict[str, Any]],
    src_doc: dict[str, Any],
    dst_doc: dict[str, Any],
    dst_frames: int,
    dst_existing: list[dict[str, Any]],
    src_existing: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """The other stream's label list for ``labels`` (checked, of the edited stream) and how many labels were dropped.

    Each label keeps its tags and src; its indices come through the device clock. A label of ``dst_existing`` with the
    same tags within :data:`SYNC_TOL_S` of the mapped place is kept as it is (its own ``unc_ms``) **only when the edited
    label itself is unchanged** (identical to one of ``src_existing``, the edited stream's labels on disk): an edited
    label is always mapped afresh, however small the edit. A label that lies entirely outside the other file is not
    copied (it would become a zero-length label at the file's edge); the count says how many."""
    _, r_dst = _clock(dst_doc)
    tol = max(1, int(round(SYNC_TOL_S * r_dst)))
    rate_dst = int(dst_doc.get("sample_rate") or 0)
    pool = [dict(x) for x in dst_existing if isinstance(x, dict)]
    unchanged: dict[tuple[Any, ...], int] = {}
    for old in src_existing or []:
        if isinstance(old, dict):
            unchanged[_signature(old)] = unchanged.get(_signature(old), 0) + 1
    out: list[dict[str, Any]] = []
    dropped = 0
    for lab in labels:
        r0, r1 = _map_raw(lab["i0"], src_doc, dst_doc), _map_raw(lab["i1"], src_doc, dst_doc)
        outside = r1 < 0 or r0 > dst_frames or (lab["i1"] > lab["i0"] and (r1 <= 0 or r0 >= dst_frames))
        if outside:
            dropped += 1
            continue
        j0 = min(max(r0, 0), dst_frames)
        j1 = max(j0, min(max(r1, 0), dst_frames))
        keep = None
        if unchanged.get(_signature(lab), 0) > 0:
            unchanged[_signature(lab)] -= 1
            keep = next(
                (
                    k
                    for k, old in enumerate(pool)
                    if _same_tags(old, lab)
                    and isinstance(old.get("i0"), int)
                    and isinstance(old.get("i1"), int)
                    and abs(old["i0"] - j0) <= tol
                    and abs(old["i1"] - j1) <= tol
                ),
                None,
            )
        if keep is not None:
            out.append(pool.pop(keep))
            continue
        new = {k: v for k, v in lab.items() if k not in ("t0", "t1", "i0", "i1")}
        new["i0"], new["i1"] = j0, j1
        out.append(new)
    return normalise_labels(out, dst_frames, rate_dst), dropped


# ------------------------------------------------------------------------------------------------- save


def repo_schema_problems(repo_root: Path | None, doc: dict[str, Any]) -> tuple[list[str], str | None]:
    """The schema check of ``tools/validate.py`` (its own validator) on ``doc``. ``(problems, note)``; the note says
    why it could not run (no checkout), in which case the ``rezonating_ml.io`` schema check stands alone."""
    script = (repo_root / "tools" / "validate.py") if repo_root else None
    if script is None or not script.is_file():
        return [], "tools/validate.py was not found; only the rezonating_ml schema check ran"
    spec = importlib.util.spec_from_file_location("rz_tools_validate", script)
    if spec is None or spec.loader is None:
        return [], "tools/validate.py could not be loaded"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    v = mod.validator_for("sidecar")
    return [
        f"tools/validate.py: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
        for e in sorted(v.iter_errors(doc), key=lambda e: list(map(str, e.absolute_path)))
    ], None


_save_lock = threading.Lock()


@dataclass
class _Side:
    stream: str
    wav: Path
    js: Path
    doc: dict[str, Any]
    frames: int
    new_doc: dict[str, Any] | None = None


def _side(folder: Path, stream: str) -> _Side | None:
    wav, js = stream_paths(folder, stream)
    if not js.is_file() or not wav.is_file():
        return None
    doc = load_doc(js)
    try:
        frames = io.wav_info(wav).frames
    except (OSError, ValueError) as exc:
        raise ReviewError("invalid_sidecar", f"{wav.name} cannot be read: {exc}") from exc
    return _Side(stream, wav, js, doc, frames)


def _check_version(side: _Side, version: str | None, what: str) -> None:
    if version is None:
        raise ReviewError("invalid_request", f"{what} is required: the version of {side.js.name} the page opened.")
    if file_version(side.js) != version:
        raise ReviewError(
            "changed_on_disk",
            f"{side.js.name} changed on disk since it was opened. Reload the session (your edits are lost) "
            "or save again after reloading.",
            409,
        )


def save_labels(
    root: Path,
    name: str,
    stream: str,
    labels: Any,
    version: str | None,
    schema_path: Path,
    repo_root: Path | None,
    sidecar_dir: Path | None,
    peer_version: str | None = None,
) -> dict[str, Any]:
    """Write ``labels`` (of ``stream``) into its sidecar and, mapped, into the other stream's sidecar.

    Nothing is written unless both new sidecars validate; ``peer_version`` is required when the session has both."""
    folder = session_folder(root, name)
    main = _side(folder, stream)
    if main is None:
        raise ReviewError("no_stream", f"Session {name} has no {stream} recording with a sidecar.", 404)
    other_stream = next(s for s in STREAM_BY_SUFFIX.values() if s != stream)
    with _save_lock:
        peer = _side(folder, other_stream)
        _check_version(main, version, "version")
        if peer is not None:
            _check_version(peer, peer_version, "peer_version")
        notes = io.parse_rzlab_notes(main.doc.get("notes"))
        persons = [p for p in notes.get("persons", "").split(",") if p]
        new_labels = normalise_labels(labels, main.frames, int(main.doc.get("sample_rate") or 0), persons)
        allowed, _why = labels_allowed(repo_root, main.doc.get("protocol"))
        check_allowed(new_labels, allowed)
        main.new_doc = {**main.doc, "labels": new_labels}
        sides = [main]
        dropped = 0
        if peer is not None:
            peer_labels, dropped = mirror_labels(
                new_labels,
                main.doc,
                peer.doc,
                peer.frames,
                peer.doc.get("labels") or [],
                main.doc.get("labels") or [],
            )
            peer.new_doc = {**peer.doc, "labels": peer_labels}
            sides.append(peer)
        problems: list[str] = []
        note = None
        for side in sides:
            assert side.new_doc is not None
            found = io.check_pair(side.wav, side.new_doc, schema_path)
            extra, note = repo_schema_problems(repo_root, side.new_doc)
            problems += [f"{side.js.name}: {m}" for m in found + extra]
        result: dict[str, Any] = {"saved": False, "stream": stream, "sidecar": main.js.name, "problems": problems}
        if note:
            result["note"] = note
        if problems:
            result["validation"] = None
            result["repo_copy"] = {"updated": False, "reason": "not saved"}
            return result
        _write_pair(sides, schema_path)
        rep = validate_session_folder(folder, schema_path, repo_root=repo_root)
        result.update(
            saved=True,
            backup=main.js.name + BACKUP_SUFFIX,
            version=file_version(main.js),
            labels=new_labels,
            validation={"ok": rep.ok, "problems": rep.problems, "warnings": rep.warnings},
        )
        if peer is not None:
            assert peer.new_doc is not None
            result["peer"] = {
                "stream": peer.stream,
                "sidecar": peer.js.name,
                "backup": peer.js.name + BACKUP_SUFFIX,
                "version": file_version(peer.js),
                "labels": peer.new_doc["labels"],
                "labels_dropped": dropped,
            }
            if dropped:
                result["warnings"] = [
                    f"{dropped} label(s) lie entirely outside {peer.js.name}'s recording and were not copied to it "
                    "(labels_dropped)"
                ]
        result["repo_copy"] = _update_repo_copy(sidecar_dir, name, [s.js for s in sides], rep.ok)
        return result


def _write_pair(sides: list[_Side], schema_path: Path) -> None:
    """Write every side's ``new_doc`` as a pair: each previous sidecar is kept as ``.bak`` first; when a later write
    fails, the sidecars already written are put back from their ``.bak`` (atomic copy), so both stay as they were.
    A failure is ``ReviewError("write_failed", <what is on disk>, 500)``."""
    try:
        for side in sides:
            shutil.copy2(side.js, side.js.parent / (side.js.name + BACKUP_SUFFIX))
    except OSError as exc:
        raise ReviewError(
            "write_failed", f"The previous sidecars could not be kept as .bak ({exc}); nothing was saved.", 500
        ) from exc
    written: list[_Side] = []
    for side in sides:
        try:
            assert side.new_doc is not None
            io.save_sidecar(side.js, side.new_doc, schema_path)
        except (OSError, ValueError) as exc:
            restored, lost = [], []
            for done in written:
                try:
                    _atomic_copy(done.js.parent / (done.js.name + BACKUP_SUFFIX), done.js)
                    restored.append(done.js.name)
                except OSError:
                    lost.append(done.js.name)
            state = f"{side.js.name} is unchanged"
            if restored:
                state += f"; {', '.join(restored)} was put back from its .bak"
            if lost:
                state += f"; {', '.join(lost)} could NOT be put back: it holds the new labels, its .bak the old ones"
            raise ReviewError(
                "write_failed", f"Writing {side.js.name} failed ({exc}): {state}. Nothing else changed.", 500
            ) from exc
        written.append(side)


def _atomic_copy(src: Path, dest: Path) -> None:
    _write_bytes_atomic(dest, src.read_bytes())


def _update_repo_copy(sidecar_dir: Path | None, name: str, sidecars: list[Path], valid: bool) -> dict[str, Any]:
    if sidecar_dir is None or not (sidecar_dir / name).is_dir():
        return {"updated": False, "reason": "the session has no copy in the repository's data/"}
    if not valid:
        return {"updated": False, "reason": "the session did not validate; the repository copy is unchanged"}
    paths: list[str] = []
    old: list[tuple[Path, bytes | None]] = []
    for js in sidecars:
        dest = sidecar_dir / name / js.name
        try:
            old.append((dest, dest.read_bytes() if dest.is_file() else None))
            _atomic_copy(js, dest)
        except OSError as exc:
            back = []
            for d, data in old[: len(paths)]:  # the copies already replaced go back to what they were
                with contextlib.suppress(OSError):
                    if data is None:
                        d.unlink()
                    else:
                        _write_bytes_atomic(d, data)
                    back.append(d.name)
            undone = f"; {', '.join(back)} was put back" if back else ""
            return {
                "updated": False,
                "reason": f"copying {js.name} to {dest.parent} failed ({exc}){undone}; the data root is saved",
            }
        paths.append(str(dest))
    return {"updated": True, "path": paths[0], "paths": paths}


def _write_bytes_atomic(dest: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
