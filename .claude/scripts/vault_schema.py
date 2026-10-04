#!/usr/bin/env python3
"""Check vault notes against the property rules in `10 Project/Vault rules.md`.

Usage:
  python .claude/scripts/vault_schema.py --all            # every vault note
  python .claude/scripts/vault_schema.py --changed        # notes with uncommitted changes
  python .claude/scripts/vault_schema.py "20 Work/X.md"   # specific notes
Options: --errors-only, --json. Exit code 1 when any error is found.

Tier 1: the dashboard, the Bases and every agent depend on these rules. When you change an
allowed value here, change `10 Project/Vault rules.md` in the same commit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rzlib  # noqa: E402

OWNERS = {"kaszti", "viktor", "claude"}
HUMANS = {"kaszti", "viktor"}
AREAS = {"hardware", "firmware", "ml", "data", "project", "research", "design"}
CATEGORIES = {"sensor", "mcu", "adc", "clock", "storage", "prototyping", "passive", "cable", "consumable", "tool"}
HEADS = {"geophone", "accelerometer", "piezo"}
STAGES = {"idea", "design", "data", "model", "on-device", "done"}
KINDS = {"paper", "dataset", "datasheet", "product", "article", "video"}

# type -> rules. required: present and non-empty. enums: allowed values (empty allowed unless
# required). dates/numbers/bools/links/lists: value shape. id_re: id format, and the file name
# must start with the id. name_re/name_equals: file name format and which property must equal it.
TYPES: dict[str, dict] = {
    "work": dict(
        required=["status", "owner", "priority", "area", "created"],
        enums={
            "status": {"backlog", "todo", "doing", "review", "blocked", "done"},
            "owner": OWNERS,
            "priority": {"p1", "p2", "p3"},
            "area": AREAS,
        },
        dates=["due", "created", "done"],
        links=["pack"],
    ),
    "part": dict(
        required=["status", "category", "qty"],
        enums={"status": {"needed", "ordered", "have", "later"}, "category": CATEGORIES},
        numbers=["qty", "price_eur"],
        links=["order"],
    ),
    "order": dict(
        required=["id", "status"],
        enums={"status": {"draft", "ordered", "delivered"}},
        dates=["date", "ordered", "delivered"],
        id_re=r"ORD-\d{3}",
    ),
    "build": dict(
        required=["status", "owner", "date"],
        enums={"status": {"planned", "doing", "done"}, "owner": OWNERS},
        dates=["date"],
    ),
    "pack": dict(
        required=["stage"], enums={"stage": STAGES, "head": HEADS}, numbers=["order_no", "target_value", "best_value"]
    ),
    "experiment": dict(
        required=["id", "status", "owner"],
        enums={"status": {"planned", "running", "done"}, "result": {"pass", "fail", "partial"}, "owner": OWNERS},
        dates=["date"],
        numbers=["people", "metric_value"],
        links=["pack"],
        lists=["sessions"],
        id_re=r"EXP-\d{3}",
    ),
    "research": dict(
        required=["kind", "status"],
        enums={"kind": KINDS, "status": {"to-read", "read"}, "relevance": {"high", "med", "low"}},
    ),
    "daily": dict(
        required=["date"], dates=["date"], bools=["off_day"], name_re=r"\d{4}-\d{2}-\d{2}", name_equals="date"
    ),
    "meeting": dict(
        required=["week", "date"],
        dates=["date"],
        lists=["attendees"],
        list_enums={"attendees": OWNERS},
        name_re=r"\d{4}-W\d{2}",
        name_equals="week",
    ),
    "decision": dict(
        required=["id", "status", "date", "tier"],
        enums={"status": {"proposed", "accepted", "superseded"}, "tier": {1, 2, 3}},
        dates=["date"],
        links=["supersedes"],
        lists=["decided_by"],
        list_enums={"decided_by": HUMANS},
        id_re=r"D-\d{3}",
    ),
    "inbox": dict(dates=["created"]),
    "proposal": dict(
        required=["id", "status", "target", "date"],
        enums={"status": {"proposed", "accepted", "rejected", "applied"}},
        dates=["date", "applied"],
        lists=["flags"],
        id_re=r"P-\d{3}",
    ),
    "retro": dict(required=["week", "date"], dates=["date"], name_re=r"\d{4}-W\d{2}", name_equals="week"),
    "project": dict(),
    "hub": dict(),
    "handoff": dict(dates=["updated"]),
    "log": dict(),
}

# folder prefix -> allowed note types (longest prefix wins)
FOLDERS = {
    "00 Inbox/": {"inbox", "hub"},
    "10 Project/": {"project", "hub"},
    "20 Work/": {"work", "hub"},
    "30 Hardware/": {"hub"},
    "30 Hardware/Parts/": {"part"},
    "30 Hardware/Orders/": {"order"},
    "30 Hardware/Builds/": {"build"},
    "40 Packs/": {"pack", "hub"},
    "50 Experiments/": {"experiment", "hub"},
    "60 Research/": {"research", "hub"},
    "70 Journal/Daily/": {"daily"},
    "70 Journal/Weekly/": {"meeting"},
    "80 Decisions/": {"decision", "hub"},
    "90 Meta/": {"project", "hub", "handoff", "log"},
    "90 Meta/Agents/Proposals/": {"proposal"},
    "90 Meta/Agents/Retros/": {"retro"},
    "Home.md": {"hub"},
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LINK_RE = re.compile(r"^\[\[([^\]|#]+)(#[^\]|]*)?(\|[^\]]*)?\]\]$")


@dataclass
class Issue:
    path: str
    level: str  # "error" | "warn"
    msg: str

    def __str__(self) -> str:
        return f"{self.path}: {self.level}: {self.msg}"


_NAMES: set[str] | None = None


def note_names(root: Path = rzlib.ROOT) -> set[str]:
    """Lower-cased basenames of every note and attachment (Obsidian resolves links by name)."""
    global _NAMES
    if _NAMES is None:
        names = set()
        for _dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "build")]
            for f in filenames:
                names.add(f.lower())
                if f.endswith(".md"):
                    names.add(f[:-3].lower())
        _NAMES = names
    return _NAMES


def all_notes(root: Path = rzlib.ROOT) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            r = rzlib.rel(Path(dirpath) / f, root)
            if r and rzlib.is_vault_note(r):
                out.append(r)
    return sorted(out)


def _allowed_types(relpath: str) -> set[str] | None:
    best = None
    for prefix in FOLDERS:
        if relpath == prefix or relpath.startswith(prefix):
            if best is None or len(prefix) > len(best):
                best = prefix
    return FOLDERS.get(best) if best else None


def _empty(v) -> bool:
    return v is None or v == "" or v == []


def _valid_date(v) -> bool:
    if not isinstance(v, str) or not DATE_RE.match(v):
        return False
    try:
        dt.date.fromisoformat(v)
        return True
    except ValueError:
        return False


def _links_in(v):
    """Yield (ok, text) for every link-ish value; unquoted [[x]] parses as a nested list."""
    if isinstance(v, list):
        if v and all(isinstance(x, list) for x in v):
            yield False, "[[" + ", ".join(", ".join(map(str, x)) for x in v) + "]]"
            return
        for x in v:
            yield from _links_in(x)
    elif isinstance(v, str) and "[[" in v:
        yield bool(LINK_RE.match(v.strip())), v


def check_text(relpath: str, text: str, names: set[str] | None = None) -> list[Issue]:
    issues: list[Issue] = []

    def err(m):
        issues.append(Issue(relpath, "error", m))

    def warn(m):
        issues.append(Issue(relpath, "warn", m))

    if "<%" in text:
        err("contains '<%' (Templater code). Only files in 90 Meta/Templates may; Templater would run it.")
    fm_text, body = rzlib.split_frontmatter(text)
    prev = ""
    for line in body.splitlines():
        if re.match(r"^ {4,}- \[.\] ", line) and (prev.startswith("#") or not prev.strip()):
            warn(
                f"checkbox indented 4+ spaces after a heading or blank line renders as code; Tasks won't see it: {line.strip()[:60]!r}"
            )
        prev = line
    if fm_text is None:
        err("no properties block (--- at the top). Copy the frontmatter of the matching template.")
        return issues
    try:
        fm = rzlib.parse_frontmatter(fm_text)
    except rzlib.YamlError as e:
        err(f"properties don't parse: {e}")
        return issues

    ntype = fm.get("type")
    allowed = _allowed_types(relpath)
    if _empty(ntype):
        err("missing 'type' property")
        return issues
    if ntype not in TYPES:
        err(f"unknown type {ntype!r}; allowed: {', '.join(sorted(TYPES))}")
        return issues
    if allowed is not None and ntype not in allowed:
        err(f"type {ntype!r} doesn't belong in this folder (allowed here: {', '.join(sorted(allowed))})")
    rules = TYPES[ntype]
    stem = Path(relpath).stem

    for k in rules.get("required", []):
        if _empty(fm.get(k)):
            err(f"'{k}' is required for type {ntype}")
    for k, vals in rules.get("enums", {}).items():
        v = fm.get(k)
        if not _empty(v) and v not in vals:
            shown = ", ".join(sorted(str(x) for x in vals))
            err(f"{k}: {v!r} is not allowed (use one of: {shown})")
    for k in rules.get("dates", []):
        v = fm.get(k)
        if not _empty(v) and not _valid_date(v):
            err(f"{k}: {v!r} must be a date written YYYY-MM-DD")
    for k in rules.get("numbers", []):
        v = fm.get(k)
        if not _empty(v) and (isinstance(v, bool) or not isinstance(v, (int, float))):
            err(f"{k}: {v!r} must be a number (no units, no currency sign)")
    for k in rules.get("bools", []):
        v = fm.get(k)
        if not _empty(v) and not isinstance(v, bool):
            err(f"{k}: {v!r} must be true or false")
    for k in rules.get("lists", []):
        v = fm.get(k)
        if not _empty(v) and not isinstance(v, list):
            err(f"{k}: must be a list, e.g. [a, b]")
    for k, vals in rules.get("list_enums", {}).items():
        v = fm.get(k)
        for x in v if isinstance(v, list) else []:
            if x not in vals:
                err(f"{k}: {x!r} is not allowed (use: {', '.join(sorted(vals))})")

    # links: every property that holds a link must be a quoted "[[Note]]"
    names = names if names is not None else note_names()
    for k, v in fm.items():
        for ok, txt in _links_in(v):
            if not ok:
                err(f'{k}: write links in properties quoted, exactly like "[[Note name]]" (got {txt!r})')
            else:
                target = LINK_RE.match(txt.strip()).group(1).strip()
                base = target.split("/")[-1].lower()
                if base not in names and base + ".md" not in names:
                    warn(f"{k}: link target [[{target}]] doesn't exist (yet)")
    for k in rules.get("links", []):
        v = fm.get(k)
        if isinstance(v, str) and v.strip() and "[[" not in v:
            err(f'{k}: must be a link written "[[Note name]]", got {v!r}')

    # ids and names
    id_re = rules.get("id_re")
    if id_re and not _empty(fm.get("id")):
        nid = str(fm["id"])
        if not re.fullmatch(id_re, nid):
            err(f"id {nid!r} has the wrong format ({id_re.replace(chr(92) + 'd{3}', '###')})")
        elif not (stem == nid or stem.startswith(nid + " ")):
            err(f"file name must start with its id: '{nid} …'")
    name_re = rules.get("name_re")
    if name_re and not re.fullmatch(name_re, stem):
        err(f"file name {stem!r} has the wrong format for type {ntype}")
    eq = rules.get("name_equals")
    if eq and not _empty(fm.get(eq)) and str(fm.get(eq)) != stem:
        err(f"{eq}: {fm.get(eq)!r} must equal the file name {stem!r}")

    # cross-property rules
    if ntype == "work":
        if fm.get("status") == "done" and _empty(fm.get("done")):
            err("status is done, so 'done' needs the finishing date (YYYY-MM-DD)")
        if not _empty(fm.get("done")) and fm.get("status") != "done":
            warn("'done' has a date but status isn't done")
    if ntype == "experiment" and fm.get("status") == "done" and _empty(fm.get("result")):
        warn("experiment is done but has no result (pass, fail or partial)")
    if ntype == "order":
        if fm.get("status") in ("ordered", "delivered") and _empty(fm.get("ordered")):
            warn("order is ordered but 'ordered' has no date")
        if fm.get("status") == "delivered" and _empty(fm.get("delivered")):
            warn("order is delivered but 'delivered' has no date")
    if ntype == "decision":
        if fm.get("status") == "accepted" and _empty(fm.get("decided_by")):
            err("an accepted decision needs decided_by (kaszti and/or viktor)")
    if ntype == "proposal" and fm.get("status") == "applied" and _empty(fm.get("applied")):
        warn("proposal is applied but 'applied' has no date")
    return issues


def check_file(relpath: str, root: Path = rzlib.ROOT) -> list[Issue]:
    text = rzlib.read_text(root / relpath)
    if text is None:
        return []
    return check_text(relpath, text)


def check_many(paths: list[str], root: Path = rzlib.ROOT, full: bool = False) -> list[Issue]:
    issues: list[Issue] = []
    ids: dict[str, str] = {}
    for p in paths:
        issues.extend(check_file(p, root))
        if full:  # duplicate ids only make sense across the whole vault
            fm_text, _ = rzlib.split_frontmatter(rzlib.read_text(root / p) or "")
            try:
                fm = rzlib.parse_frontmatter(fm_text) if fm_text else {}
            except rzlib.YamlError:
                continue
            if fm.get("id") and fm.get("type") in ("decision", "experiment", "order", "proposal"):
                key = f"{fm['type']}:{fm['id']}"
                if key in ids:
                    issues.append(Issue(p, "error", f"id {fm['id']} is also used by {ids[key]}"))
                ids[key] = p
    return issues


def main(argv=None) -> int:
    rzlib.utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--changed", action="store_true")
    ap.add_argument("--errors-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    paths: list[str] = []
    if a.all:
        paths = all_notes()
    if a.changed:
        paths += [p for p in rzlib.dirty_files() if rzlib.is_vault_note(p)]
    for p in a.paths:
        r = rzlib.rel(p)
        if r and rzlib.is_vault_note(r):
            paths.append(r)
    paths = sorted(set(paths))
    issues = check_many(paths, full=a.all)
    if a.errors_only:
        issues = [i for i in issues if i.level == "error"]
    if a.json:
        print(json.dumps([i.__dict__ for i in issues], ensure_ascii=False, indent=1))
    else:
        for i in issues:
            print(i)
        n_err = sum(i.level == "error" for i in issues)
        n_warn = sum(i.level == "warn" for i in issues)
        print(f"{len(paths)} notes checked: {n_err} errors, {n_warn} warnings")
    return 1 if any(i.level == "error" for i in issues) else 0


if __name__ == "__main__":
    sys.exit(main())
