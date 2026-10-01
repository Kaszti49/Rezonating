---
type: pack
stage: idea
order_no: 3
head: accelerometer
metric: induced faults flagged (of 10)
target_value: 9
best_value:
repo_path: packs/appliance/pack.json
---
# appliance

**Detects:** A machine (washer, fridge, pump) vibrating abnormally.

```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "packCard"})
```

## Method
Learn a baseline spectrum per machine state, flag drift beyond a threshold.

## Work for this pack
```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "packWork"})
```

## Results
Experiments link here with `pack: "[[appliance]]"`.
