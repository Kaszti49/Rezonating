---
type: decision
id: D-004
status: accepted
date: 2026-10-01
decided_by: [kaszti, viktor]
tier: 1
supersedes:
---
# D-004 Core parts

**Decision:** ESP32-S3 N16R8, ADS131M04 + 8.192 MHz oscillator, SM-24 geophone, ADXL355 over I2C, brass piezo discs, RJ45 head ports, USB-C, microSD.

**Why:** Simultaneous sampling for localisation, PSRAM for buffers and models.

**Rejected alternatives:** ADS1256 (not simultaneous); boards without PSRAM.
