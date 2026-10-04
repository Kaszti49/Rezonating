#!/usr/bin/env python3
"""Draft the "Since last week" part of the weekly meeting from git, the vault and the ledger.

  python tools/local/summarize_week.py                 # last 7 days, draft to stdout
  python tools/local/summarize_week.py --days 14 --raw # just the collected facts, no model
  python tools/local/summarize_week.py --out "00 Inbox/Week summary 2026-W41.md"

Uses the local model when it's available, otherwise prints the facts. The draft is marked as a
draft; read it before pasting it anywhere.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ollama_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True)
    return p.stdout.decode("utf-8", errors="replace")


def props(text: str) -> dict:
    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
    out = {}
    for line in m.group(1).splitlines() if m else []:
        k, _, v = line.partition(":")
        if v:
            out[k.strip()] = v.strip().strip('"')
    return out


def collect(days: int) -> str:
    since = dt.date.today() - dt.timedelta(days=days)
    lines = [f"# Facts {since.isoformat()} to {dt.date.today().isoformat()}", "", "## Commits"]
    log = git("log", f"--since={since.isoformat()}", "--date=short", "--format=%ad %an: %s")
    lines += [f"- {l}" for l in log.splitlines()] or ["- none"]
    lines += ["", "## Work finished"]
    for f in sorted((ROOT / "20 Work").glob("*.md")):
        p = props(f.read_text(encoding="utf-8"))
        if p.get("status") == "done" and p.get("done", "") >= since.isoformat():
            lines.append(f"- {f.stem} ({p.get('owner')}, {p.get('done')})")
    lines += ["", "## Work in progress or blocked"]
    for f in sorted((ROOT / "20 Work").glob("*.md")):
        p = props(f.read_text(encoding="utf-8"))
        if p.get("status") in ("doing", "review", "blocked"):
            lines.append(f"- {f.stem} ({p.get('owner')}, {p.get('status')}, due {p.get('due') or '—'})")
    lines += ["", "## Daily notes"]
    for f in sorted((ROOT / "70 Journal" / "Daily").glob("*.md")):
        if f.stem >= since.isoformat():
            body = re.sub(r"^---.*?---", "", f.read_text(encoding="utf-8"), flags=re.S)
            body = re.sub(r"```.*?```", "", body, flags=re.S)
            lines.append(f"### {f.stem}\n" + "\n".join(l for l in body.splitlines() if l.strip() not in ("", "-")))
    lines += ["", "## Agent flags"]
    flags = ROOT / "90 Meta" / "Agents" / "Ledger" / "flags.jsonl"
    for raw in flags.read_text(encoding="utf-8").splitlines() if flags.exists() else []:
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if e.get("ev") == "flag" and e.get("ts", "")[:10] >= since.isoformat():
            lines.append(f"- {e.get('agent')} {e.get('kind')}/{e.get('severity')}: {e.get('summary')}")
    return "\n".join(lines)


SYSTEM = (
    "You summarise a small hardware startup's week for its weekly meeting. Use only the facts given. "
    "Write 5-10 short English bullets grouped under Kaszti, Viktor and Claude, then one line 'Watch:' with "
    "anything blocked or late. No praise, no guesses, no new facts."
)


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    facts = collect(a.days)
    draft = None if a.raw else ollama_client.chat(facts, system=SYSTEM)
    text = (
        f"> Draft by {ollama_client.model_name()} (local). Check it against the facts below.\n\n{draft}\n\n---\n\n{facts}"
        if draft
        else facts
    )
    if a.out:
        out = ROOT / a.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"---\ntype: inbox\ncreated: {dt.date.today().isoformat()}\n---\n{text}\n", encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
