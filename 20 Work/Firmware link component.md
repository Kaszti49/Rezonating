---
type: work
status: backlog
owner: claude
priority: p2
area: firmware
due: 2026-11-10
pack:
created: 2026-10-12
done:
---
# Firmware link component

**Goal:** The node side of D-018 over USB, later Wi-Fi.

## Done when
- [ ] `firmware/components/link/` builds
- [ ] passes the golden vectors
- [ ] streams to `rzlab` over USB once a board is on the desk
- [ ] Wi-Fi link works by 2026-12-01

## Notes
- Protocol: [[D-018 Node link protocol v0]]; the PC side is [[Lab 1 Link codec and simulator]].
- Needs a board from [[ORD-001 First rig]].
- Tier 2 component, kept separate from `net` (MQTT).

## Log
- 2026-10-12 created
