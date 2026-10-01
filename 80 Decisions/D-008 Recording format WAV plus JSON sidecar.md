---
type: decision
id: D-008
status: accepted
date: 2026-10-01
decided_by: [kaszti, viktor]
tier: 1
supersedes:
---
# D-008 Recording format WAV plus JSON sidecar

**Decision:** Multichannel WAV (32-bit int) + JSON sidecar, schema v0. Continuous recording ≤ 4 kSPS, event clips above.

**Why:** The dataset lasts all three years.

**Rejected alternatives:** CSV (too big), HDF5 (harder).
