#!/usr/bin/env python3
"""PostToolUse(Agent): tell the orchestrator what the gate and the verifier concluded.

subagent_gate.py queues one line per finished subagent; this hook hands the unread lines to the
main session as context next to the Agent tool result, and adds the run's telemetry (model,
duration, tool calls) to the ledger so the weekly retro can compare models.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rzlib  # noqa: E402


def describe(e: dict) -> str:
    if e.get("agent") == "verifier":
        s = f"verifier on {e.get('subject')}: VERDICT {e.get('verdict')}"
        if e.get("flags"):
            s += f"; logged {', '.join(e['flags'])}"
        if e.get("verdict") in ("FLAG", "BLOCK"):
            s += ". Next step per the escalation ladder: re-dispatch with these findings (L2) or escalate (L3)."
        if e.get("verdict") == "NONE":
            s += " (no VERDICT line found; ask the verifier again for its standard report format)"
        return s
    s = f"{e.get('agent')} gate: {e.get('gate')}"
    if e.get("checks"):
        s += f" ({e['checks']})"
    if e.get("retries"):
        s += f" after {e['retries']} fix round(s)"
    if e.get("flag"):
        s += f"; flag {e['flag']} logged. The gate is still failing: escalate (L3) or ask a human (L4)."
    for sk in e.get("skipped") or []:
        s += f"\n  not verified here: {sk}"
    if e.get("note"):
        s += f" ({e['note']})"
    return s


def main() -> int:
    rzlib.utf8_stdio()
    data = rzlib.read_hook_input()
    session = data.get("session_id", "")
    resp = data.get("tool_response")
    if isinstance(resp, dict) and resp.get("status") == "completed" and resp.get("agentId"):
        sub = (data.get("tool_input") or {}).get("subagent_type", "")
        rzlib.append_jsonl(
            rzlib.RUNS,
            {
                "ev": "telemetry",
                "ts": rzlib.now_iso(),
                "agent": sub,
                "agent_id": resp.get("agentId"),
                "model": resp.get("resolvedModel", ""),
                "requested_model": (data.get("tool_input") or {}).get("model", ""),
                "duration_ms": resp.get("totalDurationMs"),
                "tool_uses": resp.get("totalToolUseCount"),
            },
        )

    safe = re.sub(r"[^\w.-]", "_", session)
    queue = rzlib.STATE / "gate" / f"report-{safe}.jsonl"
    entries = rzlib.read_jsonl(queue)
    if not entries:
        return 0
    queue.unlink(missing_ok=True)
    text = "Agent system report (from hooks):\n" + "\n".join("- " + describe(e) for e in entries)
    rzlib.emit({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text[:9000]}})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"agent_report error (ignored): {e}", file=sys.stderr)
        sys.exit(0)
