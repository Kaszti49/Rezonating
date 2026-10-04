"""Tests for the agent system's hooks and scripts (Tier 1: they run unattended on every machine).

Run: python -m unittest discover -s .claude/tests -v
Each test builds a throwaway git repo with a copy of .claude/ and a few vault notes, then feeds the
hooks the same JSON Claude Code would send on stdin.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".claude" / "scripts"))
import rzlib  # noqa: E402
import vault_schema  # noqa: E402

WORK_OK = (
    "---\ntype: work\nstatus: todo\nowner: claude\npriority: p2\narea: ml\ndue:\npack:\n"
    "created: 2026-10-03\ndone:\n---\n# T\n"
)
WORK_BAD = "---\ntype: work\nstatus: done\nowner: claude\npriority: p1\narea: ml\ncreated: 2026-10-03\n---\n# T\n"
DECISION = (
    "---\ntype: decision\nid: D-001\nstatus: accepted\ndate: 2026-10-01\ndecided_by: [kaszti]\ntier: 2\n"
    "supersedes:\n---\n# D-001 X\n"
)


class Sandbox:
    """A temporary repo that looks enough like Rezonating for the hooks."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rz-test-"))
        shutil.copytree(
            REPO / ".claude", self.dir / ".claude", ignore=shutil.ignore_patterns("state", "evals", "__pycache__")
        )
        for d in ["20 Work", "80 Decisions", "00 Inbox", "firmware/main", "tools", "90 Meta/Agents/Ledger"]:
            (self.dir / d).mkdir(parents=True, exist_ok=True)
        (self.dir / "20 Work/Ok.md").write_text(WORK_OK, encoding="utf-8")
        (self.dir / "80 Decisions/D-001 X.md").write_text(DECISION, encoding="utf-8")
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")
        self.env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.dir), PYTHONUTF8="1")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.dir, capture_output=True, text=True)

    def hook(self, name: str, payload: dict, *args: str) -> tuple[int, dict | None, str]:
        payload = {"session_id": "s", "cwd": str(self.dir), **payload}
        p = subprocess.run(
            [sys.executable, str(self.dir / ".claude" / "hooks" / f"{name}.py"), *args],
            input=json.dumps(payload).encode(),
            capture_output=True,
            env=self.env,
            cwd=self.dir,
        )
        out = p.stdout.decode("utf-8").strip()
        return p.returncode, (json.loads(out) if out.startswith("{") else None), p.stderr.decode("utf-8")

    def write(self, rel: str, text: str) -> str:
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return str(p)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def decision_of(out: dict | None) -> str | None:
    return ((out or {}).get("hookSpecificOutput") or {}).get("permissionDecision")


class TestFrontmatter(unittest.TestCase):
    def test_parser_shapes(self):
        fm = rzlib.parse_frontmatter(
            'a: 1\nb: 2.5\nc: "[[X]]"\nd: [x, y]\ne:\n  - {name: "Kill test", date: 2026-10-04}\nf:\ng: true\n'
        )
        self.assertEqual(fm["a"], 1)
        self.assertEqual(fm["b"], 2.5)
        self.assertEqual(fm["c"], "[[X]]")
        self.assertEqual(fm["d"], ["x", "y"])
        self.assertEqual(fm["e"], [{"name": "Kill test", "date": "2026-10-04"}])
        self.assertIsNone(fm["f"])
        self.assertIs(fm["g"], True)

    def test_unquoted_link_is_an_error(self):
        issues = vault_schema.check_text("20 Work/A.md", WORK_OK.replace("pack:\n", "pack: [[footstep-id]]\n"))
        self.assertTrue(any("quoted" in i.msg for i in issues))

    def test_done_needs_date(self):
        issues = vault_schema.check_text("20 Work/A.md", WORK_BAD)
        self.assertTrue(any(i.level == "error" and "done" in i.msg for i in issues))

    def test_real_vault_is_clean(self):
        issues = [
            i for i in vault_schema.check_many(vault_schema.all_notes(REPO), REPO, full=True) if i.level == "error"
        ]
        self.assertEqual([], [str(i) for i in issues])

    def test_glob(self):
        self.assertTrue(rzlib.glob_match("firmware/main/x.c", "firmware/**"))
        self.assertTrue(rzlib.glob_match("README.md", "**/README.md"))
        self.assertTrue(rzlib.glob_match("ml/README.md", "**/README.md"))
        self.assertFalse(rzlib.glob_match("ml/x.py", "firmware/**"))


class TestHooks(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.close()

    def test_scope_denies_outside_folder(self):
        _, out, _ = self.sb.hook(
            "pre_edit",
            {
                "agent_type": "researcher",
                "agent_id": "a",
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.sb.dir / "firmware/main/x.c"), "content": "x"},
            },
        )
        self.assertEqual("deny", decision_of(out))

    def test_scope_allows_inside_folder(self):
        _, out, _ = self.sb.hook(
            "pre_edit",
            {
                "agent_type": "vault-keeper",
                "agent_id": "a",
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.sb.dir / "20 Work/New.md"), "content": WORK_OK},
            },
        )
        self.assertIsNone(decision_of(out))

    def test_never_accepts_decision(self):
        new = DECISION.replace("D-001", "D-002").replace("[kaszti]", "[]")
        _, out, _ = self.sb.hook(
            "pre_edit",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.sb.dir / "80 Decisions/D-002 Y.md"), "content": new},
            },
        )
        self.assertEqual("deny", decision_of(out))

    def test_never_unaccepts_decision(self):
        _, out, _ = self.sb.hook(
            "pre_edit",
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(self.sb.dir / "80 Decisions/D-001 X.md"),
                    "old_string": "status: accepted",
                    "new_string": "status: superseded",
                },
            },
        )
        self.assertEqual("deny", decision_of(out))

    def test_accepted_decision_body_is_read_only(self):
        _, out, _ = self.sb.hook(
            "pre_edit",
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(self.sb.dir / "80 Decisions/D-001 X.md"),
                    "old_string": "# D-001 X",
                    "new_string": "# D-001 X\n\nSuperseded by D-015.",
                },
            },
        )
        self.assertEqual("deny", decision_of(out))

    def test_daily_note_other_sections_protected(self):
        daily = "---\ntype: daily\ndate: 2026-10-05\n---\n## Kaszti\n- oscilator\n\n## Claude\n- \n"
        f = self.sb.write("70 Journal/Daily/2026-10-05.md", daily)
        _, out, _ = self.sb.hook(
            "pre_edit",
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": f, "old_string": "oscilator", "new_string": "oscillator"},
            },
        )
        self.assertEqual("deny", decision_of(out))
        _, out, _ = self.sb.hook(
            "pre_edit",
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": f, "old_string": "## Claude\n- ", "new_string": "## Claude\n- did x"},
            },
        )
        self.assertIsNone(decision_of(out))

    def test_templater_code_denied(self):
        _, out, _ = self.sb.hook(
            "pre_edit",
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": str(self.sb.dir / "00 Inbox/x.md"),
                    "content": "---\ntype: inbox\n---\n<% tp.date.now() %>",
                },
            },
        )
        self.assertEqual("deny", decision_of(out))

    def test_raw_data_denied(self):
        _, out, _ = self.sb.hook(
            "pre_edit",
            {"tool_name": "Write", "tool_input": {"file_path": str(self.sb.dir / "data/raw/a.wav"), "content": "x"}},
        )
        self.assertEqual("deny", decision_of(out))

    def test_post_edit_reports_rule_breaks(self):
        f = self.sb.write("20 Work/Bad.md", WORK_BAD)
        rc, _, err = self.sb.hook("post_edit", {"tool_name": "Write", "tool_input": {"file_path": f}})
        self.assertEqual(2, rc)
        self.assertIn("done", err)

    def test_commit_guard(self):
        self.sb.write("20 Work/New.md", WORK_OK)
        self.sb.write("tools/x.py", "x = 1\n")
        self.sb.git("add", "-A")
        _, out, _ = self.sb.hook("commit_guard", {"tool_name": "Bash", "tool_input": {"command": 'git commit -m "x"'}})
        self.assertEqual("deny", decision_of(out), "mixed vault + code commit must be refused")
        self.sb.git("restore", "--staged", "tools/x.py")
        _, out, _ = self.sb.hook("commit_guard", {"tool_name": "Bash", "tool_input": {"command": 'git commit -m "x"'}})
        self.assertIsNone(decision_of(out))
        _, out, _ = self.sb.hook(
            "commit_guard", {"tool_name": "Bash", "tool_input": {"command": "git add . && git commit -m x"}}
        )
        self.assertEqual("deny", decision_of(out))
        self.sb.write("data/raw/a.wav", "x")
        self.sb.git("add", "-f", "data/raw/a.wav")
        _, out, _ = self.sb.hook(
            "commit_guard", {"tool_name": "PowerShell", "tool_input": {"command": "git commit -m x"}}
        )
        self.assertEqual("deny", decision_of(out))
        rc, _, _ = self.sb.hook("commit_guard", {}, "--git-hook")
        self.assertEqual(1, rc)

    def test_gate_retries_then_flags(self):
        f = self.sb.write("20 Work/Bad.md", WORK_BAD)
        self.sb.hook(
            "post_edit",
            {"agent_type": "vault-keeper", "agent_id": "a1", "tool_name": "Write", "tool_input": {"file_path": f}},
        )
        stop = {
            "hook_event_name": "SubagentStop",
            "agent_type": "vault-keeper",
            "agent_id": "a1",
            "stop_hook_active": False,
        }
        for _ in range(2):
            _, out, _ = self.sb.hook("subagent_gate", stop)
            self.assertEqual("block", (out or {}).get("decision"))
        _, out, _ = self.sb.hook("subagent_gate", stop)
        self.assertNotEqual("block", (out or {}).get("decision"))
        flags = rzlib.read_jsonl(self.sb.dir / "90 Meta/Agents/Ledger/flags.jsonl")
        self.assertEqual(["gate-fail"], [x["kind"] for x in flags])
        _, out, _ = self.sb.hook(
            "agent_report",
            {
                "tool_name": "Agent",
                "tool_input": {"subagent_type": "vault-keeper"},
                "tool_response": {"status": "completed", "agentId": "a1"},
            },
        )
        self.assertIn("gate: fail", out["hookSpecificOutput"]["additionalContext"])

    def test_gate_passes_clean_work(self):
        f = self.sb.write("20 Work/Fine.md", WORK_OK)
        self.sb.hook(
            "post_edit",
            {"agent_type": "vault-keeper", "agent_id": "a2", "tool_name": "Write", "tool_input": {"file_path": f}},
        )
        _, out, _ = self.sb.hook(
            "subagent_gate", {"agent_type": "vault-keeper", "agent_id": "a2", "stop_hook_active": False}
        )
        self.assertIsNone(out)
        runs = rzlib.read_jsonl(self.sb.dir / "90 Meta/Agents/Ledger/runs.jsonl")
        self.assertEqual("pass", runs[-1]["gate"])

    def test_verifier_findings_are_logged(self):
        msg = (
            "SUBJECT: ml-dev\nVERDICT: FLAG\nFINDINGS:\n- [high] tools/x.py:3 — wrong — evidence — fix\n"
            "- [low] naming\nCHECKS RUN:\n- ruff: ok"
        )
        self.sb.hook("subagent_gate", {"agent_type": "verifier", "agent_id": "v", "last_assistant_message": msg})
        flags = rzlib.read_jsonl(self.sb.dir / "90 Meta/Agents/Ledger/flags.jsonl")
        self.assertEqual([("ml-dev", "high"), ("ml-dev", "low")], [(x["agent"], x["severity"]) for x in flags])

    def test_stop_gate_blocks_once(self):
        f = self.sb.write("20 Work/Bad.md", WORK_BAD)
        self.sb.hook("post_edit", {"tool_name": "Write", "tool_input": {"file_path": f}})
        _, out, _ = self.sb.hook("stop_gate", {"stop_hook_active": False})
        self.assertEqual("block", out["decision"])
        _, out, _ = self.sb.hook("stop_gate", {"stop_hook_active": True})
        self.assertIn("systemMessage", out)

    def test_session_start_context(self):
        _, out, _ = self.sb.hook("session_start", {"source": "startup"})
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Today is", ctx)
        self.assertIn("Agent ledger", ctx)


class TestLedger(unittest.TestCase):
    def test_resolve_folds(self):
        sb = Sandbox()
        try:

            def run(*a):
                return subprocess.run(
                    [sys.executable, str(sb.dir / ".claude/scripts/ledger.py"), *a],
                    capture_output=True,
                    text=True,
                    env=sb.env,
                    cwd=sb.dir,
                )

            fid = run("add", "--agent", "ml-dev", "--kind", "note", "--summary", "x").stdout.strip()
            self.assertTrue(fid.startswith("F-"))
            self.assertIn("1 flags", run("list", "--open").stdout)
            self.assertEqual(0, run("resolve", fid, "--how", "fixed").returncode)
            self.assertIn("0 flags", run("list", "--open").stdout)
        finally:
            sb.close()


if __name__ == "__main__":
    unittest.main()
