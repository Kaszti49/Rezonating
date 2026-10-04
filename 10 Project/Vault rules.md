---
type: project
cssclasses: [rz-wide]
---
# Vault rules

These rules keep the vault readable for all three of us. The **properties are the data**: the dashboard, the Bases and Claude all read them, so keep them exact.

## Where things go
| Folder | Note type | One note per | Name |
| --- | --- | --- | --- |
| `00 Inbox` | inbox | Loose idea, link, question | anything |
| `10 Project` | project | Charter, plan, roadmap, team, rules | fixed |
| `20 Work` | work | Piece of work with an owner | what to do, e.g. `Place first order` |
| `30 Hardware/Parts` | part | Part we buy | part name |
| `30 Hardware/Orders` | order | Order | `ORD-### name` |
| `30 Hardware/Builds` | build | Rig or board build | what was built |
| `40 Packs` | pack | Pack | pack id, e.g. `footstep-id` |
| `50 Experiments` | experiment | Test or recording session | `EXP-### name` |
| `60 Research` | research | Paper, dataset, datasheet, product | title |
| `70 Journal/Daily` | daily | Day (shared, one section each) | `YYYY-MM-DD` |
| `70 Journal/Weekly` | meeting | Weekly meeting | `YYYY-Www` |
| `80 Decisions` | decision | Decision that's expensive to change | `D-### few words` |
| `90 Meta` | — | Templates, Bases, dashboard code, Claude | — |
| `90 Meta/Agents/Proposals` | proposal | Change to the agent system | `P-### few words` |
| `90 Meta/Agents/Retros` | retro | Weekly agent retro | `YYYY-Www` |

New notes in each folder get the right template automatically (Templater).

## Allowed values
| Property | Values |
| --- | --- |
| `owner` | `kaszti`, `viktor`, `claude` |
| work `status` | `backlog`, `todo`, `doing`, `review`, `blocked`, `done` |
| `priority` | `p1` (this week matters), `p2`, `p3` |
| `area` | `hardware`, `firmware`, `ml`, `data`, `project`, `research`, `design` |
| part `status` | `needed`, `ordered`, `have`, `later` |
| order `status` | `draft`, `ordered`, `delivered` |
| pack `stage` | `idea`, `design`, `data`, `model`, `on-device`, `done` |
| experiment `status` | `planned`, `running`, `done` |
| experiment `result` | `pass`, `fail`, `partial` |
| decision `status` | `proposed` (Claude only proposes), `accepted`, `superseded` |
| research `status` | `to-read`, `read` |
| proposal `status` | `proposed`, `accepted`, `rejected`, `applied` |
| daily `off_day` | `true` on days other than Monday and Tuesday (the template sets it) |
| dates | `YYYY-MM-DD` |
| links in properties | `"[[Note name]]"`, in quotes |

When a work item is finished: `status: done` **and** `done: <date>`. The dashboard's velocity and heatmap use `done`.

## Rhythm
We work on **Monday and Tuesday**. Project work on another day is fine but rare; its daily note gets `off_day: true`.

- **Daily:** one line each in today's daily note (Calendar on the right sidebar, click today).
- **Weekly:** meeting note (click the week number in the Calendar): empty the inbox, check the board, set next week's focus.
- **Decisions:** anything Tier 1 gets a `D-###` note before it's built.
- **Agent retro:** Tuesday after the work, `/retro` in Claude Code ([[Agent system]]).

## Checking
`python .claude/scripts/vault_schema.py --all` checks every note against this page. Claude's edits are checked automatically.

## Git
- Obsidian Git **pulls when Obsidian starts**. Commit and push with the Git panel, never automatically.
- The repo also holds code: before you commit from Obsidian, check you're not committing Viktor's half-finished code.
- Pull before you start, push when you stop. Two people editing the same note at once makes merge conflicts.
- Once per clone: `git config core.hooksPath .githooks`. The pre-commit hook refuses raw recordings.

## Open source
Before the repo goes public, every numbered vault folder (`00`–`90`), `Home.md` and `.obsidian/` are removed from it ([[D-012 Obsidian vault in the repo]]).
