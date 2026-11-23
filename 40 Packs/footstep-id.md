---
type: pack
stage: design
order_no: 1
head: geophone
metric: person-ID accuracy (%)
target_value: 85
best_value:
repo_path: packs/footstep-id/pack.json
---
# footstep-id

**Detects:** Who is walking, from the floor vibration of their steps, and which side of the device (left/right) each step came from ([[D-027 Footstep-id tells the side of a step]], proposed).

```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "packCard"})
```

## Method
Event trigger (STA/LTA) → step features → classifier with an "unknown" reject. Enrol each household member with walk-pass recordings.

**Side (D-027):** the two geophones in the case are about 123 mm apart, so a step reaches one up to about 0.2–0.6 ms before the other (under 1.2 samples at 2 kSPS). The side comes from the sub-sample arrival-time difference (cross-correlation of the two channels around the trigger) and the amplitude ratio. Left/right only: two sensors can't tell front from back. The two geophones currently read with opposite polarity (bench test 2026-11-23).

## Work for this pack
```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "packWork"})
```

## Results
Experiments link here with `pack: "[[footstep-id]]"`.
