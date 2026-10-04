---
paths:
  - "00 Inbox/**"
  - "10 Project/**"
  - "20 Work/**"
  - "30 Hardware/**"
  - "40 Packs/**"
  - "50 Experiments/**"
  - "60 Research/**"
  - "70 Journal/**"
  - "80 Decisions/**"
  - "90 Meta/**"
  - "Home.md"
---

# Vault notes

You are reading or editing the Obsidian vault. The `vault-conventions` skill has the exact
frontmatter per note type; `10 Project/Vault rules.md` is the source of truth.

- Properties are data read by the dashboard and the Bases: allowed values only, dates
  `YYYY-MM-DD`, links in properties quoted (`"[[Note name]]"`), numbers without units.
- Never write `<%` outside `90 Meta/Templates/`.
- `status: done` always comes with `done: <date>`.
- Decisions: Claude writes `status: proposed` only.
- Daily notes: write only under `## Claude`. Session log: append only. Handoff: rewrite whole.
- `90 Meta/Views/`, `90 Meta/Bases/` and `90 Meta/Templates/` are code the dashboard runs: change
  them only when the task is about them, and test the dashboard afterwards.
- Never delete notes; move doubtful ones to `00 Inbox`.
