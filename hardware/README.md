# Hardware

## First rig (Tier 3, wired directly, no breadboard)

Goal: two geophones → ADC 15 Click (ADS131M02) and one ADXL355 → ESP32-S3 →
microSD, recording real floor and machine data as early as possible.

- ADC: MikroElektronika ADC 15 Click (MIKROE-4890) with a TI ADS131M02: 2
  simultaneous 24-bit channels, PGA 1–128. The 4-channel ADS131M04 comes back
  on our own PCB.
- Clock: the board's LTC6903 programmable oscillator, set to 8.192 MHz by the
  firmware over SPI mode 0 (chip select CS2 = mikroBUS PWM pin) before the ADC
  is read in SPI mode 1. It is a silicon oscillator, not a crystal (0.5 % typ, 1.1 % max at 25 °C, up to 1.65 % over temperature): measure
  the real sample rate and record it. DRDY is active low (falling edge).
- Wiring, mikroBUS → ESP32-S3: SCK, SDO (MISO), SDI (MOSI), CS, INT (DRDY, to an
  interrupt-capable GPIO), RST, PWM (oscillator CS2), 3V3, GND. 3.3 V only.
- Geophone coil across AIN0P / AIN0N, AIN0N tied to AGND, gain 32 to start
  (full scale ±37.5 mV; each input must stay between AGND − 1.3 V and about
  +1.5 V at this gain). 1 kΩ shunt across each coil.
- Second geophone on AIN1P / AIN1N, wired the same way.
- ADXL355 breakout on the ESP32-S3's I2C bus at 3.3 V (digital, not through the
  ADC). SCLK/VSSIO to ground selects I2C; address 0x1D (ASEL low) or 0x53.
- microSD breakout on SPI (a second bus or a separate CS).
- GPIOs for all of the above still need to go into the pin map in
  `firmware/README.md`. Never use GPIO 33–37 (octal PSRAM).

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
