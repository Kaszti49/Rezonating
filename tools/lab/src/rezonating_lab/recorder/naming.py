"""Session names ``YYYY-MM-DD_<site>_<room>_<nn>`` (schema pattern) and their reservation.

``nn`` is reserved by creating the session folder in the data root with ``mkdir`` (atomic, also on a shared
drive): when it already exists, the next ``nn`` is tried. Two lab instances starting at the same moment get
different names.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

from rezonating_ml.io import SESSION_RE

MAX_NN = 99
SLUG_MAX = 32

__all__ = ["MAX_NN", "SESSION_RE", "SessionNameError", "reserve_session", "session_name", "slugify"]


class SessionNameError(Exception):
    pass


def slugify(text: str) -> str:
    """Lower-case ``[a-z0-9-]+``: accents folded, every other run of characters becomes one ``-``.

    Returns an empty string when nothing usable is left (the form then refuses the value)."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    return slug[:SLUG_MAX].strip("-")


def session_name(day: date, site: str, room: str, nn: int) -> str:
    """``2026-11-17_home-a_kitchen_01`` for already slugged ``site`` and ``room``."""
    if not 1 <= nn <= MAX_NN:
        raise SessionNameError(f"session number {nn} is outside 01..{MAX_NN}")
    name = f"{day.isoformat()}_{site}_{room}_{nn:02d}"
    if not SESSION_RE.match(name):
        raise SessionNameError(f"{name!r} does not match the session name pattern")
    return name


def reserve_session(data_root: Path, staging_dir: Path, day: date, site: str, room: str) -> tuple[str, Path, Path]:
    """Reserve the lowest free ``nn``: create ``data_root/<name>/`` and ``staging_dir/<name>/``.

    Returns ``(name, data_folder, staging_folder)``. A staging folder left over from an earlier crashed session
    with the same name makes that ``nn`` unavailable too (its data is not overwritten). Raises
    :class:`SessionNameError` when 01..99 are all taken.
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    for nn in range(1, MAX_NN + 1):
        name = session_name(day, site, room, nn)
        data_folder = data_root / name
        try:
            data_folder.mkdir()
        except FileExistsError:
            continue
        staging_folder = staging_dir / name
        try:
            staging_folder.mkdir()
        except FileExistsError:
            data_folder.rmdir()
            continue
        except OSError:
            data_folder.rmdir()
            raise
        return name, data_folder, staging_folder
    raise SessionNameError(f"all session numbers 01..{MAX_NN} are taken for {day.isoformat()}_{site}_{room}")
