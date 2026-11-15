---
type: decision
id: D-023
status: accepted
date: 2026-11-15
decided_by:
  - kaszti
  - viktor
tier: 1
supersedes: "[[D-003 Year 1 order footstep fall appliance]]"
---
# D-023 Year 1 order fall first

**Decision:** Year 1 builds `fall` first, then `footstep-id`, then `appliance`.

**Why:** The HARMAN Hackathon (13–14 Nov 2026) produced a fall detector that worked on stage with one SM-24 geophone on the ADC 15 Click: 3 of 3 stage falls caught, 3 of 3 jumps rejected ([[EXP-001 Hackathon fall detector on stage]]). Fall is now the pack closest to done, so it goes first; footstep-id keeps its target but starts after the fall pack runs on the node. Kaszti confirmed the change in chat on 2026-11-15.

**Rejected alternatives:** Keep footstep-id first and treat the hackathon code as an archive (wastes the only pack that already works). Make the standalone fall alarm the product and drop the pack architecture (throws away D-002, D-005, D-007).

**Affects:** [[Charter]], [[Roadmap]] (pack bars and gates), [[fall]] and [[footstep-id]] (`order_no`), `CLAUDE.md` scope line, study lesson s08. Flip `status` to `accepted` and fill `decided_by` in Obsidian.
