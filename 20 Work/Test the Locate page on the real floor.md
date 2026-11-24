---
type: work
status: doing
owner: kaszti
priority: p1
area: ml
due: 2026-11-24
pack: "[[footstep-id]]"
created: 2026-11-23
done:
---
# Test the Locate page on the real floor

**Goal:** find out how well the Lab's Locate page tells where a real step came from with the S3 rig (two SM-24s about 123 mm apart in the case), before OTIO Veszprém on 2026-11-30.

## Done when
- [ ] Coin test: a coin dropped on the middle of the lid. Same sign on both channels means the −0.99 anti-phase comes from the case rocking; opposite signs mean the wiring is reversed. Result written in the Log
- [ ] Calibrated on the test floor (5 steps at 1 m straight left, then 5 at 1 m straight right); the wave speed it found is in the Log
- [ ] Walked past at about 1, 2 and 3 m on each side: side right or wrong counted for at least 20 steps per side, in the Log
- [ ] Bearing checked at 3 marked spots (e.g. 45° left, straight ahead, 45° right at 1.5 m): measured against shown, in the Log
- [ ] Distance band checked: does a step at 0.5 m show "near", and one at 2.5 m show "far"?
- [ ] Ripples and wedges are readable from 2 m away (the OTIO screen)
- [ ] Kaszti or Viktor set the D-027 target from these numbers ([[D-027 Footstep-id tells the side of a step]])

## Notes
- **Start:** plug the rig into its USB-OTG port, then double-click **Rezonating Lab** on the desktop. It connects to the board by itself and opens the Locate page. On a machine without the shortcut: `powershell -ExecutionPolicy Bypass -File tools\lab\launcher\Install-Shortcuts.ps1`.
- **Background:** the maths and its limits are in [[Footstep direction with two geophones]]. Front and back look the same; distance comes only from loudness.
- **What the page shows per step:** the time gap (µs and samples), the timing and loudness votes, and the correlation sign. Note these when something looks wrong.
- **Tuning knobs** (Claude changes them from the results): detector threshold `TRIGGER_K`, band 10–200 Hz, distance decay `n` (default 1), window 50 ms before and 300 ms after the onset. Code: `tools/lab/src/rezonating_lab/core/locate.py`, `server/locate.py`.
- **Simulator:** the Lab's Simulator connection walks a person around the device for demos. Don't calibrate against it.

## Log
- 2026-11-23 created. The Locate page, the simulated walker and the one-click launcher are built and work with the simulator (side 46/46 on the ideal simulated floor; a real floor will be worse). Water-drop ripples added at each step's estimated spot
- 2026-11-24 Kaszti, first real-floor run (EP-LAPTOP, rig-s3 on COM17): distance almost random (about 2 cm shown for a 2 m step), left/right often correct, front/back not working
- 2026-11-24 Claude, from the last 10 minutes of raw samples (no ground truth, kept outside git on EP-LAPTOP):
  - **Calibration:** 374 m/s, so the full left-to-right delay is only ±0.33 ms.
  - **Timing:** 0.16 ms scatter from step to step in 12 walking runs (90 steps). Enough for a side, not for an angle.
  - **Loudness:** 7.6 dB scatter, a factor 2.4 in distance per step. Half the "steps" (50 %) were retriggers, 22 windows were clipped and 24 % sat at the 0.1 m floor.
  - **Channels:** anti-phase (cc −0.99) with a gain ratio of 0.90 at 10 Hz and 1.00 at 40–50 Hz. Coin test still needed.
  - **Front/back:** not possible with two sensors on one line (D-027); no software change fixes it.
- 2026-11-24 Claude fixed in the Lab: detector (high-pass, must rise out of the previous 140 ms), clipped steps skipped and counted, loudness no longer noise-subtracted with the wrong band, distance from the median of 5 steps (min. 3) and shown as a band only, bearing hidden when the calibration scatter is too big. Same capture, before → after: steps 580 → 318, retriggers 50 % → 4 %, median step-to-step distance change ×2.18 → ×1.18, same band 44 % → 87 %, unsure side 29 % → 37 %. That is consistency, not accuracy: the marked-spot test is still to do, and the calibration must be redone
- 2026-11-24 Kaszti redid the calibration (8 + 8 steps): only left/right was shown, no direction. Claude found the 16 steps in the raw data. My rule hid the angle on both sides because of one left step (1.70 ms); the right side was fine. New: timing in 20–60 Hz (scatter over delay: left 0.76 → 0.31, right 0.17 → 0.07; picked on these same 16 steps, so optimistic), each side judged on its own, a third "1 m ahead" calibration spot, timing alone decides the side. Leave-one-out on the 16 steps: side 16/16 (also with the old band), angle error about 15–20° on average at straight left/right (zero taken from steps at an unknown spot)
- 2026-11-24 **Left and right are not mirror images:** 1.73 ms against −0.75 ms at 20–60 Hz, and left scatters 4× more. Case coupling or floor? Check: turn the case 180° and calibrate again
- 2026-11-24 Kaszti: after "Calibrate left", left steps read as right. Two causes: (1) **hardware state:** at about 09:11 the two geophones stopped moving alike (correlation on loud steps from −0.9…−1.0 to mostly +0.6…−0.4, loudness ratio up to 6, ch0 DC 3 400 → 5 000); cause not known, coincides with very loud events; (2) **Lab:** one spot could set `swap_sides`, so a garbage spot (−3.5 ms ± 4.4 ms) flipped every step (F-261124-63e1). Fixed: steps need |cc| ≥ 0.9 with the calibrated polarity; a spot is refused if the geophones disagree or the scatter is over 1 ms; one spot never sets sides; the page warns when the geophones disagree. The same 8 steps are now refused, the good 16 still give 16/16
- 2026-11-24 Kaszti: small steps weren't registered, so calibration would need jumps. Cause: the detector's noise floor rose with step tails (about 1.6×, up to 6×). New floor: 20th percentile of the last 5 s, threshold 5×, gentler rise rule. On the latest capture, bumps 5–8× the quiet level found 12 % → 66 %, 8–12× 44 % → 85 % (bumps, not confirmed steps; 0 triggers in 10–15 s of quiet). Second finding: the geophones disagree more the louder the step (agree 94 % of the quietest, 19 % of the loudest), so don't calibrate with jumps. Cause of the disagreement is still open
- 2026-11-24 Kaszti: make it black and white, no maths: first or stronger on the left is left, on the right is right, the same is front or back; no exact location from two geophones. Claude scored that rule on 32 steps whose side is known (8 left 08:53, 8 left 09:15 while the geophones disagreed, 8 right 08:53, 8 right 09:40; sides from where Kaszti was told to stand): 28 right, 3 same, 1 wrong with **no calibration**; every setting tried gave 26–28. Zero offsets (0.2 ms, ratio 1.05) come from background steps at unknown places. In-sample, so expect less; front/back not tested. Earlier 8-step left calibration at 09:15 was readable all along by loudness (7 of 8, the rest too close)
- 2026-11-24 Locate rewritten: LEFT / RIGHT / FRONT or BACK, the calibration, angle, distance and wave-speed code removed; **Swap left and right** for a turned case. D-027 (bearing + distance band) no longer matches the page: Kaszti to confirm before the decision, Charter, Roadmap and pack note change
- 2026-11-24 Kaszti: far steps come out FRONT or BACK; close up it needs exactly 90°. Asked whether raw data (learning) can do better. Confirmed on the two recordings: FRONT or BACK is 60 % of the faintest steps and 0 % of the loudest. Learning check (per-band loudness and phase, nearest class): trained on 08:53 only, the later sessions give 15 of 16 right (09:15 left 8/8, 09:40 right 7/8), against 12 of 16 for the rule; but trained on the other three sets, 08:53 left is 0 of 8. Too little data (32 steps, no front/back) and one set has the geophones disagreeing. Next: 8 spots × 10 labelled steps, twice, before choosing
- 2026-11-24 Kaszti did round 1 (8 spots, about 10 steps each, no 10 s pauses, walking between spots): 10:00:59–10:02:57, 135 steps, in `floor-2026-11-24-round1.npz` on EP-LAPTOP. Claude split it from the pattern and the instructed order (1 m left, right, front, back, then 2 m the same), so **the labels are Claude's reading and not independent**; accuracy can't be taken from it. What holds without labels: 1 m left and right stand far apart in the loudness ratio (about 1.36 against 0.65), 2 m left is 1.09, and 2 m right, front and back all sit at 0.99–1.00 with the same delay (−0.1 to −0.3 ms): these three can't be told apart. The neutral ratio here is about 1.00, not the 1.05 in the code, so the page calls almost everything at 1.00 RIGHT. At 1 m the geophones agree in 6 % (left) and 47 % (right) of steps. Round 2 needs clear pauses
- 2026-11-24 Recorded as [[EXP-002 Locate page first real floor run]] and [[EXP-003 Eight spots round 1]] (the fair test is round 2); review and proposals in [[Lab and Locate review 2026-11-24]]. Open here: coin test, round 2, the D-027 target
- 2026-11-24 Kaszti approved the proposals: the rule is now louder, else first, else front, back or far ([[EXP-004 Louder then first on the recorded steps]]); record round 2 with the protocol `locate-spots-v1` on the Record page
