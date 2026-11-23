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

**Detects:** Who is walking, from the floor vibration of their steps, and where each step came from: the side (left/right), a bearing with its front/back mirror, and a rough distance band ([[D-027 Footstep-id tells the side of a step]], proposed).

```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "packCard"})
```

## Method
Event trigger (STA/LTA) → step features → classifier with an "unknown" reject. Enrol each household member with walk-pass recordings.

**Where the step came from (D-027):** the two geophones in the case are about 123 mm apart. Floor waves travel at 30–300 m/s, so a step reaches one geophone up to 0.4–4 ms before the other (0.8–8 samples at 2 kSPS).
- **Side:** from the sub-sample arrival-time difference (cross-correlation of the two channels around the trigger), backed by the amplitude ratio.
- **Bearing:** sin θ = c · Δt / d, with the floor's wave speed c calibrated on site (steps at 1 m straight left and right). Front and back look the same, so both candidates are kept.
- **Distance:** a band from loudness against the calibration steps.
- **Polarity:** the two geophones currently read in anti-phase (bench test 2026-11-23): reversed wiring or the case rocking.

The maths, its limits and the sources are in [[Footstep direction with two geophones]]. The Lab's Locate page shows all of it live (display maths only, `tools/lab/src/rezonating_lab/core/locate.py`).

## Work for this pack
```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "packWork"})
```

## Results
Experiments link here with `pack: "[[footstep-id]]"`.
