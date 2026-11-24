---
type: experiment
id: EXP-004
status: done
date: 2026-11-24
owner: claude
pack: "[[footstep-id]]"
protocol:
floor: EP-LAPTOP room (material not written down)
people: 1
sessions: []
metric: known steps with the right side (%)
metric_value: 81.3
result: partial
---
# EXP-004 Louder then first on the recorded steps

**Takeaway:** the rule the Lab uses from 2026-11-24 on (louder on one side, else heard first on one side, else front, back or far; no calibration) gets **26 of 32** recorded steps with a known side right, 5 get no side, 1 is wrong. **In-sample:** the limits (1.10, 0.93, 0.5 ms) were chosen on these steps and on round 1, one person, one floor, one day.

## Results
| Set | Right | Same | Wrong |
| --- | --- | --- | --- |
| Left, 08:53 | 8 | 0 | 0 |
| Right, 08:53 | 8 | 0 | 0 |
| Left, 09:15 | 7 | 1 | 0 |
| Right, 09:40 | 3 | 4 | 1 |

## Why this rule and not the others
| Rule | Known 32 | Wrong | Round 1 (Claude's labels): 1 m sides of 35 | 2 m front and back of 20 |
| --- | --- | --- | --- | --- |
| First, else louder against 1.05 (before) | 28 | 1 | 33 | 2 |
| Louder only, 0.90 and 1.12 (Claude's proposal) | 19 | 0 | 29 | 20 |
| **Louder 0.93 and 1.10 (flat window), else first (used)** | **26** | **1** | **33** | **18** |

- Claude proposed "louder only" without scoring it on the known steps. Scored, it loses the 08:53 left steps (2 of 8), which only "first" catches. So "first" stays as the second question.
- The rule before called 18 of 20 far steps RIGHT; the new one gives them no side.
- Round 1, 1 m front and back: 12 of 30 get no side; the others come out left or right. Close up, front and back are still weak.

## What it does not show
- Accuracy on new steps: there is no held-out set. Round 2 of [[EXP-003 Eight spots round 1]] is the test.
- A second person, floor or day.

## Data
The captures of [[EXP-002 Locate page first real floor run]] (hashes there).
