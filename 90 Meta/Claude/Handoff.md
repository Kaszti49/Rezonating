---
type: handoff
updated: 2026-11-23
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-11-23, pc-10, work day)
- **Footstep-id goes first now** (Kaszti confirmed; the architecture stays): 1 of 3 people at ≥ 85 %, plus the side (left/right) of each step. Proposed, **not yet accepted**: [[D-026 Year 1 order footstep-id first]] (supersedes D-023) and [[D-027 Footstep-id tells the side of a step]] (no target yet).
  - Charter, Roadmap, the pack notes and lesson s08 are updated. The Roadmap dates (footstep gate 2027-03-02, fall 2027-04-06) are Claude's proposal. [[Port the fall core to ESP-IDF]] is in the backlog.
  - The `CLAUDE.md` scope line still says fall first: it changes only after an OK.
- **OTIO Veszprém on 2026-11-30 (Monday).** The S3 rig (ESP32-S3 + ADC 15 Click + two SM-24 geophones ~123 mm apart, USB-C) goes in [[OTIO case v1]] ([[Design the OTIO case v1]], due 2026-11-24).
  - Case: Ø186.4 × 51.0 mm PLA, bayonet with a click, inlaid REZON + wave. FreeCAD model, STLs, fit tests and renders in `hardware/case-v1/`. Built through the FreeCAD MCP Bridge on 127.0.0.1:39280.
  - Wiring guide: `hardware/case-v1/Rezon_Wiring_Guide_OTIO.html` (gain 4).
- **The rig works with the Lab.** `firmware/rig-s3` (bring-up sources, OTIO pins in `rig.h`, gain 4) is flashed on pc-10's board: UART0 text report on COM40, link on the USB-OTG port (COM41) with `adc_raw` 2 kSPS + `adc_dec`. Measured 1996.10 Hz cold, 1994.93 Hz warm, 0 lost. `rzlab serve --connect serial:COM41` now starts acquisition by itself.
- **Bench facts:** at gain 2, direct taps reach 6.2 M of 8.39 M codes (gain 32 would clip). One geophone's polarity is reversed (−0.99 correlation on floor signals; probably the CH2 terminal order).
- `scratch/side_test.py` (cross-correlation delay + amplitude ratio) gets the side right on synthetic steps; not yet tried on real footsteps.

## Next up
| Who | What |
| --- | --- |
| Kaszti | Accept or change D-026 and D-027 (in Obsidian). OK the look of the case, and take three caliper measurements: corner holes, header height, USB spacing. OK the Roadmap dates and the `CLAUDE.md` scope line. Print the bayonet fit test. Older: ORD-001 dates, D-021/D-022 |
| Kaszti + Viktor | Swap the reversed geophone's wires (or note it). Set a Lab data root on pc-10 and record real footsteps from 3 people, both sides. Set the D-027 target |
| Viktor | Firmware README pin map vs the hackathon guide (they differ). The hackathon guide's 3D view looks mirrored for J1/J3. Review `firmware/rig-s3` |
| Claude | 1) **Retro** (due: three logged corrections, 13 open flags). 2) Run `side_test.py` on the first real recordings. 3) Finish the case after the measurements. 4) `verify` the study site |

## Open flags
- 13 open. New today: F-261123-dab8 (advised a second USB cable without checking the board's power paths). Older: F-261101-b2c0 (gate skips idf-build when IDF is only on the EIM profile; it ran fine on pc-10 today), F-261102-f78b (README mislabel bound), F-261103-e4ed (Lab connect lows), the 2026-10-13 ml-dev flags. The retro takes them.

## Watch out
- `scratch/` stays out of git (`prefboard.jpg` is 6.9 MB). Promote `side_test.py` into `ml/` before anything imports it.
- The LTC6903 drifts with temperature (0.06 % cold to warm): use the measured rate, not 2000 Hz.
- On this board one cable in the USB-OTG port is enough; don't plug two host cables.
- Build from PowerShell (idf.py refuses MSYS). Ω measurements only with USB unplugged.
- Accepted decisions are hook-locked: propose a new one with `supersedes`.
- `firmware/hackathon-rezon/` is a reference: port from it, don't develop it.
