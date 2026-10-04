---
name: vault-conventions
description: Exact frontmatter for every Rezonating vault note type (work, part, order, build, pack, experiment, research, decision, daily, weekly, inbox, proposal, retro) and the rules for editing notes. Use before creating or changing any note in the numbered vault folders.
---

# Vault conventions

The full rules live in `10 Project/Vault rules.md`; this is the working copy for writing notes.
`python .claude/scripts/vault_schema.py <note>` checks a note (the edit hook runs it for you).

## General
- File names are the title. No `/ \ : * ? " < > |` in names. IDs prefix the name: `D-013 Agent system`.
- Dates `YYYY-MM-DD`. Links in properties quoted: `pack: "[[footstep-id]]"`. Empty value = nothing after the colon.
- Never write `<%`. The templates in `90 Meta/Templates/` contain Templater code; copy the
  properties below instead.
- Owners: `kaszti`, `viktor`, `claude`. Next free id: look at the highest existing one in the folder.

## Frontmatter by type

**work** — `20 Work/<What to do>.md`
```yaml
---
type: work
status: todo            # backlog | todo | doing | review | blocked | done
owner: claude           # kaszti | viktor | claude
priority: p2            # p1 (this week matters) | p2 | p3
area: firmware          # hardware | firmware | ml | data | project | research | design
due:                    # YYYY-MM-DD or empty
pack:                   # "[[footstep-id]]" or empty
created: 2026-10-05
done:                   # set together with status: done
---
# <title>

**Goal:** one sentence.

## Done when
- [ ] observable result

## Notes

## Log
- 2026-10-05 created
```

**part** — `30 Hardware/Parts/<Part name>.md`
```yaml
---
type: part
status: needed          # needed | ordered | have | later
category: sensor        # sensor | mcu | adc | clock | storage | prototyping | passive | cable | consumable | tool
qty: 1
price_eur:              # number only, e.g. 4.5
price_note:
supplier:
url: "https://…"
datasheet:
order: "[[ORD-001 First rig]]"
---
```

**order** — `30 Hardware/Orders/ORD-### <name>.md`: `type: order`, `id: ORD-###`,
`status: draft | ordered | delivered`, `date:`, `ordered:`, `delivered:`, `supplier:`, `paid_by: company`.

**build** — `30 Hardware/Builds/<what>.md`: `type: build`, `status: planned | doing | done`, `owner:`, `date:`.

**pack** — `40 Packs/<pack-id>.md`: `type: pack`, `stage: idea | design | data | model | on-device | done`,
`order_no:` (number), `head: geophone | accelerometer | piezo`, `metric:`, `target_value:`, `best_value:`, `repo_path:`.

**experiment** — `50 Experiments/EXP-### <name>.md`
```yaml
---
type: experiment
id: EXP-002
status: planned         # planned | running | done
date: 2026-10-12
owner: kaszti
pack: "[[footstep-id]]"
protocol: walk-pass-v1  # file name in docs/protocols without .md
floor:
people:                 # number
sessions: []
metric:
metric_value:           # number
result:                 # pass | fail | partial (when done)
---
```

**research** — `60 Research/<Title>.md`: `type: research`,
`kind: paper | dataset | datasheet | product | article | video`, `status: to-read | read`,
`relevance: high | med | low`, `url: "https://…"`. Body starts with **Takeaway for Rezonating**.

**decision** — `80 Decisions/D-### <few words>.md` (Claude writes only proposals)
```yaml
---
type: decision
id: D-013
status: proposed        # Claude never writes accepted or superseded
date: 2026-10-05
decided_by: []          # kaszti / viktor fill this when they accept
tier: 2                 # 1 load-bearing | 2 structural | 3 scaffolding
supersedes:             # "[[D-00x …]]" or empty
---
# D-013 <few words>

**Decision:** 

**Why:** 

**Rejected alternatives:** 

**Affects:** 
```

**daily** — `70 Journal/Daily/YYYY-MM-DD.md`
```yaml
---
type: daily
date: 2026-10-05        # same as the file name
off_day: false          # true on days other than Monday and Tuesday
---
```
Body: `# Monday, 5 October 2026`, then `## Kaszti`, `## Viktor`, `## Claude` (each with `- `),
then `## Done today` with a `tasks` code block containing `done on 2026-10-05`. Copy an existing
daily note's body and change the dates. Claude writes only under `## Claude`.

**meeting** (weekly) — `70 Journal/Weekly/YYYY-Www.md`: `type: meeting`, `week: 2026-W41`
(same as file name), `date:` (Monday of that week), `attendees: [kaszti, viktor, claude]`.

**inbox** — `00 Inbox/<anything>.md`: `type: inbox`, `created: YYYY-MM-DD`. Tag `#ask-claude` in the body.

**proposal** — `90 Meta/Agents/Proposals/P-### <name>.md`: `type: proposal`, `id: P-###`,
`status: proposed | accepted | rejected | applied`, `target: .claude/agents/x.md`, `date:`, `applied:`, `flags: []`.

**retro** — `90 Meta/Agents/Retros/YYYY-Www.md`: `type: retro`, `week: YYYY-Www`, `date: YYYY-MM-DD`.

## Editing rules
- Work done: `status: done` and `done: <date>` together; tick the "Done when" boxes; add a Log line.
- Changing a due date or owner that isn't yours: add a `## Log` line saying who changed what and why.
- Never delete notes; move doubtful ones to `00 Inbox`.
- Session log (`90 Meta/Claude/Session log.md`): append `## YYYY-MM-DD` with **Did / Decided with
  the team / Left open / Next session should**. Never edit old entries.
- Handoff (`90 Meta/Claude/Handoff.md`): rewrite whole, under a page; set `updated:`.
