"""``rzlab validate <data root>``: check every session folder of a data root.

For each ``<root>/<session>/`` folder:

* the folder name matches ``YYYY-MM-DD_<site>_<room>_<nn>``;
* it holds ``<session>.adc.wav|json`` and/or ``<session>.accel.wav|json``, each WAV with its sidecar and each sidecar
  with its WAV, and nothing else that could be a recording (stray ``.wav`` / ``.json`` files are failures);
* every sidecar is valid against ``schemas/sidecar.schema.json`` and says the session and stream its file name says;
* the WAV header agrees with the sidecar (channels, rate, frame count where the sidecar notes it) and every label lies
  inside the file (``rezonating_ml.io.check_pair``);
* the streams of a session agree on the node, the protocol and the session name.

An empty folder is only a warning: it is a reservation that no recording ever used. ``sidecars_only`` checks a folder
of sidecars without WAV files (the repository's ``data/``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rezonating_ml import io

STREAM_BY_SUFFIX = {"adc": "adc_raw", "accel": "accel"}  # D-020: adc_dec is not recorded


@dataclass
class SessionReport:
    name: str
    path: Path
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    streams: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def validate_session_folder(folder: Path, schema_path: Path, sidecars_only: bool = False) -> SessionReport:
    name = folder.name
    rep = SessionReport(name, folder)
    if not io.SESSION_RE.match(name):
        rep.problems.append("folder name is not YYYY-MM-DD_<site>_<room>_<nn> (lower-case letters, digits, dashes)")
    files = sorted(p for p in folder.iterdir())
    if not files:
        rep.warnings.append("empty folder (a reserved session name that no recording used)")
        return rep
    expected: set[str] = set()
    docs: dict[str, dict] = {}
    for suffix, stream in STREAM_BY_SUFFIX.items():
        wav, js = folder / f"{name}.{suffix}.wav", folder / f"{name}.{suffix}.json"
        has_wav, has_js = wav.is_file(), js.is_file()
        if not has_wav and not has_js:
            continue
        expected.update({wav.name, js.name})
        rep.streams.append(stream)
        if not has_js:
            rep.problems.append(f"{wav.name}: no sidecar {js.name}")
            continue
        if not has_wav and not sidecars_only:
            rep.problems.append(f"{js.name}: no recording {wav.name}")
        try:
            doc = io.load_sidecar(js)
        except (OSError, ValueError) as exc:
            rep.problems.append(f"{js.name}: cannot read: {exc}")
            continue
        docs[stream] = doc
        if sidecars_only or not has_wav:
            problems = [f"sidecar: {m}" for m in io.validate_sidecar(doc, schema_path)]
        else:
            problems = io.check_pair(wav, doc, schema_path)
        rep.problems += [f"{js.name}: {m}" for m in problems]
        if doc.get("session") != name:
            rep.problems.append(f"{js.name}: session is {doc.get('session')!r}, the folder is {name!r}")
        if doc.get("schema") == 1 and doc.get("stream") != stream:
            rep.problems.append(f"{js.name}: stream is {doc.get('stream')!r}, the file name says {stream!r}")
    for p in files:
        if p.name not in expected:
            kind = "recording" if p.suffix.lower() in (".wav", ".json") else "file"
            rep.problems.append(f"{p.name}: unexpected {kind} (only <session>.adc|accel.wav|json belong here)")
    if not rep.streams and files:
        rep.problems.append("no <session>.adc.* or <session>.accel.* files")
    if len(docs) == 2:
        a, b = docs.values()
        for key in ("node", "protocol", "session"):
            if a.get(key) != b.get(key):
                rep.problems.append(f"the streams disagree on {key}: {a.get(key)!r} and {b.get(key)!r}")
    return rep


def validate_root(root: Path, schema_path: Path, sidecars_only: bool = False) -> list[SessionReport]:
    return [validate_session_folder(p, schema_path, sidecars_only) for p in sorted(root.iterdir()) if p.is_dir()]


def run_validate(root: Path, schema_path: Path, sidecars_only: bool = False, out=print) -> int:
    """Print one line per session and a summary. Returns 0 when every session is fine, 1 otherwise, 2 for a bad root."""
    if not root.is_dir():
        out(f"rzlab validate: {root} is not a folder")
        return 2
    reports = validate_root(root, schema_path, sidecars_only)
    stray = [p for p in sorted(root.iterdir()) if p.is_file() and p.suffix.lower() == ".wav"]
    failed = 0
    for r in reports:
        status = "ok  " if r.ok else "FAIL"
        out(f"{status} {r.name}  [{', '.join(r.streams) or '-'}]")
        for m in r.problems:
            out(f"       problem: {m}")
        for m in r.warnings:
            out(f"       warning: {m}")
        failed += 0 if r.ok else 1
    for p in stray:
        out(f"FAIL {p.name}: a recording outside a session folder")
        failed += 1
    out(f"{len(reports)} session(s) checked, {failed} failed")
    return 1 if failed else 0
