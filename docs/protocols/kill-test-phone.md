# Protocol: kill-test-phone (v1)

**Question:** do footsteps on our floors produce a vibration a sensor can see?
**Cost:** €0, about 1 hour. **Tier 3.**

## Setup

1. Install the free **phyphox** app. Open "Acceleration (without g)".
2. Take the phone out of its case. Lay it flat, screen up, on bare floor.
3. Mark three spots on a straight line at 1 m, 3 m and 5 m from the phone.
4. Note the floor type (e.g. "laminate on concrete slab", "wooden floorboards").

## Run

1. Record 30 s with nobody moving: this is the noise floor.
2. Each of 3 people walks across each spot 5 times, normal pace, shoes on.
   Call out the start of each pass so it can be marked.
3. Repeat barefoot.
4. Export as CSV; name it `kill_<date>_<floor>.csv`.

## Decide

| Result at 3 m | Meaning |
| --- | --- |
| Steps clearly above the noise floor | Pass: order the geophones |
| Visible only at 1 m | Inconclusive: phones are far less sensitive than geophones; order one geophone first |
| Nothing visible at 1 m | Re-test on another floor before buying anything |
