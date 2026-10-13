---
type: part
status: have
category: mcu
qty: 1
price_eur:
price_note: Already in the lab; price unknown
supplier:
url:
datasheet:
order:
---
# ESP32 DevKit V1 with expansion board

**Why we have it:** The board in the lab on 2026-10-13, used for the bench rig in [First rig bench guide](https://claude.ai/code/artifact/53c286fe-182d-4bf3-91f6-4778f18e5648). It is a **classic ESP32** (ESP-WROOM-32 class module, CP2102 USB-to-serial, AMS1117 3.3 V regulator, micro-USB, EN and BOOT buttons), **not** the planned [[ESP32-S3-DEV-N16R8 board]]: no octal PSRAM, no native USB, ESP-IDF target `esp32` instead of `esp32s3`.

![[ESP32_board_left.jpg]]
![[ESP32_board_right.jpg]]

## Ports (read from the photos)
**DevKit, 30 pins.**
- Left column, top to bottom: EN, VP (GPIO 36), VN (GPIO 39), D34, D35, D32, D33, D25, D26, D27, D14, D12, D13, GND, VIN.
- Right column, top to bottom: D23, D22, TX0, RX0, D21, D19, D18, D5, TX2 (D17), RX2 (D16), D4, D2, D15, GND, 3V3.

**Expansion board.**
- Each GPIO has a row of 3 pins (signal, V, G). Which column is which isn't checked: confirm with a multimeter.
- Left side: EN … D13. Right side: D23 … D15, with TX2/RX2 printed as D17/D16.
- A 4-pin header: D22, D21, VCC, GND. That is the I²C header (D21 = SDA, D22 = SCL).
- A GND/5V/3.3V power block.
- A **5V / 3.3V jumper** that sets the voltage on the V pins. Keep it on **3.3V**.
- Power: USB-C (USB5V), micro-USB and a DC barrel jack. The DevKit's own micro-USB is the programming port.

## Pin rules for this chip (classic ESP32)
- GPIO 34, 35, 36 (VP) and 39 (VN) are input only and have no pull-ups.
- Strapping pins: 0, 2, 5, 12 and 15. **GPIO 12 must be low at boot**, or the board fails to start; never put a pull-up (e.g. an SD card's) on it.
- GPIO 6–11 belong to the flash and are not brought out.
- GPIO 16 and 17 are free on a WROOM module; on a WROVER module they belong to the PSRAM.
- Default buses: VSPI = SCK 18, MISO 19, MOSI 23, CS 5. I²C = SDA 21, SCL 22.

## Notes
- 2026-10-13: logged from Kaszti's photos. Qty 1 seen; a second board not seen.
- 2026-10-13: plugged in with the bench wiring attached. Shows as COM22 (CP210x, VID 10C4:EA60). Boot log: classic ESP32, chip revision 3, module **WROOM-32** (so D16/D17 are free), 4 MB flash, DIO 40 MHz. Ships with Espressif's factory AT firmware 2.4.0. It boots normally with the wiring attached. Only the micro-USB on the DevKit itself carries data.
