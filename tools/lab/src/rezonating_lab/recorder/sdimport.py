"""``rzlab import-sd <folder>``: bring sessions recorded on a node's SD card into the data root (WEB_API.md 12.6).

The card holds session folders in the recorder's own layout: ``<session>/<session>.adc.wav|json`` and
``<session>.accel.wav|json`` (the folder given may itself be a session folder, or hold them at any depth). Per
session:

1. **validate** it where it lies (``rzlab validate``'s checks: name, WAV/sidecar pairs, schema, WAV header against
   the sidecar, labels inside the file). An invalid session is reported with its problems and not imported;
2. **skip** it when the data root already has a folder of that name (an import never overwrites anything);
3. **copy** its recording files to a fresh staging folder and validate the copy again (a bad copy is caught there);
4. **move** them into a new ``<data root>/<session>/`` (created exclusively: a race with another import or the
   recorder is a skip): recordings first, sidecars last, as the recorder does (a sidecar in the data root means its
   recording is complete);
   If a move fails, whatever reached the new folder is removed again and the folder too, so a failed import leaves
   nothing in the data root and a later import tries again;
5. **copy the sidecars** (never a WAV) to the repository's ``data/<session>/`` when ``sidecar_dir`` is set, with the
   recorder's rules: a simulated session (``rzlab: source=sim``) only when ``copy_sim`` is set, and never over an
   existing ``data/<session>/`` (the note says so).

Only the recording files are copied; anything else on the card stays there. Links are never followed: a session
folder or recording file that is a symbolic link is skipped.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rezonating_ml import io

from .validate import STREAM_BY_SUFFIX, validate_session_folder

MAX_DEPTH = 4


@dataclass
class ImportResult:
    session: str
    source: str
    status: str  # "imported" | "skipped" | "invalid" | "failed"
    problems: list[str] = field(default_factory=list)
    path: str | None = None
    sidecars_copied: list[str] = field(default_factory=list)
    note: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "source": self.source,
            "status": self.status,
            "problems": self.problems,
            "path": self.path,
            "sidecars_copied": self.sidecars_copied,
            "note": self.note,
            "warnings": self.warnings,
        }


def find_session_folders(src: Path, max_depth: int = MAX_DEPTH) -> list[Path]:
    """Folders named like a session under ``src`` (``src`` included), at most ``max_depth`` levels down."""
    found: list[Path] = []

    def walk(d: Path, depth: int) -> None:
        if d.is_symlink():
            return
        if io.SESSION_RE.match(d.name):
            found.append(d)
            return  # a session folder holds files, not more sessions
        if depth >= max_depth:
            return
        try:
            children = sorted(
                p for p in d.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")
            )
        except OSError:
            return
        for c in children:
            walk(c, depth + 1)

    walk(src, 0)
    return found


def recording_files(folder: Path) -> list[Path]:
    """The ``<session>.<adc|accel>.wav|json`` files of a session folder, WAVs first."""
    out = [
        folder / f"{folder.name}.{suffix}.{ext}"
        for ext in ("wav", "json")
        for suffix in STREAM_BY_SUFFIX
        if (folder / f"{folder.name}.{suffix}.{ext}").is_file()
        and not (folder / f"{folder.name}.{suffix}.{ext}").is_symlink()
    ]
    return out


def import_one(
    folder: Path,
    root: Path,
    staging_dir: Path,
    schema_path: Path,
    sidecar_dir: Path | None,
    copy_sim: bool = False,
    repo_root: Path | None = None,
) -> ImportResult:
    name = folder.name
    res = ImportResult(name, str(folder), "invalid")
    rep = validate_session_folder(folder, schema_path, repo_root=repo_root)
    res.warnings = list(rep.warnings)
    if not rep.streams:
        res.problems = rep.problems or ["no recording files"]
        return res
    if not rep.ok:
        res.problems = rep.problems
        return res
    target = root / name
    if target.exists():
        res.status, res.path = "skipped", str(target)
        res.note = "the data root already has this session; nothing was changed"
        return res
    staging_dir.mkdir(parents=True, exist_ok=True)
    stage_parent = Path(tempfile.mkdtemp(prefix="sd-import-", dir=staging_dir))
    staged = stage_parent / name
    try:
        staged.mkdir()
        for f in recording_files(folder):
            shutil.copy2(f, staged / f.name)
        rep2 = validate_session_folder(staged, schema_path)
        if not rep2.ok:
            res.status, res.problems = "failed", [f"the copy did not validate: {m}" for m in rep2.problems]
            return res
        try:
            os.mkdir(target)  # exclusive: never into a folder that appeared meanwhile
        except FileExistsError:
            res.status, res.path = "skipped", str(target)
            res.note = "the data root got this session while importing; nothing was changed"
            return res
        try:
            for f in sorted(staged.iterdir(), key=lambda p: (p.suffix != ".wav", p.name)):
                shutil.move(str(f), str(target / f.name))
        except OSError:
            _remove_partial(target)
            raise
        res.status, res.path = "imported", str(target)
        res.sidecars_copied, res.note = _copy_sidecars(target, sidecar_dir, copy_sim)
        return res
    except OSError as exc:
        res.status, res.problems = "failed", [f"copying failed: {exc}"]
        return res
    finally:
        shutil.rmtree(stage_parent, ignore_errors=True)


def _remove_partial(target: Path) -> None:
    """A move into ``target`` failed: take out what arrived and the folder, so the data root is as before."""
    with contextlib.suppress(OSError):
        for f in target.iterdir():
            with contextlib.suppress(OSError):
                f.unlink()
    with contextlib.suppress(OSError):
        target.rmdir()


def _is_sim(folder: Path) -> bool:
    for p in recording_files(folder):
        if p.suffix == ".json":
            try:
                notes = io.parse_rzlab_notes(io.load_sidecar(p).get("notes"))
            except (OSError, ValueError):
                continue
            if notes.get("source") == "sim":
                return True
    return False


def _copy_sidecars(folder: Path, sidecar_dir: Path | None, copy_sim: bool = False) -> tuple[list[str], str | None]:
    """Copy the sidecars to ``data/<session>/``. Never raises: the session is already in the data root, so a failure
    here is a note (and the partial ``data/<session>/`` is removed again), not a failed import."""
    try:
        return _copy_sidecars_unsafe(folder, sidecar_dir, copy_sim)
    except OSError as exc:
        return (
            [],
            f"the session was imported, but copying its sidecars to the repository failed ({exc}); nothing was left there",
        )


def _copy_sidecars_unsafe(
    folder: Path, sidecar_dir: Path | None, copy_sim: bool = False
) -> tuple[list[str], str | None]:
    if sidecar_dir is None:
        return [], "no sidecar_dir is configured: the sidecars were not copied to the repository"
    if not copy_sim and _is_sim(folder):
        return [], "simulated session: the sidecars were not copied to the repository (set RZ_COPY_SIM_SIDECARS=1)"
    dest = sidecar_dir / folder.name
    if dest.exists():
        return [], f"the repository already has {dest}; its sidecars were left unchanged (nothing was copied)"
    dest.mkdir(parents=True)
    out: list[str] = []
    try:
        for p in recording_files(folder):
            if p.suffix == ".json":
                shutil.copyfile(p, dest / p.name)
                out.append(str(dest / p.name))
    except OSError:
        _remove_partial(dest)  # this call created dest: take it out again, so a later copy is not blocked
        raise
    return out, None


def import_sd(
    src: Path,
    root: Path,
    staging_dir: Path,
    schema_path: Path,
    sidecar_dir: Path | None,
    copy_sim: bool = False,
    repo_root: Path | None = None,
) -> list[ImportResult]:
    """Import every session folder found under ``src``. ``src`` must exist; the data root must be a folder."""
    if not src.is_dir():
        raise FileNotFoundError(f"{src} is not a folder")
    if not root.is_dir():
        raise FileNotFoundError(f"the data root {root} is not a folder")
    if src.resolve() == root.resolve() or root.resolve() in src.resolve().parents:
        raise ValueError("the SD folder lies inside the data root; give the card's folder")
    return [
        import_one(f, root, staging_dir, schema_path, sidecar_dir, copy_sim, repo_root)
        for f in find_session_folders(src)
    ]


def summary(results: list[ImportResult]) -> dict[str, int]:
    out = {"imported": 0, "skipped": 0, "invalid": 0, "failed": 0}
    for r in results:
        out[r.status] += 1
    return out


def run_import(
    src: Path,
    root: Path,
    staging_dir: Path,
    schema_path: Path,
    sidecar_dir: Path | None,
    out=print,
    copy_sim: bool = False,
    repo_root: Path | None = None,
) -> int:
    """The CLI: one line per session. 0 when nothing was invalid or failed, 1 otherwise, 2 for a bad folder."""
    try:
        results = import_sd(src, root, staging_dir, schema_path, sidecar_dir, copy_sim, repo_root)
    except (FileNotFoundError, ValueError) as exc:
        out(f"rzlab import-sd: {exc}")
        return 2
    for r in results:
        out(f"{r.status:<8} {r.session}  ({r.source})")
        for m in r.problems:
            out(f"         problem: {m}")
        for m in r.warnings:
            out(f"         warning: {m}")
        if r.note:
            out(f"         note: {r.note}")
    s = summary(results)
    out(f"{len(results)} session(s) found: " + ", ".join(f"{v} {k}" for k, v in s.items()))
    return 1 if s["invalid"] or s["failed"] else 0
