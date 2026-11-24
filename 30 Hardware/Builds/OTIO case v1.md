---
type: build
status: doing
owner: claude
date: 2026-11-23
---
# OTIO case v1

**What:** the first designed 3D-printed case for the prototype node shown at OTIO Veszprém (2026-11-30). At OTIO it only has to prove that the node detects footsteps. Modelled in FreeCAD (MCP Bridge add-on) by Claude; work item: [[Design the OTIO case v1]].

## Inside (Kaszti, 2026-11-23)
- **Two [[SM-24 geophone]]s** (changed from one on 2026-11-23), each with its 1 kΩ shunt resistor soldered on top of the terminals. One per Click channel (CH1, CH2).
- [[ESP32-S3-DEV-N16R8 board]] and [[ADC 15 Click board]], hand-wired on a **new, blank 150 × 90 mm perfboard**: double-sided, plated through-holes, a mounting hole in each corner (photo `scratch/prefboard.jpg`, not in git). The hackathon board was a cut-down 35 × 27-hole piece (`hardware/hackathon/wiring_source/gen.py`), so the new board needs its own wiring layout.
- **Power: USB-C** to the ESP32-S3, no battery.
- **Left out for OTIO:** the SIM868 module and its GSM antenna.
- Tallest point today: the geophone with the resistor on top. The hackathon case was about 43 mm tall (Kaszti's memory). Measured from `hardware/hackathon/`: the base was Ø190 × 40 mm and the lid Ø196 × 14 mm.

## Design choices (Kaszti, 2026-11-23)
- **Round case** about Ø195 × 50 mm. The board's diagonal is 175 mm, so its corners locate it in the wall.
- **No screws:** a bayonet twist lock on the lid (quarter turn with a click detent). The board is held without screws or standoffs.
- **The geophone sits inside the case** in a press-fit cup in the floor, beside a long edge of the board. It is not a separate outside part.
- **Flat bottom** (no contact pads).
- **Lid marking:** "REZON" with a clean wave symbol, no other symbols. Changed on 2026-11-23: the lid is printed **black**, and REZON and the wave are printed **white** as separate pieces that sit in a pocket in the lid. The boss's minimum depth is 0.6 mm.
- **No LED window** and no light pipe.
- **Material:** PLA, printed on the Bambu Lab X1E or the A1 (both have 256 × 256 mm beds).

- **USB-C:** the DevKitC's "UART" port (CP210x) is the one exposed. The firmware console is on UART, with USB-Serial-JTAG as the secondary (`firmware/sdkconfig`).

## Model v1 (Claude, 2026-11-23)
Source `hardware/case-v1/case_v1.py`, which is parametric and rebuilt in FreeCAD 1.1.4 through the MCP Bridge. The README there has the print settings.
- **Size:** outside Ø186.4 × 51.0 mm. Base about 203 cm³ and lid about 93 cm³ of solid; about 200 g of PLA (estimate).
- **Logo inlay:** a 1.2 mm pocket in a 3.0 mm lid plate, leaving 1.8 mm under it. The white pieces (R, E, Z, O, N, wave) are 1.2 mm thick and 0.1 mm smaller per side; they press in, with CA glue if one is loose. Checked: no overlap with the lid, flush with the top. `out/fit_test_logo_coupon.stl` is just the plate around the logo, for testing the fit. Before this change the STL already had a 0.6 mm engraving (floor at 49.8 mm, top at 50.4 mm in the file); Kaszti saw 0.2 in the slicer.
- **Lid:** 3-lug bayonet, 30° clockwise to close. A click bump with 0.2 mm interference meets each lug in the last 6°. The lugs and groove roofs are at 45°, so no supports are needed.
- **Board:** on 4 corner pins, 5 mm above the floor. A post on the lid axis lands 0.4 mm above the board centre: keep a Ø12 mm circle there free of parts.
- **Geophones:** cups at y = ±61.5 mm, each with 6 crush ribs (0.15 mm press fit). Geophone top at 46 mm, lid underside at 48 mm.
- **USB-C:** a 27 × 8.6 mm tunnel at the −X short edge, centre 21.3 mm above the floor underside. That height assumes 8.5 mm female headers.
- **Fit check:** the case doesn't touch the board, ESP32-S3, Click, geophones or plug. The lid's path, dropping in and turning, is free except at the click bumps; locked overlap is 0.
- **Fit-test rings:** `out/fit_test_*.stl`, just the bayonet, for a print of about an hour before the full one.
- **Wiring layout and guide:** `hardware/case-v1/Rezon_Wiring_Guide_OTIO.html` (source `hardware/case-v1/wiring/gen.py`). It is the hackathon guide stripped to the ESP32-S3, the Click and two geophones. The case model places its dummies from the same holes.
  - **Board grid** (from the photo): 33 columns × 54 rows. The board prints A–Z, A–Z, A, B along the long side; the guide calls the second round AA–AZ and the third BA, BB.
  - **Positions:** ESP32-S3 J3 in column 7 and J1 in column 16, pin 22 in row A at the USB end. Click headers in columns 19 and 28, GND in row A. Everything sits in rows A–V; the right half stays free.
  - **Wiring:** six SPI links each run straight along one row; RST has one bend; 3V3 is one link. A bare GND bus runs along row A and up column 30. Geophone 1 (column-1 side) goes to CH1, geophone 2 to CH2, with twisted pairs of 145 mm and 90 mm.
  - **Pin map:** the hackathon one (`rezon.ino`): SCK 12, MISO 13, MOSI 14, CS 11, CS2 9, DRDY 10, RST 8.
  - **Case change:** the USB tunnel moved to y = −14 mm, and the corner pins are now Ø2.5 mm (0.5 mm under the hole) to take up hole-position error. The fit check is still clean.

## Geophone lock (Claude, 2026-11-24, prototype in CAD, not printed)
Kaszti: the press-fit cups are too tight and the geophones aren't accurate, so the cups go and the geophones stand on the room floor through two holes. Kaszti chose: reprint the base, a collar with three pins, one lever for both. Replaces the press-fit cup above. Files: `hardware/case-v1/geo_lock.py` (sizes and sums), `geo_lock_build.py` (model and checks), `geo_lock.FCStd`, `out/geo_lock_*.stl`, `out/geo_lock_report.txt`. Background: [[Geophone lock for the OTIO case]].
- **Deploy:** the geophone stands free in a Ø32 mm hole. Free air: 3.3 mm at the hole, 1.77 mm to the cage, 1.50 mm below the pins. Still free when tilted 1° and 0.9 mm off centre.
- **Travel:** a cam ring (lower layer) lifts the three pins 2.5 mm into V notches in a fixed cage (upper layer). About 43° of lever; a 5° wedge holds it.
- **Lifted while deployed:** the pins land on the cam ring and the geophone hangs 1.5 mm below the case.
- **Lever** through a slot in the +Y wall; a **rod** over the free half of the board turns both rings. The cage twist-locks on four nubs. The lid is unchanged.
- **Checked in FreeCAD:** 43 checks (9 that the parts are sound solids, 34 for fit and motion), no collisions (board, modules, lid, five lever positions, fitting path). The rod snaps over a lip on its pins, so it stays on upside down (F-261124-7192). Not checked: strength, wear, print tolerance, a real geophone.
- **Keep free:** the rod's path over the board (x = 24 to 36 mm) and 6.5 mm of board edge under each cam ring.

## Open
- Geophone lock: body diameter, bottom shape and smooth height of the real SM-24s (the model uses the datasheet); print one lock first (`fit_test_geo_lock_base.stl`); thin geophone leads with a slack loop.
- The wiring layout above: Kaszti and Viktor OK it, or move parts in `gen.py` and rerun it and `case_v1.py`.
- **Pin maps disagree:** `firmware/README.md` (draft v0: SCLK 12, MOSI 11, MISO 13, CS 10, DRDY 9, RESET 8, no CS2) vs the hackathon `rezon.ino`, which this guide uses. Viktor to pick one for the ESP-IDF port.
- **Hackathon guide's 3D view looks mirrored:** it draws the ESP32-S3's J1 and the Click's AN header on the wrong side for a module seen from above with USB-C on the left (Espressif's v1.1 pin layout shows J1 on the left with the antenna up). The new guide follows Espressif. Check against the real modules when placing the sockets.
- **Click terminal order** (CH1+, CH1−, CH2−, CH2+) is from the part note, not checked on the board.
- Corner-hole diameter and its distance from the board edges: measure with calipers.
- Geophone leads: both geophones sit in floor cups, so their leads to the Click terminals need lengthening.

## Log
- 2026-11-23 created from Kaszti's brief
- 2026-11-23 two geophones instead of one (Kaszti); blank board photo; new wiring layout to be made
- 2026-11-23 model v1 built and fit-checked in FreeCAD; STLs and fit-test rings exported
- 2026-11-23 wiring guide for the OTIO node (2 geophones, ESP32-S3, Click); case dummies moved to its layout
- 2026-11-24 geophone cups replaced by floor holes and a lever lock (Kaszti); prototype modelled, 43 CAD checks pass
- 2026-11-23 logo changed from a 0.6 mm engraving to a 1.2 mm pocket with white inlay pieces (Kaszti, from the boss); lid plate 2.4 → 3.0 mm
