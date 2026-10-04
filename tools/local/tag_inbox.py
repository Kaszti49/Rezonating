#!/usr/bin/env python3
"""Suggest where each inbox note should go (work item, part, research, decision, experiment, delete).

  python tools/local/tag_inbox.py            # suggestions to stdout
  python tools/local/tag_inbox.py --raw      # just the list, no model

Suggestions only: nothing is moved or edited. Empty the inbox in the weekly meeting as usual.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ollama_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHOICES = ["work", "part", "research", "decision", "experiment", "keep", "delete"]
SYSTEM = (
    "You triage notes for a two-person hardware project (vibration sensing, ESP32-S3). For the note, answer JSON "
    '{"destination": one of ' + json.dumps(CHOICES) + ', "title": "short note title", "why": "one sentence"}. '
    "work = a task someone must do; part = something to buy; research = a link or source to read; decision = a "
    "choice that is expensive to change; experiment = a test or recording to run."
)


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", action="store_true")
    a = ap.parse_args()
    notes = [f for f in sorted((ROOT / "00 Inbox").glob("*.md")) if f.stem.lower() != "read me"]
    if not notes:
        print("Inbox is empty.")
        return 0
    use_model = not a.raw and ollama_client.status()[0]
    print(
        f"# Inbox triage {dt.date.today().isoformat()}"
        + (f" (suggestions by {ollama_client.model_name()})" if use_model else "")
    )
    for f in notes:
        body = re.sub(r"^---.*?---", "", f.read_text(encoding="utf-8"), flags=re.S).strip()
        age = (dt.date.today() - dt.date.fromtimestamp(f.stat().st_mtime)).days
        line = f"- **{f.stem}** ({age} d old)"
        if use_model:
            ans = ollama_client.chat(f"Note title: {f.stem}\n\n{body[:3000]}", system=SYSTEM, json_mode=True)
            try:
                s = json.loads(ans or "{}")
                dest = s.get("destination") if s.get("destination") in CHOICES else "keep"
                line += f" → **{dest}**: {s.get('title', f.stem)} — {s.get('why', '')}"
            except ValueError:
                line += " → (no usable suggestion)"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
