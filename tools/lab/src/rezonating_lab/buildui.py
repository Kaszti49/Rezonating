"""``rzlab build-ui``: build the Svelte UI in ``tools/lab/web/`` into ``src/rezonating_lab/static/``.

The Vite config in ``web/`` must set ``build.outDir`` to ``../src/rezonating_lab/static`` (with
``emptyOutDir: true``); the server then serves it. The output folder is git-ignored.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parents[2]  # tools/lab
WEB_DIR = LAB_DIR / "web"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def find_npm() -> str | None:
    """Path of npm (npm.cmd on Windows), or None."""
    names = ("npm.cmd", "npm") if sys.platform == "win32" else ("npm",)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def build_ui(web_dir: Path = WEB_DIR, static_dir: Path = STATIC_DIR, npm: str | None = None) -> int:
    if not web_dir.is_dir() or not (web_dir / "package.json").is_file():
        print(
            f"rzlab build-ui: {web_dir} (with a package.json) does not exist. The browser UI is not in the repo yet.",
            file=sys.stderr,
        )
        return 1
    npm = npm or find_npm()
    if npm is None:
        print(
            "rzlab build-ui: npm was not found on PATH. Install Node.js (https://nodejs.org) and retry.",
            file=sys.stderr,
        )
        return 1
    for args in ([npm, "ci"], [npm, "run", "build"]):
        print(
            f"rzlab build-ui: {' '.join(Path(args[0]).name if i == 0 else a for i, a in enumerate(args))}", flush=True
        )
        try:
            rc = subprocess.run(args, cwd=web_dir, check=False).returncode
        except OSError as exc:
            print(f"rzlab build-ui: cannot run npm: {exc}", file=sys.stderr)
            return 1
        if rc != 0:
            print(f"rzlab build-ui: `{' '.join(args[1:])}` failed with exit code {rc}", file=sys.stderr)
            return rc
    if not (static_dir / "index.html").is_file():
        print(
            f"rzlab build-ui: the build finished but {static_dir / 'index.html'} is missing. "
            "Set build.outDir to '../src/rezonating_lab/static' in web/vite.config.",
            file=sys.stderr,
        )
        return 1
    print(f"rzlab build-ui: done, the UI is in {static_dir}")
    return 0
