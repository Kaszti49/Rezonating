---
type: work
status: doing
owner: claude
priority: p1
area: design
due: 2026-11-24
pack: "[[footstep-id]]"
created: 2026-11-23
done:
---
# Design the OTIO case v1

**Goal:** a clean, screwless, PLA-printable case for the OTIO prototype (perfboard, ESP32-S3, ADC 15 Click, two SM-24s, USB-C), ready to print before OTIO Veszprém on 2026-11-30.

## Done when
- [x] FreeCAD model in `hardware/case-v1/` with base and lid as separate bodies, driven by named parameters
- [x] Fit check against dummy models of the perfboard, ESP32-S3, Click and both SM-24s: no collisions, USB-C reachable
- [x] Bayonet lock closes with a quarter turn and a detent; fit clearances stated
- [x] "REZON" and the wave engraved on the lid
- [x] STL or 3MF for each part, printable in PLA on the X1E or A1 without supports, or with the supports named
- [ ] Kaszti OKs the look

## Notes
Requirements and choices: [[OTIO case v1]].

## Log
- 2026-11-23 created
- 2026-11-23 model v1 in `hardware/case-v1/`: fit check clean, lock path checked, STLs and fit-test rings out. Waiting on Kaszti's OK of the look, and on three caliper measurements (corner holes, header height, USB spacing)
