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

**Decision:** In Year 1 the `footstep-id` pack gets a second output next to the person: **which side** a step came from, left or right of the device, meaning which of its two geophones the step is nearer to. Both SM-24 geophones stay inside the OTIO case, about 123 mm apart (cup centres at ±61.5 mm, [[OTIO case v1]]). Side is worked on together with the 1-of-3-people goal ([[D-026 Year 1 order footstep-id first]]).

**Why:** Kaszti asked for it on 2026-11-23 and chose in chat: "Yes, with footstep-id", output "Which side", geophones "In the case (12 cm)". The ADS131M02 samples both channels at the same instant, so the arrival-time difference between the geophones is measurable (the reason for simultaneous sampling in [[D-004 Core parts]]).

**What limits it:** at a few hundred m/s through the floor, 123 mm gives at most about 0.2–0.6 ms between the geophones, under 1.2 samples at 2 kSPS: side needs sub-sample timing (cross-correlation) and the amplitude ratio, not just "which one peaked first". Two sensors cannot tell front from back, so the output is only left/right. The bench test on 2026-11-23 found the two geophones wired with opposite polarity; the side maths must undo that.

**Target:** not set yet. Kaszti or Viktor set it (for example "correct side for ≥ x % of steps more than 1 m to the side") before the first walk-pass recordings are scored.

**Rejected alternatives:** An angle in degrees (needs the geophones 1–2 m apart on cables; the case stays as designed). Walking direction over several steps (can be built on top of side later). A third geophone for front/back (not in the case).

**Affects:** [[Charter]] (footstep-id target line), [[footstep-id]] (outputs), `packs/footstep-id/pack.json` (a `side` output; `requires.heads` min 2 and `simultaneous: true` for it), the walk-pass protocol (where people walk relative to the device), shared feature code in `ml/` (Tier 1: the side estimate and its firmware twin need this decision accepted first), the Lab's bench view. Flip `status` to `accepted` and fill `decided_by` in Obsidian.
