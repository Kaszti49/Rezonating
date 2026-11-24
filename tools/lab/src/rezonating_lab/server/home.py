"""Results for the Lab's Home page: read from the vault's experiment notes, never typed into the UI (WEB_API.md 16).

``50 Experiments/EXP-*.md`` hold the team's results. A note's frontmatter gives the headline (metric, value, result); a
table in it whose header is ``Set | Right | Same | Wrong`` gives the score per set of steps. A number shown to a visitor
is therefore always a number somebody logged, with its note next to it. Without a vault (D-012) the lists are empty.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import yaml
from fastapi import FastAPI

from ..recorder.config import LabConfig

FOLDER = "50 Experiments"
HEADER = ["set", "right", "same", "wrong"]
ID_RE = re.compile(r"^EXP-\d{3}\b")
MAX_NOTES = 200
IN_SAMPLE_RE = re.compile(r"\bin-sample\b", re.IGNORECASE)


def _split(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", text, re.S)
    if not m:
        return {}, text
    try:
        front = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        front = None
    return (front if isinstance(front, dict) else {}), m.group(2)


def _cells(line: str) -> list[str]:
    return [c.strip().strip("*") for c in line.strip().strip("|").split("|")]


def score_table(body: str) -> list[dict]:
    """Rows of the first ``Set | Right | Same | Wrong`` table; a row that is not three whole numbers is left out."""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|") or [c.lower() for c in _cells(line)] != HEADER:
            continue
        rows = []
        for row in lines[i + 2 :]:
            if not row.lstrip().startswith("|"):
                break
            c = _cells(row)
            if len(c) == 4 and c[0].lower() != "total" and all(re.fullmatch(r"\d+", x) for x in c[1:]):
                rows.append({"set": c[0], "right": int(c[1]), "same": int(c[2]), "wrong": int(c[3])})
        return rows
    return []


def read_experiments(vault: Path | None) -> list[dict]:
    """The experiment notes, oldest first. A note that cannot be read is skipped."""
    folder = vault / FOLDER if vault is not None else None
    if folder is None or not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.glob("EXP-*.md"))[:MAX_NOTES]:
        try:
            front, body = _split(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if front.get("type") != "experiment" or not ID_RE.match(p.stem):
            continue
        value = front.get("metric_value")
        out.append(
            {
                "id": str(front.get("id") or p.stem[:7]),
                "title": p.stem[8:].strip(),
                "date": str(front.get("date") or ""),
                "status": str(front.get("status") or ""),
                "pack": str(front.get("pack") or "").strip("[]"),
                "people": front.get("people") if isinstance(front.get("people"), int) else None,
                "metric": str(front.get("metric") or ""),
                "value": float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None,
                "result": str(front.get("result") or ""),
                "in_sample": bool(IN_SAMPLE_RE.search(body)),
                "score": score_table(body),
            }
        )
    return out


def register_home_routes(app: FastAPI, cfg: LabConfig) -> None:
    @app.get("/api/home/results")
    async def home_results():
        return {"experiments": await asyncio.to_thread(read_experiments, cfg.repo_root)}
