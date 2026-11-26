---
type: research
kind: article
status: read
relevance: med
url: "https://github.com/Kaszti49/Rezonating"
---
# Locate ideas parked

**Takeaway for Rezonating:** these ideas were built on 2026-11-23 and 2026-11-24 and taken out because the recorded steps did not support them, not because they are wrong. Each has what it did, why it left and **what would bring it back**. Kaszti, 2026-11-24: don't abandon them, log them.

Code: commit `ebccb71` (2026-11-23) holds the first version; the later ones are the patch files in `scratch/parked-locate-2026-11-24/` (throwaway folder: rewrite properly before use).

| Idea | What it did | Why it left | Bring it back when |
| --- | --- | --- | --- |
| **Bearing from the delay** | `sin(phi) = -(tau - tau0) / span`, 20–60 Hz cross-correlation, sub-sample | 0.16 ms scatter from step to step against ±0.33 to ±0.59 ms full delay; 15–20° error even at straight left and right; needs a calibration that broke when the rig changed | Geophones further apart, or 3+ sensors; the geophones move alike close up |
| **Front/back mirror wedge** | Drew the bearing and its mirror | Two sensors on one line can't separate them; confusing to look at | A third sensor off the line |
| **Distance from loudness** | `r = r_ref (a_ref / a)^(1/n)`, band near / mid / far, median of 5 steps | 7.6 dB scatter from step to step is a factor 2.4 in distance; a heavier step looks closer | Several nodes in a room, or a person's own step strength is known (person ID) |
| **Wave speed calibration** (2 spots, then 3 with "ahead") | Delay per side, zero point, gain ratio, swapped sides | Left and right were not mirror images (1.73 against −0.75 ms); it must be redone after any change | The rig is stable for days and one recording gives the same numbers twice |
| **Calibration gates** (cc ≥ 0.9, scatter ≤ 1 ms, polarity) | Refused bad spots | Not needed without a calibration; the agreement idea lives on as rig health | With any calibration |
| **Loudness only** | No "first" at all | 19 of 32 known steps against 26 for louder-then-first (EXP-004) | The geophones' loudness differs clearly at every distance. 2026-11-26: loudness 1.10 was right for 47 % of the steps timing left open; only 1.5 times or more stays, as the second question |
| **"First" as the first question** | First, else louder | Agreed only in 6 % and 47 % of the close steps; far steps came out RIGHT | **Brought back 2026-11-26** ([[EXP-005 Timing first on one-side walks]]): the geophones now move alike (\|cc\| ≥ 0.95 for 90 % of steps), and with ch0 known to be the right geophone (coin test) timing put 90 % of its sided steps right against 52 % for louder-then-first |
| **Learned classifier** (per-band loudness and phase, nearest class) | Trained on one session, tested on others | 15 of 16 on two later sets, but 0 of 8 on one held-out set; 32 steps are too few | Two labelled rounds of `locate-spots-v1` on two days |
| **Energy over 5 s** (Akiyama et al., [[Side of a step with two nearby sensors]]) | Not built; the majority of 3 steps is a small version | No walk recordings yet | The walk-pass dataset exists |
| **Gyroscope or ADXL355 for turning and tilt** | Not built | Would not have fixed the faults of 2026-11-24; a *Swap* button and the rest-level warning cover the demo | Turning the case in use becomes a product need (a decision) |

Related: [[EXP-005 Timing first on one-side walks]], [[EXP-002 Locate page first real floor run]], [[EXP-003 Eight spots round 1]], [[EXP-004 Louder then first on the recorded steps]], [[Footstep direction with two geophones]], [[D-027 Footstep-id tells the side of a step]]
