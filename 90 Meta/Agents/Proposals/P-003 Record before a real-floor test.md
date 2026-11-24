---
type: proposal
id: P-003
status: applied
target: .claude/skills/ml-training/SKILL.md
date: 2026-11-24
applied: 2026-11-24
flags: [F-261124-13a0, F-261124-17a0]
---
# P-003 Record before a real-floor test

**Evidence.** The Lab has a recorder with labels, and none of today's six runs used it. The data were saved from a 10-minute ring buffer, so the first run's calibration steps were lost, and "which side" was known for only 32 steps. Round 1 had to be split from its own signal, so it can't give an accuracy figure ([[EXP-003 Eight spots round 1]]). Person corrections F-261124-13a0 and -17a0 both needed data that had not been labelled.

**Change (unified diff, not applied):**
```diff
--- a/.claude/skills/ml-training/SKILL.md
+++ b/.claude/skills/ml-training/SKILL.md
@@ ## Data
 - Public data first: FootprintID and the 2025 structural-vibration gait dataset (see `60 Research/`).
+- **A real-floor test is a recording first.** Before a person steps, start a Lab recording (Record page) with the
+  spot, shoes, floor and order as labels, and write the order in the experiment note. The Lab's 10-minute ring
+  buffer is not a record. No labels → no accuracy figure.
```

**Check.** The next floor test has a session in the Lab's data root and an EXP note that names it; no test result cites a capture from the ring buffer.

**Risk.** A little more setup per test. Rollback: remove the three lines.

**Applied 2026-11-24** (Kaszti in chat: "apply all proposed ideas and the retro"). Applied as written, with the protocol `locate-spots-v1` named (`docs/protocols/`).
