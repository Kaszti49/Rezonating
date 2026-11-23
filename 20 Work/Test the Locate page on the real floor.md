---
type: work
status: todo
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
