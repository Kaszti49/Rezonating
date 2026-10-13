---
type: handoff
updated: 2026-10-13
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-10-13)
- **Rezonating Lab phases 1–3 done** ([[Lab 2 Live and Device pages]], [[Lab 3 Recorder and live labels]]):
  - live view, device page and recorder;
  - server-stamped Space marks and a phone marker (QR);
  - WAV + v1 sidecars through `rezonating_ml.io`, and `rzlab validate`.
  - Verified (verifier PASS). The team has looked at the site and likes it.
  - Short explainer: Claude Doc "Rezonating Lab: how it works". Next phases are in [[Lab build prompts]] (phase 4 onwards).
- **Hardware in the lab differs from the plan.** The photos (in `90 Meta/Attachments`) show:
  - a **classic ESP32** DevKit (WROOM-32, CP2102) on an expansion board ([[ESP32 DevKit V1 with expansion board]]), **not** the [[ESP32-S3-DEV-N16R8 board]] (set back to `needed`);
  - the [[ADC 15 Click board]] (ports logged);
  - a [[YZC-133 load cell 5 kg]] (a weighing cell, not a geophone);
  - an [[HX711 load cell amplifier board]].
- The ADXL355 and microSD are not in the photos. The SM-24 geophones are missing.
- **First rig bench guide** (Claude Doc) is written for these boards:
  - pin map for the classic ESP32 (VSPI D18/D19/D23, CS1 D17, CS2 D16, DRDY D4, RST D27, HX711 D34/D32);
  - load cell on Click CH1 through a 680 Ω resistor, or on the HX711;
  - a wiring diagram and a build-order diagram.
- **First board is alive** on COM22 (CP2102; data only via the DevKit's own micro-USB): ESP32 rev 3, **WROOM-32**, 4 MB, factory AT firmware. It boots fine with the bench wiring attached.
- **Bench bring-up firmware** `firmware/bringup-esp32/` (Kaszti: bench-only, separate from the node firmware; flashing approved). It builds clean for `esp32`, but has **verifier FLAG F-261013-34f1, not flashed yet**. Fix first: arm the DRDY interrupt before the two-frame FIFO flush, read two frames when behind, and fix the README range note (the rig feeds 2.0 V through 680 Ω, so about 1.0 V is in range). Then flash: `eim run "idf.py -C firmware/bringup-esp32 -p COM22 flash monitor"` from PowerShell (`Remove-Item Env:MSYSTEM` first if it came from Git Bash).
- **Agents pinned to 5.5 models**: firmware-dev and ml-dev run on Opus 5.5 (Changelog 2026-10-13). Keep each brief small: ml-dev hit its 60-turn limit twice on big briefs (F-261013-906b, for /retro).

## Next up
| Who | What |
| --- | --- |
| Kaszti + Viktor | Decide: is the classic ESP32 the node now, or are S3 boards coming? (bring-up is bench-only either way) Is the ADXL355 in the lab? Is the load cell on Click CH1 or on the HX711? |
| Viktor | Confirm the bench-guide pin map; [[Wire the first rig]] follows the guide now; [[FootprintID dataset loader]] (2026-10-20) |
| Claude | firmware-dev retry on F-261013-34f1 (small) → verifier → flash COM22 and read the first report: ADC ID, real sample rate, load cell on CH1, noise floor on CH2, HX711. Then streaming to the Lab. Small Lab follow-ups: reject IPv6 `marker_bind`, drop `kill-test-phone` from the protocol list |
| Kaszti | Real-phone marker test on the Record page; ORD-001 status |

## Open questions
- Everything up to 2026-10-13 is pushed to GitHub (Kaszti asked).
- License for open source (backlog); which GPU the home desktop has.

## Watch out
- Git Bash on pc-10 has no coreutils or python on PATH. Use full paths: Python `C:\Users\benedek.kaszti\AppData\Local\Programs\Python\Python312\python.exe`, git `C:\Program Files\Git\cmd\git.exe`. Or use PowerShell.
- `idf.py` refuses Git Bash (MSYS); build from PowerShell or the EIM shortcut.
- Accepted decisions are hook-locked. To change one, propose a new decision with `supersedes`.
- Lab: install with `pip install -e ml -e "tools/lab[dev]"`. The slow accuracy test runs only with `RZ_SLOW=1`. Vite dev needs `rzlab serve --dev`. Today's data root was `C:\Users\benedek.kaszti\rzlab-data` (env var only, not saved to config).
- pc-10 ran low on memory on 2026-10-13: Claude Code stopped the background sim and server. Close other programs before long runs.
- 13 old `rz-accept-*` folders with simulator WAVs sit in `%TEMP%`; delete by hand.
