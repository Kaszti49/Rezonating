---
name: esp-idf-build-flash
description: Build, size-check, flash and monitor the Rezonating ESP32-S3 firmware with ESP-IDF v6 (idf.py, eim, the esp-idf MCP server), and read build errors. Use when building or debugging firmware/ or when a person asks how to flash a board.
---

# ESP-IDF build and flash

Project: `firmware/` · target `esp32s3` (set in `sdkconfig.defaults`) · ESP-IDF **v6.0+**.

## Find ESP-IDF on this machine
1. Activated shell (ESP-IDF PowerShell / terminal): `IDF_PATH` is set and `idf.py` works.
2. Otherwise the ESP-IDF Installation Manager: `eim run "<command>"` runs one command inside
   the IDF environment. `eim list` shows installed versions.
3. Neither: report "ESP-IDF not installed here" and stop; never install toolchains yourself.

## Build (safe, run freely)
```bash
idf.py -C firmware build                        # or: eim run "idf.py -C firmware build"
idf.py -C firmware size                         # flash/RAM use per section
idf.py -C firmware size-components              # who uses the memory
```
- First build takes minutes; later builds are incremental. Build output lives in `firmware/build/`
  (gitignored). `firmware/sdkconfig` is generated from `sdkconfig.defaults`: change defaults,
  never commit `sdkconfig`.
- After changing `sdkconfig.defaults` or the partition table: `idf.py -C firmware fullclean`, then build.
- The `esp-idf` MCP server (when connected) offers `build_project`, `set_target`, `clean_project`
  and `flash_project`; prefer it over shell commands when it's available.

## Reading build errors
- Read the **first** `error:` line, not the last: later errors are usually consequences.
- `fatal error: driver/xxx.h: No such file` → peripheral drivers live in their own components
  (e.g. `esp_driver_gpio`, `esp_driver_spi`) and the old umbrella `driver` component doesn't pull
  them in on v6: add the component to `REQUIRES`/`PRIV_REQUIRES` in that component's
  `CMakeLists.txt`. Confirm the exact name in the v6 migration guide.
- `undefined reference` → missing `REQUIRES`, or a source file not listed in `idf_component_register`.
- `region 'iram0_0_seg' overflowed` → too much `IRAM_ATTR`; keep only ISRs and their callees there.

## Flash and monitor (needs a person and a board — never run these yourself)
Write the commands into your report for a person to run:
```bash
idf.py -C firmware -p COM5 flash monitor        # Windows: COMx from Device Manager
eim run "idf.py -C firmware -p COM5 flash monitor"
```
Exit the monitor with `Ctrl+]`. If flashing fails to connect: hold BOOT, tap RESET, release BOOT.
First boot prints flash size and PSRAM size; no PSRAM means the board isn't an N16R8.

## Board facts
- ESP32-S3-N16R8: 16 MB flash, 8 MB **octal** PSRAM (GPIO 35–37 reserved).
- USB: the DevKit's "USB" port is the native USB-Serial/JTAG; the "UART" port goes through a USB-UART chip.
  Either works for flashing; logs default to UART0.
