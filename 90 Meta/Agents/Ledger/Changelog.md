---
type: log
---
# Agent system changelog

Append-only. One line per change to agents, skills, rules, hooks or routing, newest at the bottom.
Format: `- YYYY-MM-DD · P-### or "setup" · file · what changed · how to roll back`.

- 2026-10-03 · setup · `.claude/` · Agent system v1: orchestrator in CLAUDE.md, 8 agents, 6 skills, 2 rules, 7 hooks, ledger, evals ([[D-013 Agent system]]) · roll back by reverting the commit "Add agent system"
- 2026-10-13 · Kaszti (chat) · `.claude/agents/*.md`, `CLAUDE.md`, [[Agent system]] · Agents pinned to exact 5.5 model ids. firmware-dev and ml-dev move from Sonnet to **Opus 5.5** (Kaszti: too many mistakes and re-runs on Lab 3 cost more than a stronger model); verifier, deep-engineer and curator `claude-opus-5-5`; researcher and writer `claude-sonnet-5-5`; vault-keeper `claude-haiku-5-5`. Effort and maxTurns unchanged · roll back by setting `model:` back to `sonnet`/`opus`/`haiku` in the agent files and the two tables
- 2026-11-15 · Kaszti (chat) · `.claude/`, `CLAUDE.md`, [[Agent system]] · Agent system v2: the 8 agents, `agent-scopes.json`, `subagent_gate.py`, `agent_report.py` and the evals are removed. One agent with playbooks (new: `firmware`, `research`, `writing`, `verify`, `root-cause`; `ml-training`, `vault-conventions`, `retro`, `wrap-up` reworked). The L0 gate moves to the Stop hook. The retro is triggered by evidence (`ledger.py retro-due`) and stays proposal + approval ([[D-025 One agent with playbooks]]) · roll back by reverting the commit "Replace agents with playbooks"
- 2026-11-24 · P-001 · `ml-training/SKILL.md`, `verify/SKILL.md` · Simplest rule first, held-out data before a claim ([[P-001 Baseline and held-out data before a claim]]) · roll back by removing rule 7 and the added words in verify
- 2026-11-24 · P-002 · `stop_gate.py`, `session_start.py`, `rzlib.py`, tests · The Stop gate also checks uncommitted files touched since the session started (edits through Bash) ([[P-002 Stop gate sees every changed file]]) · roll back by reverting these files
- 2026-11-24 · P-003 · `ml-training/SKILL.md` · A real-floor test is a recording first ([[P-003 Record before a real-floor test]]) · roll back by removing the three lines
