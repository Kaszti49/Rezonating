---
type: proposal
id: P-001
status: applied
target: .claude/skills/ml-training/SKILL.md
date: 2026-11-24
applied: 2026-11-24
flags: [F-261124-13a0, F-261124-1bff, F-261124-63e1, F-261124-cfd6, F-261124-17a0]
---
# P-001 Baseline and held-out data before a claim

**Evidence.** Five corrections from Kaszti in one day, with the same cause: I built on a rule that was tested only on a simulator or on the steps it was tuned on, and told a person it worked.
- 13a0: the page was "46 of 46" on its own simulator and random on the real floor.
- 1bff, 63e1, cfd6: limits and gates chosen from the same data they were judged on.
- 17a0: the simplest rule (28 of 32) beat the elaborate one and was never scored first.

**Change (unified diff, not applied):**
```diff
--- a/.claude/skills/ml-training/SKILL.md
+++ b/.claude/skills/ml-training/SKILL.md
@@ Working rules
 6. Finish with `ruff check` and `python -m pytest -q ml/tests` (the stop gate repeats them), then
    the `verify` playbook. Report dataset, split, metric, baseline and what the number doesn't show.
+7. **Simplest rule first, real data before a claim.** Before building anything with a threshold, score
+   the simplest rule on recorded data and keep it as the baseline. State which steps chose each limit,
+   and score on steps that did not; if there are none, say "in-sample" in the same sentence as the number.
+   A simulator result is never evidence for the real floor.
--- a/.claude/skills/verify/SKILL.md
+++ b/.claude/skills/verify/SKILL.md
@@ 4. Look for the failure mode
    - ml: splitting by window instead of by person, float64/float32 mismatch, features without test
-     vectors, unseeded randomness, a metric without a baseline.
+     vectors, unseeded randomness, a metric without a baseline, a limit scored on the data it was chosen on.
```

**Check.** `python -m unittest discover -s .claude/tests` still passes. Next time Claude reports a number about real steps, the reply names the steps that chose the limits; the retro looks for it in the Session log.

**Risk.** Slower answers on small fixes. Rollback: revert the two edits.

**Applied 2026-11-24** (Kaszti in chat: "apply all proposed ideas and the retro"). Applied as written (ml-training rule 7, one line in verify). It worked at once: scoring Claude's own loudness-only proposal first showed 19 of 32 against 26, so it was not shipped ([[EXP-004 Louder then first on the recorded steps]]).
