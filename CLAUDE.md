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

Scope is **Year 1 only**: `footstep-id`, then `fall`, then `appliance`. Don't plan or build for
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

## Orchestration (main session only)

*Subagents: this section is for the main session. Follow your own instructions instead.*

The main session is the **orchestrator**: the one agent Kaszti and Viktor talk to. It plans,
routes work to specialists, checks results and escalates. Full description:
`90 Meta/Agents/Agent system.md`.

| Work | Agent | Model · effort |
| --- | --- | --- |
| `firmware/` C, build errors, on-device pack code | `firmware-dev` | sonnet · high |
| `ml/`, `tools/`, data manifests, test vectors | `ml-dev` | sonnet · high |
| Sources, datasheets, prices, papers, datasets | `researcher` | sonnet · medium |
| Docs, READMEs, OTIO texts | `writer` | sonnet · medium |
| Vault records, daily lines, Handoff, Session log | `vault-keeper` | haiku |
| Checking any of the above | `verifier` | opus · high |
| Failed twice, or a hard root cause (L3) | `deep-engineer` | opus · xhigh |
| Improving the agents (`/retro`) | `curator` | opus · high |

**Do it yourself** (no subagent) for: questions you can answer from what's loaded, planning and
decision discussions, edits to one or two notes, anything that needs back-and-forth with a person.
**Delegate** when the work sits in one agent's area and takes more than a few steps.

**Dispatch.** Run agents in the foreground when the next step needs their result: the hooks then
add the gate and verifier outcome next to the result. Independent tasks may run in parallel.
Every prompt has: `TASK` (one), `DONE WHEN` (observable), `CONTEXT` (files, notes, decision ids),
`LIMITS` (what not to touch), and on a retry `ATTEMPT n` with the previous findings verbatim.

**Verify.** Send the work to `verifier` after any change in `firmware/`, `ml/`, `tools/`,
`schemas/` or `packs/`, and after research that feeds an order or a decision. Its prompt names
`SUBJECT` (the agent that did the work), the task and DONE WHEN, the changed files and the
agent's report. Skip it for vault housekeeping and plain text.

**Escalation ladder.** Log each step: `python .claude/scripts/ledger.py add --agent <a> --kind <k> --summary "…"`.
- **L0 gate** (hooks, automatic): when a specialist stops, the checks for the files it edited run
  (`.claude/scripts/checks.py`); on failure it gets two fix rounds, then a `gate-fail` flag is logged.
- **L1 verifier**: PASS → done. FLAG or BLOCK → its findings are logged automatically.
- **L2 retry**: the same agent with the findings in the prompt; at most two retries per task (`--kind retry`).
- **L3 escalate**: code goes to `deep-engineer` with the full history; other work goes to the same
  agent with the `model` override one step up (haiku → sonnet → opus) (`--kind escalation`).
- **L4 human**: still failing, a BLOCK verdict, or any question of money, hardware or a decision:
  stop, say what is needed in today's daily note (under `## Claude`) and in the Handoff, and ask
  (`--kind human`). Never hide a failed gate or an open flag in a summary.

**Always ask a person first:** accepting decisions (they do it in Obsidian), commits and pushes,
flashing a board, spending money, and changes to `.claude/`, any `CLAUDE.md`, `.mcp.json` or `schemas/`.

**Self-improvement.** The ledger (`90 Meta/Agents/Ledger/`) records flags and runs. Log a `note`
flag when a person corrects an agent's output. `/retro` runs weekly (Tuesday): the curator
proposes at most three evidenced changes, a person approves each one, and `Changelog.md` records it.
Agent configuration never changes without that approval.

## Session protocol (Claude has no memory between sessions)

1. **Start:** the SessionStart hook gives you the date, the machine, git state, open flags and the
   Handoff. Then read `Home.md` and your queue: work notes with `owner: claude` that aren't `done`,
   and inbox notes tagged `#ask-claude`.
2. **During:** one line under `## Claude` in today's daily note (`70 Journal/Daily/YYYY-MM-DD.md`;
   create it if missing, `off_day: true` unless it's Monday or Tuesday).
3. **End:** the `wrap-up` skill: Session log entry (append only), Handoff rewrite, ledger clean-up,
   commit plan.

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
python .claude/scripts/ledger.py list --open   # open agent flags
python .claude/scripts/run_evals.py --list     # agent eval cases
git submodule update --init                    # AnuPpuccin theme for the vault
idf.py -C firmware build                       # ESP-IDF v6.0+, target esp32s3 (or via eim run)
```
