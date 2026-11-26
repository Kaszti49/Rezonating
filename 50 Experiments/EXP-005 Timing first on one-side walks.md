---
type: experiment
id: EXP-005
status: done
date: 2026-11-26
owner: claude
pack: "[[footstep-id]]"
protocol: walk-pass-v1
floor: pc-10 office (material not written down)
people: 1
sessions: [2026-11-26_office_pc-10_01, 2026-11-26_office_pc-10_02, 2026-11-26_office_pc-10_03, 2026-11-26_office_pc-10_04, 2026-11-26_office_pc-10_05, 2026-11-26_office_pc-10_06, 2026-11-26_office_pc-10_07, 2026-11-26_office_pc-10_08]
metric: sided steps on the right side (%)
metric_value: 90
result: partial
---
# EXP-005 Timing first on one-side walks

**Takeaway:** on the S3 rig the **arrival time** tells left from right, and loudness doesn't. With a new step detector and the rule "heard first, else 1.5 times louder, else no side", the Lab puts **267 of 298 sided steps (90 %)** on the right side in six one-side walks. 110 of 408 steps get no side. The old rule (louder, else first) got 52 %. The zero point is out-of-sample (picked on the other walks each time). The 0.1 ms and 1.5 limits were picked on these same steps, so **the 90 % is in-sample**. One person, one floor, one case position, one day.

## Set-up
- S3 rig in the OTIO case, geophones about 123 mm apart, touching the floor. `adc_raw` at 1994.9 Hz measured, 0 lost samples in every recording.
- **Channel map from the coin test:** taps by the left geophone (`_03`, 37 taps) reached ch1 first by 0.62 ms (median); taps by the right one (`_04`, 29 taps) reached ch0 first by 0.83 ms. So **ch0 is the right geophone**, the opposite of what the Lab assumed. Even beside a geophone, the loudness differed by only about 15 % (0.88 and 1.18).
- Walks: 60 s each, one side per recording, mixed distances up to about 4 m, also forwards and backwards on that side. The order was L `_01`, R `_02`, then alternating L `_05`, R `_06`, L `_07`, R `_08`. Distances weren't labelled per step.

## Results
Replayed through the Lab's live code (`server/locate.py`, `core/locate.py` as of 2026-11-26), without swap.

| Set | Right | Same | Wrong |
| --- | --- | --- | --- |
| Left `_01` | 37 | 25 | 5 |
| Right `_02` | 40 | 23 | 14 |
| Left `_05` | 53 | 12 | 3 |
| Right `_06` | 45 | 19 | 2 |
| Left `_07` | 53 | 10 | 1 |
| Right `_08` | 39 | 21 | 6 |
| Total | 267 | 110 | 31 |

- **Walk side** (2 of the last 3 steps agree), the side the radar lights up now: right for 274 and wrong for 17 of the steps where the walk had a side (94 %).
- **The old rule** on the same walks (its own detector, with swap on so the channel map is right): 317 steps; 60 right, 56 wrong, 201 no side.

## How the limits were chosen
| What | Picked on | Value | Score |
| --- | --- | --- | --- |
| Zero point (no side) | the other five walks, each time (leave one walk out) | about 0 ms | 352 of 447 steps (79 %), 71 to 85 % per walk; every walk's median on its own side |
| Timing band | 2026-11-24, unchanged | 20 to 60 Hz | 100 to 400 Hz looked best on `_01`/`_02` alone (84 %) and dropped to 69 % with the new walks |
| Clearly first | all 413 detected steps (in-sample) | 0.1 ms | 69 % of steps get a side this way, 89 % of those right |
| Much louder | the same steps (in-sample) | 1.5 times | 9 of 9; at 1.10 only 47 % of the rest were right |
| Detector | the same walks, plus 2 min of simulated noise with hum | k = 3 sigma, energy 1.5 times quiet | 408 steps; 0 false steps in the noise (k = 3 alone gave 25 a minute) |

## What it does not show
- Accuracy on a new day, floor, person or case position. Next: a labelled series (distance and spot per walk) on another day, scored with the limits fixed as they are now.
- From how far the timing still works: the distances weren't labelled.
- How many steps the detector misses or invents on these walks: the steps themselves aren't labelled. In 2 minutes of simulated noise it reported none.

## Data
WAVs in the data root (`Recordings`), sidecars in `data/2026-11-26_office_pc-10_0*`. The sidecars of `_01` to `_04` give ch0 the **left** position (written before the coin test); `_05` to `_08` have ch0 on the right. Analysis scripts: `scratch/steps/` (throwaway).

Related: [[EXP-004 Louder then first on the recorded steps]], [[Locate ideas parked]], [[D-027 Footstep-id tells the side of a step]]
