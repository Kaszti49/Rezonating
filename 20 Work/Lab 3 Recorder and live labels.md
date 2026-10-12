---
type: work
status: todo
owner: claude
priority: p1
area: data
due: 2026-11-03
pack:
created: 2026-10-12
done:
---
# Lab 3 Recorder and live labels

**Goal:** Record sessions to WAV + sidecar and mark labels live.

## Done when
- [ ] `rezonating_ml.io` WAV + sidecar round-trip
- [ ] simulated 5-min session passes `tools/validate.py`
- [ ] keyboard marks have label error < 20 ms against ground truth
- [ ] phone marks have label error < 150 ms against ground truth

## Notes
- Sidecar fields (`loss`, `sample_rate_measured`, `labels[].src`, `unc_ms`): [[D-019 Sidecar v1]].
- Recordings go to the shared data root, never into git ([[D-017 Rezonating Lab bench tool]]).

## Log
- 2026-10-12 created
