---
type: decision
id: D-020
status: accepted
date: 2026-10-12
decided_by:
  - kaszti
  - viktor
tier: 1
supersedes:
---
# D-020 Recordings keep the 2 kSPS ADC stream

**Decision:** Every ADC recording, both from the lab and on the node's microSD, stores the **`adc_raw`** stream at 2 kSPS ([[D-016 ADC records at 2 kSPS]], stream id 0 in [[D-018 Node link protocol v0]]). The firmware's 1 kSPS `adc_dec` stream is for live use and for the packs on the node; it is not recorded. In the session layout of [[D-019 Sidecar v1]], `<session>.adc.wav|json` holds `adc_raw` (`stream: adc_raw`) and `<session>.accel.wav|json` holds the ADXL355. `rezonating_ml` decimates the recordings to 1 kSPS with exactly the same FIR as the firmware (one feature implementation, two languages).

**Why:** Kaszti chose this on 2026-10-12. Raw data keeps everything the ADC delivers: the FIR can still change, and old recordings can be decimated again. It costs about 58 MB per hour for 2 channels (32-bit WAV), which is cheap. It also answers the Handoff's open question "which stream goes to the microSD".

**Rejected alternatives:** Record `adc_dec` at 1 kSPS (half the size, but the firmware FIR is baked into the data for good). Record both (most disk space; comparing the firmware FIR with Python can be done with the lab's live streams instead).

**Affects:** the lab recorder, [[WAV and sidecar writer on microSD]], `rezonating_ml.io` and the decimator, `schemas/examples/` (the v1 example uses `stream: adc_raw`). Adds to D-019 without changing it. Accept in Obsidian if this is right.
