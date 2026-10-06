---
type: part
status: needed
category: adc
qty: 1
price_eur: 30.29
price_note: "Reference: RS Germany €30.29 net (search summary, 2026-10-06). Farnell price and stock not yet seen (site didn't load); check when ordering"
supplier: Farnell
url: "https://www.mikroe.com/adc-15-click"
datasheet: "https://www.ti.com/lit/ds/symlink/ads131m02.pdf"
order: "[[ORD-001 First rig]]"
---
# ADC 15 Click

**Why we need it:** The prototype's ADC, a ready-made MikroElektronika board (MIKROE-4890). It replaces the hand-soldered [[ADS131M04IPWR ADC]] with its oscillator and adapters. Chosen by Kaszti after talking with the boss on 2026-10-06; Farnell is the supplier. Proposed in [[D-015 Prototype ADC on ADC 15 Click]].

## Notes
- **Chip:** TI ADS131M02, a 2-channel, simultaneously sampling, 24-bit delta-sigma ADC, up to 64 kSPS (datasheet p.1). Same family as the ADS131M04, so the same register map style, PGA 1–128 and ±1.2 V / gain full scale. Gain 32 gives ±37.5 mV.
- **What changes:** 2 analog channels instead of 4. That covers the 2 SM-24 geophones; the ADXL355 is on I²C and doesn't use the ADC. A 3rd or 4th analog head (e.g. piezo) needs the ADS131M04 on our own PCB later.
- **Clock:** an on-board LTC6903 programmable silicon oscillator (chip select CS2 on the mikroBUS PWM pin). The firmware sets it to 8.192 MHz over SPI **mode 0** before reading the ADC in SPI **mode 1** (two SPI devices on one bus). It is far less accurate than a crystal (LTC6903 datasheet (ADI 69034fe): total accuracy 0.5 % typ, 1.1 % max at 2.7 V; 10 ppm/°C; 0.05 %/V; powers up at 1.039 kHz until programmed): the real sample rate can be off by up to ≈ 1 % (about 18 000 samples per hour at 1 kSPS, typical). Measure it by counting DRDY (active low, falling edge) against the ESP32 timer and record it in the sidecar. The 8.192 MHz oscillator we have is not needed.
- **Input limits at gain 32:** each input between AGND − 1.3 V and about +1.5 V; full scale ±37.5 mV (ADS131M02 datasheet).
- **Connection to the ESP32-S3:** jumper wires from the mikroBUS pins: SCK, MISO (SDO), MOSI (SDI), CS, INT (DRDY), RST, PWM (oscillator CS2), 3V3 and GND. 3.3 V logic only. Never use GPIO 33–37 (octal PSRAM).
- **Stock:** thin. DigiKey lists it as Active (6 in stock on 2026-10-06); SparkFun and Robot Gear stopped carrying it. Buy 2 if Farnell has them.
- **To confirm on the board's schematic:** input connector type, any input RC filters, the LTC6903 default frequency, the power jumper. Research: [[60 Research/ADC 15 Click|ADC 15 Click research]].
