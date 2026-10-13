"""Datasets page: an index of every session, and the builder of ``data/manifest.json`` (WEB_API.md section 13).

Sources (all read only):

- the repository's sidecars ``<sidecar_root>/<session>/<session>[.<adc|adcdec|accel>].json`` (``data/``, in git),
- the WAVs on the data root ``<data_root>/<session>/*.wav`` (the shared drive, never in git), and
- for a session with no sidecar in the repository, the sidecars next to its WAVs on the data root (a simulated
  session is kept there but not copied to ``data/``; so is a session that did not validate). Such a row is read and
  validated the same way and marked ``in_repo: false, sidecar_source: "data_root"``. It never goes into a manifest
  (format v1 ``sidecar`` paths are relative to the repository): the preview names it "sidecar not in repo".

Every per-recording field comes from :func:`rezonating_ml.manifest.build_manifest` (validity, errors, people,
duration, loss, ...): this module groups its entries by session, caches them and filters them. Nothing here
re-reads a sidecar's fields itself.

**Cache.** A per-machine SQLite file (``LabConfig.index_db``, default in the user's cache folder, never in the
repository). It holds one manifest entry per sidecar, keyed by the sidecar's and the WAV's ``(mtime_ns, size)``: a
refresh stats the files and rebuilds only the sessions whose key changed. The cache is dropped whole when the data
root, the sidecar folder, the sidecar schema, ``MANIFEST_VERSION`` or :data:`INDEX_LOGIC_VERSION` changes, and
"Rebuild index" drops it on request. Deleting the file
is always safe: it is rebuilt from the sidecars.

**Hashes.** ``build_manifest`` hashes every WAV it lists (about 58 MB per hour of recording). The index must not
read whole recordings on every refresh, so the index calls it with ``hash_wavs=False`` and keeps ``sha256: null``
(``size_bytes`` is filled from the index's own stat of the WAV). SHA-256 is computed only when a manifest is built (by ``build_manifest`` itself) or on
request for one session (:meth:`DatasetIndex.hash_session`); both results are kept in the ``hashes`` table under
the WAV's ``(mtime_ns, size)``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from rezonating_ml import io as rzio
from rezonating_ml import manifest as mf

from .recorder.config import is_inside

INDEX_FORMAT = 1
# Bump by hand whenever what the index stores per entry or row changes (with MANIFEST_VERSION it is part of the cache
# identity, so old caches are dropped). 2: data-root sidecars for sessions without a repository copy.
INDEX_LOGIC_VERSION = 2
MANIFEST_NAME = "manifest.json"
ROOT_KEY = "@root/"  # cache key prefix of a sidecar read from the data root (repository keys are <session>/<file>)
NOT_IN_REPO = "sidecar not in repo; import or copy first"

_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entries (
    sidecar TEXT PRIMARY KEY,
    session TEXT NOT NULL,
    sc_mtime_ns INTEGER NOT NULL,
    sc_size INTEGER NOT NULL,
    wav_mtime_ns INTEGER NOT NULL,
    wav_size INTEGER NOT NULL,
    entry TEXT NOT NULL,
    indexed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS hashes (wav TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL,
                                   sha256 TEXT NOT NULL);
"""


class DatasetError(Exception):
    """A request the index cannot answer. ``code`` is the API error code, ``message`` is fit for a toast."""

    def __init__(self, code: str, message: str, http: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http = http


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size) if path.is_file() else None


def _session_dirs(root: Path | None) -> list[Path]:
    """Folders named like a session (so ``raw/`` and ``private/`` are never opened), sorted by name."""
    if root is None or not root.is_dir():
        return []
    try:
        return sorted(
            (d for d in root.iterdir() if d.is_dir() and rzio.SESSION_RE.fullmatch(d.name)), key=lambda d: d.name
        )
    except OSError:
        return []


def sidecar_names(session: str) -> list[str]:
    """The sidecar names a session folder may hold (the same rule as ``rezonating_ml.manifest``)."""
    return [f"{session}.json"] + [f"{session}.{suffix}.json" for suffix in rzio.STREAM_FILE_SUFFIX.values()]


def parse_session_name(name: str) -> dict[str, str]:
    """``YYYY-MM-DD_site_room_nn`` (site and room have no ``_``) -> date, site, room, take."""
    date, site, room, take = name.split("_")
    return {"date": date, "site": site, "room": room, "take": take}


# ------------------------------------------------------------------------------------------------ filters


@dataclass
class Filters:
    """Row filters of the list and of the manifest selection. ``None`` = no filter."""

    protocol: str | None = None
    floor: str | None = None
    person: str | None = None
    valid: bool | None = None
    wav: str | None = None  # "present" | "missing"
    simulated: bool | None = None
    date_from: str | None = None  # YYYY-MM-DD, inclusive (the date in the session name)
    date_to: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Filters:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})

    def match(self, row: dict[str, Any]) -> bool:
        if self.protocol is not None and row["protocol"] != self.protocol:
            return False
        if self.floor is not None and row["floor"] != self.floor:
            return False
        if self.person is not None and self.person not in row["people"]:
            return False
        if self.valid is not None and row["valid"] != self.valid:
            return False
        if self.wav == "present" and not row["wav_present"]:
            return False
        if self.wav == "missing" and row["wav_present"]:
            return False
        if self.simulated is not None and row["simulated"] != self.simulated:
            return False
        if self.date_from is not None and row["date"] < self.date_from:
            return False
        return not (self.date_to is not None and row["date"] > self.date_to)


def totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sessions, hours, labels, problem counts, and per person: sessions and hours they take part in."""
    per: dict[str, dict[str, float]] = {}
    for r in rows:
        for p in r["people"]:
            t = per.setdefault(p, {"sessions": 0, "hours": 0.0})
            t["sessions"] += 1
            t["hours"] += (r["duration_s"] or 0.0) / 3600
    return {
        "sessions": len(rows),
        "hours": round(sum((r["duration_s"] or 0.0) for r in rows) / 3600, 3),
        "labels": sum(r["label_count"] for r in rows),
        "invalid": sum(not r["valid"] for r in rows),
        "wav_missing": sum(not r["wav_present"] for r in rows),
        "simulated": sum(r["simulated"] for r in rows),
        "per_person": [
            {"person": p, "sessions": int(v["sessions"]), "hours": round(v["hours"], 3)}
            for p, v in sorted(per.items(), key=lambda kv: int(kv[0][1:]))
        ],
    }


def facets(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """The values the filter bar can offer."""
    return {
        "protocols": sorted({r["protocol"] for r in rows if r["protocol"]}),
        "floors": sorted({r["floor"] for r in rows if r["floor"]}),
        "people": sorted({p for r in rows for p in r["people"]}, key=lambda p: int(p[1:])),
    }


# ------------------------------------------------------------------------------------------------ rows


def _session_row(
    name: str, entries: list[dict[str, Any]], drive_wavs: list[str] | None, source: str | None = "repo"
) -> dict[str, Any]:
    """One row per session from its manifest entries (one per sidecar), the WAV names in its data-root folder
    (``None`` when the folder is not on the data root) and where the sidecars were read: ``"repo"`` or
    ``"data_root"`` (``None`` when there is none)."""
    source = source if entries else None
    referenced = {e["wav"].split("/", 1)[1] for e in entries}
    unmatched = sorted(w for w in (drive_wavs or []) if w not in referenced)
    errors = [f"{e['stream'] or 'v0'}: {msg}" for e in entries for msg in e["errors"]]
    if not entries:
        errors.append("no sidecar, neither in the repository (data/<session>/) nor next to the WAVs on the data root")
    losses = [e["loss"] for e in entries if e["loss"] is not None]
    durations = [e["duration_s"] for e in entries if e["duration_s"] is not None]
    protocols = [e["protocol"] for e in entries if e["protocol"]]
    floors = [e["floor"] for e in entries if e["floor"]]
    adc = [e for e in entries if e["stream"] in ("adc_raw", None)]
    return {
        "session": name,
        **parse_session_name(name),
        "floor": floors[0] if floors else None,
        "protocol": protocols[0] if protocols else None,
        "people": sorted({p for e in entries for p in e["people"]}, key=lambda p: int(p[1:])),
        "surface": sorted({s for e in entries for s in e["surface"]}),
        "duration_s": max(durations) if durations else None,
        "label_count": max((e["label_count"] for e in (adc or entries)), default=0),
        "streams_n": len(entries),
        "valid": bool(entries) and all(e["valid"] for e in entries),
        "errors": errors,
        "warnings": [f"{w}: WAV on the data root has no sidecar" for w in unmatched],
        # without a sidecar the WAVs on the data root are what there is: present when there are any
        "wav_present": all(e["wav_present"] for e in entries) if entries else bool(drive_wavs),
        "wav_missing": sum(not e["wav_present"] for e in entries),
        "simulated": any(e["simulated"] for e in entries),
        "incomplete": any(e["incomplete"] for e in entries),
        "loss": {k: sum(x[k] for x in losses) for k in mf.LOSS_KEYS} if losses else None,
        "in_repo": source == "repo",
        "sidecar_source": source,
        "on_data_root": drive_wavs is not None,
        "unmatched_wavs": unmatched,
        "size_bytes": sum(e["size_bytes"] or 0 for e in entries),
        "streams": entries,
    }


# ------------------------------------------------------------------------------------------------ index


class DatasetIndex:
    """The session index of one machine. Thread-safe; every call opens its own SQLite connection.

    ``db_path``: the cache file (never in the repository: ``repo_root`` is checked). ``sidecar_root``: the
    repository's ``data/``. ``sidecar_prefix``: how that folder is written in manifest ``sidecar`` paths."""

    def __init__(
        self,
        db_path: Path,
        sidecar_root: Path,
        schema_path: Path,
        sidecar_prefix: str = mf.DEFAULT_SIDECAR_PREFIX,
        repo_root: Path | None = None,
    ) -> None:
        if repo_root is not None and is_inside(db_path, repo_root):
            raise DatasetError(
                "index_in_repo",
                f"The index cache {str(db_path)!r} is inside the git repository. Set RZ_INDEX_DB (or index_db in "
                "the config file) to a file outside it.",
            )
        self.db_path = Path(db_path)
        self.sidecar_root = Path(sidecar_root)
        self.schema_path = Path(schema_path)
        self.sidecar_prefix = sidecar_prefix
        self._lock = threading.RLock()
        self.last_refresh: dict[str, Any] | None = None

    # ------------------------------------------------------------------------------------ database

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=30)
        try:
            try:
                con.executescript(_DDL)
            except sqlite3.DatabaseError:
                con.close()  # before the unlink: Windows cannot delete an open file
                self.db_path.unlink(missing_ok=True)  # a damaged cache: it is only a cache
                con = sqlite3.connect(self.db_path, timeout=30)
                con.executescript(_DDL)
            yield con
        finally:
            con.close()

    def _identity(self, data_root: Path | None) -> dict[str, str]:
        try:
            schema = hashlib.sha256(self.schema_path.read_bytes()).hexdigest()
        except OSError:
            schema = "missing"
        return {
            "format": str(INDEX_FORMAT),
            "logic": str(INDEX_LOGIC_VERSION),
            "manifest_version": str(mf.MANIFEST_VERSION),
            "data_root": str(data_root.resolve()) if data_root else "",
            "sidecar_root": str(self.sidecar_root.resolve()),
            "schema": schema,
        }

    # ------------------------------------------------------------------------------------ refresh

    def _scan(self, data_root: Path | None) -> dict[str, tuple[str, tuple[int, int, int, int]]]:
        """``<session>/<sidecar>.json`` -> (session, key) for every sidecar in the repository, and
        ``@root/<session>/<sidecar>.json`` for the data-root sidecars of sessions with none in the repository."""
        found: dict[str, tuple[str, tuple[int, int, int, int]]] = {}
        in_repo: set[str] = set()
        for source, root in (("repo", self.sidecar_root), ("data_root", data_root)):
            for folder in _session_dirs(root):
                if source == "data_root" and folder.name in in_repo:
                    continue  # the repository's copy is the one that counts
                for name in sidecar_names(folder.name):
                    sc = _stat(folder / name)
                    if sc is None:
                        continue
                    wav = _stat(data_root / folder.name / (name[: -len(".json")] + ".wav")) if data_root else None
                    prefix = "" if source == "repo" else ROOT_KEY
                    found[f"{prefix}{folder.name}/{name}"] = (folder.name, (*sc, *(wav or (-1, -1))))
                    if source == "repo":
                        in_repo.add(folder.name)
        return found

    def refresh(self, data_root: Path | None, force: bool = False) -> dict[str, Any]:
        """Bring the cache up to date. ``data_root``: the usable data root, or ``None`` (every WAV is then missing).
        ``force``: drop the cache and rebuild every session. Returns counts."""
        if not self.sidecar_root.is_dir():
            raise DatasetError(
                "no_sidecar_dir",
                f"The repository's data folder {str(self.sidecar_root)!r} was not found (sidecar_dir, RZ_SIDECAR_DIR).",
            )
        t0 = time.monotonic()
        with self._lock, self._db() as db:
            identity = self._identity(data_root)
            stored = dict(db.execute("SELECT key, value FROM meta").fetchall())
            dropped = force or stored != identity
            if dropped:
                db.execute("DELETE FROM entries")
                db.execute("DELETE FROM meta")
                db.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", identity.items())
            cached = {
                row[0]: tuple(row[1:])
                for row in db.execute("SELECT sidecar, sc_mtime_ns, sc_size, wav_mtime_ns, wav_size FROM entries")
            }
            found = self._scan(data_root)
            stale_rels = {rel for rel, (_s, key) in found.items() if cached.get(rel) != key}
            stale = {found[rel][0] for rel in stale_rels}
            removed = sorted(set(cached) - set(found))
            built: set[str] = set()
            for prefix, sc_root in (("", self.sidecar_root), (ROOT_KEY, data_root)):
                sessions = {found[r][0] for r in stale_rels if r.startswith(ROOT_KEY) == bool(prefix)}
                if not sessions or sc_root is None:
                    continue
                with tempfile.TemporaryDirectory(prefix="rzlab-empty-root-") as empty:
                    manifest = mf.build_manifest(
                        data_root or Path(empty),
                        sc_root,
                        select=sessions.__contains__,
                        schema_path=self.schema_path,
                        sidecar_prefix=self.sidecar_prefix if not prefix else "",
                        hash_wavs=False,
                    )
                now = time.time()
                for e in manifest["entries"]:
                    rel = prefix + "/".join(e["sidecar"].split("/")[-2:])
                    if rel not in found:  # appeared after the scan: the next refresh picks it up
                        continue
                    built.add(rel)
                    wav_size = found[rel][1][3]
                    e["size_bytes"] = wav_size if e["wav_present"] and wav_size >= 0 else None
                    db.execute(
                        "INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (rel, e["session"], *found[rel][1], json.dumps(e), now),
                    )
            # a stale sidecar that vanished during the build
            removed += sorted(rel for rel, (s, _k) in found.items() if s in stale and rel not in built)
            db.executemany("DELETE FROM entries WHERE sidecar = ?", [(r,) for r in removed])
            db.commit()
            stats = {
                "sidecars": len(found),
                "sidecars_data_root": sum(rel.startswith(ROOT_KEY) for rel in found),
                "sessions_rebuilt": len(stale),
                "sidecars_reused": len(found) - sum(1 for _r, (s, _k) in found.items() if s in stale),
                "sidecars_removed": len(removed),
                "cache_dropped": dropped,
                "seconds": round(time.monotonic() - t0, 3),
                "at": time.time(),
            }
            self.last_refresh = stats
            return stats

    # ------------------------------------------------------------------------------------ read

    def rows(self, data_root: Path | None) -> list[dict[str, Any]]:
        """Every session (sidecars in the repository, WAV folders on the data root), newest name first.
        Call :meth:`refresh` first. ``sha256`` is filled from the hash table when the WAV is unchanged."""
        with self._lock, self._db() as db:
            stored = [
                (r[0], json.loads(r[1])) for r in db.execute("SELECT sidecar, entry FROM entries ORDER BY sidecar")
            ]
            hashes = {r[0]: (r[1], r[2], r[3]) for r in db.execute("SELECT wav, mtime_ns, size, sha256 FROM hashes")}
        by_source: dict[str, dict[str, list[dict[str, Any]]]] = {"repo": {}, "data_root": {}}
        for rel, e in stored:
            known = hashes.get(e["wav"])
            if known is not None and data_root is not None and _stat(data_root / e["wav"]) == known[:2]:
                e["sha256"] = known[2]
            source = "data_root" if rel.startswith(ROOT_KEY) else "repo"
            by_source[source].setdefault(e["session"], []).append(e)
        by_session = dict(by_source["data_root"])
        by_session.update(by_source["repo"])  # the repository's sidecars win
        if data_root is None:  # data-root rows only while that root is in use
            by_session = by_source["repo"]
        drive: dict[str, list[str]] = {}
        for folder in _session_dirs(data_root):
            try:
                drive[folder.name] = sorted(p.name for p in folder.glob("*.wav") if p.is_file())
            except OSError:
                drive[folder.name] = []
        names = sorted(set(by_session) | set(drive), reverse=True)
        return [
            _session_row(n, by_session.get(n, []), drive.get(n), "repo" if n in by_source["repo"] else "data_root")
            for n in names
        ]

    def session(self, data_root: Path | None, name: str) -> dict[str, Any]:
        for row in self.rows(data_root):
            if row["session"] == name:
                return row
        raise DatasetError("not_found", f"No session {name!r} in the repository's data/ or on the data root.", 404)

    def _store_hashes(self, data_root: Path, items: list[tuple[str, str]]) -> None:
        """Keep ``(wav, sha256)`` pairs under the WAV's current ``(mtime_ns, size)``."""
        rows = []
        for wav, sha in items:
            key = _stat(data_root / wav)
            if key is not None:
                rows.append((wav, *key, sha))
        with self._lock, self._db() as db:
            db.executemany("INSERT OR REPLACE INTO hashes VALUES (?, ?, ?, ?)", rows)
            db.commit()

    def hash_session(self, data_root: Path, name: str) -> list[dict[str, Any]]:
        """SHA-256 of a session's WAVs (on request; reads the whole files)."""
        row = self.session(data_root, name)
        out = []
        for e in row["streams"]:
            path = data_root / e["wav"]
            sha = mf.sha256_file(path) if path.is_file() else None
            out.append({"wav": e["wav"], "sha256": sha})
        self._store_hashes(data_root, [(o["wav"], o["sha256"]) for o in out if o["sha256"]])
        return out

    # ------------------------------------------------------------------------------------ manifest

    def plan_manifest(
        self,
        data_root: Path | None,
        sessions: list[str] | None = None,
        filters: Filters | None = None,
        include_simulated: bool = False,
        include_invalid: bool = False,
    ) -> dict[str, Any]:
        """The preview: which sessions a manifest would list, which are left out and why. Reads the cache only
        (call :meth:`refresh` first); nothing is hashed or written."""
        rows = self.rows(data_root)
        by_name = {r["session"]: r for r in rows}
        if sessions is not None:
            unknown = sorted(set(sessions) - set(by_name))
            if unknown:
                raise DatasetError("not_found", "Unknown sessions: " + ", ".join(unknown[:10]), 404)
            chosen = [by_name[n] for n in sorted(set(sessions), reverse=True)]
        else:
            chosen = [r for r in rows if (filters or Filters()).match(r)]
        include: list[dict[str, Any]] = []
        excluded: list[dict[str, str]] = []
        for r in chosen:
            if not r["streams"]:
                reason = "no sidecar (neither in the repository nor on the data root)"
            elif r["simulated"] and not include_simulated:
                reason = "simulated"
            elif not r["in_repo"]:  # manifest v1 'sidecar' paths are relative to the repository
                reason = NOT_IN_REPO
            elif not r["valid"] and not include_invalid:
                reason = "invalid: " + (r["errors"][0] if r["errors"] else "see the session")
            else:
                include.append(r)
                continue
            excluded.append({"session": r["session"], "reason": reason})
        out = self.sidecar_root / MANIFEST_NAME
        return {
            "sessions": [r["session"] for r in include],
            "entries": sum(r["streams_n"] for r in include),
            "hours": round(sum(r["duration_s"] or 0.0 for r in include) / 3600, 3),
            "bytes_to_hash": sum(r["size_bytes"] for r in include),
            "wav_missing": sum(r["wav_missing"] for r in include),
            "excluded": excluded,
            "include_simulated": include_simulated,
            "include_invalid": include_invalid,
            "out": f"{self.sidecar_prefix}/{MANIFEST_NAME}",
            "exists": out.is_file(),
        }

    def build_manifest(
        self,
        data_root: Path,
        sessions: list[str] | None = None,
        filters: Filters | None = None,
        include_simulated: bool = False,
        include_invalid: bool = False,
        created: str | None = None,
    ) -> dict[str, Any]:
        """Write ``<sidecar_root>/manifest.json`` with the planned sessions only, through
        :func:`rezonating_ml.manifest.write_manifest` (which validates it). Hashes every listed WAV. An entry whose
        state changed since the preview (now simulated or invalid while those are left out) is dropped and listed
        in ``excluded``. Nothing is written when no entry is left."""
        t0 = time.monotonic()
        plan = self.plan_manifest(data_root, sessions, filters, include_simulated, include_invalid)
        if not plan["sessions"]:
            raise DatasetError("empty_manifest", "No session is left to list: nothing was written.", 422)
        chosen = set(plan["sessions"])
        manifest = mf.build_manifest(
            data_root,
            self.sidecar_root,
            select=chosen.__contains__,
            schema_path=self.schema_path,
            created=created,
            sidecar_prefix=self.sidecar_prefix,
        )
        excluded = list(plan["excluded"])
        kept = []
        for e in manifest["entries"]:
            if e["simulated"] and not include_simulated:
                excluded.append(
                    {"session": e["session"], "wav": e["wav"], "reason": "simulated (changed since the preview)"}
                )
            elif not e["valid"] and not include_invalid:
                excluded.append(
                    {"session": e["session"], "wav": e["wav"], "reason": "invalid (changed since the preview)"}
                )
            else:
                kept.append(e)
        if not kept:
            raise DatasetError("empty_manifest", "No entry is left to list: nothing was written.", 422)
        manifest["entries"] = kept
        out = self.sidecar_root / MANIFEST_NAME
        try:
            mf.write_manifest(out, manifest)
            mf.read_manifest(out)
        except ValueError as exc:
            raise DatasetError("invalid_manifest", str(exc), 500) from exc
        self._store_hashes(data_root, [(e["wav"], e["sha256"]) for e in kept if e["sha256"]])
        return {
            "written": plan["out"],
            "created": manifest["created"],
            "sessions": sorted({e["session"] for e in kept}, reverse=True),
            "entries": len(kept),
            "hours": round(sum(e["duration_s"] or 0.0 for e in kept) / 3600, 3),
            "bytes_hashed": sum(e["size_bytes"] or 0 for e in kept),
            "wav_missing": sum(not e["wav_present"] for e in kept),
            "unmatched_wavs": manifest["unmatched_wavs"],
            "excluded": excluded,
            "seconds": round(time.monotonic() - t0, 3),
        }
