---
type: research
kind: product
status: read
relevance: high
url: "https://www.analog.com/media/en/technical-documentation/data-sheets/adxl354_adxl355.pdf"
---
# ORD-001 open checks

**Takeaway for Rezonating:** The ADXL355 chip does I2C (verified in the datasheet, via a text mirror): SCLK/VSSIO goes to VSSIO, ASEL low gives 0x1D and high gives 0x53, and the I2C bus runs up to 3.4 MHz. The one gap that remains is whether the EVAL-ADXL355Z headers bring out those four pins: UG-1030 could not be loaded on 2026-10-06, so the header table is NOT VERIFIED. For the 3.2 x 2.5 mm oscillator, the practical option is a bare multi-footprint "7050 5032 3225 active oscillator adapter" PCB (about 15 x 8 mm, 10-packs). We found no listing with a confirmed price and ship-from in the EU, so a person must pick one on AliExpress or eBay.

Checked 2026-10-06. Everything below comes from a text mirror or from search summaries, as marked. Verifier review the same day: the mirror is datasheet **Rev. 0** (9/2016), not Rev. A.

## 1. ADXL355 I2C

### Chip level: VERIFIED (text mirror of the Analog Devices datasheet, radiolocman.com, Rev. 0)
Page numbers below are the mirror's page index (`p=`), not the printed datasheet page numbers (not matched).

| Pin | Name | Datasheet wording (mirror p=9, Table of pin functions) |
| --- | --- | --- |
| 1 | CS/SCL | "Chip Select for SPI (CS). Serial Communications Clock for I2C (SCL)." |
| 2 | SCLK/VSSIO | "Serial Communications Clock for SPI (SCLK). Connect to VSSIO for I2C (VSSIO)." |
| 3 | MOSI/SDA | "Master Output, Slave Input for SPI (MOSI). Serial Data for I2C (SDA)." |
| 4 | MISO/ASEL | "Master Input, Slave Output for SPI (MISO). Alternate I2C Address Select for I2C (ASEL)." |

(The four rows are quoted as returned by the fetch tool, which summarised the table. The one-sentence limit is exceeded in the table as a whole; treat these as pin-name wording.)

- **How I2C mode is selected** (mirror p=24): the 4-wire serial interface works in SPI or I2C and "effectively autodetects the format being used, requiring no configuration control". So there is no mode register or pin; the SPI/I2C pin list just says to tie SCLK/VSSIO to VSSIO when using I2C. The datasheet's exact rule for CS in I2C mode is not stated in the text we saw (inferred: CS/SCL is the I2C clock, so it is not tied high or low).
- **Addresses** (mirror p=25): "ASEL (pin) = 0, device address = 0x1D" and "ASEL (pin) = 1, device address = 0x53". Same result in the EngineerZone/search snippet.
- **Speed** (mirror p=25): the interface works in standard (100 kHz), fast (400 kHz), fast plus (1 MHz) and high speed (3.4 MHz) mode. **UNVERIFIED** (search snippet only, not found on mirror p=25 by the verifier): "at 400 kHz I2C the maximum output data rate is 800 Hz". It matters because the appliance pack asks for 2000 Hz (3 axes × 3 B × 2000 = 18 kB/s); confirm on the current datasheet.
- **Pull-ups:** NOT VERIFIED. The pages we could load do not state a value. The snippet says only that there are no internal pull-ups or pull-downs on unused pins. Inferred: external pull-ups on SCL/SDA are required (standard I2C), typically 2.2 to 4.7 kOhm to 3.3 V at 400 kHz. Check whether the EVAL board fits any.

### Board level (EVAL-ADXL355Z, UG-1030): NOT VERIFIED
- UG-1030 would not load: analog.com timed out three times; the mirror `www-cce.cldnet.analog.com` refused the connection; the Farnell copy `farnell.com/datasheets/2310319.pdf` timed out. Kaszti's Ctrl+F for "I2C" fails because the guide writes "I²C".
- Search summaries (not the guide itself) say the board has "2 sets of spaced vias for populating 6-pin headers", i.e. the headers may not be fitted. A header pin table (pin number to signal) was not found. Do not treat the earlier hint "CS/SCL, SCLK/VSSIO, MOSI/SDA, MISO/ASEL on the headers" as confirmed.
- **What a person checks:** open UG-1030 in a browser, search for "SCL" and "ASEL" (not "I2C"), and read the header table. Confirm four things: SCL, SDA, ASEL and VSSIO are on the headers; SCLK/VSSIO can be tied to VSSIO or GND; whether the board fits I2C pull-ups; whether J1 and J2 come unpopulated.
- If the header table lacks SCL or SDA, D-004 (I2C) fails for this board. Then the options are SPI (extra GPIOs) or another board.

## 2. 8.192 MHz oscillator on a breadboard adapter

### Oscillator facts (QST QTM325-8.192MBD-T)
- QTM325 datasheet (text extract, p.1 note [2]): pin 1 is enable: output on at logic 1 or open, off at logic 0. Pin 3 output, pin 2 GND and pin 4 VDD are the usual layout; the drawing on p.2 has no extractable text, so **check pins 2 and 4 on the drawing before wiring**.
- Mouser lists a QTM325 datasheet at `https://www.mouser.com/datasheet/2/417/QTM325-3044233.pdf` (timed out when we tried).

### Chosen: "7050 / 5032 / 3225 active oscillator adapter PCB" (multi-footprint, bare PCB)
Several shops sell the same generic board. It is a small FR4 PCB (about 15.3 x 8 mm) with pads for 7050, 5032 and 3225 oscillators and through-hole pins on 2.54 mm pitch (sizes and pins from search summaries of Sunrom/Sharvi listings; not seen on a product photo). Some listings say it carries 0805/0603 spots for a filter resistor and a decoupling capacitor: use that for a 100 nF cap at VDD.

| Source | Name | Price | Pack | Link | Note |
| --- | --- | --- | --- | --- | --- |
| Sunrom (India) | SMD Crystal 7050 5032 3225 PCB Adapter, code 5451 | Rs. 40.25 each (page, 2026-10-06; about EUR 0.40, inferred conversion) | 1 pc, 26 in stock | https://www.sunrom.com/p/smd-crystal-7050-5032-3225-pcb-adapter | Ships from India, so slow and costly to Hungary. Page lists "Pins: 2", which looks wrong for a 4-pad part; page gives no pitch. |
| eBay | 10 Pcs Active Oscillator Adapter PCB Board Converter for 7050 5032 3225 SMT | USD 8.60 + USD 8.28 shipping (search summary, not confirmed) | 10 pcs | https://www.ebay.com/p/10-Pcs-Active-Oscillator-Adapter-PCB-Board-Converter-for-7050-5032-3225-SMT-B69/2175185138 | Listing showed "currently out of stock" on 2026-10-06. Ship-from not seen. |

Fit to our part: the board lists 3225 as one of its footprints (matches 3.2 x 2.5 mm, 4 pads). Which header pins come out and how the pins map to oscillator pads was not seen. If the board follows the DIP-14/DIP-8 oscillator convention, then four pins are used (inferred, common for the can-type oscillators it replaces); check against a product photo or the pin map before use.

### Alternative: open-source DIP-14 oscillator adapter (make your own)
- matze79/DIP14-OSC-Adapter on GitHub: KiCad files, MIT licence, supports 7050, 5032 and 3225 footprints, form factor DIP-14. The Vogons thread says the designer forgot the pin 1 mark. Link: https://github.com/matze79/DIP14-OSC-Adapter; thread: https://www.vogons.org/viewtopic.php?p=1395727. Pin map and capacitor spot not read; the Gerbers would have to be ordered from a PCB house (not priced).
- Cheapest fallback (inferred, no source): dead-bug the 4-pad part on a generic SMD-to-DIP prototype pad board, or buy a ready 3.3 V 8 MHz class breakout. Not researched.

## Not found / not checked
- Later the same day the orchestrator found an AliExpress listing in search results ("Convertor Board Active Crystal Oscillator Adapter Plate … 7050 5032 3225", item 3256801612916682). The page needs a login, so its price and pinout are not confirmed.
- No EU shop with a live price was found for the adapter.
- UG-1030 header table: not found.
- ADXL355 I2C pull-up value: not found.
- QTM325 pin 2/4 assignment: not confirmed on the datasheet PDF.

## Sources (all checked 2026-10-06)
- ADXL354/ADXL355 datasheet, text mirror: https://www.radiolocman.com/datasheet/pdf.html?di=130145 (pages p=9, 24, 25). Original: https://www.analog.com/media/en/technical-documentation/data-sheets/adxl354_adxl355.pdf (timed out).
- UG-1030: https://www.analog.com/media/en/technical-documentation/user-guides/EVAL-ADXL354-355-UG-1030.pdf (not loaded).
- QST QTM325: https://www.qstproducts.com/Oscillator/QTM325.pdf (binary, not read).
