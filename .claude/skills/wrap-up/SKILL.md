---
name: wrap-up
description: End-of-session protocol for Rezonating (daily note line, Session log entry, Handoff rewrite, ledger clean-up, commit plan). Use when the person says they're stopping, says "wrap up", or a long piece of work is finished.
---

# Wrap up a session

Claude remembers nothing between sessions; this is how the next session continues cold. Do the
steps in order. Steps 1–3 can go to `vault-keeper` as one task if the session was long.

1. **Daily note** `70 Journal/Daily/<today>.md` (create from the vault-conventions frontmatter if
   missing; `off_day: true` unless it's Monday or Tuesday): one line under `## Claude` saying what
   got done, with links to the notes touched.
2. **Session log** `90 Meta/Claude/Session log.md`: append
   ```
   ## YYYY-MM-DD
   - **Did:** …
   - **Agents:** which ran, gate/verifier outcomes, escalations (ledger ids)
   - **Decided with the team:** … (only what Kaszti or Viktor decided)
   - **Left open:** …
   - **Next session should:** …
   ```
   Never edit older entries.
3. **Handoff** `90 Meta/Claude/Handoff.md`: rewrite whole, under a page, `updated: <today>`:
   where we are, next up per person (table), open questions, watch-outs.
4. **Ledger**: `python .claude/scripts/ledger.py list --open`. Resolve flags this session actually
   fixed (`ledger.py resolve <id> --how "…"`); leave the rest open with a line in the Handoff.
5. **Git**: `git status`. Tell the person what changed, split into a vault commit and a code
   commit, with a suggested message for each. Commit only if they ask (the commit guard refuses
   mixed commits). Remind them to push and that Obsidian Git pulls on the next start.
6. **Finish** with three lines to the person: what got done, what's next, what needs them.
