"""Shared helpers for Rezonating's hooks and agent scripts.

Tier 1: hooks run unattended on every machine. Standard library only, Python 3.10+,
must behave the same on Windows (Git Bash or no shell) and Linux.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import secrets
import socket
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- paths

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
STATE = ROOT / ".claude" / "state"
LEDGER_DIR = ROOT / "90 Meta" / "Agents" / "Ledger"
FLAGS = LEDGER_DIR / "flags.jsonl"
RUNS = LEDGER_DIR / "runs.jsonl"

VAULT_TOP = re.compile(r"^\d\d [^/]+(/|$)")
TEMPLATES = "90 Meta/Templates/"


def utf8_stdio() -> None:
    """Windows pipes default to cp1252; Hungarian names would crash a hook."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def rel(path: str | os.PathLike, root: Path | None = None) -> str | None:
    """Repo-relative POSIX path, or None if the path is outside the repo."""
    root = Path(root or ROOT)
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    a = os.path.normcase(os.path.abspath(p))
    b = os.path.normcase(os.path.abspath(root))
    if a != b and not a.startswith(b.rstrip("\\/") + os.sep):
        return None
    return Path(os.path.relpath(os.path.abspath(p), os.path.abspath(root))).as_posix()


def is_vault_note(relpath: str) -> bool:
    """A markdown note that belongs to the Obsidian vault (not code docs)."""
    if not relpath.endswith(".md"):
        return False
    if relpath == "Home.md":
        return True
    return bool(VAULT_TOP.match(relpath)) and not relpath.startswith(TEMPLATES)


def is_vault_path(relpath: str) -> bool:
    return relpath == "Home.md" or relpath.startswith(".obsidian/") or bool(VAULT_TOP.match(relpath))


# ---------------------------------------------------------------- globs


def _glob_re(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def glob_match(relpath: str, patterns) -> bool:
    if isinstance(patterns, str):
        patterns = [patterns]
    return any(_glob_re(p).match(relpath) for p in patterns)


# ---------------------------------------------------------------- time, machine


def now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def today() -> str:
    return _dt.date.today().isoformat()


def machine() -> str:
    return (os.environ.get("COMPUTERNAME") or socket.gethostname() or "unknown").lower()


def parse_since(spec: str | None) -> _dt.date | None:
    """'14d', '3w' or 'YYYY-MM-DD' -> date."""
    if not spec:
        return None
    m = re.fullmatch(r"(\d+)([dw])", spec)
    if m:
        n = int(m.group(1)) * (7 if m.group(2) == "w" else 1)
        return _dt.date.today() - _dt.timedelta(days=n)
    return _dt.date.fromisoformat(spec)


def new_id(prefix: str) -> str:
    return f"{prefix}-{_dt.date.today().strftime('%y%m%d')}-{secrets.token_hex(2)}"


# ---------------------------------------------------------------- io


def read_text(path: Path) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return None
    except UnicodeDecodeError:
        return Path(path).read_text(encoding="utf-8", errors="replace")


def read_hook_input() -> dict:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        return {}


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


def read_jsonl(path: Path) -> list[dict]:
    out = []
    txt = read_text(path)
    if not txt:
        return out
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # a bad merge line must never break the ledger
    return out


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


# ---------------------------------------------------------------- git


def git(args: list[str], cwd: Path | None = None, timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=str(cwd or ROOT),
            capture_output=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def git_root(cwd: str | Path | None) -> Path:
    if cwd:
        rc, out = git(["rev-parse", "--show-toplevel"], cwd=Path(cwd))
        if rc == 0 and out.strip():
            return Path(out.strip())
    return ROOT


def dirty_files(root: Path | None = None) -> list[str]:
    """Modified, staged and untracked files (repo-relative), excluding deletions."""
    rc, out = git(["status", "--porcelain=v1", "-z", "-uall"], cwd=root)
    if rc != 0:
        return []
    files, items, i = [], out.split("\0"), 0
    while i < len(items):
        entry = items[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            i += 1  # skip the rename source
        if "D" in code:
            continue
        files.append(path)
    return files


def staged_files(root: Path | None = None) -> list[str]:
    rc, out = git(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"], cwd=root)
    return [f for f in out.split("\0") if f] if rc == 0 else []


def head_version(relpath: str, root: Path | None = None) -> str | None:
    rc, out = git(["show", f"HEAD:{relpath}"], cwd=root)
    return out if rc == 0 else None


# ---------------------------------------------------------------- edit tracking


def _edits_dir(session_id: str) -> Path:
    return STATE / "edits" / re.sub(r"[^\w.-]", "_", session_id or "nosession")


def record_edit(session_id: str, agent_id: str | None, relpath: str) -> None:
    d = _edits_dir(session_id)
    d.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w.-]", "_", agent_id or "main")
    with open(d / f"{name}.txt", "a", encoding="utf-8", newline="\n") as f:
        f.write(relpath + "\n")


def edits_by(session_id: str, agent_id: str | None) -> list[str]:
    name = re.sub(r"[^\w.-]", "_", agent_id or "main")
    txt = read_text(_edits_dir(session_id) / f"{name}.txt") or ""
    seen, out = set(), []
    for line in txt.splitlines():
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return out


# ---------------------------------------------------------------- frontmatter (YAML subset)


class YamlError(ValueError):
    pass


def split_frontmatter(text: str) -> tuple[str | None, str]:
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return None, text
    m = re.match(r"^---[ \t]*\r?\n(.*?)(?:\r?\n)?^---[ \t]*(?:\r?\n|$)", text, re.S | re.M)
    if not m:
        return None, text
    return m.group(1), text[m.end() :]


_NUM = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")


def _scalar(tok: str):
    t = tok.strip()
    if t == "" or t in ("~", "null", "Null", "NULL"):
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        body = t[1:-1]
        if t[0] == "'":
            return body.replace("''", "'")
        try:
            return json.loads(t)
        except ValueError:
            return body
    if t in ("true", "True", "TRUE"):
        return True
    if t in ("false", "False", "FALSE"):
        return False
    if _NUM.match(t):
        return float(t) if any(c in t for c in ".eE") else int(t)
    return t


def _strip_comment(s: str) -> str:
    out, q = [], None
    for i, c in enumerate(s):
        if q:
            if c == q:
                q = None
        elif c in "\"'":
            q = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            break
        out.append(c)
    return "".join(out).rstrip()


class _Flow:
    def __init__(self, s: str):
        self.s, self.i = s, 0

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def value(self, stops: str):
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == "[":
            return self.seq()
        if self.i < len(self.s) and self.s[self.i] == "{":
            return self.mapping()
        start, q = self.i, None
        while self.i < len(self.s):
            c = self.s[self.i]
            if q:
                if c == q:
                    q = None
            elif c in "\"'" and self.i == start:
                q = c
            elif c in stops:
                break
            self.i += 1
        return _scalar(self.s[start : self.i])

    def seq(self):
        self.i += 1
        out = []
        while True:
            self.ws()
            if self.i >= len(self.s):
                raise YamlError("unclosed [")
            if self.s[self.i] == "]":
                self.i += 1
                return out
            out.append(self.value(",]"))
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1

    def mapping(self):
        self.i += 1
        out = {}
        while True:
            self.ws()
            if self.i >= len(self.s):
                raise YamlError("unclosed {")
            if self.s[self.i] == "}":
                self.i += 1
                return out
            start = self.i
            while self.i < len(self.s) and self.s[self.i] not in ":}":
                self.i += 1
            key = str(_scalar(self.s[start : self.i]))
            if self.i < len(self.s) and self.s[self.i] == ":":
                self.i += 1
            out[key] = self.value(",}")
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1


def _inline(v: str):
    v = v.strip()
    if v[:1] in "[{":
        f = _Flow(v)
        val = f.value("")
        f.ws()
        if f.i != len(v):
            raise YamlError(f"trailing text after {v[:1]}…: {v[f.i :]!r}")
        return val
    if v[:1] in "|>":
        raise YamlError("block scalars (| or >) are not supported in properties")
    return _scalar(v)


def parse_frontmatter(fm: str) -> dict:
    """Parse the YAML subset Obsidian properties use: scalars, flow lists/maps, block lists."""
    data: dict = {}
    lines = [_strip_comment(l) for l in fm.splitlines()]
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line[0] in " \t":
            raise YamlError(f"unexpected indentation: {line.strip()!r}")
        m = re.match(r"^([^:#][^:]*?)\s*:(?:\s+(.*)|\s*)$", line)
        if not m:
            raise YamlError(f"not a 'key: value' line: {line!r}")
        key, val = m.group(1).strip().strip("\"'"), (m.group(2) or "").strip()
        if key in data:
            raise YamlError(f"duplicate property {key!r}")
        i += 1
        if val:
            data[key] = _inline(val)
            continue
        items = []
        while i < len(lines) and (not lines[i].strip() or lines[i][:1] in " \t-"):
            s = lines[i].strip()
            i += 1
            if not s:
                continue
            if not s.startswith("-"):
                raise YamlError(f"nested mappings are not supported (under {key!r})")
            items.append(_inline(s[1:].strip()) if s[1:].strip() else None)
        data[key] = items if items else None
    return data
