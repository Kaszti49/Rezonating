---
type: handoff
updated: 2026-11-15
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-11-15, desktop-db0e1qv, off-day)
- **The hackathon fall detector is in the repo.** The HARMAN Hackathon (13–14 Nov) built a working detector: 3 of 3 stage falls caught, 3 of 3 jumps rejected ([[EXP-001 Hackathon fall detector on stage]]).
  - Snapshot of `Kaszti49/RezonFallDetector` at `f6d2eee`: the code is in `firmware/hackathon-rezon/` (Arduino, reference only; read its README), the hardware sources in `hardware/hackathon/`.
  - Recordings are **not** in git. The 4 CSVs and the 2 session logs are in `data/raw/hackathon/` on the home desktop (Kaszti, 2026-11-15); the README's replay check passes from there. Other machines need their own copy.
- **OTIO in Veszprém on 2026-11-30 (Monday):** the next thing that has to be presentable. The plan is to present the fall detector. More fall tests come first, which is why the gain question is open.
- **Fall goes first now; the architecture stays.** Accepted: [[D-023 Year 1 order fall first]] and [[D-024 Hackathon core is the fall pack engine]].
  - The C++ core is ported into the ESP-IDF node with a linear score and a Python twin. Calling, speaker and BLE are parked under Later in the [[Roadmap]].
  - The new Roadmap dates (fall gate 2027-01-12, footstep 2027-04-06) are Claude's proposal.
- **Claude is one agent with playbooks** ([[D-025 One agent with playbooks]], accepted; [[Agent system]]).
- **Work cleanup (2026-11-15):** 7 items that were done but never logged are now `done`, each with its evidence in the Log: Push repo, Lab 1, EU stock, company PC, ESP-IDF, OTIO Győr, first order. [[ORD-001 First rig]] still needs its order and delivery dates.
  - The Stop hook is the L0 gate.
  - `verify` is the L1 check.
  - The retro is triggered by evidence: `ledger.py retro-due` already says **due** (12 agent-era flags, three logged corrections).
- **Bench (from 2026-11-03):** load-cell press test PASS after the 680 kΩ → 690 Ω (470 + 220) fix. The Lab connect fix passed the verifier but is not yet tested on the real board.
- **Study site** (`python tools/study/serve.py`, port 8790) still needs checking with the `verify` playbook. Lesson facts flagged by the writers: AMS1117 values, SM-24 damping, f_data = CLKIN/2/OSR, a native-speaker skim of the Hungarian.

## Next up
| Who | What |
| --- | --- |
| Kaszti | Fill in the ORD-001 dates. OK the new Roadmap dates. Older items: D-021/D-022, the EP-LAPTOP git clone, delete the old `docs/study-guide.html`? |
| Kaszti + Viktor | More fall tests, then decide gain 2 or 4. OTIO Veszprém prep (2026-11-30): should Claude make a work item for it? Is the SM-24 + ADC 15 Click setup now the Year 1 bench rig? |
| Viktor | Review [[Port the fall core to ESP-IDF]] and D-024. D-021 parameters. [[FootprintID dataset loader]] |
| Claude | 1) **Retro** (due): triage the 12 open flags ([[First agent retro]]). 2) [[Port the fall core to ESP-IDF]] (unblocked). 3) `verify` the study site. 4) Lab: restart acquisition after a reconnect, then the README fixes from F-261102-f78b |

## Commit plan (not committed)
1. **Code:** "Merge hackathon fall detector (f6d2eee) as reference": `firmware/hackathon-rezon/`, `hardware/hackathon/`, `.gitignore`, `tools/study/.../s08.*`.
2. **Code:** "Replace agents with playbooks": `.claude/`, `CLAUDE.md`.
3. **Vault:** the decisions, EXP-001, the work notes, the pack notes, Charter, Roadmap, the system notes, the daily note, the Session log, this Handoff, the Changelog.

The two uncommitted vault files that were there before this session (`10 Project/Study/Kaszti.md`, `20 Work/Push repo to GitHub.md`) are untouched.

## Open flags
- 12 open from the agent era (they keep their agent names); the retro takes them. Notable: F-261101-b2c0 (the gate skips idf-build when IDF is only reachable through the EIM profile), F-261013-860d (4c), F-261102-f78b (README bound).

## Watch out
- The dashboard's Claude card still shows a "Verifier" KPI; it stays at 0/0 now. Fix it only if someone asks (view code).
- `firmware/hackathon-rezon/` is a reference: don't develop it further, port from it.
- The replay defaults differ from the settings that were in the device's flash; use the `--set` values in its README.
- After a USB unplug, `rzlab serve` reconnects but stays idle: Start in the UI.
- Ω measurements only with the USB unplugged.
- Accepted decisions are hook-locked: propose a new one with `supersedes`.
