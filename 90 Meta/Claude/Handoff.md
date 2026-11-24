---
type: handoff
updated: 2026-11-24
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-11-24, EP-LAPTOP)
- **EP-LAPTOP is a real clone.** The whole day is committed and pushed (code, `.claude/`, vault in three commits), at Kaszti's request. Other machines: pull, then `rzlab build-ui`.
- **The Lab opens on Home** (for the OTIO judges): a Connect ring that becomes a bento dashboard: radar, device health, session, heat map, vibration line, tested so far. Results come from `50 Experiments/` (`GET /api/home/results`); simulated data says SIMULATION. The eight pages are under "Lab": Capture, Data, Test.
- **Locate rule:** louder (1.10 / 0.93), else first, else front, back or far. 26 of 32 known steps, **in-sample** ([[EXP-004 Louder then first on the recorded steps]]). Good at 1 m left and right; front/back at 1 m is weak (12 of 30 in round 1); at 2 m mostly no side.
- **Rig:** channels in anti-phase, **coin test not done**. The geophone pair did not move alike at about 09:11 and at about 12:10, when the case was probably being built. The health ring shows it. Save the reference (Home → Case position) when the case is in place.
- **Retro 2026-W48 done:** P-001, P-002, P-003 applied.
- **OTIO Veszprém is Monday 2026-11-30, the next work day.**

## Next up
| Who | What |
| --- | --- |
| Kaszti | Case: check the Home health (pair alike?), save the reference. Coin test. Round 2 with `locate-spots-v1` on the Record page (needs a data root, a pseudonym and consent). D-027: side only? Home page feedback or layout template; English or Hungarian for the judges? |
| Kaszti + Viktor | OTIO: mats 1 m left and right, case fixed, FRONT marked, rehearsal with other people |
| Viktor | Firmware README pin map vs the hackathon guide. Review `firmware/rig-s3` |
| Claude | Score round 2 with limits fixed as they are (EXP-003); convert the captures once consent is given |

## Open flags
- `ledger.py list --open`: Lab 4c, sim people, Lab 7 (wait for a re-verify), F-261101-b2c0, F-261102-f78b, F-261103-e4ed, F-261123-dab8.

## Watch out
- The new Stop gate (P-002) works from the next session start on.
- `python` on PATH is Espressif's 3.11; the Lab runs on `Python312\Scripts\rzlab.exe`. The Lab server stops with the Claude session that started it.
- Known Lab test failures here: two symlink tests; `test_soak_end_to_end_smoke` only in full runs; `test_runner_produces_90_labelled_passes_per_person` is flaky (1 of 5 also on untouched code).
- Raw captures: `%LOCALAPPDATA%\rzlab\captures\` (hashes in EXP-002). Removed ideas: [[Locate ideas parked]].
- Accepted decisions are hook-locked: propose a new one with `supersedes`.
