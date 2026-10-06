---
type: work
status: todo
owner: claude
priority: p2
area: hardware
due: 2026-10-12
pack:
created: 2026-10-01
done:
---
# Check pin map against ADS131M04 datasheet

**Goal:** Make sure `firmware/README.md` and `hardware/README.md` match the ADC 15 Click (ADS131M02, mikroBUS pins), the ADXL355 (I²C) and the ESP32-S3 datasheets before anyone wires the boards ([[D-015 Prototype ADC on ADC 15 Click]]). Include the PSRAM pins (GPIO 33–37) and the decoupling findings from the datasheet review.

## Done when
- [ ] Every pin cross-checked
- [ ] Supply and decoupling notes confirmed
- [ ] Differences fixed in the repo

## Notes

## Log
- 2026-10-01 created
- 2026-10-05 Claude: due 2026-10-10 → 2026-10-12 (work days are Mon/Tue, schedule recounted at Kaszti's request)
- 2026-10-06 Claude: goal updated for the ADC 15 Click, ADXL355 and GPIO 33–37
