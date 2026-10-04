---
type: project
---
# Team

| | Kaszti Benedek | Szabó Viktor | Claude |
| --- | --- | --- | --- |
| Role | Design, management and everything else | Programming and electronics | Orchestrator + specialist agents: research, code drafts, reviews, docs, vault upkeep |
| Owner tag | `kaszti` | `viktor` | `claude` |
| Owns | Plan, budget, orders, design, OTIO, the vault | Firmware, electronics, training pipeline, data tools | Research notes, datasheet checks, code review, decision proposals, session logs |

Roles: [[D-011 Roles]], updated by [[D-014 Roles v2]] (proposed). Work days: **Monday and Tuesday**; project work on other days is rare and noted as an off-day in the daily note.

## Working with Claude
- Claude has **no memory between sessions**. The vault is its memory: it reads [[Handoff]] first and updates it before it stops.
- Give Claude work by setting `owner: claude` on a work note, or by tagging an inbox note `#ask-claude`.
- Claude runs as Claude Code in CMD or PowerShell on the machine you're at (your Claude subscription). The orchestrator hands work to specialist agents and has it checked: [[Agent system]].
- Claude proposes; you decide. It never marks a decision note `accepted` on its own.
- More in [[Claude]].
