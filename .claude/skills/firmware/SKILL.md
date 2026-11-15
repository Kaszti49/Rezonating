---
name: firmware
description: Playbook for any change under firmware/ or a pack's on-device side (ESP-IDF v6 C/C++ on the ESP32-S3: drivers, acquisition, storage, trigger, engines, pack loader, build fixes, porting the hackathon fall core). Load before writing firmware code.
---

# Playbook: firmware

Read `firmware/CLAUDE.md` and `firmware/README.md` (component plan, pin map) first. Build and flash
details: the `esp-idf-build-flash` playbook. The hackathon fall detector (Arduino, reference only)
is in `firmware/hackathon-rezon/`: read its README before touching the fall engine.

## Before you start
1. Write the task's **Done when** in one or two observable lines.
2. Tier 1 components (`acquire`, `heads`, `dsp`, `trigger`, `features`, `packs`, `storage`): name
   the accepted `D-###` that allows the change. None → stop and ask; propose the decision instead.
3. Check every ESP-IDF API against the docs (`espressif-docs` MCP, else docs.espressif.com v6.0),
   never from memory: v6 renamed and split driver headers. Note the page you used.

## While you work
- Smallest change that meets Done when; match the style; no drive-by refactors.
- Count every sample: anything that can drop data increments a reported counter.
- ISRs: `IRAM_ATTR`, no blocking, no logging, no malloc; hand off to a task.
- Big buffers in PSRAM, DMA buffers in internal DMA-capable RAM. GPIO 33–37 are PSRAM.
- ADS131M0x: continuous 8.192 MHz CLKIN (LTC6903 on the Click, programmed first); cite the
  datasheet section for every register value.
- Feature maths must equal `ml/` exactly: a change names the test vectors that must change.

## Finish
- `idf.py -C firmware build` (or `eim run "idf.py -C firmware build"`). The stop gate runs it too.
- Never flash, erase or monitor a board yourself: write the exact command for the person.
- Then run the `verify` playbook.
