---
type: experiment
id: EXP-001
status: done
date: 2026-11-14
owner: kaszti
pack: "[[fall]]"
protocol:
floor: hackathon stage
people: 1
sessions: []
metric: falls caught (%)
metric_value: 100
result: partial
---
# EXP-001 Hackathon fall detector on stage

**Takeaway:** On the stage floor, one SM-24 geophone caught 3 of 3 falls (near, mid, far) and rejected 3 of 3 jumps. That is far too few events to claim the Charter target (≥ 95 % caught, < 1 false alarm a week), so the result is `partial`.

## Setup
- Hardware: ESP32-S3 DevKit, ADC 15 Click (ADS131M02 + LTC6903), one SM-24, gain ×2, 1000 samples/s (measured 998).
- Firmware: `firmware/hackathon-rezon` (Arduino), copied from `Kaszti49/RezonFallDetector` at `f6d2eee`. The settings stored in flash were stepMin 1.5, impactMin 6, walkerMargin 1.5 and stepRef 8.
- Session `session_2026-11-14T01-41-28.log` (not in git; goes to `data/raw/hackathon/`). Kaszti walked near (0–11 s), mid (12–30 s) and far (31–43 s), then fell near, mid and far, then did 3 jumps. Labels are in `firmware/hackathon-rezon/data/labels.tsv`.

## Results
- Replay on 2026-11-15 with the stored settings: falls flagged at 43.7, 51.5 and 60.4 s, which are the three labelled falls. None of the jumps at 64.3, 70.1 and 74.9 s was flagged as a fall, and the alarm called once.
- The same three falls and three jumps as a table, for the Lab's Home page (added by Claude 2026-11-24, same numbers):

| Set | Right | Same | Wrong |
| --- | --- | --- | --- |
| Falls caught | 3 | 0 | 0 |
| Jumps not taken for a fall | 3 | 0 | 0 |

- Earlier bench recordings (2026-11-12, gain 4, compiled defaults): all 7 impact-sized events were flagged and the walking-only recording raised 0 alarms. The labels on those 7 events are provisional. A synthetic walking-over-fall mix found 35 of 35 falls.

## What it does not show
- Only one person and one floor, with no real falls. The falls were deliberate.
- Walker tracking rarely confirmed tracks on soft shoes, so the bystander rule is mostly untested.
- A new walker who starts after a fall cancels it, the same as someone getting up.

## Next
The core moves into the node firmware: see [[D-024 Hackathon core is the fall pack engine]] and [[Port the fall core to ESP-IDF]].
