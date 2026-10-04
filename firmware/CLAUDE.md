# firmware/ — context for Claude

ESP-IDF **v6.0+** project in C (C++ only where a library needs it), target `esp32s3`
(ESP32-S3-N16R8). The component plan, build order and pin map are in `README.md` here.

## Layout
- `main/` — app entry; keep it thin (start components, nothing else).
- `components/<name>/` — one component per job (`acquire`, `heads`, `dsp`, `trigger`, `features`,
  `engines`, `packs`, `storage`, `net`, `ota`). Tier 1: `acquire`, `heads`, `dsp`, `trigger`,
  `features`, `packs`, `storage` (change only with an accepted decision).
- `sdkconfig.defaults` — the only committed config; `sdkconfig` is generated and gitignored.
- `partitions.csv` — two OTA slots + a filesystem for packs.

## Code style
- `clang-format` with `.clang-format` here (the edit hook applies it): 4 spaces, 120 columns,
  function braces on their own line.
- Public API in `components/<name>/include/<name>.h`, prefixed `rz_<name>_`. Everything else `static`.
- Functions that can fail return `esp_err_t`; `ESP_ERROR_CHECK` only during init in `main/`.
- Log with `ESP_LOGx(TAG, …)`, one `static const char *TAG = "rz_<name>";` per file. Never log in an ISR.
- Fixed-width types (`int32_t`, `uint32_t`) for samples and counters; sample counters are 64-bit.
- No dynamic allocation after init in the acquisition path; size buffers from the pack and
  allocate once (PSRAM for big ring buffers, internal DMA-capable RAM for SPI DMA buffers).
- Every place that can lose a sample increments a dropped-sample counter that gets reported.

## Commands
```bash
idf.py -C firmware build            # or: eim run "idf.py -C firmware build"
idf.py -C firmware size
```
Flashing and monitoring need a person and a board: see the `esp-idf-build-flash` skill.
