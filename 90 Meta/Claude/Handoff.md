---
type: handoff
updated: 2026-11-23
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-11-23 evening, desktop-db0e1qv)
- **Footstep-id goes first** (1 of 3 people at ≥ 85 %) and now also says **where a step came from**: the side, a bearing with its front/back mirror, and a distance band. Both decisions are proposed, **not yet accepted**: [[D-026 Year 1 order footstep-id first]] and [[D-027 Footstep-id tells the side of a step]] (rewritten today, no target yet). Background: [[Footstep direction with two geophones]].
- **The Lab has a Locate page** (`tools/lab`, display maths only, D-017):
  - A 2D radar with the device in the middle, wedges at each step's bearing, a dashed mirror wedge, and water-drop ripples where each step landed.
  - Two-spot calibration: 1 m left, then 1 m right. It is saved in `%APPDATA%\rzlab\locate.json`.
  - API: WEB_API.md section 15. Code: `core/locate.py`, `server/locate.py`, `sim/room.py`, `web/src/components/LocatePage.svelte`.
  - Only the simulator has been tried so far (side 46/46 on an ideal simulated floor). **The real-floor test is [[Test the Locate page on the real floor]], 2026-11-24.**
- **One-click start:** the "Rezonating Lab" desktop shortcut (installed on desktop-db0e1qv) does everything:
  - starts the server hidden (with `--sim-room`)
  - connects a plugged-in node
  - opens a Chrome/Edge app window; closing it stops the server
  - Another machine: run `tools\lab\launcher\Install-Shortcuts.ps1` once. The first click then builds `.venv` and the UI.
- **OTIO Veszprém on 2026-11-30 (Monday).** The S3 rig (ESP32-S3 + ADC 15 Click + two SM-24 ~123 mm apart, USB-C) goes in [[OTIO case v1]]. The Locate page is the demo screen.
- **Bench facts:** `firmware/rig-s3` is flashed on pc-10's board: link on the USB-OTG port, 1996.10 Hz cold, 0 lost. The two channels read in anti-phase (−0.99): either reversed wiring or the case rocking; the coin test decides.

## Next up
| Who | What |
| --- | --- |
| Kaszti | **Tomorrow:** [[Test the Locate page on the real floor]] (coin test, calibrate, walk at 1/2/3 m). Accept or change D-026 and D-027 in Obsidian, and set the D-027 target. OK the case look and take the three caliper measurements. Commit tonight's work (plan below) |
| Kaszti + Viktor | Record real footsteps from 3 people, both sides (Lab data root on pc-10). Swap the geophone wires if the coin test says wiring |
| Viktor | Firmware README pin map vs the hackathon guide. Review `firmware/rig-s3` |
| Claude | 1) Tune the Locate page from tomorrow's numbers (detector threshold, band, decay `n`, wedge widths). 2) **Retro** (due). 3) Finish the case after the measurements. 4) `verify` the study site |

## Commit plan (not committed)
1. **Code:** "Lab: Locate page (step direction, calibration, ripples), room simulator, one-click launcher": `tools/lab/` (README, WEB_API, src, tests, web/src, launcher/).
2. **Vault:** "Vault: 2026-11-23 step direction research, D-027 widened, Locate test plan, Handoff": `60 Research/`, `80 Decisions/D-027…`, `10 Project/Charter.md`, `10 Project/Roadmap.md`, `40 Packs/footstep-id.md`, `20 Work/Test the Locate page…`, the daily note, the Session log, this Handoff, `runs.jsonl`.
3. **Not mine, left untouched:** `docs/otio-poster/poster.html` and `70 Journal/Daily/2026-11-16.md` (Kaszti's edits from before this session).

## Open flags
- 13 open, none new today. The retro takes them: F-261123-dab8 (second USB cable), F-261101-b2c0 (idf-build gate), F-261102-f78b, F-261103-e4ed, the 2026-10-13 ml-dev flags.

## Watch out
- **Two Lab tests fail on desktop-db0e1qv:** `test_links_are_not_followed…` and `test_out_dir_guard…`. Windows won't let this PC create symlinks (WinError 1314). `test_soak_end_to_end_smoke` fails only when the whole suite runs.
- **Locate:**
  - Don't calibrate against the simulator: the walker never stands still.
  - Before calibration the wave speed is a 100 m/s guess and the distance is "not calibrated".
- **The browser builds aren't in git.** Run `rzlab build-ui` (or the launcher's setup) after pulling UI changes; the launcher serves `static/` from disk.
- `scratch/` stays out of git. Promote `side_test.py` (pc-10) into `ml/` before anything imports it. Shared side/bearing code in `ml/` needs D-027 accepted (Tier 1).
- **Hardware and build:**
  - The LTC6903 drifts with temperature: use the measured rate.
  - Build firmware from PowerShell.
  - One USB cable in the OTG port.
- Accepted decisions are hook-locked: propose a new one with `supersedes`.
