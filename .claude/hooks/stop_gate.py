#!/usr/bin/env python3
"""Stop: the L0 gate. Before the session ends its turn, the files it edited must pass the checks.

Runs `checks.py` (vault rules, validate.py, ruff/pytest, idf.py build: picked by path) on the files
Claude edited (Write/Edit, or any uncommitted file touched since the session started, which covers
edits made through Bash) since they last passed. On failure the turn is sent back with the
errors (decision: block), at most MAX_RETRIES times; after that it may stop, a gate-fail flag goes to
the ledger (evidence for the retro) and the person is told. Passing files are remembered by mtime, so
a long session doesn't rebuild the firmware on every turn. Fails open on internal errors.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import checks  # noqa: E402
import ledger  # noqa: E402
import rzlib  # noqa: E402

MAX_RETRIES = 2
OWN_FILES = ("90 Meta/Agents/Ledger/", ".claude/state/")  # written by the gate itself
PLAYBOOK_OF = [  # first match wins: which playbook a failing file belongs to (for the ledger)
    ("firmware/", "firmware"),
    ("packs/", "firmware"),
    ("ml/", "ml"),
    ("tools/", "ml"),
    ("schemas/", "ml"),
    (".claude/", "retro"),
]


def playbook_for(paths: list[str]) -> str:
    for p in paths:
        for prefix, name in PLAYBOOK_OF:
            if p.startswith(prefix):
                return name
    return "vault" if any(rzlib.is_vault_note(p) for p in paths) else "session"


def _state(session: str) -> Path:
    d = rzlib.STATE / "gate"
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]", "_", session)
    return d / f"stop-{safe}.json"


def _mtime(root: Path, p: str) -> float | None:
    try:
        return (root / p).stat().st_mtime
    except OSError:
        return None


def _changed_since_start(session: str, root: Path) -> list[str]:
    """Uncommitted files touched since the session started: edits made through Bash are not recorded (P-002).

    Older uncommitted work is left alone, and so are the files the gate writes itself."""
    start = rzlib.session_start_time(session)
    if start is None:
        return []
    return [p for p in rzlib.dirty_files(root) if not p.startswith(OWN_FILES) and (_mtime(root, p) or 0.0) >= start]


def main() -> int:
    rzlib.utf8_stdio()
    data = rzlib.read_hook_input()
    session = data.get("session_id", "")
    root = Path(rzlib.git_root(data.get("cwd")))
    state_file = _state(session)
    state = json.loads(rzlib.read_text(state_file) or "{}")
    passed: dict = state.get("passed", {})
    tries = int(state.get("tries", 0))

    todo = [
        p
        for p in dict.fromkeys(rzlib.edits_by(session, None) + _changed_since_start(session, root))
        if _mtime(root, p) is not None and passed.get(p) != _mtime(root, p)
    ]
    if not todo:
        return 0

    results = checks.run_checks(todo, root)
    failed = [c for c in results if c.result == "fail"]

    def save(n: int) -> None:
        if not failed:
            passed.update({p: _mtime(root, p) for p in todo})
        state_file.write_text(json.dumps({"passed": passed, "tries": n}), encoding="utf-8")

    if failed and tries < MAX_RETRIES:
        save(tries + 1)
        details = "\n\n".join(f"[{c.name}]\n{c.detail}" for c in failed)
        rzlib.emit(
            {
                "decision": "block",
                "reason": f"Rezonating gate (L0) failed, round {tries + 1} of {MAX_RETRIES}. Fix these before you "
                f"finish:\n\n{details}"[:9000],
            }
        )
        return 0

    gate = "fail" if failed else ("pass" if any(c.result == "pass" for c in results) else "skip")
    flag_id = None
    if failed:
        first = failed[0].detail.strip().splitlines()[:1]
        flag_id = ledger.add_flag(
            playbook_for(todo),
            "gate-fail",
            f"{failed[0].name} still failing after {MAX_RETRIES} fix rounds: " + (first[0][:200] if first else ""),
            "high",
            files=todo,
            session=session,
            by="gate",
        )
        passed.update({p: _mtime(root, p) for p in todo})  # flagged once; don't nag every turn
    save(0)
    ledger.add_run(
        {
            "agent": playbook_for(todo),
            "session": session,
            "gate": gate,
            "retries": tries,
            "edited": len(todo),
            "checks": checks.as_dicts(results),
            "flag": flag_id,
        }
    )
    if failed:
        rzlib.emit(
            {
                "systemMessage": f"Rezonating gate: checks still failing ({checks.summary(results)}); flag {flag_id} "
                "logged. Say so in the reply, and the retro will pick it up."
            }
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"stop_gate error (ignored): {e}", file=sys.stderr)
        sys.exit(0)
