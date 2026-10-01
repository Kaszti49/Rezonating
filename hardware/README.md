# Hardware

## First rig (Tier 3, breadboard)

Goal: one geophone → ADS131M04 → ESP32-S3 → microSD, recording real floor
data as early as possible.

- ADS131M04 soldered on a TSSOP-20 → DIP adapter.
- 8.192 MHz 3.3 V CMOS oscillator into CLKIN (required; no internal clock).
- AVDD and DVDD from the dev board's 3.3 V through a 10 Ω + 10 µF filter on
  AVDD. A separate low-noise LDO comes on the first PCB.
- Geophone coil across AIN0P / AIN0N, AIN0N tied to AGND, gain 32 to start.
- 100 nF on every supply pin, close to the chip.

## Head port (Year 1 PCB, draft v0)

RJ45, T568B pairs. Label every port "not Ethernet".

| Pins | Signal |
| --- | --- |
| 1–2 | Analog channel + / − |
| 3–6 | I2C SDA / SCL (EEPROM, ADXL355) |
| 4–5 | +3.3 V |
| 7–8 | GND |

## Heads

| Head | Parts | Notes |
| --- | --- | --- |
| Geophone | SM-24, AT24C02 EEPROM, spike or weighted base | Direct to ADC first; preamp only if signal is too weak |
| Accelerometer | ADXL355 board, AT24C02, magnet mount | I2C, not through the ADC |
| Piezo | 27–35 mm disc, high-impedance buffer, clamp diodes, AT24C02 | Clamp is mandatory |

Folders `node/` and `heads/` will hold KiCad projects once the breadboard rig
works.
