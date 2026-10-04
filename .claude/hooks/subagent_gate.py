#!/usr/bin/env python3
"""SubagentStop: the L0 gate for specialist agents, and verdict logging for the verifier.

Specialists: run the checks for the files this agent edited (checks.py). On failure the agent is
sent back to fix it (decision: block) up to MAX_RETRIES times; after that it may stop, a
gate-fail flag goes to the ledger and the orchestrator is told to escalate.
Verifier: parse "VERDICT:" and "- [high|med|low] ..." finding lines from its report and log
each finding as a verifier-flag against the agent named on its "SUBJECT:" line.
Every run is appended to 90 Meta/Agents/Ledger/runs.jsonl.
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
SPECIALISTS = {"firmware-dev", "ml-dev", "deep-engineer", "researcher", "writer", "vault-keeper", "curator"}
FINDING_RE = re.compile(r"^\s*[-*]\s*\[(high|med|medium|low)\]\s*(.+)$", re.I | re.M)


def _state(name: str) -> Path:
    d = rzlib.STATE / "gate"
    d.mkdir(parents=True, exist_ok=True)
    return d / re.sub(r"[^\w.-]", "_", name)


def report(session: str, entry: dict) -> None:
    """Queue a line for agent_report.py to hand to the orchestrator."""
    rzlib.append_jsonl(_state(f"report-{session}.jsonl"), dict(entry, ts=rzlib.now_iso()))


def handle_verifier(data: dict) -> int:
    msg = data.get("last_assistant_message") or ""
    session = data.get("session_id", "")
    m = re.search(r"VERDICT:\s*\**\s*(PASS|FLAG|BLOCK)", msg, re.I)
    verdict = m.group(1).upper() if m else "NONE"
    sm = re.search(r"SUBJECT:\s*\**\s*([\w-]+)", msg)
    subject = sm.group(1) if sm else "unknown"
    ids = []
    if verdict in ("FLAG", "BLOCK"):
        for sev, text in FINDING_RE.findall(msg)[:10]:
            sev = "med" if sev.lower().startswith("med") else sev.lower()
            ids.append(ledger.add_flag(subject, "verifier-flag", text.strip(), sev, session=session, by="verifier"))
        if not ids:
            ids.append(
                ledger.add_flag(
                    subject,
                    "verifier-flag",
                    f"verifier said {verdict} (no itemised findings)",
                    "high" if verdict == "BLOCK" else "med",
                    session=session,
                    by="verifier",
                )
            )
    ledger.add_run(
        {
            "agent": "verifier",
            "agent_id": data.get("agent_id"),
            "session": session,
            "gate": "none",
            "verdict": verdict,
            "subject": subject,
            "flags": ids,
        }
    )
    report(
        session,
        {"agent": "verifier", "agent_id": data.get("agent_id"), "verdict": verdict, "subject": subject, "flags": ids},
    )
    return 0


def handle_specialist(data: dict) -> int:
    agent = data.get("agent_type", "")
    session = data.get("session_id", "")
    agent_id = data.get("agent_id") or f"main-{session}"  # main session started with --agent
    root = rzlib.git_root(data.get("cwd"))
    edited = rzlib.edits_by(session, data.get("agent_id"))
    if not edited:
        ledger.add_run(
            {"agent": agent, "agent_id": agent_id, "session": session, "gate": "none", "edited": 0, "retries": 0}
        )
        report(session, {"agent": agent, "agent_id": agent_id, "gate": "none", "note": "no file edits"})
        return 0

    results = checks.run_checks(edited, root)
    failed = [c for c in results if c.result == "fail"]
    counter = _state(f"retries-{agent_id}.json")
    tries = json.loads(rzlib.read_text(counter) or '{"n": 0}').get("n", 0)

    if failed and tries < MAX_RETRIES:
        counter.write_text(json.dumps({"n": tries + 1}), encoding="utf-8")
        details = "\n\n".join(f"[{c.name}]\n{c.detail}" for c in failed)
        rzlib.emit(
            {
                "decision": "block",
                "reason": f"Automatic gate (L0) failed, attempt {tries + 1} of {MAX_RETRIES}. Fix these before you finish, "
                f"then stop again:\n\n{details}",
            }
        )
        return 0

    gate = "fail" if failed else ("pass" if any(c.result == "pass" for c in results) else "skip")
    flag_id = None
    if failed:
        first = failed[0].detail.strip().splitlines()[:1]
        flag_id = ledger.add_flag(
            agent,
            "gate-fail",
            f"{failed[0].name} still failing after {MAX_RETRIES} fixes: " + (first[0][:200] if first else ""),
            "high",
            files=edited,
            session=session,
            by="gate",
        )
    ledger.add_run(
        {
            "agent": agent,
            "agent_id": agent_id,
            "session": session,
            "gate": gate,
            "retries": tries,
            "edited": len(edited),
            "checks": checks.as_dicts(results),
            "flag": flag_id,
        }
    )
    report(
        session,
        {
            "agent": agent,
            "agent_id": agent_id,
            "gate": gate,
            "retries": tries,
            "checks": checks.summary(results),
            "flag": flag_id,
            "skipped": [f"{c.name}: {c.detail}" for c in results if c.result == "skip"],
        },
    )
    if counter.exists():
        counter.unlink()
    if failed:
        rzlib.emit(
            {
                "systemMessage": f"Rezonating gate: {agent} finished with failing checks "
                f"({checks.summary(results)}); flag {flag_id} logged."
            }
        )
    return 0


def main() -> int:
    rzlib.utf8_stdio()
    data = rzlib.read_hook_input()
    agent = data.get("agent_type", "")
    if agent == "verifier":
        return handle_verifier(data)
    if agent in SPECIALISTS:
        return handle_specialist(data)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"subagent_gate error (ignored): {e}", file=sys.stderr)
        sys.exit(0)
