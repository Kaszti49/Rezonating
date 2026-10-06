---
type: work
status: backlog
owner: viktor
priority: p1
area: firmware
due: 2026-11-03
pack: "[[footstep-id]]"
created: 2026-10-01
done:
---
# ADS131M04 driver

**Goal:** The `acquire` component: data-ready interrupt, SPI read, timestamped frames in a PSRAM ring buffer, dropped-sample counter. Prototype target: the ADS131M02 on the [[ADC 15 Click board]] ([[D-015 Prototype ADC on ADC 15 Click]]): 2-channel frame, and set up the board's LTC6903 clock over SPI (CS2 on the mikroBUS PWM pin) before reading. Keep the code ready for the 4-channel ADS131M04 on the PCB.

## Done when
- [ ] Reads 1 kSPS on 1 channel for 10 min with 0 dropped samples
- [ ] Code reviewed by Claude

## Notes

## Log
- 2026-10-01 created
- 2026-10-05 Claude: due 2026-10-31 → 2026-11-03 (work days are Mon/Tue, schedule recounted at Kaszti's request)
- 2026-10-06 Claude: goal updated for the ADC 15 Click (ADS131M02 + LTC6903); file name kept so links stay valid
