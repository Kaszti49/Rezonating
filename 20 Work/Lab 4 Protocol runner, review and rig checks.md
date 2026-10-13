---
type: work
status: review
owner: claude
priority: p1
area: data
due: 2026-11-10
pack:
created: 2026-10-12
done:
---
# Lab 4 Protocol runner, review and rig checks

**Goal:** Everything needed for the first rig day.

## Done when
- [x] walk-pass YAML runner
- [x] Review page edits labels
- [x] rig checks catch the simulator's faults
- [x] SD import
- [ ] dress rehearsal on the simulator of the first rig recording (Roadmap: "First rig records" 2026-11-17)

## Notes
- The runner reads the machine-readable protocol (`docs/protocols/walk-pass-v1.yaml`); it is used for real in [[First walk-pass recording session]] (2026-12-01).
- Rig checks support [[Wire the first rig]]; their report goes into its build note.
- SD import reads what [[WAV and sidecar writer on microSD]] writes.
- Scope: [[D-017 Rezonating Lab bench tool]].

## Log
- 2026-10-12 created
- 2026-10-13 Claude (cloud session): 4a runner + `walk-pass-v1.yaml` (verifier PASS); 4b sim faults + rig checks (PASS: swapped channels, no 1 g, +1.65 % clock all fail their check); 4c Review page + SD import: 3 rounds; Kaszti decided Review edits keep both streams in sync and labels are a fixed list per protocol; re-verify of round 3 was running at wrap-up. Dress rehearsal of the 11-17 session NOT done yet (`rzlab sim --walkers` exists for it). Flags F-261013-860d/-4a62 open.
