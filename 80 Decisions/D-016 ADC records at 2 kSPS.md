---
type: decision
id: D-016
status: accepted
date: 2026-10-06
decided_by:
  - kaszti
  - viktor
tier: 1
supersedes:
---
# D-016 ADC records at 2 kSPS

**Decision:** The ADC (ADS131M02 on the [[ADC 15 Click board]]) samples at 2 kSPS (OSR 2048). The firmware low-pass filters the stream with a sharp FIR (pass band up to 400 Hz) and decimates by 2 to the 1 kSPS that the footstep-id and fall packs ask for. The ADXL355 runs at 2000 Hz over I²C for the appliance pack.

**Why:** At 1 kSPS the ADC's own sinc filter attenuates only −4.4 dB at the 500 Hz Nyquist frequency, so 500–800 Hz vibration folds into the band almost unattenuated (datasheet-based calculation, see the study guide). At 2 kSPS the 0–400 Hz band loses only −0.9 dB, everything that could fold into 0–400 Hz (1600–2400 Hz) is cut by at least 17.5 dB in the ADC, and the FIR removes 400–1000 Hz before decimation. Kaszti decided on 2026-10-06 to start at 2 kSPS. Kaszti also confirmed that the ADXL355 works over I²C and reaches 2000 Hz.

**Rejected alternatives:** Record at 1 kSPS (aliasing near Nyquist); record at 4 kSPS (twice the data and processing for little extra gain at this stage).

**Affects:** the `acquire` and `dsp` firmware components, the sidecar `sample_rate` (record the measured rate, see [[ADC 15 Click board]]), the ML pipeline (train on data decimated the same way: one feature implementation, two languages), [[ADS131M04 driver]], [[WAV and sidecar writer on microSD]]. Accept in Obsidian if this is right.
