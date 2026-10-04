---
type: project
---
# How our system works

The short version for Kaszti and Viktor. Details: [[Agent system]], [[Vault rules]], [[Workstations]].

## 1. One folder, three things
`C:\Work\Projects\Enterpartner\Rezonating` is at the same time:
- **the code** (`firmware/`, `ml/`, `tools/`, `schemas/`, `packs/`) — Viktor's main ground
- **the vault** (numbered folders + `Home.md`) — open the folder in Obsidian; everything we plan, buy, test and decide lives here
- **Claude's workplace** (`CLAUDE.md`, `.claude/`) — the rules and agents Claude works with

GitHub (`Kaszti49/Rezonating`) keeps it in sync between machines.

## 2. A normal work day (Monday or Tuesday)
1. **Pull.** Open Obsidian (it pulls automatically) or run `git pull`.
2. **Look at `Home.md`.** Up next, who has what, what's late.
3. **Write one line** in today's daily note under your name (Calendar on the right → click today).
4. **Work.** Your own tasks, or give Claude work (below).
5. **End.** Tell Claude `/wrap-up`, then commit and push (vault and code in separate commits).

Off-day work (any other day) is fine; the daily note marks it `off_day: true` by itself.

## 3. Working with Claude
Open CMD or PowerShell in the repo folder and type `claude`. You always talk to **one** Claude. Just say what you need:
- "Check EU stock for the ADS131M04" → it sends the **researcher**
- "Write the SD card writer" → **firmware-dev**, then the **verifier** checks it
- "Mark the kill test done, it passed" → **vault-keeper**

You don't have to pick the agent. If you want a specific one: `@agent-researcher …`.

Other ways to hand Claude work, even when you're not at the computer:
- a work note with `owner: claude`
- an inbox note tagged `#ask-claude`

## 4. How Claude checks itself
1. **Hooks (automatic):** every edit is formatted and checked; when an agent finishes, its build/tests/note rules run. If they fail, the agent fixes it (twice at most).
2. **Verifier:** a second Claude on a different model reviews code and important research and answers PASS, FLAG or BLOCK.
3. **Escalation:** still wrong → a stronger agent (**deep-engineer**) → still wrong → **you** get asked, in the daily note and the Handoff.

Every problem is written to the **ledger** (`90 Meta/Agents/Ledger/`). The dashboard's Claude card shows open flags.

## 5. What Claude never does without you
- accept a decision (it writes `proposed`; you flip it to `accepted` in Obsidian)
- commit, push, flash a board, or spend money
- change its own rules or agents
- touch raw recordings (`*.wav`, `data/raw/`, `data/private/`) or edit your section of a daily note

## 6. How it gets better
Tuesday after work: type `/retro`. The **curator** reads the ledger and proposes at most three fixes, each with evidence and a test. You say yes or no; yes ones are applied and written in the [[Changelog]].

## 7. Where things are
| I want to… | Go to |
| --- | --- |
| See what's going on | `Home.md` |
| Add a task | new note in `20 Work` (template fills in) |
| Drop an idea or link | `00 Inbox` |
| See parts and the order | `30 Hardware` |
| Record a decision | `80 Decisions` (Claude can draft it) |
| Know where Claude left off | `90 Meta/Claude/Handoff` |
| See how the agents are doing | [[Agent system]] |

## 8. When something looks broken
- Claude shows a "hook error" → Python isn't on PATH on that machine, or Python isn't installed.
- The dashboard shows a red error box → tell Claude "the dashboard section X fails".
- A note's properties look wrong → `python .claude/scripts/vault_schema.py --all` lists every rule break.
- Git conflict in a note → keep both parts, delete the conflict markers, commit.
