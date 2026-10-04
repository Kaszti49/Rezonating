---
type: decision
id: D-013
status: accepted
date: 2026-10-03
decided_by:
  - kaszti
  - viktor
tier: 1
supersedes:
---
# D-013 Agent system

**Decision:** Claude works in this repo as one orchestrator (the main Claude Code session) that routes work to eight specialist agents with fixed models, effort levels and write scopes. Deterministic hooks check every agent's work (L0), a verifier on a different model reviews code and decision-grade research (L1), failures retry and escalate along a fixed ladder up to a person (L2–L4), and every flag is logged in an append-only ledger in `90 Meta/Agents/Ledger/`. A weekly `/retro` turns repeated flags into at most three proposals that a person approves; agent configuration never changes without that approval. Local models (Ollama) run only on Kaszti's home desktop and only draft through `tools/local/`. Everything runs on the Claude subscription in CMD or PowerShell: no API key.

**Why:** Two people, two work days a week: the time goes to the project, not to supervising Claude. Hooks catch the mechanical mistakes for free, a second model catches reasoning mistakes, and the ledger makes recurring problems visible instead of anecdotal. Approval-gated changes keep the system predictable.

**Rejected alternatives:** One general Claude session for everything (no checks, quality varies with the task). Fully autonomous self-editing agents (drifts, hard to trust, hard to roll back). Agent SDK pipelines (needs an API key and paid usage). Running Claude Code on local models (unsupported, much weaker for code).

**Affects:** `CLAUDE.md`, `.claude/`, `.mcp.json`, `tools/local/`, `90 Meta/Agents/`, the dashboard's Claude card. Kaszti approved the plan in chat on 2026-10-03; flip `status` to `accepted` and fill `decided_by` in Obsidian. Before going open source, the ledger has to leave the vault (D-012).
