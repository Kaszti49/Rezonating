---
type: decision
id: D-026
status: proposed
date: 2026-11-23
decided_by: []
tier: 1
supersedes: "[[D-023 Year 1 order fall first]]"
---
# D-026 Year 1 order footstep-id first

**Decision:** Year 1 builds `footstep-id` first, then `fall`, then `appliance`. The first goal is the Charter target for footstep-id: recognise which of 3 people is walking, ≥ 85 % correct, on our own floor.

**Why:** Kaszti set this as the first goal on 2026-11-23 and confirmed the change in chat ("Yes, footstep-id first"). The OTIO poster (2026-11-16) already presents footstep ID. The rig now has two SM-24 geophones on the ADC 15 Click and both channels pass the tap test (2026-11-23 daily note), so walk-pass recordings can start. The hackathon fall detector keeps working as it is and stays the `fall` engine ([[D-024 Hackathon core is the fall pack engine]]); its port to the node waits.

**Rejected alternatives:** Keep fall first and only record footsteps on the side (doesn't match the goal Kaszti set). Work on both packs at once (two people, two work days a week).

**Affects:** [[Charter]] (order line), [[Roadmap]] (pack bars and gates: Claude's proposal, needs an OK), [[footstep-id]] and [[fall]] (`order_no`), [[Port the fall core to ESP-IDF]] (later), `CLAUDE.md` scope line, study lesson s08. Flip `status` to `accepted` and fill `decided_by` in Obsidian.
