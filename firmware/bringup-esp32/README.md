# Bench bring-up (classic ESP32)

**Bench-only.** This is a small separate ESP-IDF project for the classic ESP32 bench rig (WROOM-32,
4 MB flash, no PSRAM, CP2102 USB-UART). It is not the node firmware in `firmware/main` and shares
no code with it. It checks the ADC 15 Click (ADS131M02 + LTC6903 clock) and the HX711 load-cell
board, then prints a readable report. It has no Wi-Fi. On request it switches to the link protocol on UART0 and streams
`adc_dec` to the Rezonating Lab (see [Link mode](#link-mode-uart0-115200-adc_dec-only)).

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

SPI3 (VSPI) runs at 2 MHz for the ADC and 1 MHz for the LTC6903. The ADC device uses SPI mode 1 with
`cs_ena_pretrans = 2` and `cs_ena_posttrans = 2` (row #2 of the `[DIAG]` matrix, which passed on 2026-11-01: ID
0x2205, register writes OK; the default CS timing gave a one-bit shift). The `[DIAG]` matrix only runs when the
firmware is built with `CONFIG_BRINGUP_DIAG=y` (`idf.py menuconfig` → "Rezonating bring-up"); it then uses the first
setting that passes. GPIO 12 and 6 to 11 are not used.

## What it prints (UART0, 115200 baud)

Every line starts with a tag, so `findstr "[RATE]"` or `grep '^\[STAT\]'` pulls out one kind.

| Tag | When | What |
| --- | --- | --- |
| `[BOOT]` | start | chip model, revision, cores, flash size, IDF version, pin map |
| `[DIAG]` | start, before `[LTC]` and after it, **only with `CONFIG_BRINGUP_DIAG=y`** | ADC SPI diagnostic. First a bit-banged reference (mode 1, ~125 kHz, CS by GPIO, LTC6903 also bit-banged), then one line per SPI setting (mode, SCLK, CS by SPI or GPIO, `cs_ena_pretrans`/`posttrans`, `input_delay_ns`): the ADC is reset, the raw 12 bytes of the first frame and of the RREG ID reply are printed with the decoded word, `PASS` when the first word is `0xFF22` and ID is `0x22xx`. `(=FF22>>1)` marks the one-bit shift. Last line: the setting used for the rest of the run (the first that passed), or "no SPI setting passed; keeping #0" with what the bit-bang result implies. Mode 0 rows are outside the ADC's spec and only picked if nothing else passes (with a warning) |
| `[LTC]` | start | LTC6903 word sent (`0xCF60` = OCT 12, DAC 984, CNF 00 → 8 191 507 Hz nominal, −60 ppm) |
| `[ADC]` | start | without `[DIAG]`: one `[ADC] SPI:` line with the fixed SPI setting; then the first response after reset; ID register with PASS/FAIL (`0x22xx` = ADS131M02); STATUS decoded; each register write with its ack and read-back, PASS/FAIL |
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
| `missed` | DRDY edges whose data were never read (reader too late): **lost samples**. The ADC's FIFO holds two samples per channel, so a late reader reads both and counts the rest (pending − 2) here | 0 |
| `spi_err` | SPI reads that failed: **lost samples** | 0 |
| `crc_err` | output CRC (CCITT, seed FFFFh) did not match: sample kept but suspect | 0 |
| `no_drdy_flag` | STATUS showed no new data on a read. Can rise by one after a resync: the ADC sends a narrow DRDY pulse after the first of two queued frames (SBAS853A 8.5.1.9.1), and if the ESP32 catches it, the next read finds no new data | 0 |
| `drdy_timeouts` | 100 ms with no DRDY at all | 0 |
| `adc_resets` | STATUS RESET bit set again (the ADC reset itself, e.g. supply dip) | 0 |
| `resyncs` | times the reader was late (more than one DRDY pending) and read both FIFO frames | 0 |
| `unaccounted` | edges − frames − missed − spi_err | 0 or 1 |
| `hx_reads`, `hx_bad`, `hx_timeouts` | HX711 good reads, reads where DT was not high after the 25th pulse, 1 s with no conversion | bad and timeouts 0 |

## Reading the result

- **Shorted channel:** mean near 0 µV (offset of a few µV is normal), `ac_rms` is the noise floor.
- **Load cell on the Click (way B):** press the cell and watch `mean` move on one channel. That channel's
  number tells which screw terminal is which. The firmware assumes screw **CH1 = ADC ch0** and **CH2 = ch1**;
  the line labels say `ch0(screw CH1)` until a press confirms it.
- **Input range on this rig:** at gain 128 each ADS131M02 input must stay between AGND − 1.3 V and
  AVDD − 1.8 V (≈ 1.5 V at 3.3 V). The bench guide wires the cell for that: red (E+) → **680 Ω** → 3V3,
  black (E−) → GND, green (S+) → CH1 +, white (S−) → CH1 −, and CH2 + and − joined to GND (noise-floor
  channel). With the cell's E+/E− resistance of about 1070–1120 Ω the bridge gets about 2.0 V
  (3.3 V × R_ex / (R_ex + 680 Ω)), so green and white sit near 1.0 V, inside the limit. The signal is then
  about 0.4 mV per kg (1.0 mV/V, shop listing) plus up to ±0.2 mV zero offset, well inside the ±9.375 mV
  full scale. These are calculated, not measured: check with the multimeter (about 2.0 V red to black;
  green and white each about 1.0 V to GND, never above 1.5 V) before trusting the numbers. Straight from
  3.3 V without the resistor the outputs would sit at about 1.65 V, outside the limit.
- **Load cell on the HX711 (way A):** the HX711 column moves on a press; the Click channels then show
  whatever is on their terminals (open inputs can drift or clip).
- **No HX711:** one `[HX] HX711 not found` line, then `hx711 absent` on each `[STAT]` line.

## Link mode (UART0, 115200, adc_dec only)

The board boots into the text report above. When a valid link protocol v0 `GET_INFO` frame (preceded by the PC's
`0x00`) arrives on UART0, it switches to link mode **for good, until the next reboot**: all text stops (the text
report, `ESP_LOG` at level NONE with a null vprintf, and the ROM print channels 1 and 2 disconnected), then it
answers as `tools/lab/PROTOCOL.md` section 1 says: one `0x00`, `HELLO` seq 0, `CONFIG` seq 1, then `STATUS` every
`status.period_ms`. Text printed before the switch is harmless: the `0x00` separates it from `HELLO`. To get the
text report back, press EN/RESET or send `REBOOT`.

Run the Lab on the PC with the board on COM5 (close any `idf.py monitor` first: only one program can open the port):

```powershell
rzlab serve --connect serial:COM5        # browser UI at http://127.0.0.1:8765, adc_dec live
rzlab tail --serial COM5 --streams adc_dec   # terminal: loss and rates every second
```

`rzlab tail` without `--streams` asks for all three streams; this firmware has only `adc_dec`, so it answers
`ERR 4` (bad stream mask). The PC opens the port with DTR and RTS de-asserted, so the CP2102's auto-reset circuit
does not reset the board (`tools/lab/src/rezonating_lab/link/transport_serial.py`).

**The stream.** `adc_dec` (id 1, 2 channels, nominal 1000 Hz, 24 bits, clock 0 = LTC6903, `fir_taps` 63,
`fir_delay` 31): the D-016 63-tap FIR on the 2 kSPS ADC samples, keeping the output after every odd raw sample
(`main/rz_decim.c`, a port of `rezonating_ml.dsp.Decimator2` + `to_adc_dec_codes`, compiled with
`-ffp-contract=off`). Index k is the output after raw sample 2k + 1, and its `t_dev_us` is that raw sample's DRDY
interrupt time. Index 0 is the first DRDY after `START`; the FIR history starts at zeros. A lost raw sample (missed
DRDY, failed SPI read) holds the previous good value inside the FIR, and every output whose 63-sample window holds it
is not sent and counts in `device_dropped` (and `win_device`). Values are rounded half away from zero and saturated
to 24 bits. CONFIG reports gain 128 on both channels and `scale = 1.2 V / gain / 2^23` (units V).

**What differs from PROTOCOL.md's USB row** (the contract is unchanged; this is a bench variant):

| PROTOCOL.md (node, USB) | This bench firmware |
| --- | --- |
| ESP32-S3 USB-Serial/JTAG, baud ignored | Classic ESP32 UART0 through a CP2102 at **115200 8N1** (the baud rate matters) |
| Streams `adc_raw`, `adc_dec`, `accel` | **`adc_dec` only** (`adc_raw` needs 16 kB/s, more than 115200 baud carries). A START/STOP/SD_RECORD mask other than `0x02` gets `ERR 4` |
| Heads in HELLO | `n_heads` 0 (no head descriptors on the bench rig) |
| SET keys of section 5 | `adc.gain.0`, `adc.gain.1` (ERR 5 while acquiring; the ADC must acknowledge the GAIN1 write within 100 ms, else ERR 5 and the old gain stays) and `status.period_ms`. Every other key, `sim.*` included, gets `ERR 3` |
| SD_RECORD | start: `ERR 7` (no SD card); stop: ACK |
| LOG and EVENT frames | none |
| Two send queues, DATA in ~10 s of PSRAM | One link task writes everything, control frames first; DATA waits in a 64-packet queue in internal RAM (2.56 s; no PSRAM) |
| STATUS `temp_c_x10`, `sd_state`, `rssi_dbm` | 0 (no supported die temperature sensor on the classic ESP32, no SD, no Wi-Fi) |
| Text before a session | the whole text report (any length) until `GET_INFO` |
| Port closed: unwritten DATA counts in `win_link` | the UART always clocks bytes out, so DATA sent while no PC listens is lost on the PC side (host gap) until the 5 s liveness timeout ends the session |

Session rules that are the same: a session starts only with `GET_INFO` (other frames before it are ignored, AUTH
inside a session is ignored), a later `GET_INFO` re-sends `HELLO` + `CONFIG` with seq reset and no `0x00`,
`STOP` freezes `win_end`, closes the open packet, sends the queued DATA, then the final `STATUS` (running 0) and then
the ACK; a session ends after 5 s without a valid PC frame (implicit STOP without drain; queued and open packets count
in `win_link`); unknown command `ERR 1`, short payload `ERR 2`, bad CRC no reply.

**STATUS counters** (`adc_dec`, PROTOCOL.md 4.4): `produced` = next index; `device_dropped` = indices lost in
acquisition (FIR window rule); `rate_mhz` = indices per second × 1000 over the last 10 s, from the DRDY times of the
outputs (one point every 500 ms; 0 for the first 0.2 s); `clipped` = sent frames with a channel at a 24-bit limit;
`win_first`/`win_end`/`win_device`/`win_link` = the sending window; `win_link` counts packets the ADC task could not
put in the DATA queue (full), UART write errors, and the queue and open packet thrown away at session end;
`queue_fill` = DATA queue fill in %; `heap_free` = free internal heap.

A frame read whose STATUS word shows no new data (DRDY0/DRDY1 clear: the narrow DRDY pulse after the first of two
queued frames, SBAS853A 8.5.1.9.1) is not a sample interval and gets no index; in the text report it is still counted
in `no_drdy_flag`.

**Throughput at 115200 8N1** (11 520 B/s):

| Frame | Wire size | Rate | B/s |
| --- | --- | --- | --- |
| DATA, 40 frames × 2 ch | payload 20 + 320 = 340 B, raw 346 B, COBS ≤ 346 + ⌈346/254⌉ = 348 B, + `0x00` = 349 B | 25/s at 1000 Hz; 25.4/s at +1.65 % (LTC6903 worst case) | 8 725; 8 869 worst |
| STATUS, 1 stream | payload 22 + 58 = 80 B, raw 86 B, ≤ 88 B on the wire | 1/s (5/s at the minimum 200 ms period) | 88 (440) |
| PONG | 16 B payload, ≤ 24 B on the wire | ~1/s | 24 |

Nominal total ≈ 8 840 B/s = 77 % of the line; worst case (LTC6903 +1.65 %, STATUS every 200 ms) ≈ 9 330 B/s = 81 %,
so at least 19 % margin. Measured today the raw rate is 1995.80 Hz (`adc_dec` ≈ 997.9 Hz, ≈ 8 710 B/s of DATA).

**The UART can't block the DRDY reader.** The ADC task (core 1, priority 10) runs the FIR and puts each full
40-frame packet into the DATA queue with a zero timeout; when the queue is full the packet's frames are added to
`win_link`, never waited for. Only the link task (core 0, priority 6) writes UART0, through the driver's 2 kB TX ring,
and it queues DATA only while fewer than 512 B wait there, so a control frame (ACK, PONG, STATUS) waits at most about
75 ms behind DATA.

**Host test.** `main/rz_link.c` (CRC, COBS, frame encoders, receiver, SET parser) and `main/rz_decim.c` are portable C
and are checked on the PC against the shared vectors:

```powershell
python firmware\bringup-esp32\test_host\run_host_tests.py
```

It generates `test_host/build/vectors_gen.h` from `tools/lab/tests/vectors/link-v0.json` and
`ml/tests/vectors/decimator_fir.json`, compiles with MSVC (Visual Studio 2022 C++ tools; or set `CC` to gcc/clang)
and expects every link case byte-exact and the decimator within the vector file's tolerance (it is bit-exact: 2000 of
2000 outputs and codes).

## Build, flash, monitor (PowerShell)

ESP-IDF v6.0 is installed through EIM. Run these from the repo root in PowerShell. idf.py refuses
to run under Git Bash/MSYS; if you start PowerShell from Git Bash, run `Remove-Item Env:MSYSTEM` first.

```powershell
eim run "idf.py -C firmware\bringup-esp32 set-target esp32"   # once; also creates sdkconfig
eim run "idf.py -C firmware\bringup-esp32 build"
eim run "idf.py -C firmware\bringup-esp32 -p COM22 flash monitor"
```

On a PC where `eim` is not on PATH, load the IDF profile script EIM wrote instead (it also builds with
ESP-IDF v6.1-beta1), for example on desktop-o8pjtu7, where the board is COM5:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item Env:MSYSTEM -ErrorAction SilentlyContinue; . 'C:\Espressif\tools\Microsoft.v6.1-beta1.PowerShell_profile.ps1'; idf.py -C firmware\bringup-esp32 -p COM5 flash monitor"
```

Leave the monitor with `Ctrl+]`. If flashing does not connect, hold BOOT, tap EN/RESET, release BOOT.
`build/`, `sdkconfig` and `sdkconfig.old` are generated and gitignored; only `sdkconfig.defaults` is committed.

## Sources

- ADS131M02 datasheet, TI SBAS853A: register map 8.6 (ID 8.6.1, STATUS 8.6.2, MODE 8.6.3, CLOCK 8.6.4,
  GAIN1 8.6.5), frames 8.5.1.7, commands 8.5.1.10, CRC 8.3.12, reset 8.4.1.2, data after a pause 8.5.1.9.1;
  SPI interface 8.5.1 and timing 6.6, 6.7, Figure 6-1 (for `[DIAG]`).
- ESP-IDF v6.1-beta1 SPI master on the ESP32 (for `[DIAG]`): `esp_hal_gpspi/spi_hal_iram.c`
  (`spi_hal_cal_timing`, `spi_hal_setup_trans`: half-cycle MISO delay in mode 1 when `input_delay_ns` is small),
  `esp_driver_spi/src/gpspi/spi_master.c` (`spi_bus_add_device`: `cs_ena_pretrans` does nothing in full duplex).
- LTC6903 datasheet (69034fe): serial port bitmap Table 3, output configuration Table 2, frequency equation.
- Link mode: `tools/lab/PROTOCOL.md` (D-018) and its vectors `tools/lab/tests/vectors/link-v0.json`; the simulator
  `tools/lab/src/rezonating_lab/sim/node.py` for the session and error rules; D-016 FIR from
  `ml/src/rezonating_ml/dsp.py` and `ml/tests/vectors/decimator_fir.json`. ESP-IDF v6.1-beta1 headers:
  `esp_driver_uart/include/driver/uart.h` (`uart_driver_install`, `uart_read_bytes`, `uart_write_bytes`,
  `uart_get_tx_buffer_free_size`, `uart_wait_tx_done`), `esp_rom/include/esp_rom_sys.h`
  (`esp_rom_install_channel_putc`, NULL disconnects a channel), `log/include/esp_log_write.h` (`esp_log_set_vprintf`),
  `esp_hw_support/include/esp_mac.h` (`esp_read_mac`). ADS131M02 WREG acknowledgement 8.5.1.10.8, GAIN1 8.6.5.
- Hardware notes: `30 Hardware/Parts/ADC 15 Click board.md`, `HX711 load cell amplifier board.md`,
  `YZC-133 load cell 5 kg.md`; load-cell wiring (680 Ω, CH1, CH2 to GND):
  [First rig bench guide](https://claude.ai/code/artifact/53c286fe-182d-4bf3-91f6-4778f18e5648), "Way B".
