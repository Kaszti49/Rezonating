#!/usr/bin/env python3
"""The automatic gate (escalation level L0): deterministic checks picked by which files changed.

Hooks call this after every specialist agent; people and agents can run it by hand:
  python .claude/scripts/checks.py                 # files with uncommitted changes
  python .claude/scripts/checks.py --files a b     # these files
  python .claude/scripts/checks.py --all           # everything (slow: full firmware build)
Exit code 1 when a check fails. A check whose tool isn't installed reports "skip", never "fail".

| Changed files                      | Check                                         |
| vault notes                        | vault_schema (errors only)                    |
| schemas/, packs/, data/**.json     | python tools/validate.py (needs jsonschema)   |
| *.py in ml/, tools/, .claude/      | ruff check; pytest in ml/ when tests exist    |
| firmware/                          | idf.py build (ESP-IDF via PATH or `eim run`)  |
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rzlib  # noqa: E402
import vault_schema  # noqa: E402

BUILD_TIMEOUT = int(os.environ.get("RZ_BUILD_TIMEOUT", "540"))


@dataclass
class Check:
    name: str
    result: str  # pass | fail | skip
    detail: str = ""


def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, timeout=timeout, env=dict(os.environ, PYTHONUTF8="1")
        )
        return p.returncode, (p.stdout + p.stderr).decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout} s"
    except OSError as e:
        return 127, str(e)


def _tail(out: str, n_err: int = 30, n_tail: int = 12) -> str:
    lines = out.splitlines()
    errs = [l for l in lines if re.search(r"error|Error|FAILED|failed|stopped|Traceback|assert", l)]
    picked = errs[:n_err] + ["…"] + lines[-n_tail:] if errs else lines[-n_tail:]
    return "\n".join(picked)[-3500:]


# ---------------------------------------------------------------- individual checks


def check_vault(paths: list[str], root: Path) -> Check | None:
    notes = [p for p in paths if rzlib.is_vault_note(p) and (root / p).exists()]
    if not notes:
        return None
    issues = [i for i in vault_schema.check_many(notes, root) if i.level == "error"]
    if issues:
        return Check("vault-schema", "fail", "\n".join(str(i) for i in issues[:40]))
    return Check("vault-schema", "pass", f"{len(notes)} notes")


def check_validate(paths: list[str], root: Path) -> Check | None:
    if not any(rzlib.glob_match(p, ["schemas/**", "packs/**", "data/**.json", "tools/validate.py"]) for p in paths):
        return None
    if importlib.util.find_spec("jsonschema") is None:
        return Check("validate", "skip", "jsonschema not installed (pip install -r tools/requirements.txt)")
    rc, out = _run([sys.executable, "tools/validate.py"], root, 120)
    return Check("validate", "pass" if rc == 0 else "fail", "" if rc == 0 else _tail(out))


def check_python(paths: list[str], root: Path) -> list[Check]:
    py = [
        p
        for p in paths
        if p.endswith(".py")
        and (root / p).exists()
        and rzlib.glob_match(p, ["ml/**", "tools/**", ".claude/**", "scratch/**"])
    ]
    out: list[Check] = []
    if not py:
        return out
    ruff = shutil.which("ruff")
    if ruff:
        rc, txt = _run([ruff, "check", "--quiet", *py], root, 120)
        out.append(Check("ruff", "pass" if rc == 0 else "fail", "" if rc == 0 else _tail(txt, 40, 5)))
    else:
        rc, txt = _run([sys.executable, "-m", "py_compile", *py], root, 60)
        out.append(Check("py-compile", "pass" if rc == 0 else "fail", "" if rc == 0 else _tail(txt)))
    if any(p.startswith("ml/") for p in py) and (root / "ml" / "tests").is_dir():
        if importlib.util.find_spec("pytest") is None:
            out.append(Check("pytest", "skip", "pytest not installed (pip install -e ml[dev])"))
        else:
            rc, txt = _run([sys.executable, "-m", "pytest", "-q", "-x", "ml/tests"], root, 300)
            out.append(Check("pytest", "pass" if rc == 0 else "fail", "" if rc == 0 else _tail(txt)))
    return out


def idf_build_command() -> list[str] | None:
    """ESP-IDF from an activated shell first, then the ESP-IDF Installation Manager."""
    if os.environ.get("IDF_PATH"):
        exe = shutil.which("idf.py")
        if exe:
            return [exe, "-C", "firmware", "build"]
    eim = shutil.which("eim")
    if eim:
        return [eim, "run", "idf.py -C firmware build"]
    return None


def check_firmware(paths: list[str], root: Path) -> Check | None:
    if not any(p.startswith("firmware/") for p in paths):
        return None
    if not (root / "firmware" / "CMakeLists.txt").exists():
        return Check("idf-build", "skip", "no firmware/CMakeLists.txt here")
    cmd = idf_build_command()
    if not cmd:
        return Check("idf-build", "skip", "ESP-IDF not found on this machine (no IDF_PATH + idf.py, no eim)")
    rc, out = _run(cmd, root, BUILD_TIMEOUT)
    if rc == 124:
        return Check("idf-build", "skip", f"build took longer than {BUILD_TIMEOUT} s; run it by hand")
    return Check("idf-build", "pass" if rc == 0 else "fail", "" if rc == 0 else _tail(out))


def run_checks(paths: list[str], root: Path | None = None) -> list[Check]:
    root = Path(root or rzlib.ROOT)
    paths = sorted(set(paths))
    results: list[Check] = []
    for c in (check_vault(paths, root), check_validate(paths, root)):
        if c:
            results.append(c)
    results += check_python(paths, root)
    fw = check_firmware(paths, root)
    if fw:
        results.append(fw)
    return results


def summary(results: list[Check]) -> str:
    return ", ".join(f"{c.name} {c.result}" for c in results) or "no checks apply"


def as_dicts(results: list[Check]) -> list[dict]:
    return [{k: v for k, v in asdict(c).items() if k != "detail"} for c in results]


def main(argv=None) -> int:
    rzlib.utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    if a.all:
        paths = vault_schema.all_notes() + ["schemas/x", "firmware/x"]
        paths += [rzlib.rel(p) for p in rzlib.ROOT.glob("ml/**/*.py")] + [
            rzlib.rel(p) for p in rzlib.ROOT.glob("tools/**/*.py")
        ]
    elif a.files:
        paths = [rzlib.rel(p) or p for p in a.files]
    else:
        paths = rzlib.dirty_files()
    results = run_checks([p for p in paths if p])
    for c in results:
        print(f"{c.name}: {c.result}" + (f"\n{c.detail}" if c.detail and c.result != "pass" else ""))
    print(summary(results))
    return 1 if any(c.result == "fail" for c in results) else 0


if __name__ == "__main__":
    sys.exit(main())
