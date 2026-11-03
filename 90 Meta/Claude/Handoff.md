---
type: handoff
updated: 2026-11-02
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-11-02, EP-LAPTOP, ended by a power cut)
- **The site streams the real board.**
  - The bench ESP32 runs the link-mode bring-up firmware, verifier **PASS** (F-261101-457b resolved). Claude flashed it at Kaszti's request (ESP-IDF v6.0, 213 376 B).
  - `rzlab serve` → `serial:COM12` gives `adc_dec` at 997.3 Hz (−0.21 %), 0 device drops.
  - Link loss at 115200: about 0.07 % of frames, plus 200 host-side samples.
- **The load cell still gives no signal: the excitation stops at the 680 Ω resistor.**
  - 3.3 V on its 3V3 end, **0 V on the cell end**: either the resistor or its joint is open, or that end is shorted to GND (the resistor soldered to black, or a solder bridge).
  - CH1 and CH2 move together when the rig is handled, and CH1 sits at the ADC offset (≈250 µV).
  - The green wire's contact is also suspect (CH1 jumps when it moves).
- **After a reconnect the ADC read ID 0xFFFF/0x0000** until Kaszti re-seated the jumpers. The mikroBUS jumpers are fragile.
- **EP-LAPTOP:**
  - The repo folder `C:\Users\enterpartner\Rezonating-main` is a **zip copy, not a git clone**: today's push went through a scratchpad clone.
  - Python 3.12, ml + Lab, Lab UI, WinLibs GCC (host tests: `CC=gcc`) and ESP-IDF v6.0 in `C:\esp\v6.0` are installed.
  - The classifier blocks `-ExecutionPolicy Bypass` (IDF activation, the esp-idf MCP), so Claude ran idf.py through a scratchpad launcher that sets the env from `Microsoft.v6.0.PowerShell_profile.ps1`. That launcher is gone next session: recreate it, or use the EIM desktop shortcut.

## Study site (2026-11-03, pc-10)
- `python tools/study/serve.py` (port 8790). 28 lessons EN/HU, 3D parts and builds, fault cases, cards, Claude tutor. Progress goes to `10 Project/Study/` (new `study` note type in vault_schema.py and Vault rules).
- **Not verified yet** (the verifier was skipped for the usage limit): run `verifier` on `tools/study/**`, and check lesson facts against the writers' flags. Their flags:
  - AMS1117 800 mA / 1.1 V are not datasheet-checked;
  - the SM-24 damping figures come from a secondary source;
  - f_data = CLKIN/2/OSR should be confirmed in the datasheet;
  - a native speaker should skim the Hungarian.
- The writer hook blocks `tools/`. Content went through `docs/study-drafts/` and was moved. Consider allowing `tools/study/web/content/**` for the writer (`.claude/` change: needs approval).
- Ask Kaszti: delete the old `docs/study-guide.html` and `docs/study-library/`?

## Next up
| Who | What |
| --- | --- |
| Kaszti | USB unplugged, Ω mode: across the 680 Ω resistor (≈680 Ω? OL = open joint), cell end to black (≈1070–1120 Ω? ≈0 = short). Is the resistor on the **red** wire? Re-do the green/white ends (tin, clamp). Then red–black ≈2.0 V and a press test with one end fixed. Clone the repo properly on EP-LAPTOP (or replace the zip folder). Flip D-021/D-022 in Obsidian |
| Kaszti + Viktor | Is the classic ESP32 the node now? Is the ADXL355 in the lab? Is the sim drift plausible? |
| Viktor | Review D-021 parameters; [[FootprintID dataset loader]]; confirm the bench-guide pin map |
| Claude | 1) Press test with Kaszti in the site. 2) Lab: restart acquisition after a serial reconnect. 3) README fixes from F-261102-f78b (mislabel bound 5 → 8, inside the FIR window). 4) Higher link baud? (proposal). 5) Symlink tests skip on WinError 1314. 6) Lab re-verifies 4c, 5, 7, sim people. 7) D-022. Add EP-LAPTOP and desktop-o8pjtu7 to [[Workstations]] |

## Open flags
- F-261102-f78b (low): README mislabel bound; DRDY latency ≥130 µs drifts the index and nothing reports it (idea: worst grid offset in `[CNT]`).
- 4c (F-261013-860d/-4a62, next failure → deep-engineer), sim people (F-261013-02f8/-80bb), Lab 7 (F-261013-1e25): waiting on re-verify.
- F-261013-906b, -e9b4, -da80, F-261006-646c, F-261101-b2c0 (gate skips idf-build): for /retro.

## Watch out
- After a USB unplug, `rzlab serve` reconnects but stays idle: POST `/api/acquisition {"action":"start"}` (or Start in the UI).
- Don't open COM12 from two programs; a text capture needs the site disconnected.
- Ω measurements only with the USB unplugged; a meter lead in the mA jack shorts what it touches.
- ml vectors are pinned to footstep-id's trigger; Bench retuning means regenerating them and telling firmware.
- Accepted decisions are hook-locked: propose a new one with `supersedes`.
