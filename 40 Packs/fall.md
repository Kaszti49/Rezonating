---
type: pack
stage: idea
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
Impact trigger → classifier (fall / dropped object / jump) → rule: no footsteps for 20 s after the impact.

## Work for this pack
```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "packWork"})
```

## Results
Experiments link here with `pack: "[[fall]]"`.
