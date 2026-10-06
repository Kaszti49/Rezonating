---
type: project
cssclasses: [rz-wide]
---
# Master plan

The full plan lives in the shared Claude doc **Rezonating Master Plan v1** (architecture, universality, packs, hardware, firmware, data, integration, first order, risks). This note keeps the parts we look up most often.

## Architecture in one line
Heads identify themselves (EEPROM descriptor) → packs declare what they need (`pack.json`) → the node runs every pack whose heads are present → events go to Home Assistant over MQTT, raw data to microSD.

## Hardware
- **MCU:** ESP32-S3 N16R8 (16 MB flash, 8 MB PSRAM). GPIO 35–37 are taken by the PSRAM.
- **ADC:** ADS131M04, 4 simultaneous channels, 24-bit, needs an 8.192 MHz clock on CLKIN.
- **Head ports:** RJ45. Pins 1–2 analog ±, 3–6 I2C, 4–5 +3.3 V, 7–8 GND. Label them "not Ethernet".
- **Heads:** SM-24 geophone (direct to ADC, gain 32–64), ADXL355 (I2C), piezo (buffer + clamp, mandatory).
- **First prototype:** 2 SM-24 geophones on an ADC 15 Click (ADS131M02, 2 channels, own clock) + 1 ADXL355 on I2C, wired directly to the ESP32-S3 and recording to microSD ([[ORD-001 First rig]], [[D-015 Prototype ADC on ADC 15 Click]], proposed). The 4-channel ADS131M04 comes back on our own PCB.

## Engines
| Engine | Used by |
| --- | --- |
| classifier | footstep-id, fall |
| anomaly | appliance |
| localizer | later packs |
| rule | fall (stillness), later packs |

## Tier 1 (change only with a decision note)
Dataset format and sidecar schema · head descriptor and pack manifest schemas · firmware core (acquire, buffer, timestamps, pack loader) · shared feature code.

## Top risks
1. Concrete slabs damp footsteps: the first rig's first recordings answer it (the phone kill test was dropped on 2026-10-05).
2. Person ID weaker in a real home (one student replication reached 67%).
3. Fall false alarms.
4. ADC 15 Click stock is thin and some shops list it as retired: buy 2 if possible. (The hand-soldering risk is gone with the ready-made board.)
