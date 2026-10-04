#!/usr/bin/env python3
"""Commit guard. Two entry points, one rule set:

- PreToolUse(Bash|PowerShell): checks a `git commit` Claude is about to run.
- `python .claude/hooks/commit_guard.py --git-hook`: called by .githooks/pre-commit for people
  (enable once per clone: git config core.hooksPath .githooks).

Rules: never commit raw recordings (*.wav, data/raw/, data/private/). Claude never mixes vault
notes and code in one commit (for people that's only a warning).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rzlib  # noqa: E402

COMMIT_RE = re.compile(r"\bgit\b(?:\s+-[Cc]\s+(?:\"[^\"]*\"|'[^']*'|\S+))*\s+commit\b")
ADD_RE = re.compile(r"\bgit\b(?:\s+-[Cc]\s+\S+)*\s+add\b")


def forbidden(files: list[str]) -> list[str]:
    return [f for f in files if f.lower().endswith(".wav") or f.startswith(("data/raw/", "data/private/"))]


def split_kinds(files: list[str]) -> tuple[list[str], list[str]]:
    vault = [f for f in files if rzlib.is_vault_path(f)]
    code = [f for f in files if not rzlib.is_vault_path(f)]
    return vault, code


def tracked_modified(root: Path) -> list[str]:
    rc, out = rzlib.git(["diff", "--name-only", "-z", "--diff-filter=ACMR"], cwd=root)
    return [f for f in out.split("\0") if f] if rc == 0 else []


def deny(reason: str) -> None:
    rzlib.emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def as_tool_hook() -> int:
    data = rzlib.read_hook_input()
    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    if not COMMIT_RE.search(cmd):
        return 0
    if ADD_RE.search(cmd):
        deny(
            "Run `git add …` as its own command first, then `git commit` separately, so the commit "
            "guard can see exactly what is staged."
        )
        return 0
    root = rzlib.git_root(data.get("cwd"))
    files = rzlib.staged_files(root)
    if re.search(r"\scommit\b[^|;&]*\s(-a\b|--all\b|-[a-zA-Z]*a[a-zA-Z]*\b)", cmd):
        files = sorted(set(files) | set(tracked_modified(root)))
    bad = forbidden(files)
    if bad:
        deny("Raw recordings never go in git: " + ", ".join(bad[:10]) + ". Unstage them (git restore --staged …).")
        return 0
    vault, code = split_kinds(files)
    if vault and code:
        deny(
            f"This commit mixes {len(vault)} vault file(s) and {len(code)} code file(s). Commit them separately "
            f"(vault e.g. {vault[0]!r}; code e.g. {code[0]!r}): `git restore --staged <files>` then two commits."
        )
    return 0


def as_git_hook() -> int:
    files = rzlib.staged_files(rzlib.ROOT)
    bad = forbidden(files)
    if bad:
        print("Rezonating: raw recordings never go in git. Unstage these:\n  " + "\n  ".join(bad), file=sys.stderr)
        return 1
    vault, code = split_kinds(files)
    if vault and code:
        print(
            f"Rezonating: note: this commit mixes vault notes ({len(vault)}) and code ({len(code)}). Fine if intended.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    rzlib.utf8_stdio()
    try:
        sys.exit(as_git_hook() if "--git-hook" in sys.argv else as_tool_hook())
    except SystemExit:
        raise
    except Exception as e:
        print(f"commit_guard error (ignored): {e}", file=sys.stderr)
        sys.exit(0)
