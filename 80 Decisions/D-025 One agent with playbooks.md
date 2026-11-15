---
type: decision
id: D-025
status: accepted
date: 2026-11-15
decided_by:
  - kaszti
  - viktor
tier: 1
supersedes: "[[D-013 Agent system]]"
---
# D-025 One agent with playbooks

**Decision:** Claude works in this repo as **one agent**: the session Kaszti and Viktor talk to. The eight specialist agents are removed. Each kind of work has a **playbook** (a skill in `.claude/skills/`) that the agent loads before it starts: `firmware`, `ml-training`, `research`, `writing`, `vault-conventions`, `verify`, `root-cause`, `retro`, `wrap-up` (plus `esp-idf-build-flash` and `find-skills`).
- The deterministic checks stay. The L0 gate moves from the subagent hook to the Stop hook. It checks the files edited since they last passed, allows two fix rounds, then logs a `gate-fail` flag.
- L1 review becomes the `verify` playbook: a separate cold read of the diff, the checks run again, findings logged as `review` flags.
- The ledger stays as the evidence store.
- The **retro** is the self-improvement function. The session start says "Retro due" when the ledger shows a person's correction, a high flag, three new flags, or a week of unreviewed flags (`ledger.py retro-due`). The retro then proposes at most three evidenced changes. A person approves each one, and the Changelog records it.

**Why:** Kaszti wants one agent guided by playbooks. The specialist setup cost turns and context on hand-offs. Subagents hit turn limits (F-261013-e9b4), and the hooks had to stitch results back together. One session keeps the whole context, and playbooks load only when needed. The checks, the ledger and approval-gated changes were the parts that worked, so they stay. Unlike the weekly-only `/retro`, the retro now fires when the evidence appears.

**Rejected alternatives:**
- Keep the agents and add playbooks on top: two systems to maintain.
- Keep only the independent verifier subagent: the review stays fresh, but it brings back the hand-off cost. The `verify` playbook's cold re-read is the cheaper version; if review findings slip through, the retro can propose bringing a reviewer back.
- A fully autonomous retro that edits its own rules: Kaszti chose proposals with approval on 2026-11-15.

**Consequences:**
- Review is no longer done by a second model. It is a disciplined self-review plus the deterministic gate, so Tier 1 code depends more on tests and replays.
- Per-agent evals (`run_evals.py`) are gone. A retro proposal now proves itself with a test in `.claude/tests/`, a check run, or a replay of the flagged case.
- The 12 open flags from the agent era keep their agent names and are the first retro's input.

**Affects:** `CLAUDE.md`, `.claude/` (agents, agent-scopes, subagent_gate, agent_report and evals removed; stop_gate, ledger and session_start changed; new playbooks), [[Agent system]], [[How our system works]], [[Team]], [[Claude]], [[Changelog]]. Flip `status` to `accepted` and fill `decided_by` in Obsidian. Roll back: revert the commit "Replace agents with playbooks".
