---
name: root-cause
description: Playbook for escalation (L3) when a fix failed the gate or the verify playbook twice, or for a hard root-cause investigation across firmware, ml and hardware. Reproduce first, prove the cause, then make the smallest fix.
---

# Playbook: root-cause (L3)

Log the escalation first: `python .claude/scripts/ledger.py add --playbook <area> --kind escalation --summary "..."`.
If this session runs on a lighter model or a lower effort, tell the person: a stronger setting
(`/model`, `/effort`) is part of this step.

1. **Reproduce.** Run the failing build, test or replay and read the full error before you change
   anything. If you can't reproduce it, say so. Don't guess at a fix.
2. **Write the chain:** symptom → mechanism → cause, with evidence for each link (file:line, a doc
   page, a datasheet section, a measured value).
3. **Why did the earlier attempts fail?** If the task itself is wrong or under-specified, stop and say
   what a person must decide. That is a good outcome.
4. **Smallest correct fix,** then re-run the exact failing check and the checks next to it.
5. **Lesson:** one or two lines on what the first attempt missed, logged as `--kind note`. The retro
   turns repeated lessons into playbook changes.
