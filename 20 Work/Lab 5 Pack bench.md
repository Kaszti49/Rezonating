---
type: work
status: review
owner: claude
priority: p2
area: ml
due: 2026-11-24
pack: "[[footstep-id]]"
created: 2026-10-12
done:
---
# Lab 5 Pack bench

**Goal:** Run packs stage by stage on live or recorded data.

## Done when
- [x] bench output equals a direct `rezonating_ml` call
- [x] trigger tuning saves to `pack.json` and passes validate
- [x] firmware-vs-Python compare

## Notes
- The bench calls `rezonating_ml`; it holds no signal maths of its own ([[D-017 Rezonating Lab bench tool]]).
- Firmware side of the compare: [[Footstep segmentation with STA-LTA]].

## Log
- 2026-10-12 created
- 2026-10-13 Claude (cloud session): built on [[D-021 Pack pipeline in rezonating_ml]]: every stage, trigger sliders with validated save (warns about the footstep-id vectors), scoring vs sim ground truth, compare mode (Python vs Python until real firmware sends EVENT frames), vector create/check; sim `adc_dec` now the real 63-tap decimator. Verifier was running at wrap-up. Known: y-axis labels clipped.
