---
type: handoff
updated: 2026-10-03
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-10-03)
- Repo and vault pushed to `Kaszti49/Rezonating`. Nothing ordered yet; the phone kill test comes first.
- **Agent system built** ([[Agent system]], [[D-013 Agent system]] *proposed*): the main session is the orchestrator; 8 specialist agents, hooks as the L0 gate, a verifier, a ledger, evals, `/wrap-up` and `/retro`. Not yet run on a real task.
- Roles update proposed: [[D-014 Roles v2]] (Viktor: programming and electronics).

## Next up
| Who | What |
| --- | --- |
| Kaszti | Decide D-013 and D-014; set up the company PC on Monday; kill test; place ORD-001 |
| Viktor | ESP-IDF v6 with EIM; clone the repo; FootprintID loader |
| Claude | Eval baseline on the company PC; EU stock check for the ADC and oscillator; pin-map review |

## Open questions
- License for open source (backlog)
- Which GPU the home desktop has (decides the local model)

## Watch out
- First real session on each machine: check the hooks ran (no "hook error" lines) and approve the two MCP servers. `espressif-docs` needs a one-time GitHub sign-in in `/mcp`.
- Hooks call `python`: Python must be on PATH on every machine.
- Templater "Trigger on new file creation" is a per-device switch: turn it on on every machine.
- Due dates Claude set are proposals; adjust freely.
