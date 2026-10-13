---
type: part
status: have
category: sensor
qty: 1
price_eur: 54.87
price_note: "EUR 54.87 net (65.84 with VAT) at DigiKey Austria, checked 2026-10-05 on the product page; a search snippet showed 39.64 net, so treat 54.87 as the safe figure"
supplier: DigiKey (EU, Austria site)
url: "https://www.digikey.at/en/products/detail/analog-devices-inc/EVAL-ADXL355Z/6557295"
datasheet: "https://www.analog.com/media/en/technical-documentation/data-sheets/adxl354_adxl355.pdf"
order: "[[ORD-001 First rig]]"
---
# ADXL355 breakout board

**Why we need it:** Accelerometer head for the appliance pack. Kaszti confirmed on 2026-10-05 that it goes into the first prototype next to the 2 geophones.

## Notes
- **Chosen board:** Analog Devices EVAL-ADXL355Z (simple evaluation breakout, ADXL355 on a small PCB). DigiKey Austria: 829 in stock, manufacturer lead time 10 weeks, checked 2026-10-05. Shipping to Hungary and company invoice: not checked on the live checkout (inferred: DigiKey ships to HU, check at order).
- **Price conflict:** product page shows 54.87 net / 65.84 gross; a search snippet of the same listing showed 39.64 net / 47.57 gross. Not resolved. Budget 55.
- **Supply:** the DigiKey listing gives 2.25 V to 3.6 V, so it runs from the ESP32-S3's 3.3 V.
- **Interface:** DigiKey lists "I2C, Serial, SPI" for the board (the ADXL355 chip supports both). **NOT verified** whether the headers bring out the I2C pins: UG-1030 was unreachable on 2026-10-05 and again on 2026-10-06 through three mirrors. Hint only (web-search summary): the header pins are named CS/SCL, SCLK/VSSIO, MOSI/SDA and MISO/ASEL, which would mean I2C works with SCLK/VSSIO tied to ground.
- **Chip-level I²C: VERIFIED** (ADXL354/355 datasheet Rev. 0, text mirror, 2026-10-06; see [[ORD-001 open checks]]). Pin 2 SCLK/VSSIO: "Connect to VSSIO for I2C". Pin 1 CS/SCL is the clock, pin 3 MOSI/SDA the data, pin 4 MISO/ASEL the address select. The chip detects SPI or I²C by itself (no mode register). Address 0x1D with ASEL low, 0x53 with ASEL high. Bus speeds 100 kHz, 400 kHz, 1 MHz and 3.4 MHz. Pull-ups on SDA/SCL are needed (≈ 2.2–4.7 kΩ; whether the board has them isn't known).
- **Searching the PDFs:** Analog Devices writes "I²C" with a superscript 2, so Ctrl+F for "I2C" finds nothing. Search for "SCL", "ASEL" or "VSSIO" instead.
- **Confirmed by Kaszti (2026-10-06):** the board's I²C works and the ADXL355 reaches the 2000 Hz the appliance pack needs ([[D-016 ADC records at 2 kSPS]]). The check below is done.
- ~~A person checks before ordering:~~ open UG-1030 (EVAL-ADXL354/355 user guide) in a browser and confirm that the header table lists SCL, SDA, ASEL and VSSIO, and that SCLK/VSSIO can be tied to ground for I2C. Don't order against D-004 until this is done. If it is SPI only, D-004 ("ADXL355 over I2C") needs a new decision; SPI would cost 3 extra GPIOs per head.
- **Stock 2026-10-06:** 820 at DigiKey AT, EUR 54.87 net.
- **Mounting:** the board has two sets of vias for 6-pin headers (headers are not mentioned as fitted; inferred: solder them yourself, 0.1 in pitch). Source: search summary of UG-1030.
- **Alternatives:**
  - EVAL-ADXL355-PMDZ (Pmod, 12-pin extended SPI, 3.3 V from host, about 2.5 x 2.5 cm): about USD 47 at Mouser (US site, not an EU price). SPI only, so it conflicts with D-004. Source: wiki.analog.com.
  - EVAL-ADXL355-SDP: about USD 78 to 85 (Mouser, DigiKey, Farnell); needs the SDP controller connector, not suited to our node.
  - Bare ADXL355BEZ chip: only useful with our own PCB (about 70 to 80 EUR on Farnell/Mouser, inferred from DKK and INR prices seen).
- No cheap third-party ADXL355 breakouts (Adafruit, SparkFun, etc.) were found.
- 2026-10-13: in the lab (Kaszti in chat: all parts are here except the geophones).
