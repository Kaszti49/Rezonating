---
name: retro
description: Self-improvement playbook. Turns ledger evidence (gate failures, review findings, retries, escalations, and a person correcting Claude) into at most three proposed changes to the playbooks, CLAUDE.md, hooks or checks; a person approves each one. Run it when the session start says "Retro due", right after a person corrects Claude, when the same problem shows up twice, on Tuesdays after the work, or on /retro.
---

# Playbook: retro

The system improves only through this loop. You propose; a person says yes or no to each change.

## When
- The SessionStart context says **Retro due** (`python .claude/scripts/ledger.py retro-due`
  explains why). Run it at the first natural break, not in the middle of a task.
- A person corrects your output or your way of working. Log it right away:
  `ledger.py add --playbook <which> --kind note --summary "<what they corrected>"`. Then offer the
  retro when the current task is finished.
- On demand (`/retro`), or weekly on Tuesday after the work.

## Steps
1. **Evidence.** Run `ledger.py retro-due`, `ledger.py list --open`, `ledger.py stats --since 14d`
   and `ledger.py runs --last 20`. Also read `90 Meta/Agents/Ledger/Changelog.md` (what was already
   tried and rolled back) and the last retro. If the local model works
   (`python tools/local/ollama_client.py --check` exits 0), you can use
   `tools/local/summarize_week.py --days 7` as a free first draft.
2. **Group by cause, not by wording.** A cause needs at least two flags, or one high flag or one
   person correction with a clear mechanism. Single incidents go on the watch list.
3. **Choose the cheapest fix that would have prevented it,** in this order:
   1. a deterministic check (`checks.py`, a hook, `vault_schema.py`)
   2. one sentence in the playbook that was in use
   3. a new section in a playbook
   4. a rule in `CLAUDE.md`
   5. a new playbook (last resort)

   Also retire rules or playbooks that never fire or keep causing friction.
4. **At most three proposals:** `90 Meta/Agents/Proposals/P-### <name>.md` (proposal frontmatter
   from `vault-conventions`). Each one has the evidence (flag ids), the exact change as a unified diff,
   how to check it works (a test in `.claude/tests/`, a check run, or a replay of the flagged case),
   the risk and the rollback. Don't re-propose anything the Changelog shows was rolled back unless
   there's new evidence. If the ledger is quiet, propose nothing and say so.
5. **Retro note:** `90 Meta/Agents/Retros/YYYY-Www.md` (retro frontmatter): the numbers, the causes,
   the watch list and the proposals.
6. **Ask.** Show each proposal in one paragraph (evidence, change, check, risk) and ask yes or no
   for each one (AskUserQuestion, multiSelect).
7. **Apply the approved ones only.** Edits to `.claude/` and `CLAUDE.md` ask for permission, and that
   is the point. Run the check from the proposal. Set the proposal to `status: applied`,
   `applied: <date>`; rejected ones to `status: rejected`. Add one line per change to the Changelog,
   resolve the flags it fixes (`ledger.py resolve <id> --how "P-### applied"`), then
   `ledger.py retro-done --note "<week>"`.
8. **Commit plan:** `.claude/` changes and vault notes go in two separate commits, and only when the
   person asks.
