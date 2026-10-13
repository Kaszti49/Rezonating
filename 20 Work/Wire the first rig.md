---
type: work
status: backlog
owner: viktor
priority: p1
area: hardware
due: 2026-10-20
pack:
created: 2026-10-06
done:
---
# Wire the first rig

**Goal:** Connect the [[ADC 15 Click board]], the two SM-24 geophones, the [[ADXL355 breakout board]] and the microSD breakout directly to the ESP32-S3 (no breadboard) and confirm everything powers up and answers.

## Done when
- [ ] Pin map agreed (see [[Check pin map against ADS131M04 datasheet]]); no GPIO 33–37
- [ ] ADC 15 Click: LTC6903 clock set up, ADS131M02 ID register reads correctly
- [ ] ADXL355 answers on I²C (0x1D or 0x53)
- [ ] Geophones on the two ADC channels, 1 kΩ shunt across each coil
- [ ] Build note in `30 Hardware/Builds`

## Notes
Replaces "Solder ADS131M04 on adapter" ([[D-015 Prototype ADC on ADC 15 Click]]). Due date is a proposal: parts arrive about two weeks after the order.

## Log
- 2026-10-06 created by Claude after Kaszti's decision for the ADC 15 Click
- 2026-10-13 Claude: the lab's ESP board is a classic ESP32, not the S3, and an HX711 + YZC-133 load cell were added. The pin map for these boards is in the [First rig bench guide](https://claude.ai/code/artifact/53c286fe-182d-4bf3-91f6-4778f18e5648) (for Viktor to confirm). Due date unchanged.
