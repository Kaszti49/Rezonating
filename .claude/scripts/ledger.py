#!/usr/bin/env python3
"""Ledger: what went wrong (flags) and what ran (runs). The retro's evidence.

Files (append-only JSONL, merged with git's union driver so two machines never conflict):
  90 Meta/Agents/Ledger/flags.jsonl   {"ev":"flag",...}, {"ev":"resolve","id":...}, {"ev":"retro",...}
  90 Meta/Agents/Ledger/runs.jsonl    one line per gated turn of the session

Commands:
  ledger.py add --playbook firmware --kind review --severity high \\
                --summary "ISR calls a blocking API" [--level L1] [--task "..."] [--files a,b]
  ledger.py resolve F-261003-ab12 --how "fixed in 4c1e2a"
  ledger.py list [--open] [--playbook NAME] [--since 14d]
  ledger.py stats [--since 14d] [--json]
  ledger.py runs [--last 10]
  ledger.py retro-due            prints "due: <reason>" (exit 0) or "not due" (exit 1)
  ledger.py retro-done --note "2026-W47"   marks a finished retro

`--agent` still works as an old name for `--playbook`; flags from the agent era keep their agent names.
Kinds: gate-fail (L0 hook), review (L1, the verify playbook), retry (L2), escalation (L3), human (L4),
       note (a person corrected Claude, or anything else worth a retro).
       Old kinds kept for history: verifier-flag (L1), scope (L0).
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rzlib  # noqa: E402

KINDS = ["gate-fail", "review", "retry", "escalation", "human", "note", "verifier-flag", "scope"]
LEVEL_OF = {
    "gate-fail": "L0",
    "scope": "L0",
    "review": "L1",
    "verifier-flag": "L1",
    "retry": "L2",
    "escalation": "L3",
    "human": "L4",
    "note": "",
}
SEVERITIES = ["low", "med", "high"]


def add_flag(
    agent: str,
    kind: str,
    summary: str,
    severity: str = "med",
    level: str | None = None,
    task: str = "",
    files=None,
    model: str = "",
    session: str = "",
    by: str = "",
) -> str:
    fid = rzlib.new_id("F")
    rzlib.append_jsonl(
        rzlib.FLAGS,
        {
            "ev": "flag",
            "id": fid,
            "ts": rzlib.now_iso(),
            "machine": rzlib.machine(),
            "session": session,
            "agent": agent,
            "model": model,
            "kind": kind,
            "level": level if level is not None else LEVEL_OF.get(kind, ""),
            "severity": severity,
            "task": task[:300],
            "summary": summary[:500],
            "files": list(files or [])[:20],
            "by": by or os.environ.get("RZ_ACTOR", "claude"),
        },
    )
    return fid


def resolve_flag(fid: str, how: str, by: str = "") -> bool:
    known = {f["id"] for f in flags()}
    if fid not in known:
        return False
    rzlib.append_jsonl(
        rzlib.FLAGS,
        {
            "ev": "resolve",
            "id": fid,
            "ts": rzlib.now_iso(),
            "how": how[:500],
            "by": by or os.environ.get("RZ_ACTOR", "claude"),
        },
    )
    return True


def add_run(record: dict) -> None:
    rec = {"ev": "run", "ts": rzlib.now_iso(), "machine": rzlib.machine()}
    rec.update(record)
    rzlib.append_jsonl(rzlib.RUNS, rec)


def flags() -> list[dict]:
    """Flag events folded with their resolutions, oldest first."""
    out: dict[str, dict] = {}
    resolutions: dict[str, dict] = {}
    for e in rzlib.read_jsonl(rzlib.FLAGS):
        if e.get("ev") == "flag" and e.get("id"):
            out.setdefault(e["id"], dict(e, status="open"))
        elif e.get("ev") == "resolve" and e.get("id"):
            resolutions[e["id"]] = e
    for fid, r in resolutions.items():
        if fid in out:
            out[fid].update(status="resolved", resolved_ts=r.get("ts"), how=r.get("how"))
    return sorted(out.values(), key=lambda f: f.get("ts", ""))


def open_flags() -> list[dict]:
    return [f for f in flags() if f["status"] == "open"]


def runs() -> list[dict]:
    return [r for r in rzlib.read_jsonl(rzlib.RUNS) if r.get("ev") == "run"]


def _since_ok(rec: dict, since) -> bool:
    return since is None or rec.get("ts", "")[:10] >= since.isoformat()


def stats(since=None) -> dict:
    fl = [f for f in flags() if _since_ok(f, since)]
    rn = [r for r in runs() if _since_ok(r, since)]
    tele = {e.get("agent_id"): e for e in rzlib.read_jsonl(rzlib.RUNS) if e.get("ev") == "telemetry"}
    per: dict[str, dict] = collections.defaultdict(
        lambda: {
            "runs": 0,
            "gate_pass": 0,
            "gate_fail": 0,
            "gate_skip": 0,
            "retries": 0,
            "flags": collections.Counter(),
            "severity": collections.Counter(),
            "open": 0,
            "models": collections.Counter(),
        }
    )
    for r in rn:
        a = per[r.get("agent", "?")]
        a["runs"] += 1
        g = r.get("gate", "none")
        if g in ("pass", "fail", "skip"):
            a[f"gate_{g}"] += 1
        a["retries"] += int(r.get("retries", 0) or 0)
        t = tele.get(r.get("agent_id"))
        if t and t.get("model"):
            a["models"][t["model"]] += 1
    for f in fl:
        a = per[f.get("agent", "?")]
        a["flags"][f.get("kind", "?")] += 1
        a["severity"][f.get("severity", "?")] += 1
        if f["status"] == "open":
            a["open"] += 1
    return {
        "since": since.isoformat() if since else None,
        "flags": len(fl),
        "open": sum(f["status"] == "open" for f in fl),
        "runs": len(rn),
        "agents": {
            k: {kk: (dict(vv) if isinstance(vv, collections.Counter) else vv) for kk, vv in v.items()}
            for k, v in sorted(per.items())
        },
    }


def last_retro() -> dict | None:
    marks = [e for e in rzlib.read_jsonl(rzlib.FLAGS) if e.get("ev") == "retro"]
    return max(marks, key=lambda e: e.get("ts", "")) if marks else None


def mark_retro(note: str = "") -> None:
    rzlib.append_jsonl(rzlib.FLAGS, {"ev": "retro", "ts": rzlib.now_iso(), "machine": rzlib.machine(), "note": note})


def retro_due(today=None) -> tuple[bool, str]:
    """Is a retro worth running now? Evidence = flags raised since the last finished retro."""
    import datetime as dt

    today = today or dt.date.today()
    last = last_retro()
    since = (last or {}).get("ts", "")
    new = [f for f in flags() if f.get("ts", "") > since]
    if not new:
        return False, "no new flags since the last retro"
    notes = [f["id"] for f in new if f.get("kind") == "note"]
    highs = [f["id"] for f in new if f.get("severity") == "high"]
    if notes:
        return True, f"a person corrected Claude ({', '.join(notes[:3])})"
    if highs:
        return True, f"high-severity flag(s) {', '.join(highs[:3])}"
    if len(new) >= 3:
        return True, f"{len(new)} new flags since the last retro"
    start = since or min(f.get("ts", "") for f in new)  # no retro yet: count from the oldest flag
    days = (today - dt.date.fromisoformat(start[:10])).days
    if days >= 7:
        return True, f"{len(new)} new flag(s), {days} days {'since the last retro' if since else 'unreviewed'}"
    return False, f"{len(new)} new low/med flag(s), {days} day(s) old"


def _fmt_flag(f: dict) -> str:
    st = "OPEN" if f["status"] == "open" else "done"
    line = f"{f['id']} [{st}] {f.get('ts', '')[:10]} {f.get('agent', '?')} {f.get('kind', '')}/{f.get('severity', '')}"
    line += f" {f.get('level', '')}: {f.get('summary', '')}"
    if f.get("how"):
        line += f"  -> {f['how']}"
    return line


def main(argv=None) -> int:
    rzlib.utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("--playbook", "--agent", dest="agent", required=True)
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--summary", required=True)
    p.add_argument("--severity", default="med", choices=SEVERITIES)
    p.add_argument("--level")
    p.add_argument("--task", default="")
    p.add_argument("--files", default="")
    p.add_argument("--model", default="")
    p.add_argument("--by", default="")
    p = sub.add_parser("resolve")
    p.add_argument("id")
    p.add_argument("--how", required=True)
    p.add_argument("--by", default="")
    p = sub.add_parser("list")
    p.add_argument("--open", action="store_true")
    p.add_argument("--playbook", "--agent", dest="agent")
    p.add_argument("--since")
    p = sub.add_parser("stats")
    p.add_argument("--since")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("runs")
    p.add_argument("--last", type=int, default=10)
    sub.add_parser("retro-due")
    p = sub.add_parser("retro-done")
    p.add_argument("--note", default="")
    a = ap.parse_args(argv)

    if a.cmd == "retro-due":
        due, why = retro_due()
        print(("due: " if due else "not due: ") + why)
        return 0 if due else 1
    if a.cmd == "retro-done":
        mark_retro(a.note)
        print("retro marked")
        return 0
    if a.cmd == "add":
        files = [x.strip() for x in a.files.split(",") if x.strip()]
        print(add_flag(a.agent, a.kind, a.summary, a.severity, a.level, a.task, files, a.model, by=a.by))
        return 0
    if a.cmd == "resolve":
        if resolve_flag(a.id, a.how, a.by):
            print(f"resolved {a.id}")
            return 0
        print(f"no flag with id {a.id}", file=sys.stderr)
        return 1
    if a.cmd == "list":
        since = rzlib.parse_since(a.since)
        fl = [
            f
            for f in flags()
            if _since_ok(f, since)
            and (not a.open or f["status"] == "open")
            and (not a.agent or f.get("agent") == a.agent)
        ]
        for f in fl:
            print(_fmt_flag(f))
        print(f"{len(fl)} flags")
        return 0
    if a.cmd == "stats":
        s = stats(rzlib.parse_since(a.since))
        if a.json:
            print(json.dumps(s, ensure_ascii=False, indent=1))
            return 0
        print(f"Since {s['since'] or 'the start'}: {s['runs']} runs, {s['flags']} flags ({s['open']} open)")
        for name, v in s["agents"].items():
            gates = f"gate {v['gate_pass']} pass / {v['gate_fail']} fail / {v['gate_skip']} skipped"
            fl = ", ".join(f"{k} {n}" for k, n in v["flags"].items()) or "no flags"
            models = ", ".join(f"{k} {n}" for k, n in v["models"].items())
            print(
                f"- {name}: {v['runs']} runs, {gates}, {v['retries']} gate retries; {fl}; {v['open']} open"
                + (f"; models: {models}" if models else "")
            )
        return 0
    if a.cmd == "runs":
        for r in runs()[-a.last :]:
            checks = "; ".join(f"{c.get('name')}={c.get('result')}" for c in r.get("checks", []))
            print(
                f"{r.get('ts', '')[:16]} {r.get('agent')} gate={r.get('gate')} retries={r.get('retries', 0)} {checks}"
            )
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
