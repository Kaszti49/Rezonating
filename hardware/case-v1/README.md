# Rezon case v1 (OTIO prototype)

Round PLA case, Ø186.4 × 51.0 mm, for the 150 × 90 mm perfboard with the ESP32-S3-DevKitC-1,
the ADC 15 Click and two SM-24 geophones. It has no screws:

- **Lid:** bayonet twist lock with 3 lugs. Drop the lid in, then turn it 30° clockwise (seen from
  above) until it clicks.
- **Board:** sits on 4 printed pins through its corner holes. A post on the lid's axis stops it
  lifting. The post lands on the board's centre, so **keep a Ø12 mm circle at the board centre
  free of parts**.
- **Geophones:** each press-fits into a floor cup with crush ribs, next to a long edge of the board.
- **USB-C:** a tunnel through the wall leads the plug to the DevKitC's ports. Either port fits.

## Files
| File | What |
| --- | --- |
| `case_v1.py` | The model. All sizes are named parameters at the top; values marked (E) are estimates. Run it in FreeCAD (Macro → Execute) to rebuild everything. |
| `case_v1.FCStd` | The FreeCAD document it writes: Base, Lid, and the `Fit_dummies` group (board, modules, geophones, plug; for checking only). |
| `out/rezon_case_v1_base.stl`, `out/rezon_case_v1_lid.stl` | The parts to print. |
| `out/rezon_case_v1_lid_inlay_white.stl` | REZON and the wave as 6 loose pieces (R, E, Z, O, N, wave), 1.2 mm thick, laid face down. |
| `out/fit_test_logo_coupon.stl` | Only the lid plate around the logo, face down. Print it black with the inlay in white to check the fit. |
| `out/fit_test_neck.stl`, `out/fit_test_lid_ring.stl` | Just the bayonet, about an hour of printing. Print these first. |
| `renders/` | Views of the model. |
| `Rezon_Wiring_Guide_OTIO.html` | 3D soldering guide for the board inside this case. Source in `wiring/`; the module positions in `case_v1.py` follow it. |

The script also prints a fit report. It checks for collisions between the case and the dummies,
whether the plug passes the tunnel, and lid-to-base overlap in the locked position (it must be 0).

## Printing (PLA, Bambu X1E or A1)
- **Base:** upright, floor on the plate, no supports. The USB tunnel roof is a 27 mm bridge.
- **Lid (black):** upside down, top on the plate, no supports. The lugs' undersides are already 45°.
  The logo is a 1.2 mm deep pocket (6 layers at 0.2 mm) on the plate side; 1.8 mm of plate stays under it.
- **Logo inlay (white):** the six pieces, face down, 1.2 mm thick, so they sit flush. They are 0.1 mm smaller
  per side than the pocket: press them in, with a drop of CA glue if one is loose. If they're too tight, raise
  `INLAY_GAP`; if too loose, lower it, then run the script again.
- **Settings:** 0.2 mm layers, 3 walls, 15 % gyroid. Smooth PEI gives the cleanest lid face.
- **Fit gaps:** 0.3 mm between skirt and neck, 0.2 mm lug play, 0.2 mm click interference, 0.1 mm per side
  around the logo inlay.

## Measure before the full print
1. Corner holes: diameter and centre distance from the edges (`HOLE_D`, `HOLE_IN`).
2. Female header height, i.e. ESP32-S3 PCB underside above the perfboard (`HDR_H`). This sets the
   USB tunnel height.
3. Centre-to-centre distance of the two USB-C ports (`USB_SPACING`, only for the dummy).

Then change the values at the top of `case_v1.py` and run it again.
