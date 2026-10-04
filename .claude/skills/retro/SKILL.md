---
name: retro
description: Weekly self-improvement retro for the agent system (ledger stats, curator proposals, evals, human approval). Run on Tuesdays after the work, or when the same problem keeps coming back.
disable-model-invocation: true
---

# Agent retro

The agent system improves only through this loop. Nothing here edits agent configuration on its
own: a person approves every change.

1. **Numbers.** Run `python .claude/scripts/ledger.py stats --since 14d` and
   `python .claude/scripts/ledger.py list --open`. If the local model helper works on this machine
   (`python tools/local/ollama_client.py --check` exits 0), run
   `python tools/local/summarize_week.py --days 7` for a free first draft of the week.
2. **Curator.** Start the `curator` agent with: this week (`YYYY-Www`), the numbers from step 1,
   and the open flags. It writes `90 Meta/Agents/Retros/<week>.md` and at most three proposals in
   `90 Meta/Agents/Proposals/` with eval cases.
3. **Evals** (optional, uses subscription quota, a few minutes each). For each proposal:
   ```
   python .claude/scripts/run_evals.py --agent <agent>                       # baseline
   python .claude/scripts/run_evals.py --agent <agent> --candidate "<proposal file>"
   ```
   Put the pass counts into the proposal note. A proposal that doesn't beat the baseline
   (or at least hold it while fixing the flagged case) is rejected.
4. **Human review.** Show each proposal to the person in one paragraph: evidence, change, eval
   result, risk. Ask them to run `/doctor prompt-audit <target file>` on the target before
   applying, and to say yes or no per proposal.
5. **Apply** only the approved ones (editing `.claude/` asks for permission, which is the point).
   For each: set the proposal to `status: applied`, `applied: <date>`; add a line to
   `90 Meta/Agents/Ledger/Changelog.md` (date, proposal id, file, one-line change, rollback);
   resolve the flags it addresses with `ledger.py resolve <id> --how "P-### applied"`.
6. **Commit plan.** Agent-system changes (`.claude/`) and the vault notes go in two separate commits.
