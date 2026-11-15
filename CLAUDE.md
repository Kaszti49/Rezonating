# Rezonating — context for Claude

Read this before changing anything in the repo or the vault. Claude is a member of the team,
not a tool: it owns work items like everyone else.
## What this is

A vibration-sensing platform built by two people: **Kaszti Benedek** (design, management and
everything else) and **Szabó Viktor** (programming and electronics). One ESP32-S3 node reads up
to four sensor heads through an ADS131M04 ADC (plus I2C for digital heads). Software packs, not
firmware changes, decide what a node detects. The first prototype uses an ADC 15 Click board
(ADS131M02, 2 channels) wired directly to the ESP32-S3 (D-015); the 4-channel ADS131M04 comes
back on our own PCB.

Scope is **Year 1 only**: `fall`, then `footstep-id`, then `appliance` (D-023, after the HARMAN Hackathon
fall detector; reference code in `firmware/hackathon-rezon/`). Don't plan or build for
later packs unless asked. The team works **Monday and Tuesday**; other days are off-days.

## Rules

- **Tier 1 files** (`schemas/`, `firmware/components/` core, shared feature code in `ml/`)
  change only together with an accepted decision note in `80 Decisions/`.
- **`scratch/` is throwaway.** Nothing outside it may import from it.
- **Never commit raw recordings** (`*.wav`) or the name list behind person pseudonyms (P1, P2, …).
- **Count every sample.** Firmware reports dropped samples, never hides them.
- **One feature implementation, two languages.** A Python feature change needs the matching
  firmware change and updated test vectors.
- Run `python tools/validate.py` before committing schema, pack or sidecar changes.
- **Vision changes are confirmed first.** When a person asks to change the vision, scope or a
  function (what the product does, the packs, Roadmap gates, a decision), ask whether they really
  want it. Once they confirm, update every note that states the old version (`Charter`, `Master
  plan`, `Roadmap`, the pack notes, decisions). If something isn't written in the vault, ask right
  away; never assume it.
- **Dates count work days.** Due dates fall on a Monday or Tuesday, and durations are estimated at
  two work days per week. External deadlines (OTIO) stay as given.

## How Claude works here: one agent, playbooks

There is **one agent**: the Claude session Kaszti and Viktor talk to. It does the work itself; it
doesn't hand work to subagents. Each kind of work has a **playbook** (a skill in `.claude/skills/`)
that Claude loads before starting. Full description: `90 Meta/Agents/Agent system.md` (D-025).

| Work | Playbook |
| --- | --- |
| `firmware/` C, build errors, on-device pack code | `firmware` (+ `esp-idf-build-flash`) |
| `ml/`, `tools/`, data manifests, test vectors, training | `ml-training` |
| Sources, datasheets, prices, papers, datasets | `research` |
| Docs, READMEs, OTIO texts, study lessons | `writing` |
| Vault notes, daily lines, decisions | `vault-conventions` |
| Checking finished work (L1) | `verify` |
| Failed twice, or a hard root cause (L3) | `root-cause` |
| Improving this system | `retro` |
| End of session | `wrap-up` |

**Every task:** write its Done when, load the playbook, do the work, then run `verify` after any
change in `firmware/`, `ml/`, `tools/`, `schemas/` or `packs/` and after research that feeds an
order or a decision. Skip `verify` for vault housekeeping and plain text.

**Escalation ladder.** Log each step: `python .claude/scripts/ledger.py add --playbook <p> --kind <k> --summary "…"`.
- **L0 gate** (Stop hook, automatic): the checks for the files edited since they last passed run
  (`.claude/scripts/checks.py`); two fix rounds, then a `gate-fail` flag is logged.
- **L1 verify**: PASS → done. FLAG → log the findings (`--kind review`) and fix them.
- **L2 retry**: fix with the findings in hand; at most two rounds per task (`--kind retry`).
- **L3 root cause**: the `root-cause` playbook, and tell the person if a stronger model or effort
  would help (`--kind escalation`).
- **L4 human**: still failing, a BLOCK, or any question of money, hardware or a decision: stop, say
  what is needed in today's daily note (under `## Claude`) and in the Handoff, and ask
  (`--kind human`). Never hide a failed gate or an open flag in a summary.

**Always ask a person first:** accepting decisions (they do it in Obsidian), commits and pushes,
flashing a board, spending money, and changes to `.claude/`, any `CLAUDE.md`, `.mcp.json` or `schemas/`.

**Self-improvement (the retro).** The ledger (`90 Meta/Agents/Ledger/`) is the evidence. When a
person corrects Claude, log a `note` flag at once. The SessionStart context says **Retro due** when
the evidence is there (a correction, a high flag, three new flags, or a week of unreviewed flags):
run the `retro` playbook at the next natural break. It proposes at most three evidenced changes to
playbooks, checks, hooks or this file; a person approves each one; `Changelog.md` records it.
Nothing in this system changes without that approval.

## Session protocol (Claude has no memory between sessions)

1. **Start:** the SessionStart hook gives you the date, the machine, git state, open flags and the
   Handoff. Then read `Home.md` and your queue: work notes with `owner: claude` that aren't `done`,
   and inbox notes tagged `#ask-claude`.
2. **During:** one line under `## Claude` in today's daily note (`70 Journal/Daily/YYYY-MM-DD.md`;
   create it if missing, `off_day: true` unless it's Monday or Tuesday).
3. **End:** the `wrap-up` playbook: Session log entry (append only), Handoff rewrite, ledger
   clean-up, retro check, commit plan.

## The vault (Obsidian, repo root = vault root)

- Numbered folders `00`–`90` and `Home.md` are the vault; everything else is code. Folders, note
  types and allowed values: `10 Project/Vault rules.md`; exact frontmatter: the `vault-conventions` skill.
- **Properties are data** (the dashboard and the Bases read them): allowed values only, dates
  `YYYY-MM-DD`, links in properties as `"[[Note name]]"`. Never write `<%` into a note.
- **Finishing work:** `status: done` and `done: <date>` together.
- **Decisions:** Claude proposes (`status: proposed`); only Kaszti or Viktor set `accepted`.
- **Never** edit another person's section of a daily note, change someone else's due date without a
  Log line, or delete notes; move doubtful ones to `00 Inbox`.
- **Git:** Obsidian Git pulls on startup. Claude commits only when asked and never mixes vault and
  code in one commit (the commit guard enforces it).
- Before the repo goes open source, the numbered folders, `Home.md` and `.obsidian/` are removed (D-012).

## Machines

`10 Project/Workstations.md` lists them. Local models (Ollama) exist only on Kaszti's home desktop;
`tools/local/` scripts use them and do nothing elsewhere.

## Hardware facts that bite

- ADS131M02/M04 need a continuous 8.192 MHz clock on CLKIN (no internal oscillator). All channels
  share one data rate (250 SPS to 64 kSPS). On the ADC 15 Click the clock is an LTC6903 that the
  firmware must program first (SPI mode 0, CS2 = mikroBUS PWM; the ADC itself is SPI mode 1). It
  is only 0.5 % typ accurate (1.1 % max at 25 °C, up to 1.65 % over temperature): measure the real sample rate and record it.
- The ADC records at 2 kSPS; firmware FIR low-pass + decimation gives the packs 1 kSPS (D-016).
  DRDY is active low (falling edge).
- ADS131M0x inputs survive only AGND −1.6 V to AVDD +0.3 V (at gain ≥ 8, keep inputs between
  AGND −1.3 V and AVDD −1.8 V): piezo heads must be clamped and buffered.
- ADXL355 is digital and does not go through the ADC. It runs on I2C (SCLK/VSSIO to ground,
  address 0x1D or 0x53) at 2000 Hz for the appliance pack.
- ESP32-S3-N16R8 uses octal PSRAM: GPIO 33, 34, 35, 36 and 37 are taken (datasheet Table 2-14).

## Commands

```bash
python tools/validate.py                       # schemas, examples, packs, sidecars
python .claude/scripts/checks.py               # the L0 gate on uncommitted changes
python .claude/scripts/vault_schema.py --all   # every vault note against the rules
python .claude/scripts/ledger.py list --open   # open flags
python .claude/scripts/ledger.py retro-due      # is a retro worth running now, and why
python -m unittest discover -s .claude/tests   # tests for the hooks, gate, ledger and retro trigger
git submodule update --init                    # AnuPpuccin theme for the vault
idf.py -C firmware build                       # ESP-IDF v6.0+, target esp32s3 (or via eim run)
```
