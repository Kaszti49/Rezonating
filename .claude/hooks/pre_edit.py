#!/usr/bin/env python3
"""PreToolUse(Write|Edit): refuse edits that break a hard rule, before they happen.

1. Agent scope: a specialist may only write inside its folders (.claude/agent-scopes.json).
2. Raw data: never write *.wav, data/raw/ or data/private/.
3. Vault notes: no Templater code ('<%') outside 90 Meta/Templates.
4. Decisions: Claude never sets status: accepted, never puts itself in decided_by, never edits an
   accepted decision.
5. Daily notes: Claude never changes Kaszti's or Viktor's section.
Anything else is left to the normal permission flow. Fails open on internal errors.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rzlib  # noqa: E402


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
    sys.exit(0)


def new_content(tool: str, ti: dict, path: Path) -> str | None:
    if tool == "Write":
        return ti.get("content")
    if tool == "Edit":
        old = rzlib.read_text(path)
        if old is None:
            return None
        o, n = ti.get("old_string", ""), ti.get("new_string", "")
        if not o or o not in old:
            return None  # the edit will fail by itself
        return old.replace(o, n) if ti.get("replace_all") else old.replace(o, n, 1)
    return None


PEOPLE = {"Kaszti", "Viktor"}


def sections(text: str) -> dict[str, str]:
    """'## Heading' -> section text, for the daily-note ownership check."""
    out, cur, buf = {}, None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = line[3:].strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return out


def fm_of(text: str | None) -> dict:
    if not text:
        return {}
    fm, _ = rzlib.split_frontmatter(text)
    try:
        return rzlib.parse_frontmatter(fm) if fm else {}
    except rzlib.YamlError:
        return {}


def main() -> None:
    rzlib.utf8_stdio()
    data = rzlib.read_hook_input()
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    fp = ti.get("file_path")
    if not fp:
        return
    root = rzlib.git_root(data.get("cwd")) if data.get("cwd") else rzlib.ROOT
    relpath = rzlib.rel(fp, root)
    if relpath is None:
        return

    agent = data.get("agent_type") or ""
    scopes = json.loads(rzlib.read_text(rzlib.ROOT / ".claude" / "agent-scopes.json") or "{}")
    if agent in scopes and not agent.startswith("_"):
        allowed = scopes[agent]
        if not rzlib.glob_match(relpath, allowed):
            where = ", ".join(allowed) if allowed else "nothing (read-only agent)"
            deny(
                f"{agent} may only write to: {where}. '{relpath}' is outside that. "
                "Leave this change out and mention it in your report so the orchestrator can route it."
            )

    low = relpath.lower()
    if low.endswith(".wav") or low.startswith(("data/raw/", "data/private/")):
        deny("Raw recordings and the pseudonym list never get written by Claude (data/raw, data/private, *.wav).")

    content = new_content(tool, ti, Path(root) / relpath)
    if content is None:
        return

    if rzlib.is_vault_note(relpath) and "<%" in content:
        deny(
            "Vault notes must not contain '<%': Templater would execute it. Copy the template's "
            "properties and write plain values instead."
        )

    old_text = rzlib.read_text(Path(root) / relpath)
    if relpath.startswith("70 Journal/Daily/") and old_text is not None:
        before, after = sections(old_text), sections(content)
        touched = [h for h in set(before) | set(after) if h in PEOPLE and before.get(h) != after.get(h)]
        if touched:
            deny(
                f"Daily notes: write only under '## Claude'. This edit changes {', '.join(sorted(touched))}'s "
                "section. Leave it as it is and mention the problem (e.g. a typo) in your report instead."
            )

    if relpath.startswith("80 Decisions/") and relpath.endswith(".md"):
        new = fm_of(content)
        old = fm_of(old_text)
        if old.get("status") == "accepted" and old_text != content:
            deny(
                "Accepted decisions are a record; Claude doesn't edit them. To change one, propose a new decision "
                'with supersedes: "[[<old decision>]]" and tell Kaszti or Viktor.'
            )
        if new.get("status") == "accepted" and old.get("status") != "accepted":
            deny(
                "Only Kaszti or Viktor accept decisions. Write status: proposed (and decided_by: []); "
                "they flip it to accepted in Obsidian."
            )
        if old.get("status") == "accepted" and new.get("status") != "accepted":
            deny(
                "Changing the status of an accepted decision (e.g. to superseded) is Kaszti's or Viktor's call. "
                "Propose the new decision with 'supersedes' set and tell them."
            )
        db = new.get("decided_by")
        if isinstance(db, list) and "claude" in db:
            deny("decided_by lists people who decided: kaszti and/or viktor. Claude proposes, it doesn't decide.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # a broken guard must not block all editing
        print(f"pre_edit hook error (ignored): {e}", file=sys.stderr)
    sys.exit(0)
