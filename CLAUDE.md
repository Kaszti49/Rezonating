# Rezonating — context for AI assistants

Read this before changing anything in the repo or the vault. Claude is a member of
the team here, not a tool: it owns work items like everyone else.

## What this is

A vibration-sensing platform built by a two-person team (Kaszti Benedek:
design and management; Szabó Viktor: code). One ESP32-S3 node reads up to four
sensor heads through an ADS131M04 ADC (plus I2C for digital heads). Software
packs, not firmware changes, decide what a node detects.

Scope is **Year 1 only**: `footstep-id`, then `fall`, then `appliance`. Do not
plan or build for later packs unless asked.

## Rules

- **Tier 1 files** (`schemas/`, `firmware/components/` core, shared feature
  code in `ml/`) change only together with a decision note in `80 Decisions/`.
- **`scratch/` is throwaway.** Nothing outside it may import from it.
- **Never commit raw recordings** (`*.wav`) or the name list behind person
  pseudonyms (P1, P2, …). Only sidecars and the dataset manifest go in git.
- **Count every sample.** Firmware must report dropped samples, never hide them.
- **One feature implementation, two languages.** Any change to feature code in
  Python needs the matching firmware change and updated test vectors.
- Run `python tools/validate.py` before committing schema, pack or sidecar
  changes.

## Session protocol (Claude has no memory between sessions)

1. **Start:** read this file → `90 Meta/Claude/Handoff.md` → `Home.md` → your
   queue: work notes with `owner: claude` and not `done`, plus inbox notes tagged
   `#ask-claude`.
2. **During:** add one line under `## Claude` in today's daily note
   (`70 Journal/Daily/YYYY-MM-DD.md`; create it from the Daily template if missing).
3. **End:** append an entry to `90 Meta/Claude/Session log.md` (never edit old
   entries) and **rewrite** `Handoff.md` so the next session can continue cold.

## The vault (Obsidian, repo root = vault root)

- Numbered folders `00`–`90` are the vault; everything else is code. See
  `10 Project/Vault rules.md` for folders, note types and allowed values.
- **Properties are data.** The dashboard (`90 Meta/Views/rz/view.js`) and the
  Bases (`90 Meta/Bases/*.base`) read frontmatter. Use only the allowed values,
  dates as `YYYY-MM-DD`, links in properties as `"[[Note name]]"`.
- **New notes:** copy the frontmatter of the matching template in
  `90 Meta/Templates/` and fill it in. Never write `<%` into a note: Templater
  executes it when the file appears.
- **Finishing work:** set `status: done` and `done: <date>` together.
- **Decisions:** propose a `D-###` note with `status: proposed`; only Kaszti or
  Viktor set it to `accepted`.
- **Never** edit another person's section of a daily note, change someone
  else's due dates without saying so in the note's Log, or delete notes; move
  doubtful ones to `00 Inbox` instead.
- **Obsidian Git** pulls on startup; Kaszti and Viktor commit. Claude commits
  only when asked, and never mixes vault edits with code edits in one commit.
- Before the repo goes open source, the numbered folders, `Home.md` and
  `.obsidian/` are removed (D-012).

## Hardware facts that bite

- ADS131M04 needs a continuous 8.192 MHz clock on CLKIN (no internal
  oscillator). All 4 channels share one data rate (500 SPS to 64 kSPS).
- ADS131M04 inputs survive only AGND −1.6 V to AVDD +0.3 V: piezo heads must be
  clamped and buffered.
- ADXL355 is digital (SPI/I2C) and does not go through the ADC.
- ESP32-S3-N16R8 uses octal PSRAM: GPIO 35, 36 and 37 are taken.

## Commands

```bash
python tools/validate.py                # schemas, examples, packs, sidecars
git submodule update --init             # AnuPpuccin theme for the vault
cd firmware && idf.py build             # ESP-IDF v5.3+, target esp32s3
```
