# rig-s3: bench recording firmware for the ESP32-S3 rig

**Bench-only.** It lets the Rezonating Lab (`tools/lab`, `rzlab serve`) record footsteps from the OTIO rig:
ESP32-S3 DevKit + ADC 15 Click (ADS131M02 + LTC6903) + two SM-24 geophones, wired as in
`hardware/case-v1/Rezon_Wiring_Guide_OTIO.html`. It is not the node firmware (`firmware/main`), and it replaces the
hackathon fall sketch on the board (that sketch can be flashed back with arduino-cli).

There is no code here: the project builds the bring-up sources in `../bringup-esp32/main` for the ESP32-S3.
`rig.h` there switches the pins, the gain, the link transport and the streams. The text report, its tags and the
sample counters are described in `../bringup-esp32/README.md`.

| | Classic bring-up (`bringup-esp32`) | This rig (`rig-s3`) |
| --- | --- | --- |
| Board | ESP32 WROOM-32, CP2102 | ESP32-S3 DevKit (CH343 on the UART port) |
| Pins | SCK 18, MISO 19, MOSI 23, CS1 17, CS2 16, DRDY 4, RST 27, HX711 | SCK 12, MISO 13, MOSI 14, CS1 11, CS2 9, DRDY 10, RST 8, no HX711 |
| ADC | 2000 SPS, gain 128 | 2000 SPS, **gain 4** (±300 mV), changeable per session from the Lab |
| Text report | UART0, stops for good when the link starts | UART0 (the **UART/COM** USB-C port), keeps running |
| Link (rzlab) | UART0, 115200, `adc_dec` only | native **USB** port (USB-Serial/JTAG, `303A:1001`), `adc_raw` 2 kSPS + `adc_dec` 1 kSPS |

`adc_raw` is what the Lab records (D-020); `adc_dec` feeds the live view. ADC channel 0 is the Click's **CH1**
screw terminal (geophone 1), channel 1 is **CH2** (geophone 2). On 2026-11-23 the two geophones read with opposite
polarity (see the daily note); the firmware sends the codes as they are.

## Build and flash

ESP-IDF v6.0 from PowerShell (idf.py refuses Git Bash):

```powershell
eim run "idf.py -C firmware/rig-s3 build"
eim run "idf.py -C firmware/rig-s3 -p COM40 flash"     # COM40 = the UART/COM port (CH343) on pc-10
```

Flashing needs a person at the board. If the flash does not start, hold BOOT, tap RST, let go of BOOT.

## Use it

1. Use **one** cable, in the native **USB** port (labelled USB or USB-OTG). It powers the board and carries the link;
   Device Manager shows it as "USB Serial Device (COMx)" (VID 303A). It can also flash the board.
   Don't plug PC cables into both ports unless you have checked the board's 5 V paths: on some S3 boards the two
   ports' 5 V lines are joined (or can be, through a solder jumper), which ties two PC ports together.
2. The text report is on the UART port (115200). To read it, move the one cable there, for example
   `idf.py -p COM40 monitor`: check `[ADC] ID ... PASS`, the `[RATE]` line (measured rate, record it) and `lost=0` on
   the `[STAT]` lines. The Lab shows the rate and the loss counters too.
3. Start the Lab on the USB port: `rzlab serve --connect serial:COMx`, then open http://127.0.0.1:8765. Live shows
   both geophones; Record writes `adc_raw` sessions and runs the walk-pass protocol (`tools/lab/README.md`).

## Not yet confirmed on the board (first run)

- The ROM print channel to USB-Serial/JTAG is switched off when the link starts (PROTOCOL.md 1, "Console").
- USB throughput: both streams together are about 20 kB/s. `win_link` in STATUS counts anything the link could
  not hand over; it should stay 0.
- The measured sample rate (LTC6903, up to 1.65 % off): read it from `[RATE]` or the Lab's rate column.
