---
type: work
status: review
owner: claude
priority: p3
area: ml
due: 2026-12-08
pack:
created: 2026-10-12
done:
---
# Lab 7 Experiments page

**Goal:** Run evaluations with a split and a baseline and draft EXP notes.

## Done when
- [x] session split with no overlap
- [x] baseline required
- [x] EXP draft in `50 Experiments` passes vault_schema (Kaszti 2026-10-13; was `00 Inbox`)

## Notes
- Experiment notes follow the `experiment` type in the vault-conventions skill.
- Built on [[Lab 6 Datasets page]] and [[Lab 5 Pack bench]].

## Log
- 2026-10-12 created
- 2026-10-13 Claude (cloud session): built: split by session/person with overlap refused, majority baseline always shown, SIMULATED DATA banner, runs in `tools/lab/runs/`. Kaszti: EXP drafts go to `50 Experiments` (status running), not `00 Inbox` (the vault rules forbid experiment notes there), so the third Done-when means that now. Synthetic result: bal. acc 0.69 vs baseline 0.33. Verifier was running at wrap-up.
