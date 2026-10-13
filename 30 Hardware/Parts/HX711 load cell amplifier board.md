---
type: part
status: have
category: adc
qty: 1
price_eur:
price_note: Came with the load cell; price unknown
supplier:
url:
datasheet:
order:
---
# HX711 load cell amplifier board

**Why we have it:** It came with the [[YZC-133 load cell 5 kg]]. It is the standard 24-bit weighing ADC (green board, HX711 chip). It is slow, 10 or 80 samples/s, so it suits checking weight but not vibration or tap timing. Those need the [[ADC 15 Click board]] at 2 kSPS.

![[HX711_board.jpg]]

## Ports (read from the photo)
- **J1, load-cell side:** E+, E−, A−, A+, B−, B+. Load cell: red → E+, black → E−, white → A−, green → A+. Leave B± open.
- **JP2, MCU side:** VCC, SCK, DT, GND. VCC 2.6–5.5 V: use 3.3 V with the ESP32. DT is the data output: it goes to an ESP32 input (can be input-only GPIO 34). SCK goes to an ESP32 output.
- Headers are not soldered yet; a loose 10-pin strip is included.
- Whether this board has a RATE jumper (10 vs 80 SPS) is not visible on the photo.

## Notes
- 2026-10-13: logged from Kaszti's photos.
