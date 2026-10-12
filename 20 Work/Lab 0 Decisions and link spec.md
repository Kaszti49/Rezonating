---
type: work
status: done
owner: claude
priority: p1
area: project
due: 2026-10-13
pack:
created: 2026-10-12
done: 2026-10-12
---
# Lab 0 Decisions and link spec

**Goal:** Propose D-017/018/019 and write the link protocol spec.

## Done when
- [x] D-017, D-018, D-019 written (all three accepted 2026-10-12; D-020 proposed)
- [x] `tools/lab/PROTOCOL.md` written and verified
- [x] phase work notes created

## Notes
- Decisions: [[D-017 Rezonating Lab bench tool]], [[D-018 Node link protocol v0]], [[D-019 Sidecar v1]], [[D-020 Recordings keep the 2 kSPS ADC stream]].
- Spec: `tools/lab/PROTOCOL.md`. It went through 3 verifier rounds on its own (FLAG each time, all fixed) and then through the phase 1 code review, which settled the remaining readings.
- Sidecar schema v1 is in `schemas/sidecar.schema.json` (v0 files stay valid; verifier FLAG fixed, rejection cases tested).
- Next phase: [[Lab 1 Link codec and simulator]].

## Log
- 2026-10-12 created
- 2026-10-12 Claude: done
