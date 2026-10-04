#!/usr/bin/env python3
"""Stop: before the main session ends its turn, the vault notes it edited must pass the rules.

Blocks once with the errors; if they are still there on the next stop it lets the turn end and
warns the user instead (no loops). When the session itself runs as a specialist
(`claude --agent firmware-dev`, as the evals do), the specialist gate runs instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rzlib  # noqa: E402
import subagent_gate  # noqa: E402  (same folder)
import vault_schema  # noqa: E402


def main() -> int:
    rzlib.utf8_stdio()
    data = rzlib.read_hook_input()
    if data.get("agent_type") in subagent_gate.SPECIALISTS and not data.get("agent_id"):
        return subagent_gate.handle_specialist(data)

    root = rzlib.git_root(data.get("cwd"))
    notes = [
        p
        for p in rzlib.edits_by(data.get("session_id", ""), None)
        if rzlib.is_vault_note(p) and (Path(root) / p).exists()
    ]
    if not notes:
        return 0
    errors = [str(i) for i in vault_schema.check_many(notes, Path(root)) if i.level == "error"]
    if not errors:
        return 0
    if not data.get("stop_hook_active"):
        rzlib.emit(
            {
                "decision": "block",
                "reason": "Vault notes you edited break the property rules "
                "(10 Project/Vault rules.md). Fix them before finishing:\n" + "\n".join(errors[:30]),
            }
        )
    else:
        rzlib.emit({"systemMessage": "Rezonating: some notes still break the vault rules:\n" + "\n".join(errors[:10])})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"stop_gate error (ignored): {e}", file=sys.stderr)
        sys.exit(0)
