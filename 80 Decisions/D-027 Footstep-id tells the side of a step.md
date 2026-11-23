---
type: decision
id: D-027
status: proposed
date: 2026-11-23
decided_by: []
tier: 2
supersedes:
---
# D-027 Footstep-id tells the side of a step

**Decision:** In Year 1 the `footstep-id` pack gets outputs that say **where a step came from**, next to who stepped. All three come from the two SM-24 geophones, which stay inside the OTIO case about 123 mm apart (cup centres at ±61.5 mm, [[OTIO case v1]]):
1. **Side:** left or right of the device, i.e. which geophone the step is nearer to.
2. **Bearing:** an angle from straight ahead, with its front/back mirror. Two sensors on one line can't tell θ from 180° − θ.
3. **Distance band:** near (< 1 m), 1–2 m or far (> 2 m), from loudness after an on-site calibration.

Side is worked on together with the 1-of-3-people goal ([[D-026 Year 1 order footstep-id first]]). The Lab shows all three on its Locate page, for the bench and for OTIO.

**Why:** Kaszti asked for side on 2026-11-23 and chose in chat: "Yes, with footstep-id", output "Which side", geophones "In the case (12 cm)". Later the same day he widened it to "where did the step come from", after the research in [[Footstep direction with two geophones]]. In chat he chose "Bearing + distance band" over left/right only and over a true x/y position. The ADS131M02 samples both channels at the same instant, so the arrival-time difference between the geophones is measurable (the reason for simultaneous sampling in [[D-004 Core parts]]).

**What limits it:**
- **The gap is tiny.** Floor waves travel at 30–300 m/s, so across 123 mm the gap is at most 0.4–4 ms, which is 0.8–8 samples at 2 kSPS. Timing needs sub-sample cross-correlation, backed by the amplitude ratio.
- **The bearing depends on the floor's wave speed.** That changes from floor to floor, so it is calibrated on site: steps at 1 m straight left and 1 m straight right.
- **Distance comes only from loudness.** A heavier step looks closer, so it is a band, not a number.
- **No front/back.** Both candidate directions are always shown.
- **Polarity.** The bench test on 2026-11-23 found the two channels in anti-phase. It's either reversed wiring or the case rocking; the coin-on-lid test tells which. The maths takes the strongest correlation peak of either sign.

**Target:** not set yet. Kaszti or Viktor set it before the first walk-pass recordings are scored, for example "correct side for ≥ x % of steps more than 1 m to the side" and "bearing within ± y° after calibration".

**Rejected alternatives:**
- **A true x/y position.** It needs a third sensor off the line, or geophones 1–2 m apart on cables. The ADC 15 Click has 2 channels, and published multi-sensor systems still miss by 0.4–0.8 m.
- **Left/right only.** It was the first version of this decision; the bearing and distance band cost no hardware.
- **Walking direction over several steps.** It can be built on top later.

**Affects:** [[Charter]] (footstep-id target line), [[footstep-id]] (outputs), [[Roadmap]], `packs/footstep-id/pack.json` (`side`, `bearing` and `distance_band` outputs; `requires.heads` min 2 and `simultaneous: true`), the walk-pass protocol (where people walk relative to the device), shared feature code in `ml/`, and the Lab's Locate page (`tools/lab`, display maths only, D-017). The `ml/` code is Tier 1: the side and bearing estimate and their firmware twin need this decision accepted first. Flip `status` to `accepted` and fill `decided_by` in Obsidian.
