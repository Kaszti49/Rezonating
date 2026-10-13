"""Recording I/O: multichannel WAV (32-bit int PCM) and the JSON sidecar next to it (D-008, D-019, D-020).

Arrays are ``(n_frames, n_channels)`` ``int32`` *codes*, exactly what the node sends (24-bit ADC codes sign-extended
to 32 bits, 20-bit accelerometer codes right-justified). Nothing is scaled: a code written is the code read back.
Multiply by ``channels[ch].scale`` of the sidecar to get ``channels[ch].units``.

The sidecar schema (``schemas/sidecar.schema.json``, v0 and v1) is never hard-coded here: every function that
validates takes ``schema_path``, and :func:`find_schema` locates it from a directory inside a checkout.

Nothing in this module reads ``data/raw`` or ``data/private``; paths come from the caller.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_FILENAME = "sidecar.schema.json"
WAV_SUBTYPE = "PCM_32"
SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_[a-z0-9-]+_[a-z0-9-]+_\d{2}$")
STREAM_FILE_SUFFIX = {"adc_raw": "adc", "adc_dec": "adcdec", "accel": "accel"}
LABEL_TIME_TOL_S = 1e-6

__all__ = [
    "SCHEMA_FILENAME",
    "SESSION_RE",
    "WavInfo",
    "WavWriter",
    "check_pair",
    "find_schema",
    "format_rzlab_notes",
    "iter_wav_blocks",
    "load_schema",
    "load_sidecar",
    "parse_rzlab_notes",
    "read_wav",
    "save_sidecar",
    "set_wav_sample_rate",
    "validate_sidecar",
    "wav_info",
    "write_wav",
]


# --------------------------------------------------------------------------------------------------- schema


def find_schema(start: Path) -> Path:
    """Find ``schemas/sidecar.schema.json`` in ``start`` or one of its parents (a checkout of the repo).

    Raises ``FileNotFoundError`` when there is none; the caller then has to pass ``schema_path`` itself.
    """
    start = Path(start).resolve()
    for folder in (start, *start.parents):
        candidate = folder / "schemas" / SCHEMA_FILENAME
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"no schemas/{SCHEMA_FILENAME} in {start} or any parent folder")


def load_schema(schema_path: Path) -> dict[str, Any]:
    """Load a JSON Schema file and check that it is itself a valid schema."""
    with Path(schema_path).open(encoding="utf-8") as f:
        schema = json.load(f)
    Draft202012Validator.check_schema(schema)
    return schema


def _validator(schema_path: Path) -> Draft202012Validator:
    return Draft202012Validator(load_schema(schema_path), format_checker=FormatChecker())


# --------------------------------------------------------------------------------------------------- WAV


@dataclass(frozen=True)
class WavInfo:
    """What a WAV header says."""

    frames: int
    channels: int
    fs_hz: int
    subtype: str


def _as_frames(data: np.ndarray) -> np.ndarray:
    """Check ``(n_frames, n_channels)`` int32 and return it C-contiguous."""
    if not isinstance(data, np.ndarray) or data.dtype != np.int32:
        raise ValueError("WAV data must be a numpy int32 array of codes (n_frames, n_channels)")
    if data.ndim != 2 or data.shape[1] < 1:
        raise ValueError(f"WAV data must have shape (n_frames, n_channels), got {data.shape}")
    return np.ascontiguousarray(data)


def _check_rate(fs_hz: int) -> int:
    if isinstance(fs_hz, bool) or not isinstance(fs_hz, (int, np.integer)) or fs_hz < 1:
        raise ValueError(f"fs_hz must be a positive integer (the WAV header rate), got {fs_hz!r}")
    return int(fs_hz)


def write_wav(path: Path, data: np.ndarray, fs_hz: int) -> None:
    """Write ``data`` ``(n_frames, n_channels)`` int32 as a 32-bit PCM WAV with header rate ``fs_hz``.

    ``fs_hz`` is the integer written to the header: ``round(sample_rate_measured)`` for a v1 sidecar.
    """
    frames = _as_frames(data)
    with WavWriter(path, frames.shape[1], fs_hz) as w:
        w.write(frames)


def set_wav_sample_rate(path: Path, fs_hz: int) -> None:
    """Change the sample rate in the header of an existing WAV, in place, without touching the samples.

    A recorder only knows the measured rate (and so ``round(sample_rate_measured)``) when the session ends, long
    after the file was opened. The header holds the rate and the byte rate; both are rewritten.
    """
    fs_hz = _check_rate(fs_hz)
    with Path(path).open("r+b") as f:
        head = f.read(12)
        if len(head) < 12 or head[:4] not in (b"RIFF", b"RF64") or head[8:12] != b"WAVE":
            raise ValueError(f"{path}: not a RIFF/WAVE file")
        while True:
            chunk = f.read(8)
            if len(chunk) < 8:
                raise ValueError(f"{path}: no fmt chunk")
            cid, size = chunk[:4], int.from_bytes(chunk[4:], "little")
            if cid == b"fmt ":
                body = bytearray(f.read(16))
                block_align = int.from_bytes(body[12:14], "little")
                body[4:8] = fs_hz.to_bytes(4, "little")
                body[8:12] = (fs_hz * block_align).to_bytes(4, "little")
                f.seek(-16, 1)
                f.write(body)
                return
            f.seek(size + (size & 1), 1)  # chunks are padded to an even length


def wav_info(path: Path) -> WavInfo:
    """Read only the header."""
    info = sf.info(str(path))
    return WavInfo(
        frames=int(info.frames), channels=int(info.channels), fs_hz=int(info.samplerate), subtype=info.subtype
    )


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Read a 32-bit PCM WAV. Returns ``(codes, fs_hz)``: ``codes`` is ``(n_frames, n_channels)`` int32.

    Refuses any other sample format, so a float or 16-bit file is never silently rescaled.
    """
    info = wav_info(path)
    if info.subtype != WAV_SUBTYPE:
        raise ValueError(f"{path}: expected 32-bit integer PCM, found {info.subtype}")
    data, fs = sf.read(str(path), dtype="int32", always_2d=True)
    return data, int(fs)


def iter_wav_blocks(path: Path, block_frames: int = 65536) -> Iterator[np.ndarray]:
    """Yield the WAV as ``(<= block_frames, n_channels)`` int32 blocks, without loading the whole file."""
    if block_frames < 1:
        raise ValueError("block_frames must be at least 1")
    info = wav_info(path)
    if info.subtype != WAV_SUBTYPE:
        raise ValueError(f"{path}: expected 32-bit integer PCM, found {info.subtype}")
    with sf.SoundFile(str(path), mode="r") as f:
        while True:
            block = f.read(block_frames, dtype="int32", always_2d=True)
            if len(block) == 0:
                return
            yield block


class WavWriter:
    """Streaming WAV writer (32-bit int PCM). Use as a context manager; call :meth:`write` with int32 blocks.

    :meth:`flush` also updates the header, so a file of a crashed session still opens with the frames written so far.
    """

    def __init__(self, path: Path, n_channels: int, fs_hz: int) -> None:
        if n_channels < 1:
            raise ValueError("n_channels must be at least 1")
        self.path = Path(path)
        self.n_channels = int(n_channels)
        self.fs_hz = _check_rate(fs_hz)
        self.frames_written = 0
        self._f: sf.SoundFile | None = sf.SoundFile(
            str(self.path), mode="w", samplerate=self.fs_hz, channels=self.n_channels, format="WAV", subtype=WAV_SUBTYPE
        )

    def write(self, data: np.ndarray) -> None:
        """Append ``data`` ``(n_frames, n_channels)`` int32."""
        if self._f is None:
            raise ValueError("WavWriter is closed")
        frames = _as_frames(data)
        if frames.shape[1] != self.n_channels:
            raise ValueError(f"expected {self.n_channels} channels, got {frames.shape[1]}")
        if len(frames):
            self._f.write(frames)
            self.frames_written += len(frames)

    def write_zeros(self, n_frames: int) -> None:
        """Append ``n_frames`` frames of zeros (lost samples keep their place so time stays true)."""
        block = 1 << 16
        while n_frames > 0:
            n = min(block, n_frames)
            self.write(np.zeros((n, self.n_channels), dtype=np.int32))
            n_frames -= n

    def flush(self) -> None:
        if self._f is not None:
            self._f.flush()

    def close(self) -> None:
        if self._f is not None:
            self._f.close()
            self._f = None

    def __enter__(self) -> WavWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# --------------------------------------------------------------------------------------------------- sidecar


def load_sidecar(path: Path, schema_path: Path | None = None) -> dict[str, Any]:
    """Load a sidecar. With ``schema_path`` it is validated and ``ValueError`` lists every problem."""
    with Path(path).open(encoding="utf-8") as f:
        doc = json.load(f)
    if schema_path is not None:
        errors = validate_sidecar(doc, schema_path)
        if errors:
            raise ValueError(f"{path}: invalid sidecar: " + "; ".join(errors))
    return doc


def validate_sidecar(sidecar: dict[str, Any], schema_path: Path) -> list[str]:
    """Check a sidecar dict against the schema (v0 or v1). Returns one message per problem; empty = valid."""
    v = _validator(schema_path)
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
        for e in sorted(v.iter_errors(sidecar), key=lambda e: list(map(str, e.absolute_path)))
    ]


def save_sidecar(path: Path, sidecar: dict[str, Any], schema_path: Path) -> None:
    """Validate, then write ``sidecar`` as JSON (atomic: a temp file, then a rename). Refuses an invalid sidecar."""
    errors = validate_sidecar(sidecar, schema_path)
    if errors:
        raise ValueError("refusing to write an invalid sidecar: " + "; ".join(errors))
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(sidecar, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ----------------------------------------------------------------------- "rzlab: key=value; ..." notes


def parse_rzlab_notes(notes: str | None) -> dict[str, str]:
    """Values the lab keeps in the sidecar ``notes`` field because the schema has no field for them.

    Every line that starts with ``rzlab:`` holds ``key=value`` pairs separated by ``;``. Other text is ignored.
    """
    out: dict[str, str] = {}
    for line in (notes or "").splitlines():
        line = line.strip()
        if not line.startswith("rzlab:"):
            continue
        for part in line[len("rzlab:") :].split(";"):
            key, sep, value = part.partition("=")
            if sep and key.strip():
                out[key.strip()] = value.strip()
    return out


def format_rzlab_notes(values: dict[str, str]) -> str:
    """The inverse of :func:`parse_rzlab_notes`: ``rzlab: a=1; b=2`` (empty string for no values)."""
    clean = {k: str(v) for k, v in values.items() if str(v) != ""}
    for k, v in clean.items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", k) or any(c in v for c in ";\n\r"):
            raise ValueError(f"bad rzlab note {k!r}={v!r}: keys are [A-Za-z0-9_.-], values contain no ';' or newline")
    return "rzlab: " + "; ".join(f"{k}={v}" for k, v in clean.items()) if clean else ""


# ------------------------------------------------------------------------------------- WAV against sidecar


def check_pair(wav_path: Path, sidecar: dict[str, Any], schema_path: Path) -> list[str]:
    """Check one WAV against its (already loaded) sidecar. Returns problems; empty = consistent.

    Checks: schema validity; WAV is 32-bit integer PCM; channel count equals ``len(channels)``; header rate equals
    ``sample_rate``; v1 ``sample_rate == round(sample_rate_measured)``; ``rzlab: frames=N`` (when present) equals the
    frame count; every label has ``t0 <= t1``, ``t0 = i0 / sample_rate`` (v1) and ends inside the file; the
    sidecar name matches the WAV name.
    """
    problems = [f"sidecar: {m}" for m in validate_sidecar(sidecar, schema_path)]
    wav_path = Path(wav_path)
    try:
        info = wav_info(wav_path)
    except Exception as exc:  # noqa: BLE001 - soundfile raises LibsndfileError / RuntimeError
        return [*problems, f"wav: cannot read {wav_path.name}: {exc}"]
    if info.subtype != WAV_SUBTYPE:
        problems.append(f"wav: expected 32-bit integer PCM, found {info.subtype}")
    channels = sidecar.get("channels")
    if isinstance(channels, list) and info.channels != len(channels):
        problems.append(f"wav has {info.channels} channels, the sidecar lists {len(channels)}")
    rate = sidecar.get("sample_rate")
    if isinstance(rate, int) and info.fs_hz != rate:
        problems.append(f"wav header rate is {info.fs_hz} Hz, the sidecar says sample_rate {rate}")
    measured = sidecar.get("sample_rate_measured")
    if sidecar.get("schema") == 1 and isinstance(measured, (int, float)) and isinstance(rate, int):
        if rate != round(measured):
            problems.append(f"sample_rate {rate} is not round(sample_rate_measured {measured})")
    notes = parse_rzlab_notes(sidecar.get("notes"))
    if "frames" in notes:
        if not notes["frames"].isdigit():
            problems.append(f"notes: frames={notes['frames']!r} is not a number")
        elif int(notes["frames"]) != info.frames:
            problems.append(f"wav has {info.frames} frames, the sidecar notes say frames={notes['frames']}")
    fs = rate if isinstance(rate, int) and rate > 0 else info.fs_hz
    session = sidecar.get("session")
    if isinstance(session, str) and not wav_path.name.startswith(session + "."):
        problems.append(f"wav file name {wav_path.name} does not start with the sidecar session {session}")
    for n, lab in enumerate(sidecar.get("labels") or []):
        where = f"labels[{n}]"
        t0, t1 = lab.get("t0"), lab.get("t1")
        if isinstance(t0, (int, float)) and isinstance(t1, (int, float)) and t1 < t0:
            problems.append(f"{where}: t1 {t1} is before t0 {t0}")
        i0, i1 = lab.get("i0"), lab.get("i1")
        if isinstance(i0, int) and isinstance(i1, int):
            if i1 < i0:
                problems.append(f"{where}: i1 {i1} is before i0 {i0}")
            if i1 > info.frames:
                problems.append(f"{where}: ends at index {i1}, after the end of the file ({info.frames} frames)")
            for name, i, t in (("t0", i0, t0), ("t1", i1, t1)):
                if isinstance(t, (int, float)) and abs(t - i / fs) > LABEL_TIME_TOL_S:
                    problems.append(f"{where}: {name} {t} is not index {i} / sample_rate {fs}")
        elif isinstance(t1, (int, float)) and t1 * fs > info.frames + 1:
            problems.append(f"{where}: ends at {t1} s, after the end of the file ({info.frames / fs:.3f} s)")
    return problems
