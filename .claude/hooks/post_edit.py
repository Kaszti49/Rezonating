#!/usr/bin/env python3
"""PostToolUse(Write|Edit): format the file, check it, and remember who edited it.

- *.py (ml/, tools/, .claude/): `ruff format` when ruff is installed.
- firmware C/C++: `clang-format -i` when clang-format is installed (style: firmware/.clang-format).
- vault notes: property rules (vault_schema). Errors exit 2 so Claude sees them and fixes the note.
- schemas/ and packs/: `python tools/validate.py` when jsonschema is installed.
Every edit is recorded per session and agent, so the stop gates check only what that agent touched.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rzlib  # noqa: E402
import vault_schema  # noqa: E402

C_EXT = (".c", ".h", ".cpp", ".hpp", ".cc")


def quiet(cmd: list[str], cwd: Path, timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def main() -> int:
    rzlib.utf8_stdio()
    data = rzlib.read_hook_input()
    fp = (data.get("tool_input") or {}).get("file_path")
    if not fp:
        return 0
    root = rzlib.git_root(data.get("cwd")) if data.get("cwd") else rzlib.ROOT
    relpath = rzlib.rel(fp, root)
    if relpath is None:
        return 0
    rzlib.record_edit(data.get("session_id", ""), data.get("agent_id"), relpath)
    path = Path(root) / relpath

    if relpath.endswith(".py") and rzlib.glob_match(relpath, ["ml/**", "tools/**", ".claude/**"]):
        ruff = shutil.which("ruff")
        if ruff:
            quiet([ruff, "format", "--quiet", str(path)], root)
    elif relpath.startswith("firmware/") and relpath.endswith(C_EXT):
        cf = shutil.which("clang-format")
        if cf and (Path(root) / "firmware" / ".clang-format").exists():
            quiet([cf, "-i", "--style=file", str(path)], root)

    problems: list[str] = []
    if rzlib.is_vault_note(relpath):
        problems += [str(i) for i in vault_schema.check_file(relpath, Path(root)) if i.level == "error"]
    if rzlib.glob_match(relpath, ["schemas/**", "packs/**"]) and importlib.util.find_spec("jsonschema"):
        rc, out = quiet([sys.executable, "tools/validate.py"], root, 60)
        if rc != 0:
            problems.append("tools/validate.py failed:\n" + out.strip()[-2000:])
    if problems:
        print("The edit was saved, but it breaks project rules. Fix it now:\n" + "\n".join(problems), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"post_edit hook error (ignored): {e}", file=sys.stderr)
        sys.exit(0)
