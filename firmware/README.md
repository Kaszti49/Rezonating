# Firmware

ESP-IDF (v5.3+) project for the ESP32-S3 node, in C/C++.

```bash
idf.py set-target esp32s3
idf.py build flash monitor
```

First flash prints flash and PSRAM size. If it says PSRAM is missing, the
board is not an N16R8 variant.

## Planned components (`components/`)

| Component | Job | Tier |
| --- | --- | --- |
| `acquire` | ADS131M04 driver: DRDY interrupt → SPI DMA → timestamped frames in a PSRAM ring buffer; counts dropped samples | 1 |
| `heads` | Read head EEPROMs through the I2C mux at boot | 1 |
| `dsp` | High-pass, low-pass, decimate, per pack | 1 |
| `trigger` | STA/LTA, threshold, periodic | 1 |
| `features` | Same maths as `ml/` features, checked by test vectors | 1 |
| `engines` | classifier (TFLite Micro), anomaly, rule | 2 |
| `packs` | Load and validate `pack.json`, enable packs whose heads are present | 1 |
| `storage` | WAV + sidecar writer on microSD | 1 |
| `net` | Wi-Fi, MQTT, Home Assistant discovery | 2 |
| `ota` | Firmware and pack updates | 2 |

Build order for Year 1: `acquire` → `storage` (record real data early) →
`trigger` → `features` → `engines` → `net`.

## Pin map, first rig (draft v0)

| Signal | ESP32-S3 GPIO | ADS131M04 pin |
| --- | --- | --- |
| SCLK | 12 | SCLK |
| MOSI | 11 | DIN |
| MISO | 13 | DOUT |
| CS | 10 | CS |
| DRDY | 9 | DRDY |
| RESET / SYNC | 8 | SYNC/RESET |
| — | — | CLKIN ← 8.192 MHz oscillator |

GPIO 35, 36 and 37 are used by the octal PSRAM: never assign them.
