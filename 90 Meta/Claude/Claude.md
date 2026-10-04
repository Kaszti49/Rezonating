---
type: project
---
# Claude

Claude is the third team member. It runs as Claude Code in CMD or PowerShell on whichever machine you're at, using your Claude subscription. The session you talk to is the **orchestrator**; it hands work to specialist agents and has it checked. The whole setup: [[Agent system]].

## How Claude works here
1. **Start of a session:** a hook hands Claude the date, the machine, git state, open agent flags and the [[Handoff]]. Claude then reads [[Home]] and its queue (work with `owner: claude`, inbox notes tagged `#ask-claude`).
2. **During:** routes work to the right agent, writes notes with the exact properties in [[Vault rules]], adds one line under `## Claude` in today's daily note.
3. **End of a session:** `/wrap-up`: appends to [[Session log]], rewrites [[Handoff]], tidies the ledger, proposes the commits.

## What Claude can do
- Read and edit every file in the repo on the machine it runs on
- Research on the web, check datasheets, compare suppliers
- Write and build firmware, write Python, review code and schemas, write docs and OTIO texts
- Keep properties consistent, fix broken links, update the dashboard and Bases
- Improve its own agents, but only through proposals you approve ([[Agent system#Changing the agent system]])

## What Claude can't do
- Remember anything that isn't written in the repo or the vault
- Accept decisions, spend money, flash a board or push without you
- Solder, measure, or see the real hardware

## Asking Claude
- Quick: tag an inbox note `#ask-claude`.
- Real work: a work note with `owner: claude`, a goal, and "Done when" boxes.
- Directly: start `claude` in the repo folder and say what you need.
