"""Dataset manifest ``data/manifest.json``: one entry per recording file, with its SHA-256 (format v1).

The manifest says exactly which recordings a dataset is made of, so a result can name its data and anyone can check
that their copy of the WAVs is the same. It is built from the sidecars in the repository (``data/<session>/*.json``,
in git) and the WAVs on the data root (the shared recordings drive, never in git, D-017):

    <data_root>/<session>/<session>.adc.wav      adc_raw stream (D-019, D-020)
    <data_root>/<session>/<session>.accel.wav    ADXL355 stream
    data/<session>/<session>.adc.json            validated sidecar copied by the lab
    data/<session>/<session>.accel.json

Format v1 (a JSON object; :data:`MANIFEST_SCHEMA` is the authority, :func:`validate_manifest` checks it)::

    {
      "format": "rezonating-manifest",
      "version": 1,
      "created": "2026-11-17T10:00:00Z",
      "data_root": "Paths in 'wav' are relative to the data root ...",   (fixed text, never a path)
      "entries": [
        {
          "session": "2026-11-17_lab_bench_01",
          "stream": "adc_raw",                                 (adc_raw | adc_dec | accel | null for v0)
          "wav": "2026-11-17_lab_bench_01/2026-11-17_lab_bench_01.adc.wav",    (relative to the data root)
          "sidecar": "data/2026-11-17_lab_bench_01/2026-11-17_lab_bench_01.adc.json",   (relative to the repo)
          "wav_present": true,
          "sha256": "9f2c...64 hex", "size_bytes": 2419244,    (null when the WAV was missing)
          "frames": 604800, "channels": 2,
          "fs_header_hz": 2016, "fs_measured_hz": 2016.13,     (measured: v1 only, else null)
          "duration_s": 299.980656,                            (frames / measured rate, else / header rate)
          "start_utc": "2026-11-17T09:14:02.000Z",
          "protocol": "walk-pass-v1",
          "floor": "2",                                        (sidecar notes "rzlab: floor=...")
          "surface": ["laminate on concrete slab"],            (channels[].surface, unique, sorted)
          "people": ["P2", "P10"],                             (pseudonyms from labels and "rzlab: persons=")
          "label_count": 14,
          "loss": {"device": 0, "link": 0, "host": 0},         (v1 only, else null)
          "simulated": false, "incomplete": false,             ("rzlab: source=sim", "rzlab: loss=incomplete")
          "valid": true, "errors": []
        }
      ],
      "unmatched_wavs": ["2026-11-19_lab_bench_03/2026-11-19_lab_bench_03.adc.wav"]
    }

Rules the code enforces:

- No absolute path is ever stored. ``wav`` and ``unmatched_wavs`` are ``<session>/<file>.wav`` relative to the data
  root; ``sidecar`` is ``[<prefix>/]<session>/<file>.json`` relative to the repository; ``/`` only. A drive letter,
  a leading ``/`` or ``\\``, a backslash, ``..`` or a WAV outside a session folder is refused, and an entry's
  ``wav`` and ``sidecar`` must belong to its own ``session``. So :func:`verify_manifest` only opens session folders.
- Sidecars are ``<session>.json`` (v0) or ``<session>.<adc|adcdec|accel>.json``; any other ``.json`` is ignored.
- ``valid`` is true only when the WAV is present, the sidecar meets its schema and
  :func:`rezonating_ml.io.check_pair` finds nothing; ``errors`` says why not. A sidecar that cannot be read, or one
  so malformed that ``check_pair`` raises (a label that is not an object, a NaN rate), still gets an entry, marked
  invalid; one bad sidecar never stops the build.
- ``errors`` never repeats a string from the sidecar (a name, the session text, notes, field names): schema problems
  are worded from the schema side, and ``check_pair`` lines are kept only when their variable parts are numbers,
  otherwise replaced by a fixed text. Absolute root paths are removed from any message.
- People are pseudonyms only (``P<n>``). A value that is not one is left out and reported without its text.
  ``protocol``, ``floor`` and ``surface`` are sidecar strings, copied by design; ``start_utc`` only when it is a
  valid date-time; ``fs_measured_hz`` only when finite and positive.
- Entries are sorted by ``wav``; :func:`write_manifest` writes keys in a fixed order, two-space indent, UTF-8, LF and
  a final newline, so the same content always gives the same bytes. ``created`` is the only field that changes
  between two builds of the same files (pass ``created=`` to pin it).
- ``unmatched_wavs``: WAVs in session folders on the data root with no sidecar in the repository (an invalid or
  simulated session the lab did not copy, or a sidecar not yet committed).

Only folders named like a session (``YYYY-MM-DD_site_room_nn``) are looked into, on both roots, so ``data/raw`` and
``data/private`` are never opened. Paths come from the caller. Command line::

    python -m rezonating_ml.manifest build --data-root D:/rezonating-recordings [--sidecars data] [--out FILE]
    python -m rezonating_ml.manifest verify data/manifest.json --data-root D:/rezonating-recordings

``--data-root`` defaults to the ``RZ_DATA_ROOT`` environment variable (the same one the lab uses).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from . import io

MANIFEST_FORMAT = "rezonating-manifest"
MANIFEST_VERSION = 1
DATA_ROOT_NOTE = (
    "Paths in 'wav' are relative to the data root: the shared recordings drive, which each machine sets for "
    "itself (RZ_DATA_ROOT). Paths in 'sidecar' are relative to the repository. No absolute path is stored."
)
DEFAULT_SIDECAR_PREFIX = "data"
PSEUDONYM_RE = re.compile(r"^P\d+$")
HASH_BLOCK_BYTES = 1 << 20
MAX_ERROR_CHARS = 300

TOP_KEYS = ("format", "version", "created", "data_root", "entries", "unmatched_wavs")
ENTRY_KEYS = (
    "session",
    "stream",
    "wav",
    "sidecar",
    "wav_present",
    "sha256",
    "size_bytes",
    "frames",
    "channels",
    "fs_header_hz",
    "fs_measured_hz",
    "duration_s",
    "start_utc",
    "protocol",
    "floor",
    "surface",
    "people",
    "label_count",
    "loss",
    "simulated",
    "incomplete",
    "valid",
    "errors",
)
LOSS_KEYS = ("device", "link", "host")
STREAMS = tuple(io.STREAM_FILE_SUFFIX)
_STREAM_BY_SUFFIX = {suffix: stream for stream, suffix in io.STREAM_FILE_SUFFIX.items()}

# Paths are '/'-separated and relative. A WAV is always <session>/<file>.wav (so verify only opens session folders
# on the data root, never raw/ or private/); a sidecar is [<prefix>/]<session>/<file>.json. The prefix segments
# have no drive letter (no ':'), no backslash, and no '..' segment.
_SESSION = io.SESSION_RE.pattern.removeprefix("^").removesuffix("$")
_FILE = r"[^/\\:]+"
_WAV_PATH = rf"^{_SESSION}/{_FILE}\.wav$"
_SIDECAR_PATH = rf"^(?!(?:.*/)?\.\.(?:/|$))(?:[A-Za-z0-9_.-]+/)*{_SESSION}/{_FILE}\.json$"

__all__ = [
    "DATA_ROOT_NOTE",
    "ENTRY_KEYS",
    "MANIFEST_FORMAT",
    "MANIFEST_SCHEMA",
    "MANIFEST_VERSION",
    "TOP_KEYS",
    "VerifyReport",
    "build_manifest",
    "main",
    "read_manifest",
    "sha256_file",
    "validate_manifest",
    "verify_manifest",
    "write_manifest",
]


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


_ENTRY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(ENTRY_KEYS),
    "properties": {
        "session": {"type": "string", "pattern": io.SESSION_RE.pattern},
        "stream": {"enum": [*STREAMS, None]},
        "wav": {"type": "string", "pattern": _WAV_PATH},
        "sidecar": {"type": "string", "pattern": _SIDECAR_PATH},
        "wav_present": {"type": "boolean"},
        "sha256": _nullable({"type": "string", "pattern": "^[0-9a-f]{64}$"}),
        "size_bytes": _nullable({"type": "integer", "minimum": 0}),
        "frames": _nullable({"type": "integer", "minimum": 0}),
        "channels": _nullable({"type": "integer", "minimum": 1}),
        "fs_header_hz": _nullable({"type": "integer", "minimum": 1}),
        "fs_measured_hz": _nullable({"type": "number", "exclusiveMinimum": 0}),
        "duration_s": _nullable({"type": "number", "minimum": 0}),
        "start_utc": _nullable({"type": "string"}),
        "protocol": _nullable({"type": "string"}),
        "floor": _nullable({"type": "string"}),
        "surface": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "people": {"type": "array", "items": {"type": "string", "pattern": PSEUDONYM_RE.pattern}, "uniqueItems": True},
        "label_count": {"type": "integer", "minimum": 0},
        "loss": _nullable(
            {
                "type": "object",
                "additionalProperties": False,
                "required": list(LOSS_KEYS),
                "properties": {k: {"type": "integer", "minimum": 0} for k in LOSS_KEYS},
            }
        ),
        "simulated": {"type": "boolean"},
        "incomplete": {"type": "boolean"},
        "valid": {"type": "boolean"},
        "errors": {"type": "array", "items": {"type": "string"}},
    },
    "allOf": [
        {
            "if": {"properties": {"wav_present": {"const": True}}},
            "then": {"properties": {"sha256": {"type": "string"}, "size_bytes": {"type": "integer"}}},
            "else": {"properties": {"sha256": {"type": "null"}, "size_bytes": {"type": "null"}}},
        },
        {
            "if": {"properties": {"valid": {"const": True}}},
            "then": {"properties": {"wav_present": {"const": True}, "errors": {"maxItems": 0}}},
            "else": {"properties": {"errors": {"minItems": 1}}},
        },
    ],
}

MANIFEST_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:rezonating:manifest:v1",
    "title": "Rezonating dataset manifest (data/manifest.json)",
    "type": "object",
    "additionalProperties": False,
    "required": list(TOP_KEYS),
    "properties": {
        "format": {"const": MANIFEST_FORMAT},
        "version": {"const": MANIFEST_VERSION},
        "created": {"type": "string", "format": "date-time"},
        "data_root": {"const": DATA_ROOT_NOTE},
        "entries": {"type": "array", "items": _ENTRY_SCHEMA},
        "unmatched_wavs": {
            "type": "array",
            "items": {"type": "string", "pattern": _WAV_PATH},
            "uniqueItems": True,
        },
    },
}
Draft202012Validator.check_schema(MANIFEST_SCHEMA)
_FORMATS = FormatChecker()
_MANIFEST_VALIDATOR = Draft202012Validator(MANIFEST_SCHEMA, format_checker=_FORMATS)


# --------------------------------------------------------------------------------------------------- helpers


def _int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value != "" else None


def sha256_file(path: Path, block_bytes: int = HASH_BLOCK_BYTES) -> str:
    """SHA-256 of a file's bytes as 64 lowercase hex digits, read in blocks (a WAV is never loaded whole)."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while chunk := f.read(block_bytes):
            h.update(chunk)
    return h.hexdigest()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _session_dirs(root: Path, keep: Callable[[str], bool]) -> list[Path]:
    """Folders of ``root`` named like a session, sorted by name. Nothing else (``raw/``, ``private/``) is opened."""
    return sorted(
        (d for d in root.iterdir() if d.is_dir() and io.SESSION_RE.fullmatch(d.name) and keep(d.name)),
        key=lambda d: d.name,
    )


def _scrubber(roots: Iterable[Path]) -> Callable[[str], str]:
    """Remove the machine's root folders from a message (an exception text can carry an absolute path)."""
    needles: set[str] = set()
    for root in roots:
        for p in (Path(root), Path(root).resolve()):
            needles.update({str(p), str(p).replace("\\", "/"), p.as_posix()})
    ordered = sorted((n for n in needles if n not in ("", ".", "/")), key=len, reverse=True)

    def scrub(msg: str) -> str:
        for n in ordered:
            msg = msg.replace(n, "<root>")
        return msg if len(msg) <= MAX_ERROR_CHARS else msg[: MAX_ERROR_CHARS - 3] + "..."

    return scrub


def _schema_errors(doc: Any, validator: Draft202012Validator) -> list[str]:
    """Sidecar schema problems, worded from the schema side only: no sidecar value or key (a name, notes) is
    repeated. The path holds schema property names and list indices, never a free key of the sidecar."""
    out: list[str] = []
    for e in sorted(validator.iter_errors(doc), key=lambda e: (list(map(str, e.absolute_path)), str(e.validator))):
        where = "/".join(map(str, e.absolute_path)) or "(root)"
        kw, rule = str(e.validator), e.validator_value
        if where.endswith("person") or where.endswith("persons"):
            msg = "not a pseudonym P1, P2, ... (the value is not copied here)"
        elif kw == "required":
            missing = sorted(set(rule) - set(e.instance)) if isinstance(e.instance, dict) else list(rule)
            msg = "missing " + ", ".join(map(str, missing))  # names from the schema's own list
        elif kw == "additionalProperties":
            msg = "has fields the sidecar schema does not allow (their names are not copied here)"
        elif kw == "type":
            msg = f"must be of type {rule}"
        elif kw == "enum":
            msg = f"must be one of {rule}"
        elif kw == "const":
            msg = f"must be {rule!r}"
        elif kw == "pattern":
            msg = f"must match {rule}"
        elif kw == "format":
            msg = f"must be a {rule}"
        elif kw in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minItems", "maxItems"):
            msg = f"fails {kw} {rule}"
        else:  # not / anyOf / if-then / ...: the stock message repeats the whole instance
            msg = f"breaks a '{kw}' rule of the sidecar schema (v0 may not carry v1 fields; v1 needs them)"
        out.append(f"sidecar: {where}: {msg}")
    return out


_NUM = r"-?(?:\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|nan|inf)"
# io.check_pair lines whose only variable parts are numbers are kept as they are; every other line is replaced by a
# fixed text, so a sidecar string (session, notes) never reaches the manifest. Order matters: first match wins.
_PAIR_MESSAGES: tuple[tuple[re.Pattern[str], str | None], ...] = tuple(
    (re.compile(p), fixed)
    for p, fixed in (
        (r"wav has \d+ channels, the sidecar lists \d+", None),
        (r"wav header rate is \d+ Hz, the sidecar says sample_rate \d+", None),
        (rf"sample_rate \d+ is not round\(sample_rate_measured {_NUM}\)", None),
        (r"wav has \d+ frames, the sidecar notes say frames=\d+", None),
        (rf"labels\[\d+\]: t1 {_NUM} is before t0 {_NUM}", None),
        (r"labels\[\d+\]: i1 \d+ is before i0 \d+", None),
        (r"labels\[\d+\]: ends at index \d+, after the end of the file \(\d+ frames\)", None),
        (rf"labels\[\d+\]: t[01] {_NUM} is not index \d+ / sample_rate \d+", None),
        (rf"labels\[\d+\]: ends at {_NUM} s, after the end of the file \({_NUM} s\)", None),
        (r"wav: cannot read .*", "wav: the file cannot be read as audio"),
        (r"wav: expected 32-bit integer PCM, found .*", "wav: not 32-bit integer PCM"),
        (r"notes: frames=.* is not a number", "notes: rzlab frames= is not a number"),
        (r"wav file name .* does not start with the sidecar session .*", "wav: file name does not match `session`"),
    )
)
_PAIR_OTHER = "pair: the sidecar and the WAV disagree (details withheld; run rezonating_ml.io.check_pair)"


def _pair_errors(wav_path: Path, doc: dict[str, Any], schema_path: Path) -> list[str]:
    """``io.check_pair`` without its schema lines (see :func:`_schema_errors`), reworded where it quotes the sidecar.

    A sidecar that breaks the schema can make ``check_pair`` raise (a label that is not an object, a NaN rate);
    that becomes one error line instead of stopping the whole build."""
    try:
        raw = io.check_pair(wav_path, doc, schema_path)
    except Exception as exc:  # noqa: BLE001 - any malformed sidecar value; the entry is marked invalid
        return [f"pair: the check stopped on a malformed sidecar ({exc.__class__.__name__})"]
    out: list[str] = []
    for m in raw:
        if m.startswith("sidecar: "):
            continue
        fixed = next((f for rx, f in _PAIR_MESSAGES if rx.fullmatch(m)), _PAIR_OTHER)
        out.append(m if fixed is None else fixed)
    return list(dict.fromkeys(out))  # unique, order kept


def _people(doc: dict[str, Any], notes: dict[str, str]) -> tuple[list[str], bool]:
    """Pseudonyms from labels and ``rzlab: persons=``, unique, in number order. Also: was any value not one?"""
    found: set[str] = set()
    bad = False
    labels = doc.get("labels") if isinstance(doc.get("labels"), list) else []
    values: list[Any] = [lab.get("person") for lab in labels if isinstance(lab, dict) and "person" in lab]
    values += [p.strip() for p in notes.get("persons", "").split(",") if p.strip()]
    for v in values:
        if isinstance(v, str) and PSEUDONYM_RE.fullmatch(v):
            found.add(v)
        else:
            bad = True
    return sorted(found, key=lambda p: int(p[1:])), bad


def _loss(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    counts = {k: _int(value.get(k)) for k in LOSS_KEYS}
    if any(v is None or v < 0 for v in counts.values()):
        return None
    return {k: int(v) for k, v in counts.items() if v is not None}


def _sidecar_names(session: str) -> set[str]:
    """The sidecar file names a session folder may hold: ``<session>.json`` (v0) and ``<session>.<suffix>.json``
    for each stream (``adc``, ``adcdec``, ``accel``). Any other ``.json`` there is not a recording's sidecar."""
    return {f"{session}.json"} | {f"{session}.{suffix}.json" for suffix in io.STREAM_FILE_SUFFIX.values()}


def _rel(*parts: str) -> str:
    return "/".join(p.strip("/") for p in parts if p.strip("/"))


# --------------------------------------------------------------------------------------------------- build


def _entry(
    session: str,
    sidecar_path: Path,
    data_root: Path,
    sidecar_prefix: str,
    schema_path: Path,
    validator: Draft202012Validator,
    scrub: Callable[[str], str],
    hash_wavs: bool = True,
) -> dict[str, Any]:
    stem = sidecar_path.name[: -len(".json")]
    wav_rel = _rel(session, f"{stem}.wav")
    wav_path = data_root / session / f"{stem}.wav"
    errors: list[str] = []

    doc: dict[str, Any] | None = None
    try:
        loaded = io.load_sidecar(sidecar_path)
        if isinstance(loaded, dict):
            doc = loaded
        else:
            errors.append("sidecar: cannot read: not a JSON object")
    except json.JSONDecodeError as exc:
        errors.append(f"sidecar: cannot read: {exc.msg} (line {exc.lineno})")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"sidecar: cannot read: {exc.__class__.__name__}")
    d: dict[str, Any] = doc or {}
    notes = io.parse_rzlab_notes(d.get("notes")) if isinstance(d.get("notes"), str) else {}

    wav_present = wav_path.is_file()
    sha = size = info = None
    if wav_present:
        if hash_wavs:
            size = wav_path.stat().st_size
            sha = sha256_file(wav_path)
        try:
            info = io.wav_info(wav_path)
        except Exception:  # noqa: BLE001 - soundfile raises LibsndfileError / RuntimeError; check_pair reports it
            info = None
    else:
        errors.append("wav: missing on the data root")

    if doc is not None:
        errors += _schema_errors(doc, validator)
        if wav_present:
            errors += _pair_errors(wav_path, doc, schema_path)

    stream = d.get("stream") if d.get("stream") in STREAMS else None
    if stream is None and stem != session:
        stream = _STREAM_BY_SUFFIX.get(stem[len(session) + 1 :]) if stem.startswith(session + ".") else None

    channels = len(d["channels"]) if isinstance(d.get("channels"), list) and d["channels"] else None
    if channels is None and info is not None:
        channels = info.channels
    fs_header = info.fs_hz if info is not None else _int(d.get("sample_rate"))
    if fs_header is not None and fs_header < 1:
        fs_header = None
    fs_measured = _number(d.get("sample_rate_measured")) if d.get("schema") == 1 else None
    if fs_measured is not None and not (math.isfinite(fs_measured) and fs_measured > 0):
        fs_measured = None  # NaN / inf / <= 0 (Python's json reads NaN and Infinity)
    frames = info.frames if info is not None else None
    if frames is None and re.fullmatch(r"[0-9]+", notes.get("frames", "")):
        frames = int(notes["frames"])
    fs_for_time = fs_measured or fs_header
    duration = round(frames / fs_for_time, 6) if frames is not None and fs_for_time else None

    people, bad_person = _people(d, notes)
    if bad_person:  # the schema checks labels[].person only; notes "persons=" are checked here
        errors.append("people: a person in the labels or notes is not a pseudonym P1, P2, ... (not copied here)")

    chans = d.get("channels") if isinstance(d.get("channels"), list) else []
    surfaces = {ch["surface"] for ch in chans if isinstance(ch, dict) and isinstance(ch.get("surface"), str)}
    start_utc = _str(d.get("start_utc"))
    if start_utc is not None and not _FORMATS.conforms(start_utc, "date-time"):
        start_utc = None
    labels = d.get("labels")
    errors = [scrub(m) for m in errors]
    return {
        "session": session,
        "stream": stream,
        "wav": wav_rel,
        "sidecar": _rel(sidecar_prefix, session, sidecar_path.name),
        "wav_present": wav_present,
        "sha256": sha,
        "size_bytes": size,
        "frames": frames,
        "channels": channels,
        "fs_header_hz": fs_header,
        "fs_measured_hz": fs_measured,
        "duration_s": duration,
        "start_utc": start_utc,
        "protocol": _str(d.get("protocol")),
        "floor": _str(notes.get("floor")),
        "surface": sorted(surfaces),
        "people": people,
        "label_count": len(labels) if isinstance(labels, list) else 0,
        "loss": _loss(d.get("loss")) if d.get("schema") == 1 else None,
        "simulated": notes.get("source") == "sim",
        "incomplete": notes.get("loss") == "incomplete",
        "valid": wav_present and doc is not None and not errors,
        "errors": errors,
    }


def build_manifest(
    data_root: Path,
    sidecar_root: Path,
    select: Iterable[str] | Callable[[str], bool] | None = None,
    *,
    schema_path: Path | None = None,
    created: str | None = None,
    sidecar_prefix: str = DEFAULT_SIDECAR_PREFIX,
    hash_wavs: bool = True,
) -> dict[str, Any]:
    """Build the manifest of every sidecar under ``sidecar_root/<session>/`` and its WAV on ``data_root``.

    ``data_root``: the recordings drive (``<data_root>/<session>/<stem>.wav``). ``sidecar_root``: the repository's
    ``data/`` folder; ``sidecar_prefix`` is how that folder is written in ``sidecar`` paths (``data``).
    ``select``: ``None`` for every session, session names, or a predicate on the session name. A named session that
    exists on neither root raises ``ValueError``. ``schema_path``: the sidecar schema; by default it is searched
    from ``sidecar_root``, then from the working directory. ``created``: ISO time (default: now, UTC).

    Hashes every WAV (about 58 MB per hour of 2-channel ADC). ``hash_wavs=False`` reads WAV headers only (for an
    index that must not read whole recordings): ``sha256`` and ``size_bytes`` then stay ``null`` for every entry,
    ``valid`` and ``errors`` are exactly as with hashing, and :func:`write_manifest` refuses the result while any
    WAV is present (the format requires a hash for a present WAV). Raises ``NotADirectoryError`` for a missing root.
    """
    data_root, sidecar_root = Path(data_root), Path(sidecar_root)
    for name, root in (("data_root", data_root), ("sidecar_root", sidecar_root)):
        if not root.is_dir():
            raise NotADirectoryError(f"{name} {root} is not a folder")
    if re.match(r"^(?:[A-Za-z]:|[/\\])", sidecar_prefix) or ".." in sidecar_prefix.replace("\\", "/").split("/"):
        raise ValueError(f"sidecar_prefix must be a relative path inside the repository, got {sidecar_prefix!r}")
    if schema_path is None:
        try:
            schema_path = io.find_schema(sidecar_root)
        except FileNotFoundError:
            schema_path = io.find_schema(Path.cwd())
    validator = Draft202012Validator(io.load_schema(schema_path), format_checker=FormatChecker())

    named: set[str] | None = None
    if select is None:
        keep: Callable[[str], bool] = lambda _s: True  # noqa: E731
    elif callable(select):
        keep = select
    else:
        named = {select} if isinstance(select, str) else set(select)
        keep = named.__contains__

    scrub = _scrubber([data_root, sidecar_root])
    sidecar_sessions = _session_dirs(sidecar_root, keep)
    drive_sessions = _session_dirs(data_root, keep)
    if named is not None:
        unknown = sorted(named - {d.name for d in sidecar_sessions} - {d.name for d in drive_sessions})
        if unknown:
            raise ValueError("selected sessions found on neither root: " + ", ".join(unknown))

    entries = [
        _entry(folder.name, sidecar, data_root, sidecar_prefix, schema_path, validator, scrub, hash_wavs)
        for folder in sidecar_sessions
        for sidecar in sorted(folder.glob("*.json"), key=lambda p: p.name)
        if sidecar.name in _sidecar_names(folder.name) and sidecar.is_file()
    ]
    referenced = {e["wav"] for e in entries}
    unmatched = sorted(
        rel
        for folder in drive_sessions
        for wav in folder.glob("*.wav")
        if wav.is_file() and (rel := _rel(folder.name, wav.name)) not in referenced
    )
    return {
        "format": MANIFEST_FORMAT,
        "version": MANIFEST_VERSION,
        "created": created or _now_utc(),
        "data_root": DATA_ROOT_NOTE,
        "entries": sorted(entries, key=lambda e: e["wav"]),
        "unmatched_wavs": unmatched,
    }


# ------------------------------------------------------------------------------------------- write / read


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Problems with a manifest dict. Empty list = valid.

    Schema v1, plus: no WAV is listed twice, and each entry's ``wav`` is ``<session>/<session>.<...>.wav`` and its
    ``sidecar`` ends in ``<session>/<same stem>.json`` (so an entry can only point into its own session folder).
    """
    problems = [
        f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
        for e in sorted(_MANIFEST_VALIDATOR.iter_errors(manifest), key=lambda e: list(map(str, e.absolute_path)))
    ]
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if isinstance(entries, list):
        seen: set[str] = set()
        for n, e in enumerate(entries):
            if not isinstance(e, dict):
                continue
            wav, session, sidecar = e.get("wav"), e.get("session"), e.get("sidecar")
            if isinstance(wav, str):
                if wav in seen:
                    problems.append(f"entries/{n}/wav: {wav} is listed twice")
                seen.add(wav)
            if isinstance(wav, str) and isinstance(session, str):
                if not wav.startswith(f"{session}/{session}.") or not wav.endswith(".wav"):
                    problems.append(f"entries/{n}/wav: {wav} is not {session}/{session}.<stream>.wav")
                elif isinstance(sidecar, str):
                    stem = wav[len(session) + 1 : -len(".wav")]
                    if sidecar != f"{session}/{stem}.json" and not sidecar.endswith(f"/{session}/{stem}.json"):
                        problems.append(f"entries/{n}/sidecar: {sidecar} is not the sidecar of {wav}")
    return problems


def _ordered(manifest: dict[str, Any]) -> dict[str, Any]:
    """The same content with keys in the fixed order and entries sorted by ``wav``."""
    out = {k: manifest[k] for k in TOP_KEYS}
    out["entries"] = [
        {k: ({x: e[k][x] for x in LOSS_KEYS} if k == "loss" and e[k] is not None else e[k]) for k in ENTRY_KEYS}
        for e in sorted(manifest["entries"], key=lambda e: e["wav"])
    ]
    out["unmatched_wavs"] = sorted(manifest["unmatched_wavs"])
    return out


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Validate, then write deterministically (fixed key order, sorted entries, 2-space indent, LF, UTF-8, final
    newline) and atomically (a temp file, then a rename). Refuses an invalid manifest with ``ValueError``."""
    problems = validate_manifest(manifest)
    if problems:
        raise ValueError("refusing to write an invalid manifest: " + "; ".join(problems))
    text = json.dumps(_ordered(manifest), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_manifest(path: Path) -> dict[str, Any]:
    """Load and validate a manifest. ``ValueError`` lists every problem."""
    with Path(path).open(encoding="utf-8") as f:
        manifest = json.load(f)
    problems = validate_manifest(manifest)
    if problems:
        raise ValueError(f"{Path(path).name}: invalid manifest: " + "; ".join(problems))
    return manifest


# --------------------------------------------------------------------------------------------------- verify


@dataclass(frozen=True)
class VerifyReport:
    """What :func:`verify_manifest` found. Lists hold ``wav`` paths relative to the data root.

    ``changed`` items are ``{wav, expected_sha256, found_sha256, expected_size, found_size}``. ``not_hashed``: the
    WAV was missing when the manifest was built (no ``sha256``), so its content cannot be confirmed; rebuild.
    """

    checked: int
    ok: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    not_hashed: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not (self.missing or self.changed or self.not_hashed)


def verify_manifest(manifest: dict[str, Any], data_root: Path) -> VerifyReport:
    """Check every WAV of the manifest on ``data_root``: present, same size, same SHA-256.

    The size is compared first; the hash is computed for every present file anyway, so a same-size edit is found.
    Raises ``ValueError`` for an invalid manifest and ``NotADirectoryError`` for a missing ``data_root``.
    """
    problems = validate_manifest(manifest)
    if problems:
        raise ValueError("invalid manifest: " + "; ".join(problems))
    data_root = Path(data_root)
    if not data_root.is_dir():
        raise NotADirectoryError(f"data_root {data_root} is not a folder")
    report = VerifyReport(checked=len(manifest["entries"]))
    for e in sorted(manifest["entries"], key=lambda e: e["wav"]):
        wav = data_root.joinpath(*e["wav"].split("/"))
        if not wav.is_file():
            report.missing.append(e["wav"])
            continue
        if e["sha256"] is None:
            report.not_hashed.append(e["wav"])
            continue
        size, sha = wav.stat().st_size, sha256_file(wav)
        if size != e["size_bytes"] or sha != e["sha256"]:
            report.changed.append(
                {
                    "wav": e["wav"],
                    "expected_sha256": e["sha256"],
                    "found_sha256": sha,
                    "expected_size": e["size_bytes"],
                    "found_size": size,
                }
            )
        else:
            report.ok.append(e["wav"])
    return report


# ------------------------------------------------------------------------------------------------------ CLI


def _data_root_arg(value: str | None) -> Path:
    value = value or os.environ.get("RZ_DATA_ROOT")
    if not value:
        raise SystemExit("error: give --data-root or set RZ_DATA_ROOT (the shared recordings drive)")
    return Path(value)


def main(argv: list[str] | None = None) -> int:
    """``build``: exit 0 (1 with ``--strict`` when an entry is invalid). ``verify``: exit 0 only if it passed."""
    parser = argparse.ArgumentParser(prog="python -m rezonating_ml.manifest", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build data/manifest.json from the repo sidecars and the WAVs")
    b.add_argument("--data-root", help="recordings drive (default: $RZ_DATA_ROOT)")
    b.add_argument("--sidecars", default=DEFAULT_SIDECAR_PREFIX, help="the repo's data/ folder (default: data)")
    b.add_argument("--out", help="output file (default: <sidecars>/manifest.json)")
    b.add_argument("--session", action="append", help="only this session (repeatable)")
    b.add_argument("--schema", help="sidecar schema (default: found from --sidecars or the working directory)")
    b.add_argument("--strict", action="store_true", help="exit 1 when any entry is invalid")
    v = sub.add_parser("verify", help="check the WAVs on the data root against a manifest")
    v.add_argument("manifest", nargs="?", default=f"{DEFAULT_SIDECAR_PREFIX}/manifest.json")
    v.add_argument("--data-root", help="recordings drive (default: $RZ_DATA_ROOT)")
    args = parser.parse_args(argv)

    if args.cmd == "build":
        sidecars = Path(args.sidecars)
        out = Path(args.out) if args.out else sidecars / "manifest.json"
        m = build_manifest(
            _data_root_arg(args.data_root),
            sidecars,
            select=args.session,
            schema_path=Path(args.schema) if args.schema else None,
        )
        write_manifest(out, m)
        entries = m["entries"]
        n_valid = sum(e["valid"] for e in entries)
        n_missing = sum(not e["wav_present"] for e in entries)
        print(
            f"wrote {out}: {len(entries)} entries, {n_valid} valid, {n_missing} WAV missing, "
            f"{len(m['unmatched_wavs'])} WAV without a sidecar"
        )
        for e in entries:
            if not e["valid"]:
                print(f"  invalid {e['wav']}: " + "; ".join(e["errors"]))
        return 1 if args.strict and n_valid < len(entries) else 0

    report = verify_manifest(read_manifest(Path(args.manifest)), _data_root_arg(args.data_root))
    for wav in report.missing:
        print(f"missing     {wav}")
    for c in report.changed:
        print(f"changed     {c['wav']}: size {c['expected_size']} -> {c['found_size']}, sha256 differs")
    for wav in report.not_hashed:
        print(f"not hashed  {wav} (missing when the manifest was built; rebuild it)")
    print(
        f"{'PASS' if report.passed else 'FAIL'}: {len(report.ok)}/{report.checked} WAVs match, "
        f"{len(report.missing)} missing, {len(report.changed)} changed, {len(report.not_hashed)} not hashed"
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
