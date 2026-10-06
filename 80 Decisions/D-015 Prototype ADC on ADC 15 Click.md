---
type: decision
id: D-015
status: accepted
date: 2026-10-06
decided_by:
  - kaszti
  - viktor
tier: 1
supersedes:
---
# D-015 Prototype ADC on ADC 15 Click

**Decision:** The first prototype uses the MikroElektronika ADC 15 Click (ADS131M02: 2 simultaneous 24-bit channels, on-board LTC6903 clock), bought from Farnell and wired straight to the ESP32-S3, with no breadboard. The 4-channel ADS131M04 from [[D-004 Core parts]] stays the target for our own PCB.

**Why:** Kaszti and the boss decided on 2026-10-06 not to hand-solder a 0.65 mm-pitch chip or breadboard the rig. The Click is ready-made, has its own clock, and 2 channels are enough for the 2 SM-24 geophones; the ADXL355 is on I²C.

**Rejected alternatives:** Hand-soldered ADS131M04 on a TSSOP adapter with a separate oscillator (soldering risk, more parts); ADS131M04EVM (≈ €257, too expensive).

**Affects:** [[ADC 15 Click board]] (part), [[ADS131M04IPWR ADC]] (moves to the PCB phase), [[ORD-001 First rig]], [[Master plan]], `hardware/README.md`, the driver work item (ADS131M02 framing + LTC6903 set-up), the pin map. Until a PCB exists, the node has 2 analog head channels, not 4. Accept in Obsidian if this is right.
