---
type: work
status: todo
owner: claude
priority: p2
area: project
due: 2026-10-06
pack:
created: 2026-10-03
done:
---
# Run the first agent eval baseline

**Goal:** Know how well each agent does its job before changing anything.

## Done when
- [ ] `python .claude/scripts/run_evals.py --agent vault-keeper` and `--agent verifier` run on the company PC
- [ ] Results are in [[Eval log]]
- [ ] Failures are logged as flags or turned into fixes

## Notes
Uses some subscription quota (a few minutes per case). Firmware cases need ESP-IDF.

## Log
- 2026-10-03 created by Claude with the agent system (due date is a proposal)
