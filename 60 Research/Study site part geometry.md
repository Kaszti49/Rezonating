---
type: research
kind: datasheet
status: read
relevance: high
url: "https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html"
---
# Study site part geometry

**Takeaway for Rezonating.** For the Three.js models in `tools/study/`, the pin lists of the ESP32-S3-DevKitC-1 (J1/J3), ADS131M04 (TSSOP-20), AT24C02, TCA9548A, HX711 IC and the ADC 15 Click headers are solid. Physical sizes are mostly NOT verified: the TI, ADI, Microchip and Espressif PDFs could not be decoded in this session (PDF fetch returned binary, no PDF renderer), so sizes came from retail pages, search summaries and footprint names. Anything marked ESTIMATED must be measured with calipers or checked against the PDF before being drawn as fact. Checked 2026-11-03.

Legend: V = VERIFIED (read from official/vault page), E = ESTIMATED (retail listing, mirror, footprint name, inference).

## 1. ESP32 DevKit V1 30-pin (DOIT, WROOM-32) + expansion board
- Pin order: reuse [[ESP32 DevKit V1 with expansion board]] (left EN, VP36, VN39, D34, D35, D32, D33, D25, D26, D27, D14, D12, D13, GND, VIN; right D23, D22, TX0, RX0, D21, D19, D18, D5, TX2/D17, RX2/D16, D4, D2, D15, GND, 3V3). V (photos in vault).
- PCB about 51.8 x 28.2 mm (E; reader comment on mischianti.org, retail 51.4 x 28.5 x 15). Pitch 2.54 mm (V, standard). Row spacing: NOT found for the 30-pin board. The 0.9 in (22.86 mm) figure belongs to 38-pin clones per a forum thread. Inference (E): about 25.4 mm (1.0 in) centre to centre, measure it. Source: https://mischianti.org/doit-esp32-dev-kit-v1-high-resolution-pinout-and-specs/ ; https://forum.fritzing.org/t/doit-esp32-devkit-v1/6158
- Layout (E, typical clone): WROOM-32 shield at the top (antenna end, away from USB), micro-USB bottom centre, CP2102 and AMS1117 near the USB end, EN button bottom-left and BOOT bottom-right next to USB, blue LED on GPIO2.
- Expansion board: size not found (E: roughly 65 x 55 mm). Contents from the vault note (V): 3-pin rows (signal, V, G) per GPIO, I2C 4-pin header D22/D21/VCC/GND, 5V/3.3V jumper, USB-C, micro-USB, DC jack.

## 2. ESP32-S3-DevKitC-1 (N16R8)
- Size 62.74 x 25.40 mm, pitch 2.54 mm: Espressif PCB drawing V1 (text extract via search) and Electrokit/Conrad listings. https://dl.espressif.com/dl/PCB_ESP32-S3-DevKitC-1_V1_20210312CB.pdf . Treat as V for length/width (two retail pages agree), row spacing E (about 22.86 mm / 0.9 in, inferred from the 22-pin headers on a 25.4 mm board; check the drawing).
- Components (V, user guide v1.1): module ESP32-S3-WROOM-1; two USB-C ports at the same end (one "UART" via bridge, one "USB" native OTG); RGB LED on GPIO38 (v1.1; GPIO48 on v1.0); BOOT and RST (EN) buttons; 3.3 V power LED. Exact positions: not in text. E: module at the top, USB ports and buttons at the bottom, buttons beside the ports.
- Octal PSRAM/flash (N16R8): user guide text found says GPIO35, 36, 37 are not available; CLAUDE.md and the datasheet Table 2-14 say 33-37 (GPIO33, 34 too). Use 33-37 as reserved. Vault fact.
- **J1** (left, pins 1-22), V, https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html (pin tables):
  1 3V3, 2 3V3, 3 RST(EN), 4 GPIO4, 5 GPIO5, 6 GPIO6, 7 GPIO7, 8 GPIO15, 9 GPIO16, 10 GPIO17, 11 GPIO18, 12 GPIO8, 13 GPIO3, 14 GPIO46, 15 GPIO9, 16 GPIO10, 17 GPIO11, 18 GPIO12, 19 GPIO13, 20 GPIO14, 21 5V, 22 G.
- **J3** (right, pins 1-22):
  1 G, 2 TX (GPIO43, U0TXD), 3 RX (GPIO44, U0RXD), 4 GPIO1, 5 GPIO2, 6 GPIO42, 7 GPIO41, 8 GPIO40, 9 GPIO39, 10 GPIO38 (RGB LED), 11 GPIO37*, 12 GPIO36*, 13 GPIO35*, 14 GPIO0, 15 GPIO45, 16 GPIO48, 17 GPIO47, 18 GPIO21, 19 GPIO20 (USB D+), 20 GPIO19 (USB D-), 21 G, 22 G.
  * = octal PSRAM (33-37; 33 and 34 are not brought out on this header).

## 3. ADC 15 Click (MIKROE-4890)
- Headers (V, vault note from the board): left top to bottom NC, RST, CS1, SCK, SDO, SDI, 3V3, GND; right CS2, INT, NC x5, GND. Two 2-pole screw terminals: CH2 left (+ left, - right), CH1 right (- left, + right).
- Board size and terminal pitch: NOT found. E: mikroBUS Click size M is 28.6 x 25.4 mm (mikroBUS spec, not re-checked) and 5.0 mm or 3.5 mm terminals (unknown). Chips (E, from the vault photo only): ADS131M02 and LTC6903 near the middle, PWR LED with R1 470 ohm. Schematic v1.00: https://cdn.sparkfun.com/assets/6/f/d/8/1/Schematic-20487-MIKROE_ADC_15_Click.PDF (not decoded). mikroe.com returned 403.
- LTC6903 MSOP-8 (E, datasheetq mirror and flux.ai agree; not the ADI PDF): 1 GND, 2 SDI, 3 SCK, 4 SEN, 5 CLK-bar, 6 CLK, 7 OE, 8 V+. The ADI PDF timed out.
- ADS131M02 TSSOP-20 pinout: not fetched. The M04 table below applies to M04 only. M02 differs (two channels). Mark E if you draw it.

## 4. ADS131M04IPWR (TSSOP-20)
- Pins (V, TI ADS131M04-Q1 datasheet Table 5-1 via ti.com document viewer; base-part wiki gives the identical table): 1 AVDD, 2 AGND, 3 AIN0P, 4 AIN0N, 5 AIN1N, 6 AIN1P, 7 AIN2P, 8 AIN2N, 9 AIN3N, 10 AIN3P, 11 SYNC/RESET (act. low), 12 CS, 13 DRDY (act. low), 14 SCLK, 15 DOUT, 16 DIN, 17 CLKIN, 18 CAP (220 nF to DGND), 19 DGND, 20 DVDD. https://ti.com/document-viewer/ja-jp/ADS131M04-Q1/datasheet/GUID-3065C13F-76ED-4C76-9520-FD6FAA5F0A39.html ; https://wiki.adom.inc/ray/ads131m04
- Package: TI product page says TSSOP (PW) 20 pins, 6.5 x 6.4 mm footprint area (V, https://www.ti.com/product/ADS131M04); body 6.5 x 4.4 mm, pitch 0.65 mm (E, KiCad footprint name TSSOP-20_4.4x6.5mm_P0.65mm); height about 1.2 mm max (E, TSSOP generic); lead span 6.4 mm (inferred from the 6.4 mm).

## 5. QTM325-8.192MBD-T oscillator (3.2 x 2.5 mm)
- 4 pads. Vault note (V, datasheet Rev 1.04): pad 1 = enable (high or open = on). Pads 2 GND, 3 OUT, 4 VDD are the usual layout (E, not read from the drawing). Height about 1 mm (E). Datasheet: https://www.qstproducts.com/Oscillator/QTM325.pdf (not fetched).

## 6. HX711 green breakout
- J1 (V, vault photo): E+, E-, A-, A+, B-, B+. JP2: VCC, SCK, DT, GND. Board size: not found. E: about 34 x 21 mm for the common green board (not verified).
- HX711 SOP-16 (V, AVIA datasheet per several mirrors in search summary): 1 VSUP, 2 BASE, 3 AVDD, 4 VFB, 5 AGND, 6 VBG, 7 INA-, 8 INA+, 9 INB-, 10 INB+, 11 PD_SCK, 12 DOUT, 13 XO, 14 XI, 15 RATE, 16 DVDD. Note: sources disagree slightly, one community page has errors. SOP-16 body about 9.9 x 3.9 mm, pitch 1.27 mm (E, generic SOIC-16).

## 7. YZC-133 5 kg load cell
- Not found in any manufacturer source. E (typical parallel-beam 5 kg cells): about 80 x 12.7 x 12.7 mm, two M5 threaded holes at each end, hole pitch about 12.7 mm... measure with calipers. Wires: red/black/green/white (V vault). Strain gauges bonded in the thinned centre section, one pair on top, one pair underneath (E).

## 8. SM-24 geophone (Opencircuit, insulating disc)
- Element: diameter 25.4 mm, height 32 mm, weight 74 g; natural frequency 10 Hz +-2.5 %; coil resistance 375 ohm +-2.5 % (web search summary of the SM-24 datasheet at proto-pic.co.uk, domain no longer resolves). V-ish; confirm in the PDF.
- Opencircuit listing: 40 x 65 x 40 mm, 168 g, 28.8 V/(m/s), 10-240 Hz, upright with insulating disc (https://opencircuit.shop/product/geophone-sm-24-with-insulating-disc). These are package-with-disc numbers, E for the model envelope.
- Damping (secondary source, TI E2E forum reproducing the datasheet): open circuit 0.25; 0.60 with 1339 ohm shunt; 0.69 with 1000 ohm. E. Terminals: two (E; not read). Spike/base: not found; listing says "insulating disc" only.

## 9. EVAL-ADXL355Z
- Board 0.8 x 0.8 in (20.3 x 20.3 mm), four corner holes, two sets of vias for 6-pin headers: V-ish (UG-1030 text mirror at omo-ic.com).
- Header P1 signals: VDDIO, VDD (to VSUPPLY), VSS/VSSIO, INT1, INT2, DRDY. P2: V1P8ANA, V1P8DIG, MISO/ASEL, CS/SCL, SCLK/VSSIO, MOSI/SDA. The pin NUMBER order within P1/P2 is NOT known: mark E if drawn. Do not use the ADXL354 board's P2 (TEMP, ST1, ST2).
- Chip LGA-14: pins 1 CS/SCL, 2 SCLK/VSSIO, 3 MOSI/SDA, 4 MISO/ASEL, 8 V1P8DIG, 9 VSS, 10 V1P8ANA, 11 VSUPPLY, 12 INT1, 13 INT2, 14 DRDY (V partial, datasheet excerpt via search). Pins 5 (VDDIO, likely), 6 (VSSIO, likely, ADXL354 table), 7 (not found, E). Package 6 x 6 x 2.1 mm (datasheet excerpt) vs 6 x 5.6 x 2.2 mm (ADI product page): conflict, show both.

## 10. AT24C02
- Pinout (E-high, Utmel summary of the datasheet): 1 A0, 2 A1, 3 A2, 4 GND, 5 SDA, 6 SCL, 7 WP, 8 VCC. Same in SOIC-8 and DIP-8.
- SOIC-8 body 3.9 x 4.9 mm, pitch 1.27 mm (E, KiCad footprint name); DIP-8 row spacing 7.62 mm (0.3 in), pitch 2.54 mm, body about 9.3 x 6.4 mm (E, generic).

## 11. TCA9548A breakout (Adafruit)
- Pins (V, https://learn.adafruit.com/adafruit-tca9548a-1-to-8-i2c-multiplexer-breakout/pinouts): Vin, GND, SCL, SDA, RST (pulled high), A0, A1, A2, then SD0/SC0 ... SD7/SC7. Address 0x70 + A0 (1) + A1 (2) + A2 (4); range 0x70-0x77.
- Board size: not found (fab print is an image). E: about 1.6 x 1.1 in... verify.

## 12. microSD SPI breakouts
- 6-pin 5 V module (E, vendor listings): header CS, SCK, MOSI, MISO, VCC (4.5-5.5 V), GND; AMS1117-3.3 and 74LVC125A level buffer; about 42 x 25 x 9 mm (ShillehTek; another sizing 42 x 24 not found). Order of pins on the header varies by clone (E). Sources: https://shillehtek.com/blogs/shillehtek-product-manuals/micro-sd-tf-card-adapter-reader-module-spi-interface-for-arduino-manual ; https://envistiamall.com/blogs/learn/micro-sd-card-spi-module-user-guide
- Bare 3.3 V variant: size not found; E: about 15 x 20 mm. Pins CS, MOSI, SCK, VCC, MISO, GND (order varies, E).

## 13. microSD card, SPI mode
- 1 CS, 2 DI (MOSI), 3 VSS, 4 VDD, 5 CLK, 6 VSS, 7 DO (MISO), 8 NC/RSV (Micrium reference lists 1, 2, 5, 7; pins 3, 4, 6, 8 from the SD standard, E). Delkin lists a different SPI order: conflict, check the SD spec. Size 11 x 15 x 1.0 mm: not found in a source (E, standard).

## 14. RJ45 breakout
- Not researched in a source. E: 8-pin breakout about 30 x 20 mm, 2.54 mm pitch, pins 1-8 as the jack contacts. T568B (E-high, TIA standard, not fetched): 1 white/orange, 2 orange, 3 white/green, 4 blue, 5 white/blue, 6 green, 7 white/brown, 8 brown. Pairs: 1-2, 3-6, 4-5, 7-8.

## 15. Cat5e cable
- 4 twisted pairs, 24 AWG solid copper (typical), outer diameter about 5 mm (E, typical UTP). Pair colours: orange, green, blue, brown.

## 16. Breadboard 830
- About 165 x 55 x 8.5-10 mm (listings: 165.1 x 54.6 x 8.5; 165 x 54 x 10; Multicomp 165 x 56 x 8.3). Pitch 2.54 mm, 63 rows, 10 columns (a-e, f-j, centre gap 7.62 mm), four power rails of 50 holes each (100 points per pair of rails; some split mid-length). E-high. https://www.elektor.com/breadboard-830-tie-points ; https://uk.robotshop.com/products/full-size-bare-breadboard-830-tie-point

## 17. Resistor and capacitor assortment (all E)
- 1/4 W axial resistor: body about 6.3 x 2.4 mm, lead 0.5-0.6 mm, 4 or 5 colour bands. Colour code: 0 black, 1 brown, 2 red, 3 orange, 4 yellow, 5 green, 6 blue, 7 violet, 8 grey, 9 white; tolerance gold 5 %, silver 10 %. 1 kΩ = brown black red, 10 Ω = brown black black.
- 100 nF ceramic disc: about 5 mm diameter, 2.5-5 mm lead spacing. MLCC 0805: 2.0 x 1.25 mm.
- 10 µF electrolytic radial 5 x 11 mm (typical for 16-50 V; 2.0 mm lead spacing). Negative stripe on the can.

## 18. Solder flux pen (E)
- Pen about 140 x 16 mm, chisel or brush tip.

## Gaps for a person to check
Row spacing of the DevKit V1; every size marked E; ADC 15 Click outline and terminal pitch; EVAL-ADXL355Z header pin order; QTM325 pad drawing.
