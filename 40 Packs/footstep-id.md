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

**Detects:** Who is walking, from the floor vibration of their steps.

```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "packCard"})
```

## Method
Event trigger (STA/LTA) → step features → classifier with an "unknown" reject. Enrol each household member with walk-pass recordings.

## Work for this pack
```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "packWork"})
```

## Results
Experiments link here with `pack: "[[footstep-id]]"`.
