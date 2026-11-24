---
type: proposal
id: P-002
status: applied
target: .claude/hooks/stop_gate.py
date: 2026-11-24
applied: 2026-11-24
flags: []
---
# P-002 Stop gate sees every changed file

**Evidence.** On 2026-11-24 `runs.jsonl` has **one** gate run (09:53, one file, ruff), while code was changed in at least six rounds. `stop_gate.py` checks only `rzlib.edits_by(session)`, which `post_edit.py` fills from the Write and Edit tools. Edits made through Bash (scripts, `sed`) are never recorded, so the automatic gate skipped them. Checks were run by hand instead (`checks.py`, pytest), and one numpy value that would have broken the live page was caught by a test I wrote, not by the gate. No flag was logged because nothing failed visibly; that's the gap.

**Change (unified diff, not applied):**
```diff
--- a/.claude/hooks/stop_gate.py
+++ b/.claude/hooks/stop_gate.py
@@ def main() -> int:
     passed: dict = state.get("passed", {})
     tries = int(state.get("tries", 0))
 
-    todo = [
-        p
-        for p in rzlib.edits_by(session, None)
-        if _mtime(root, p) is not None and passed.get(p) != _mtime(root, p)
-    ]
+    # Edits through Bash are not recorded: take git's changed files too, but only those touched since this
+    # session's first Stop, so a person's own uncommitted work is not gated.
+    started = state.setdefault("started", time.time())
+    changed = subprocess.run(
+        ["git", "ls-files", "-m", "-o", "--exclude-standard"], cwd=root, capture_output=True, text=True, timeout=30
+    ).stdout.splitlines()
+    changed = [p for p in changed if (_mtime(root, p) or 0) >= started]
+    todo = [
+        p
+        for p in dict.fromkeys(rzlib.edits_by(session, None) + changed)
+        if _mtime(root, p) is not None and passed.get(p) != _mtime(root, p)
+    ]
```
(`import subprocess, time` at the top; `started` must be saved with `passed` in `save()`. A cleaner start time is the SessionStart hook writing it; that's the one to build.)

**Check.** A test in `.claude/tests/test_agent_system.py`: change a tracked `.py` with a shell command in a temporary repo, run the hook, expect ruff to run on it; a file changed before the session must not be checked. Then `python -m unittest discover -s .claude/tests`.

**Risk.** A person's edits made during the session would be gated too; worst case an extra failed check. Rollback: revert the hunk.

**Applied 2026-11-24** (Kaszti in chat: "apply all proposed ideas and the retro"). Applied with three differences from the diff above: the start time is written by the SessionStart hook (`rzlib.mark_session_start`), the changed files come from `rzlib.dirty_files`, and the files the gate writes itself (ledger, `.claude/state/`) are left out, because they would have triggered it on every turn (a test caught that). 21 tests in `.claude/tests` pass. It works from the next session start on.
