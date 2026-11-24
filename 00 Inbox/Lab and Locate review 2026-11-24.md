---
type: inbox
created: 2026-11-24
---
# Lab and Locate review 2026-11-24

Written as proposals; **Kaszti approved them on 2026-11-24** (what was built is at the end). From a cold read of the Locate chain, today's recordings ([[EXP-002 Locate page first real floor run]], [[EXP-003 Eight spots round 1]]) and the studies in [[Side of a step with two nearby sensors]]. #ask-claude

## What works today
- Left and right at 1 m, by loudness (about 1.36 against 0.65 in round 1). In-sample, one person, one floor.
- Small steps are found better (latest capture: the smallest bumps 12 % → 66 %). No ground truth for how many were missed.

## What I'd change, most important first
| # | Finding | Evidence | Proposal |
| --- | --- | --- | --- |
| 1 | The neutral point (loudness 1.05, delay −0.2 ms) came from steps at unknown places | In round 1 the neutral ratio is 1.00, so 18 of 20 steps read as 2 m front and back came out RIGHT | Loudness only: LEFT above 1.12, RIGHT below 0.90, between = "FRONT, BACK or TOO FAR". Check it on round 2 before shipping |
| 2 | "First" barely works: the geophones agreed in 6 % (left) and 47 % (right) of the 1 m steps | Round 1; Akiyama et al. found that the far sensor often fires first | Remove it (about half of `core/locate.py`) |
| 3 | One step decides alone | 7.6 dB step-to-step scatter; Akiyama decides over 5 s | Show a majority of the last 3 steps of a walk next to the single step |
| 4 | The 350 ms Hann window weights the step itself to about 19 % | Offline: a flat window is a little better (round 1 left 2 → 0 wrong of 16, right 2 → 1 of 19; too few to decide) | Test a flat window on round 2, then decide |
| 5 | Nothing warns when the rig changes | At about 09:11 the geophones stopped moving alike; DC shifted 3 400 → 5 000 | A rig-health line: rest level, quiet level, agreement against the last good day |
| 6 | Anti-phase all day, cause not known | cc −0.99; coin test still not done | **Do the coin test first:** it decides whether the case rocks or a wire is reversed. Everything above depends on it |
| 7 | A step in the ~60 ms after lost samples is neither shown nor counted | Read in the code, `SETTLE_BLOCKS` | Count it as `skipped_gaps` |
| 8 | Today's test data is not recorded as sessions | 10-minute ring buffer only | A `locate-spots-v1` protocol for the Record page (spot labels, 10 s pauses, shoes, floor) |

Not checked in this review: the firmware, and Lab pages 1 to 7 beyond the open flags. The five older flags on Lab 4c, sim people and Lab 7 still wait for a re-verify.

## Database
- Written today: [[EXP-002 Locate page first real floor run]], [[EXP-003 Eight spots round 1]], [[Side of a step with two nearby sensors]], the retro and three proposals.
- **Not filled:** the dataset. The six captures are raw `.npz` files on EP-LAPTOP only, outside git. To become data they need WAV + sidecar (D-008), a pseudonym and consent, and a folder. Open: a pseudonym and written consent. Then Claude can convert them.
- Nothing is committed: the day's code and these notes exist only on EP-LAPTOP. The power cut on 2026-11-02 is the reason to commit and push today.

## What should be next
Monday 2026-11-30 is OTIO Veszprém and there is **no other work day before it** (next work day: 2026-12-01). So:
1. **Today:** coin test. Round 2 with pauses. Then decide finding 1 and freeze Locate. Commit and push.
2. **For OTIO:** one rule on the stand: a mat 1 m left and 1 m right of the case, marked; people step on it. Case fixed flat, FRONT marked on the lid, the rig's cable and USB checked. Rehearse with three different people if possible. A fallback: the Lab Live page showing the two channels.
3. **After OTIO (from 2026-12-01):** the walk-pass dataset (Roadmap 2026-12-01), which is also the step that tests side across days. D-026 and D-027 accepted or changed. The third sensor (off the line) decided for front/back.

## Dashboard
**Yes, but as the first page of the Lab, not a ninth tab.** The vault's dashboard already shows project status. What is missing is the rig and the data.
- **Home (new landing page):** rig connected or not, rate, losses, quiet level, agreement of the geophones; recordings today and the dataset count per person; the last experiment and its result; open flags; one big "Start recording".
- **Group the 8 tabs under three headings:** Capture (Live, Device, Record), Data (Review, Datasets, Experiments), Test (Bench, Locate). No pages removed.
- Read-only at first, from APIs that exist (`/api/state`, `/api/datasets/sessions`, `/api/experiments/runs`); my estimate is about a day of work. Ask before building it: it isn't in the Year 1 scope notes.

## Built on 2026-11-24 (Kaszti: apply all)
| # | Outcome |
| --- | --- |
| 1 | **Changed after scoring it:** loudness only gave 19 of 32 known steps. Used instead: louder (1.10 / 0.93, flat window), else first, else front, back or far: 26 of 32, 1 wrong, in-sample ([[EXP-004 Louder then first on the recorded steps]]) |
| 2 | **Not removed, moved to second place**, for the same reason |
| 3 | Majority of a walk's last 3 steps (`walk_side`), on Home and Locate |
| 4 | Flat window for the loudness |
| 5 | Rig health: geophones alike, rest level and quiet level against a saved good state, warnings on the page |
| 6 | **Open: the coin test needs a person** |
| 7 | A loud block right after a gap counts in `skipped_gaps` |
| 8 | Protocol `locate-spots-v1` (`docs/protocols/`), runs in the Record page's runner |
| Dashboard | Home page: Connect ring that becomes a bento dashboard (radar, health, session, heat map, vibration line, tested so far). The eight pages are grouped as Capture, Data, Test. Results come from the experiment notes |
| Ideas taken out | [[Locate ideas parked]] |

Not done, waits for Kaszti: consent and pseudonym for the captures; D-027; commit and push.
