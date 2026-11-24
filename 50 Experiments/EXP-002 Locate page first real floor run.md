---
type: experiment
id: EXP-002
status: done
date: 2026-11-24
owner: kaszti
pack: "[[footstep-id]]"
protocol:
floor: EP-LAPTOP room (material not written down)
people: 1
sessions: []
metric: known steps with the right side (%)
metric_value: 87.5
result: partial
---
# EXP-002 Locate page first real floor run

**Takeaway:** with the S3 rig (two SM-24 geophones, about 123 mm apart, in the OTIO case), **left and right are told apart at 1 m** by loudness, but not at 2 m. Front and back are not told apart. The rule "first, else louder, else same" got 28 of 32 known steps right, 3 "same" and 1 wrong. **In-sample:** the limits were set on these same 32 steps, and their true sides are where Kaszti was told to stand, so expect less.

## Setup
- Hardware: ESP32-S3 + ADC 15 Click + two SM-24, gain 4, USB (COM17, firmware bringup-0.3.0, `adc_raw` 1996.2 Hz measured).
- Software: Lab Locate page, changed several times during the day (see the Log of [[Test the Locate page on the real floor]]).
- No recordings were made with the Record page. The data are saved from the Lab's 10-minute ring buffer.

## Data (raw, on EP-LAPTOP, not in git: `%LOCALAPPDATA%\rzlab\captures\`)
| File | Saved | First 16 hex of sha256 | What it holds |
| --- | --- | --- | --- |
| floor-2026-11-24.npz | 08:27 | eeb60d61f5fe9ff2 | first run; no marked spots |
| floor-2026-11-24-cal2.npz | 08:55 | f3052bd569c5fe1d | 8 left and 8 right calibration steps (known), then walking |
| floor-2026-11-24-cal3.npz | 09:17 | 6f605adeb2f281a4 | change at about 09:11; 8 left steps at 09:15 (known) |
| floor-2026-11-24-cal4.npz | 09:30 | 2c568a4e9e7bc5eb | small steps missed; no marked spots |
| floor-2026-11-24-cal5.npz | 09:43 | 6b9f0f37552a5b25 | 8 right steps at 09:40 (known), left and ahead attempts (not confirmed) |
| floor-2026-11-24-round1.npz | 10:03 | d698e0c238b1c8b5 | round 1 of the marked-spot test, see [[EXP-003 Eight spots round 1]] |

## Results
| Set | Right | Same | Wrong |
| --- | --- | --- | --- |
| 08:53 left, 8 steps | 8 | 0 | 0 |
| 08:53 right, 8 steps | 8 | 0 | 0 |
| 09:15 left, 8 steps (geophones not moving alike) | 7 | 1 | 0 |
| 09:40 right, 8 steps | 5 | 2 | 1 |

- **Loudness** (ch0/ch1): left about 1.08 to 1.75, right about 0.87 to 0.96. **Timing** (−0.2 ms neutral) only helped in the first set.
- The geophones change state: at about 09:11 they stopped moving alike, and from then on they agree less the louder the step. Cause not known.
- The channels are in anti-phase all day (cc −0.99). Reversed wiring or a rocking case: the coin test was not done.

## What it does not show
- Anything for a second person, a second floor or a second day.
- Accuracy: no held-out set. [[EXP-003 Eight spots round 1]] and round 2 should give one.
- Detection rate: no ground truth for how many steps there were.

## Next
See [[Lab and Locate review 2026-11-24]] and [[Side of a step with two nearby sensors]].
