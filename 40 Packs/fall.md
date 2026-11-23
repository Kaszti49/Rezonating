---
type: pack
stage: model
order_no: 2
head: geophone
metric: falls caught (%)
target_value: 95
best_value:
repo_path: packs/fall/pack.json
---
# fall

**Detects:** A person falling, with nobody wearing anything.

```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "packCard"})
```

## Method
From the HARMAN Hackathon core ([[D-024 Hackathon core is the fall pack engine]], proposed). An event is cut from the impact and step paths and turned into a feature vector: peak, energy, duration, sub-impacts, rise, decay, band ratio and centroid. A linear fall score with hard gates decides. Walker tracks keep bystanders from cancelling the alarm, and a new steady rhythm after the impact counts as "got up".

First result: [[EXP-001 Hackathon fall detector on stage]] (3/3 falls, 3/3 jumps rejected, one person, stage floor). Code: `firmware/hackathon-rezon/`.

The plan before the hackathon was impact trigger → classifier (fall / dropped object / jump) → no footsteps for 20 s after the impact.

## Work for this pack
```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "packWork"})
```

## Results
Experiments link here with `pack: "[[fall]]"`.
