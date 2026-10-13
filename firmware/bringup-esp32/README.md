# Bench bring-up (classic ESP32)

**Bench-only.** This is a small separate ESP-IDF project for the classic ESP32 bench rig (WROOM-32,
4 MB flash, no PSRAM, CP2102 USB-UART). It is not the node firmware in `firmware/main` and shares
no code with it. It checks the ADC 15 Click (ADS131M02 + LTC6903 clock) and the HX711 load-cell
board, then prints a readable report. It has no Wi-Fi and no link protocol.

## Pin map (as wired on 2026-10-13)

| Signal | ESP32 GPIO | Board pin |
| --- | --- | --- |
| SPI SCK | 18 | Click SCK |
| SPI MISO | 19 | Click SDO (ADC DOUT) |
| SPI MOSI | 23 | Click SDI (ADC DIN, LTC6903 SDI) |
| ADC chip select | 17 | Click CS1 (SPI mode 1) |
| LTC6903 chip select | 16 | Click CS2 / mikroBUS PWM (SPI mode 0) |
| DRDY | 4 | Click INT (active low) |
| ADC reset | 27 | Click RST (SYNC/RESET, active low) |
| HX711 DT | 34 | HX711 DT (input-only pin) |
| HX711 SCK | 32 | HX711 SCK |

SPI3 (VSPI) runs at 2 MHz for the ADC and 1 MHz for the LTC6903. GPIO 12 and 6 to 11 are not used.

## What it prints (UART0, 115200 baud)

Every line starts with a tag, so `findstr "[RATE]"` or `grep '^\[STAT\]'` pulls out one kind.

| Tag | When | What |
| --- | --- | --- |
| `[BOOT]` | start | chip model, revision, cores, flash size, IDF version, pin map |
| `[LTC]` | start | LTC6903 word sent (`0xCF60` = OCT 12, DAC 984, CNF 00 → 8 191 507 Hz nominal, −60 ppm) |
| `[ADC]` | start | first response after reset; ID register with PASS/FAIL (`0x22xx` = ADS131M02); STATUS decoded; each register write with its ack and read-back, PASS/FAIL |
| `[RATE]` | after ~12 s | DRDY falling edges counted for 10 s against `esp_timer`: measured Hz, % off 2000 Hz, implied CLKIN |
| `[HX]` | after `[RATE]` | `HX711 found` with its conversion period (10 or 80 SPS), or one `HX711 not found: <reason>` line |
| `[STAT]` | every second | per ADC channel: mean, RMS, AC RMS (noise about the mean) in µV input-referred; min/max raw codes; `clip` count and `CLIPPING` if codes hit full scale; `lost` samples this second; HX711 reading count, last and mean raw value |
| `[CNT]` | every 10 s | cumulative counters (below) |

ADC settings: 24-bit words, 2000 SPS (OSR 2048, high-resolution mode, 8.192 MHz CLKIN), **gain 128 on
both channels** (full scale ±9375 µV, 1 LSB ≈ 0.0011 µV), DRDY as a level output.

### Counters (count every sample)

| Counter | Meaning | Normal |
| --- | --- | --- |
| `drdy_edges` | DRDY falling edges seen by the GPIO4 interrupt | about 2000 per second |
| `frames` | frames read successfully | = drdy_edges |
| `missed` | DRDY edges whose data were never read (reader too late): **lost samples** | 0 |
| `spi_err` | SPI reads that failed: **lost samples** | 0 |
| `crc_err` | output CRC (CCITT, seed FFFFh) did not match: sample kept but suspect | 0 |
| `no_drdy_flag` | STATUS showed no new data on a read | 0 |
| `drdy_timeouts` | 100 ms with no DRDY at all | 0 |
| `adc_resets` | STATUS RESET bit set again (the ADC reset itself, e.g. supply dip) | 0 |
| `unaccounted` | edges − frames − missed − spi_err | 0 or 1 |
| `hx_reads`, `hx_bad`, `hx_timeouts` | HX711 good reads, reads where DT was not high after the 25th pulse, 1 s with no conversion | bad and timeouts 0 |

## Reading the result

- **Shorted channel:** mean near 0 µV (offset of a few µV is normal), `ac_rms` is the noise floor.
- **Load cell on the Click (way B):** press the cell and watch `mean` move on one channel. That channel's
  number tells which screw terminal is which. The firmware assumes screw **CH1 = ADC ch0** and **CH2 = ch1**;
  the line labels say `ch0(screw CH1)` until a press confirms it. Note: at gain 128 the ADS131M02 only
  accepts inputs between AGND − 1.3 V and AVDD − 1.8 V (≈ 1.5 V). A bridge fed from 3.3 V sits at about 1.65 V
  common mode, just above that limit, so readings may be distorted. Feed the bridge from a lower voltage, or
  use a lower gain (gains 1 to 4 allow inputs up to AVDD), before trusting the numbers.
- **Load cell on the HX711 (way A):** the HX711 column moves on a press; the Click channels then show
  whatever is on their terminals (open inputs can drift or clip).
- **No HX711:** one `[HX] HX711 not found` line, then `hx711 absent` on each `[STAT]` line.

## Build, flash, monitor (PowerShell)

ESP-IDF v6.0 is installed through EIM. Run these from the repo root in PowerShell. idf.py refuses
to run under Git Bash/MSYS; if you start PowerShell from Git Bash, run `Remove-Item Env:MSYSTEM` first.

```powershell
eim run "idf.py -C firmware\bringup-esp32 set-target esp32"   # once; also creates sdkconfig
eim run "idf.py -C firmware\bringup-esp32 build"
eim run "idf.py -C firmware\bringup-esp32 -p COM22 flash monitor"
```

Leave the monitor with `Ctrl+]`. If flashing does not connect, hold BOOT, tap EN/RESET, release BOOT.
`build/`, `sdkconfig` and `sdkconfig.old` are generated and gitignored; only `sdkconfig.defaults` is committed.

## Sources

- ADS131M02 datasheet, TI SBAS853A: register map 8.6 (ID 8.6.1, STATUS 8.6.2, MODE 8.6.3, CLOCK 8.6.4,
  GAIN1 8.6.5), frames 8.5.1.7, commands 8.5.1.10, CRC 8.3.12, reset 8.4.1.2, data after a pause 8.5.1.9.1.
- LTC6903 datasheet (69034fe): serial port bitmap Table 3, output configuration Table 2, frequency equation.
- Hardware notes: `30 Hardware/Parts/ADC 15 Click board.md`, `HX711 load cell amplifier board.md`,
  `YZC-133 load cell 5 kg.md`.
