---
type: research
kind: product
status: read
relevance: high
url: "https://www.mikroe.com/adc-15-click"
---
# ADC 15 Click (MIKROE-4890)

**Takeaway for Rezonating.** The ADC 15 Click carries the ADS131M**02**, the 2-channel sibling of our ADS131M04, so it is not a 4-channel replacement. It does remove the two hardest soldering jobs (the TSSOP chip and the 8.192 MHz clock; the clock comes from an SPI-programmable LTC6903 oscillator chip). It fits the two-SM-24 geophone prototype (2 simultaneous channels, 24 bit, gain up to 128, DRDY and RST on mikroBUS), but the node would have 2 analog head channels, not 4, and the oscillator must be programmed over SPI before any sample appears. Verdict: **fits with limits** (2 channels only; the Mikroe product page, schematic and TI datasheet were not readable in this session, so several rows are unverified). Stock is thin everywhere seen: Mikroe's own shop could not be loaded, TME shows it out of stock, the UK shop is sold out.

Checked 2026-10-06. Mikroe's own pages (mikroe.com, libstock) and TME, RS, Mouser, Arrow returned HTTP 403 or timed out for direct fetch, so the facts below come from search-result summaries, SparkFun, Debug Store, Robot Gear, DigiKey and the Mikroe GitHub library. "unverified" = not seen on a page I could open or on the schematic.

## 1. What's on it

| Item | Value | Source | Status |
| --- | --- | --- | --- |
| ADC chip | TI ADS131M02 (not M04) | DigiKey, SparkFun, Debug Store | seen |
| Channels | 2, simultaneous sampling | SparkFun, Debug Store | seen |
| Resolution | 24-bit delta-sigma | SparkFun | seen |
| Data rate | 250 SPS to 64 kSPS at f_CLKIN 8.192 MHz (high-resolution mode); 1–4 kSPS is fine | ADS131M02 datasheet SBAS853A | verified (verifier, 2026-10-06) |
| PGA gains | 1 to 128 (so 32 is available) | SparkFun, Debug Store | seen |
| Input range | Each input pin, recommended: gain 1/2/4: AGND − 1.3 V to AVDD; **gain 8–128: AGND − 1.3 V to AVDD − 1.8 V** (≈ +1.5 V at AVDD 3.3 V). Abs-max AGND − 1.6 V to AVDD + 0.3 V. Full scale ±1.2 V / gain = ±37.5 mV at gain 32. (The "−1.3 V to 3.6 V" shop text mixes the two limits.) | ADS131M02 datasheet SBAS853A, Recommended Operating Conditions + Abs Max | verified |
| Input type | Per chip: differential pair per channel (inferred from the ADS131M0x family); the pair may be negative-referenced to AGND as we plan | not confirmed on schematic | unverified |
| Input connection (screw terminal, header, pads) | not found | | unverified |
| Clock | CLKIN must be a continuous LVCMOS clock, 0.3–8.4 MHz in HR mode, 40–60 % duty (ADS131M02 datasheet SBAS853A). On the board: an **LTC6903 programmable silicon oscillator** (not a crystal) on CS2 = mikroBUS PWM. Mikroe's driver sets 8.192 MHz (OCT 12, DAC 984 → ≈ 8.1915 MHz, −60 ppm). Its accuracy/drift is looser than a crystal: measure the real sample rate (count DRDY against the ESP32 timer) and write it to the sidecar. LTC6903 datasheet (ADI 69034fe): total accuracy 0.5 % typ, 1.1 % max at 2.7 V; 10 ppm/°C; 0.05 %/V; powers up at 1.039 kHz until programmed (verifier, 2026-10-06, https://download.mikroe.com/documents/datasheets/LTC6903_datasheet.pdf). | ADS131M02 datasheet SBAS853A; mikrosdk_click_v2 adc15.c; LTC6903 datasheet | verified |
| Reference | internal low-drift 1.2 V in the ADC | SparkFun, Mikroe summary | seen |
| Anti-aliasing RC | not found | | unverified |
| Supply / logic | 3.3 V logic only (3.3 V mikroBUS rail; no 5 V option listed) | SparkFun, Debug Store | seen; power jumper not found |
| Interface | ADC: SPI **mode 1** (driver: 1 MHz). LTC6903: SPI **mode 0**, 16-bit word on CS2. On ESP-IDF that means two `spi_device` handles on one bus. Pins (adc15.h:162–169): CS = CS, RST = RST, CS2 = PWM, DRDY = INT | mikrosdk_click_v2 adc15.h/adc15.c | verified |
| Power modes | high-resolution, low-power, very low-power | SparkFun | seen |
| Size | M, 42.9 x 25.4 mm | SparkFun, Debug Store | seen |
| Driver | mikroSDK library `adc15` (Luka Filipovic, Sept 2021): setup, init, default cfg, read voltage, set gain, set word length; waits for DRDY | github.com/MikroElektronika/mikrosdk_click_v2 | seen |

## 2. Can it do our job?

Compare to CLAUDE.md, D-004 and hardware/README (not re-read here; needs are as the task states them).

- **Fits:** simultaneous sampling of two SM-24 geophones; 24 bit; gain 32 available; 1 to 4 kSPS is far below the stated maximum; DRDY interrupt on a 3.3 V board; mikroSDK driver is a readable register-level reference for our own ESP-IDF driver; no 8.192 MHz oscillator or TSSOP soldering.
- **Does not fit:** only **2 analog head channels** instead of 4. A piezo head later would need another ADC or the real ADS131M04 board. ADXL355 is digital and unaffected.
- **Differences from our plan:** (1) the clock is not a free-running crystal oscillator, it must be programmed by SPI (LTC6903 via the CS2/PWM pin) and the ADC will only answer after CLKIN runs, so the driver needs an extra init step; (2) our ADS131M04 driver work item and pin map check (M04 pinout, 4 channels) do not carry over one to one: register map is similar, channel count and status word differ (inferred); (3) the input connection method is unknown, so the geophone coil may need soldered wires or a header.
- **Wiring (ESP32-S3-DEV-N16R8 to mikroBUS):** SCK, MISO, MOSI, CS (SPI), INT to a GPIO with interrupt for DRDY, RST to a GPIO, PWM (CS2) to a GPIO used as a second chip select for the oscillator, 3V3, GND. Avoid GPIO 35 to 37 (octal PSRAM). Check the mikroBUS pin order on the schematic before wiring (unverified).
- **Coil negative to AGND:** allowed. At gain 32 each input may sit between AGND − 1.3 V and about +1.5 V, and the geophone signal is millivolts around 0 V. Still check the board's input connector on the schematic.

## 3. European suppliers (checked 2026-10-06)

| Shop | Ships from | Price | Stock / lead time | Note |
| --- | --- | --- | --- | --- |
| Mikroe own shop | Serbia | not found (page returned 403) | not found | try in a browser |
| TME | Poland | not found | search summary said out of stock | page 403 |
| Mouser EU | not checked | USD 31.00 on mouser.com per a search summary (not EUR) | not found | EU page timed out |
| DigiKey | | USD 31.00 net; 6 units; lead time 4 weeks; **part status Active** (digikey.com, verifier 2026-10-06) | a search summary elsewhere said 27 units, so stock changes; DigiKey EU site not loaded | EUR price not found |
| RS (de.rs-online.com) | | EUR 30.29 net, EUR 36.05 incl. VAT (search summary, German RS site) | not found | page 403; DE VAT 19% |
| Farnell, Conrad, Reichelt, Hestore (HU) | | not found | not found | not checked or not found in search |
| The Debug Store (UK, for reference) | UK | GBP 31.00 net / 37.20 incl. VAT | sold out | UK, post-Brexit customs |
| SparkFun | | USD 25.95 | retired | not available |

Price level in all places is about 26 to 31 units of currency, roughly EUR 28 to 30 net (inferred). Check the live pages before ordering.

## 4. Alternatives

| Board | Channels | Price, EU stock | Note |
| --- | --- | --- | --- |
| TI ADS131M04EVM (with PHI controller board) | 4, simultaneous | DigiKey AT EUR 257.33 net / 308.79 incl. VAT; another summary says DigiKey EUR 280.89 net, 7 in stock; Mouser EUR 315.00 | far too expensive; needs the TI PHI board and TI software, not a plain SPI board (inferred) |
| Hand-soldered ADS131M04IPWR on adapter | 4 | LCSC, ≈ USD 4.69 each | replaced for the prototype by the ADC 15 Click (Kaszti, 2026-10-06; D-015 proposed); returns on our PCB |
| Other Mikroe Clicks, Olimex, Adafruit, SparkFun with ADS131M04 | not found | not found | the search found no ADS131M04 breakout; not an exhaustive search |

Other ADC Clicks with 4 simultaneous 24-bit channels were not checked. The Mikroe "ADC Click" (https://www.mikroe.com/adc-click) appeared in search but its chip and channel count were not read.

## Unresolved
- Open the Mikroe page and the schematic PDF in a browser: input connector type, LTC6903 frequency settings and whether CLKIN can take an external clock, RC filters, power jumper, exact mikroBUS pins.
- ~~Read the ADS131M02 datasheet~~ done by the verifier on 2026-10-06 (data rates, CLKIN, per-gain input range above).
- Live stock and EUR price from Mikroe, TME, Mouser EU, DigiKey EU, Farnell, Conrad, Reichelt, Hestore.
- ~~Decide whether 2 channels is acceptable~~ Kaszti chose the ADC 15 Click from Farnell on 2026-10-06 (D-015 proposed).
