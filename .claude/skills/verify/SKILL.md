---
name: verify
description: Playbook for checking finished work before calling it done (L1). Run it after any change in firmware/, ml/, tools/, schemas/ or packs/, and after research that feeds an order or a decision. Reviews the diff as if someone else wrote it, logs findings to the ledger, and ends with PASS, FLAG or BLOCK.
---

# Playbook: verify (L1)

You wrote this work, so assume your summary is wrong and check the files instead. Do it as a separate
step after the work, never while writing it.

## Steps
1. **Re-read the diff cold:** `git diff` (plus `git status` for new files). Don't look at what you
   meant to change, only at what changed.
2. **Done when:** go through each point and quote the file:line (or the output) that meets it. If a
   point has no evidence, it isn't met.
3. **Run the gate:** `python .claude/scripts/checks.py --files <changed files>`. For new behaviour, run
   the thing itself (a test, a replay, a build), not just lint.
4. **Look for the failure mode** in each area:
   - firmware: blocking or logging in an ISR, missing `IRAM_ATTR`, buffers in the wrong RAM, silent
     sample drops, register values against the datasheet, counter overflow, GPIO 33–37, v5 APIs on v6.
   - ml: splitting by window instead of by person, float64/float32 mismatch, features without test
     vectors, unseeded randomness, a metric without a baseline, a limit scored on the data it was chosen on.
   - schemas/packs: a breaking change with no version bump or decision, examples not updated.
   - research: open 1–3 cited sources and confirm the numbers are really there.
   - vault: `10 Project/Vault rules.md`; a decision marked accepted by Claude.
5. **Scope creep:** changes the task didn't ask for are findings too.
6. **Severity:** high = wrong, unsafe or breaks a rule. med = will cause trouble soon. low = clarity.
   Don't pad the list: having no findings is a valid result.

## Verdict and ledger
- **PASS:** no high or med findings and the gate passes. You're done.
- **FLAG:** fixable. Log each high or med finding:
  `python .claude/scripts/ledger.py add --playbook <firmware|ml|research|writing|vault> --kind review --severity <s> --summary "<file:line: what is wrong>"`,
  then fix it (L2, at most two rounds, each one `--kind retry`), then verify again. Resolve the flags
  you fixed with `ledger.py resolve <id> --how "..."`.
- **BLOCK:** the task is wrong, unsafe, or needs a decision. Stop and ask the person (L4, `--kind human`).
- Still failing after two rounds: the `root-cause` playbook (L3).

Tell the person the verdict in one line, with the checks you ran. Never hide an open flag.
