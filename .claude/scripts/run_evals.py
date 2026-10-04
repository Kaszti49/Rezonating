#!/usr/bin/env python3
"""Run agent eval cases with headless Claude Code (your subscription, no API key).

  python .claude/scripts/run_evals.py --list
  python .claude/scripts/run_evals.py --agent vault-keeper              # baseline: current config
  python .claude/scripts/run_evals.py --agent vault-keeper --case done-needs-date
  python .claude/scripts/run_evals.py --agent researcher --candidate "90 Meta/Agents/Proposals/P-001 x.md"
  python .claude/scripts/run_evals.py --all --dry-run                   # set up, don't call Claude

Each case runs in a throwaway git worktree in the system temp folder (rz-evals/): HEAD's files plus the current
(uncommitted) agent configuration, plus the case's setup files. With --candidate, a proposal's
```diff block is applied with `git apply` (or an .md file replaces the agent's definition). Then
`claude -p <prompt> --agent <agent>` runs there and the case's checks are evaluated.
Results: .claude/evals/results/*.json (gitignored) and one line in 90 Meta/Agents/Evals/Eval log.md.

Case file: .claude/evals/cases/<agent>/<name>.json
  {"description": "...", "prompt": "...", "max_turns": 20, "requires": ["idf", "ruff", "py:pytest"],
   "allowed_tools": ["Read", "Edit", "Write", "Glob", "Grep"],
   "setup": {"files": {"path": "content"}, "replace": [{"path": "...", "old": "...", "new": "..."}]},
   "checks": [{"type": "file_exists", "path": "..."},
              {"type": "file_contains" | "file_not_contains", "path": "...", "pattern": "regex"},
              {"type": "output_contains" | "output_not_contains", "pattern": "regex"},
              {"type": "vault_schema", "paths": ["glob", ...]},
              {"type": "unchanged", "paths": ["glob", ...]},
              {"type": "changed_only", "paths": ["glob", ...]},
              {"type": "command", "run": ["python", "..."], "expect_rc": 0}]}
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks as gate  # noqa: E402
import rzlib  # noqa: E402
import vault_schema  # noqa: E402

CASES = rzlib.ROOT / ".claude" / "evals" / "cases"
# Outside the repo: Claude Code treats any path under a .claude/ folder as protected config.
WORK = Path(tempfile.gettempdir()) / "rz-evals"
RESULTS = rzlib.ROOT / ".claude" / "evals" / "results"
EVAL_LOG = rzlib.ROOT / "90 Meta" / "Agents" / "Evals" / "Eval log.md"
CONFIG_PATHS = [
    ".claude/agents",
    ".claude/skills",
    ".claude/rules",
    ".claude/hooks",
    ".claude/scripts",
    ".claude/settings.json",
    ".claude/agent-scopes.json",
    "CLAUDE.md",
    "firmware/CLAUDE.md",
    "ml/CLAUDE.md",
    "ruff.toml",
]
DEFAULT_TOOLS = [
    "Read",
    "Edit",
    "Write",
    "Glob",
    "Grep",
    "Bash(python .claude/scripts/*)",
    "Bash(git status*)",
    "Bash(git diff*)",
]


def load_cases(agent: str | None = None, case: str | None = None) -> list[dict]:
    out = []
    for f in sorted(CASES.glob("*/*.json")):
        c = json.loads(f.read_text(encoding="utf-8"))
        c.setdefault("agent", f.parent.name)
        c["name"] = f.stem
        c["file"] = rzlib.rel(f)
        if (agent is None or c["agent"] == agent) and (case is None or c["name"] == case):
            out.append(c)
    return out


def missing_requirements(case: dict) -> list[str]:
    miss = []
    for r in case.get("requires", []):
        if r == "idf":
            if not gate.idf_build_command():
                miss.append("ESP-IDF")
        elif r.startswith("py:"):  # an importable Python module, e.g. py:pytest
            if importlib.util.find_spec(r[3:]) is None:
                miss.append(f"Python module {r[3:]}")
        elif not shutil.which(r):
            miss.append(r)
    return miss


def git(args: list[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True)
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", errors="replace")


def make_worktree(name: str) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    wt = WORK / name
    if wt.exists():
        git(["worktree", "remove", "--force", str(wt)], rzlib.ROOT)
        shutil.rmtree(wt, ignore_errors=True)
    rc, out = git(["worktree", "add", "--detach", str(wt), "HEAD"], rzlib.ROOT)
    if rc != 0:
        raise RuntimeError(f"git worktree add failed: {out}")
    for p in CONFIG_PATHS:  # current, possibly uncommitted, agent configuration
        src, dst = rzlib.ROOT / p, wt / p
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        elif src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    no_mcp = wt / ".claude" / "evals" / "no-mcp.json"
    no_mcp.parent.mkdir(parents=True, exist_ok=True)
    no_mcp.write_text('{"mcpServers": {}}', encoding="utf-8")
    return wt


def apply_candidate(wt: Path, agent: str, candidate: Path) -> str:
    text = candidate.read_text(encoding="utf-8")
    m = re.search(r"```diff\s*\n(.*?)```", text, re.S)
    if m:
        patch = wt / ".claude" / "evals" / "candidate.patch"
        patch.parent.mkdir(parents=True, exist_ok=True)
        patch.write_text(m.group(1), encoding="utf-8")
        rc, out = git(["apply", "--whitespace=nowarn", str(patch)], wt)
        patch.unlink()
        if rc != 0:
            raise RuntimeError(f"candidate diff doesn't apply: {out.strip()}")
        return f"diff from {candidate.name}"
    shutil.copy2(candidate, wt / ".claude" / "agents" / f"{agent}.md")
    return f"agent file {candidate.name}"


def snapshot(wt: Path) -> None:
    git(["add", "-A"], wt)
    git(
        [
            "-c",
            "user.name=eval",
            "-c",
            "user.email=eval@localhost",
            "commit",
            "-q",
            "--no-verify",
            "-m",
            "eval setup",
            "--allow-empty",
        ],
        wt,
    )


def changed_files(wt: Path) -> list[str]:
    files = rzlib.dirty_files(wt)
    return [f for f in files if not f.startswith((".claude/state/", "90 Meta/Agents/Ledger/"))]


def run_claude(case: dict, wt: Path, timeout: int) -> dict:
    exe = shutil.which("claude")
    if not exe:
        return {"error": "claude not on PATH"}
    empty_mcp = wt / ".claude" / "evals" / "no-mcp.json"
    cmd = [
        exe,
        "-p",
        case["prompt"],
        "--agent",
        case["agent"],
        "--output-format",
        "json",
        "--max-turns",
        str(case.get("max_turns", 20)),
        "--permission-mode",
        "acceptEdits",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--mcp-config",
        str(empty_mcp),
        "--allowedTools",
        *case.get("allowed_tools", DEFAULT_TOOLS),
    ]
    if case.get("model"):
        cmd += ["--model", case["model"]]
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd, cwd=str(wt), capture_output=True, timeout=timeout, env=dict(os.environ, RZ_EVAL="1", PYTHONUTF8="1")
        )
    except subprocess.TimeoutExpired:
        return {"error": f"timed out after {timeout} s", "seconds": round(time.time() - t0)}
    out = p.stdout.decode("utf-8", errors="replace")
    try:
        data = json.loads(out)
    except ValueError:
        data = {"result": out, "is_error": True, "stderr": p.stderr.decode("utf-8", errors="replace")[-2000:]}
    data["seconds"] = round(time.time() - t0)
    return data


def evaluate(case: dict, wt: Path, output: str) -> list[dict]:
    results = []
    changed = changed_files(wt)
    for chk in case.get("checks", []):
        t, ok, why = chk["type"], False, ""
        path = wt / chk["path"] if "path" in chk else None
        if t == "file_exists":
            ok = path.exists()
        elif t == "file_absent":
            ok = not path.exists()
        elif t in ("file_contains", "file_not_contains"):
            txt = rzlib.read_text(path) or ""
            found = re.search(chk["pattern"], txt, re.M) is not None
            ok = found if t == "file_contains" else not found
        elif t in ("output_contains", "output_not_contains"):
            found = re.search(chk["pattern"], output or "", re.M | re.I) is not None
            ok = found if t == "output_contains" else not found
        elif t == "vault_schema":
            notes = [f for f in vault_schema.all_notes(wt) if rzlib.glob_match(f, chk["paths"])]
            errs = [str(i) for i in vault_schema.check_many(notes, wt) if i.level == "error"]
            ok, why = (bool(notes) and not errs), ("; ".join(errs[:3]) or ("no matching notes" if not notes else ""))
        elif t == "unchanged":
            hit = [f for f in changed if rzlib.glob_match(f, chk["paths"])]
            ok, why = not hit, ", ".join(hit[:5])
        elif t == "changed_only":
            extra = [f for f in changed if not rzlib.glob_match(f, chk["paths"])]
            ok, why = not extra, ", ".join(extra[:5])
        elif t == "command":
            p = subprocess.run(chk["run"], cwd=str(wt), capture_output=True)
            ok = p.returncode == chk.get("expect_rc", 0)
            why = (p.stdout + p.stderr).decode("utf-8", errors="replace")[-300:] if not ok else ""
        else:
            why = f"unknown check type {t}"
        results.append({"check": {k: v for k, v in chk.items() if k != "run"} | {"type": t}, "pass": ok, "why": why})
    return results


def log_line(agent: str, candidate: str, passed: int, total: int, failed: list[str]) -> None:
    if not EVAL_LOG.exists():
        return
    line = (
        f"| {rzlib.today()} | {rzlib.machine()} | {agent} | {candidate or 'baseline'} | {passed}/{total} | "
        f"{', '.join(failed) or '—'} |\n"
    )
    with open(EVAL_LOG, "a", encoding="utf-8", newline="\n") as f:
        f.write(line)


def main(argv=None) -> int:
    rzlib.utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--agent")
    ap.add_argument("--case")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--candidate", help="proposal note with a ```diff block, or a replacement agent .md")
    ap.add_argument("--keep", action="store_true", help="keep the worktrees for inspection")
    ap.add_argument("--dry-run", action="store_true", help="set up worktrees and checks, don't call Claude")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args(argv)

    cases = load_cases(a.agent, a.case)
    if a.list or not (a.agent or a.all):
        for c in load_cases():
            print(f"{c['agent']:14} {c['name']:28} {c.get('description', '')}")
        return 0
    if not cases:
        print("no matching cases", file=sys.stderr)
        return 1
    candidate = Path(a.candidate) if a.candidate else None
    if candidate and not candidate.is_absolute():
        candidate = rzlib.ROOT / candidate
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report, by_agent = [], {}
    for c in cases:
        miss = missing_requirements(c)
        if miss:
            print(f"SKIP {c['agent']}/{c['name']}: needs {', '.join(miss)}")
            report.append({"case": c["name"], "agent": c["agent"], "skipped": miss})
            continue
        wt = make_worktree(f"{stamp}-{c['agent']}-{c['name']}")
        cand_desc = ""
        try:
            if candidate:
                cand_desc = apply_candidate(wt, c["agent"], candidate)
            for rel_path, content in (c.get("setup", {}).get("files") or {}).items():
                p = wt / rel_path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8", newline="\n")
            for rep in c.get("setup", {}).get("replace") or []:
                p = wt / rep["path"]
                txt = p.read_text(encoding="utf-8")
                if rep["old"] not in txt:
                    raise RuntimeError(f"setup replace: {rep['old']!r} not found in {rep['path']}")
                p.write_text(txt.replace(rep["old"], rep["new"], 1), encoding="utf-8", newline="\n")
            snapshot(wt)
            run = {"result": "", "dry_run": True} if a.dry_run else run_claude(c, wt, a.timeout)
            output = run.get("result", "") or ""
            checks = evaluate(c, wt, output) if not a.dry_run else []
            ok = (not run.get("error")) and (not run.get("is_error")) and all(x["pass"] for x in checks)
            rec = {
                "case": c["name"],
                "agent": c["agent"],
                "candidate": cand_desc,
                "pass": ok,
                "checks": checks,
                "turns": run.get("num_turns"),
                "cost_usd": run.get("total_cost_usd"),
                "seconds": run.get("seconds"),
                "error": run.get("error"),
                "output": output[-4000:],
            }
            report.append(rec)
            mark = "DRY " if a.dry_run else ("PASS" if ok else "FAIL")
            print(
                f"{mark} {c['agent']}/{c['name']}"
                + (
                    ""
                    if ok or a.dry_run
                    else "  ← "
                    + "; ".join(f"{x['check']['type']}: {x['why']}" for x in checks if not x["pass"])
                    + (f" {run.get('error')}" if run.get("error") else "")
                )
            )
            if not a.dry_run:
                by_agent.setdefault(c["agent"], []).append(rec)
        finally:
            if not a.keep:
                git(["worktree", "remove", "--force", str(wt)], rzlib.ROOT)
                shutil.rmtree(wt, ignore_errors=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{stamp}-{a.agent or 'all'}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for agent, recs in by_agent.items():
        log_line(
            agent,
            candidate.name if candidate else "",
            sum(r["pass"] for r in recs),
            len(recs),
            [r["case"] for r in recs if not r["pass"]],
        )
    print(f"results: {rzlib.rel(out)}")
    return 0 if all(r.get("pass", True) for r in report) else 1


if __name__ == "__main__":
    sys.exit(main())
