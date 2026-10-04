#!/usr/bin/env python3
"""SessionStart: give the main session the facts it would otherwise have to look up.

Date and work-day status, which machine this is, local-model availability, git state, today's
daily note, open agent-ledger flags, and the current Handoff. Fast (< 1 s) and read-only, apart
from deleting hook state older than 14 days.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ledger  # noqa: E402
import rzlib  # noqa: E402

WORK_DAYS = {0: "Monday", 1: "Tuesday"}


def ollama_status() -> str | None:
    cfg = json.loads(rzlib.read_text(rzlib.ROOT / "tools" / "local" / "config.json") or "{}")
    host = cfg.get("host", "http://localhost:11434").rstrip("/")
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=0.4) as r:
            models = [m.get("name", "") for m in json.loads(r.read().decode("utf-8")).get("models", [])]
    except Exception:
        return None
    want = cfg.get("model", "")
    have = "installed" if any(m == want or m.split(":")[0] == want for m in models) else "NOT pulled"
    return (
        f"Local models (Ollama) answer at {host}; configured model {want or '(none)'} is {have}. "
        f"Helpers: tools/local/*.py (fail-open, Kaszti's desktop only)."
    )


def workstation_row(name: str) -> str:
    txt = rzlib.read_text(rzlib.ROOT / "10 Project" / "Workstations.md") or ""
    for line in txt.splitlines():
        if line.startswith("|") and name.lower() in line.lower():
            cells = [c.strip() for c in line.strip("|").split("|")]
            return " · ".join(c for c in cells if c)
    return ""


def git_summary() -> str:
    rc, branch = rzlib.git(["rev-parse", "--abbrev-ref", "HEAD"])
    if rc != 0:
        return "Git: not a git checkout here."
    files = rzlib.dirty_files()
    vault = sum(rzlib.is_vault_path(f) for f in files)
    _, last = rzlib.git(["log", "-1", "--format=%h %ad %an: %s", "--date=short"])
    return (
        f"Git: branch {branch.strip()}, {len(files)} uncommitted file(s) ({vault} vault, {len(files) - vault} code). "
        f"Last commit {last.strip()}. Nothing was fetched; others may have pushed since."
    )


def cleanup_state(days: int = 14) -> None:
    cutoff = time.time() - days * 86400
    for p in rzlib.STATE.rglob("*") if rzlib.STATE.exists() else []:
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


def main() -> int:
    rzlib.utf8_stdio()
    data = rzlib.read_hook_input()
    today = dt.date.today()
    iso = today.isocalendar()
    lines = [f"Rezonating session facts (from .claude/hooks/session_start.py, source: {data.get('source', '?')}):"]
    wd = today.strftime("%A")
    if today.weekday() in WORK_DAYS:
        lines.append(f"Today is {wd} {today.isoformat()} (week {iso[0]}-W{iso[1]:02d}), a team work day.")
    else:
        lines.append(
            f"Today is {wd} {today.isoformat()} (week {iso[0]}-W{iso[1]:02d}). The team works Monday and "
            "Tuesday, so this is off-day work: its daily note gets off_day: true."
        )

    name = rzlib.machine()
    row = workstation_row(name)
    lines.append(f"Machine: {name}" + (f" — {row}." if row else " — not listed in 10 Project/Workstations.md yet."))
    tools = [t for t in ("idf.py", "eim", "ruff", "clang-format", "clangd", "node") if shutil.which(t)]
    lines.append(
        "Tools on PATH: " + (", ".join(tools) if tools else "none of idf.py/eim/ruff/clang-format/clangd/node") + "."
    )
    ol = ollama_status()
    if ol:
        lines.append(ol)
    lines.append(git_summary())

    daily = rzlib.ROOT / "70 Journal" / "Daily" / f"{today.isoformat()}.md"
    lines.append(
        f"Today's daily note {'exists' if daily.exists() else 'does not exist yet'}: 70 Journal/Daily/{today.isoformat()}.md"
    )

    fl = ledger.open_flags()
    if fl:
        lines.append(f"Agent ledger: {len(fl)} open flag(s), newest first:")
        for f in sorted(fl, key=lambda f: f.get("ts", ""), reverse=True)[:6]:
            lines.append(
                f"  - {f['id']} {f.get('agent')} {f.get('kind')}/{f.get('severity')}: {f.get('summary', '')[:160]}"
            )
    else:
        lines.append("Agent ledger: no open flags.")

    handoff = rzlib.read_text(rzlib.ROOT / "90 Meta" / "Claude" / "Handoff.md") or ""
    _, body = rzlib.split_frontmatter(handoff)
    body = re.sub(r"\n{3,}", "\n\n", body.strip())
    if body:
        lines.append(
            "\nCurrent 90 Meta/Claude/Handoff.md:\n" + body[:4000] + ("\n[…truncated]" if len(body) > 4000 else "")
        )

    cleanup_state()
    rzlib.emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(lines)[:9500]}})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"session_start error (ignored): {e}", file=sys.stderr)
        sys.exit(0)
