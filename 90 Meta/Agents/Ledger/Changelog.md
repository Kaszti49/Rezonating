---
type: log
---
# Agent system changelog

Append-only. One line per change to agents, skills, rules, hooks or routing, newest at the bottom.
Format: `- YYYY-MM-DD · P-### or "setup" · file · what changed · how to roll back`.

- 2026-10-03 · setup · `.claude/` · Agent system v1: orchestrator in CLAUDE.md, 8 agents, 6 skills, 2 rules, 7 hooks, ledger, evals ([[D-013 Agent system]]) · roll back by reverting the commit "Add agent system"
- 2026-10-13 · Kaszti (chat) · `.claude/agents/*.md`, `CLAUDE.md`, [[Agent system]] · Agents pinned to exact 5.5 model ids. firmware-dev and ml-dev move from Sonnet to **Opus 5.5** (Kaszti: too many mistakes and re-runs on Lab 3 cost more than a stronger model); verifier, deep-engineer and curator `claude-opus-5-5`; researcher and writer `claude-sonnet-5-5`; vault-keeper `claude-haiku-5-5`. Effort and maxTurns unchanged · roll back by setting `model:` back to `sonnet`/`opus`/`haiku` in the agent files and the two tables
