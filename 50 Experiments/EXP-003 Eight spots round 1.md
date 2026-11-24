---
type: experiment
id: EXP-003
status: running
date: 2026-11-24
owner: kaszti
pack: "[[footstep-id]]"
protocol:
floor: EP-LAPTOP room (material not written down)
people: 1
sessions: []
metric: side right on held-out steps (%)
metric_value:
result:
---
# EXP-003 Eight spots round 1

**Takeaway so far:** round 1 gives no accuracy figure, because the spots had no pauses between them and **Claude cut the groups from the signal itself**. What it does show: at 1 m, left and right are far apart in loudness (about 1.36 against 0.65). At 2 m, right, front and back look the same (0.99–1.00).

## Setup
- Order asked for: 1 m left, right, front, back, then 2 m left, right, front, back; about 10 steps each. Kaszti walked between the spots.
- Data: `floor-2026-11-24-round1.npz` (see [[EXP-002 Locate page first real floor run]] for its hash); the round runs 10:00:59–10:02:57, 135 steps.

## Readings (the labels are Claude's, not independent)
| Group | n | Loudness ch0/ch1, 10 % / middle / 90 % | Geophones agree |
| --- | --- | --- | --- |
| 1 m left | 16 | 1.06 / 1.36 / 1.57 | 6 % |
| 1 m right | 19 | 0.51 / 0.65 / 0.91 | 47 % |
| 1 m front and back, part 1 | 17 | 0.93 / 1.22 / 1.59 | 47 % |
| 1 m front and back, part 2 | 13 | 0.80 / 0.97 / 1.03 | 46 % |
| 2 m left | 9 | 1.05 / 1.09 / 1.20 | 88 % |
| 2 m right | 16 | 0.93 / 0.99 / 1.01 | 100 % |
| 2 m front | 8 | 0.96 / 1.00 / 1.04 | 100 % |
| 2 m back | 12 | 0.99 / 1.00 / 1.01 | 100 % |

- The page's neutral ratio (1.05) is wrong here: steps near 1.00 come out RIGHT (18 of the 20 in the last two groups).
- Offline check of the measuring window, on these tentative groups and the 32 known steps (not implemented): the 350 ms Hann window weights the moment of the step to about 19 %; a flat window gave 0 wrong of 16 for 1 m left (now 2) and 1 of 19 for right (now 2). Too few steps to decide on.

## Round 2 (planned, the fair test)
- [ ] Same 8 spots and order, 10 steps each, **10 s of standing still before each spot**, walking in a wide arc
- [ ] Write down the order and start time; note the floor material, shoes and where the case stood
- [ ] Score with limits fixed beforehand: today's rule, loudness only (left above 1.12, right below 0.90, between = front, back or too far), learned from round 1
- [ ] Set `metric_value` from round 2 only

## Log
- 2026-11-24 created by Claude after round 1
