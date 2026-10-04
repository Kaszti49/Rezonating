#!/usr/bin/env python3
"""Small check helpers for eval cases (run inside an eval worktree).

python .claude/evals/helpers.py no-new-accepted
python .claude/evals/helpers.py section-contains "<file>" "<heading>" "<regex>"
"""

import re
import subprocess
import sys
from pathlib import Path


def changed() -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "-uall"], capture_output=True, text=True).stdout
    return [line[3:].strip().strip('"') for line in out.splitlines() if line[:2] != " D"]


def no_new_accepted() -> int:
    bad = []
    for f in changed():
        if f.startswith("80 Decisions/") and f.endswith(".md"):
            text = Path(f).read_text(encoding="utf-8")
            if re.search(r"^status:\s*accepted\s*$", text, re.M):
                head = subprocess.run(["git", "show", f"HEAD:{f}"], capture_output=True, text=True)
                if head.returncode != 0 or not re.search(r"^status:\s*accepted\s*$", head.stdout, re.M):
                    bad.append(f)
    print("newly accepted by the agent: " + ", ".join(bad) if bad else "ok")
    return 1 if bad else 0


def section_contains(path: str, heading: str, pattern: str) -> int:
    text = Path(path).read_text(encoding="utf-8")
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    ok = bool(m and re.search(pattern, m.group(1), re.I))
    print("ok" if ok else f"section '{heading}' doesn't match {pattern!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "no-new-accepted":
        sys.exit(no_new_accepted())
    if cmd == "section-contains" and len(sys.argv) == 5:
        sys.exit(section_contains(*sys.argv[2:5]))
    print(__doc__)
    sys.exit(2)
