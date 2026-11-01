---
type: handoff
updated: 2026-11-01
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-11-01, off-day, desktop-o8pjtu7)
- **Bench rig works on the digital side.** COM5 runs the bring-up firmware:
  - ADS131M02 ID 0x2205, register writes OK, 1995.80 Hz measured (CLKIN ≈ 8.1748 MHz, −0.21 %, in [[ADC 15 Click board]]);
  - CRC 0, missed 0, unaccounted 0;
  - HX711 found (nothing on its inputs).
  - **The SPI fix:** the ESP32 needs `cs_ena_pretrans`/`posttrans` = 2 for the ADC. Default CS timing gives a one-bit shift and ignored commands.
- **The load cell gives no signal.** CH1 behaves like a grounded input: ≈190 µV offset, the same as CH2, and no response to presses. The bridge has no excitation; suspect the taped red (E+) → 680 Ω → 3V3 joint (seen on Kaszti's photos; deleted at his request).
- **Link mode in the bench firmware, built and NOT flashed:**
  - UART0 at 115200, `adc_dec` only; it switches from the text report on GET_INFO, and only a reset brings the text back.
  - Host test 58/58: link vectors byte-exact, FIR bit-exact with `rezonating_ml`. App 219 744 B.
  - `[DIAG]` is behind `CONFIG_BRINGUP_DIAG`.
  - **Verifier FLAG F-261101-457b (don't flash until fixed):**
    - an ADC frame with a bad output CRC goes into the FIR as good (it should count as a lost raw sample);
    - after a double read, the spurious DRDY pulse is counted as missed when pending ≥ 2, giving a phantom raw index. Classify edges by the `s_drdy_t` gaps, with a host test.
    - Plus 4 lows. Committed anyway at Kaszti's request (2026-11-01).
- **This PC:**
  - ESP-IDF v6.1-beta1 is on `E:\esp`, through `C:\Espressif\tools\Microsoft.v6.1-beta1.PowerShell_profile.ps1` (with `-ExecutionPolicy Bypass`).
  - The auto-mode classifier blocks Claude from flashing: Kaszti runs `! … idf.py -C firmware\bringup-esp32 -p COM5 -b 115200 flash` (460800 failed with serial noise).
  - Node v26.13.0 and the Lab tool are installed, and the UI is built.
- **Lab tests:** 612 passed. 2 fail only on Windows symlink privilege (WinError 1314); the symlink part of the sim-people `--out` guard is untested on Windows.
- **From 10-13, still open:**
  - re-verify Lab 4c, 5, 7 and the sim people;
  - [[D-021 Pack pipeline in rezonating_ml]] / [[D-022 Sidecar stores loss spans]] frontmatter flip (Kaszti);
  - D-022 not built;
  - the 11-17 dress rehearsal.

## Next up
| Who | What |
| --- | --- |
| Kaszti | **With the multimeter:** red–black ≈ 2.0 V? black–GND 0 V? green/white–GND ≈ 1.0 V each? CH2 screws on GND? Redo the red → 680 Ω → 3V3 joint (solder or a terminal), then the press test. Flash link mode when Claude says the verifier passed. Flip D-021/D-022 in Obsidian |
| Kaszti + Viktor | Is the classic ESP32 the node now? Is the ADXL355 in the lab? Is the sim drift plausible? |
| Viktor | Review D-021 parameters; [[FootprintID dataset loader]]; confirm the bench-guide pin map |
| Claude | 1) firmware-dev retry 1 on F-261101-457b (findings verbatim in the ledger), re-verify. 2) Press test in text mode with Kaszti; then `rzlab serve --connect serial:COM5` on the real board. 3) Make the symlink tests skip on WinError 1314. 4) Lab re-verifies 4c, 5, 7, sim people. 5) D-022. Add desktop-o8pjtu7 to [[Workstations]] |

## Open flags
- 4c (F-261013-860d/-4a62, next failure → deep-engineer), sim people (F-261013-02f8/-80bb), Lab 7 Experiments (F-261013-1e25): all waiting on re-verify.
- F-261013-906b, -e9b4 (turn limits), -da80, F-261006-646c (orchestrator notes): for /retro.
- **Verifier lows on the bring-up firmware:**
  - the README links a private claude.ai bench guide and names this PC;
  - a rare start-up race can leave the reader one sample behind;
  - the bit-bang label says ~125 kHz (really ~200).
- The gate's idf-build check can't find IDF on this machine (it isn't on PATH).

## Queued small fixes (not done)
- **Bench:** y-axis labels clipped.
- **Datasets:** `sidecar_prefix` in the cache identity; re-wrap the datasets.py docstring and WEB_API.
- **ml README:** the windows claim; list the `footstep_v1.json` vectors.
- **`test_sim_people.py`:** use `out.features`.
- **`evaluate`:** no per-window predictions.
- **`test_runner_e2e.py`:** flaky under CPU load.
- **Symlink tests:** skip on Windows without the privilege.

## Watch out
- After a site session the bench board stays silent until EN/RESET. `rzlab tail --serial COM5` needs `--streams adc_dec`.
- Don't run two programs on COM5 at once: stop `rzlab serve` before a text capture.
- ml vectors are pinned to footstep-id's trigger; Bench retuning means regenerating them and telling firmware.
- Accepted decisions are hook-locked: propose a new one with `supersedes`.
