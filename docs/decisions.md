# Decisions

Every change to a Tier 1 file needs a new entry here. Newest first. Never edit
an old entry; add a new one that replaces it.

| # | Date | Decision | Why |
| --- | --- | --- | --- |
| D-011 | 2026-10-01 | Roles (provisional): Kaszti = design and management, Viktor = code | Team of two |
| D-010 | 2026-10-01 | Plan Year 1 only. Later years are not planned until Year 1 results are in | Unknown pace |
| D-009 | 2026-10-01 | Repo on Kaszti's personal GitHub, private during development, open source later (license to be chosen) | — |
| D-008 | 2026-10-01 | Recordings: multichannel WAV (32-bit int) + JSON sidecar, schema v0. Raw recording on: continuous at ≤ 4 kSPS, event clips above | Dataset lasts all years |
| D-007 | 2026-10-01 | Integration: Home Assistant via MQTT with discovery; own app later | Free, local, no cloud |
| D-006 | 2026-10-01 | Training: own Python (scikit-learn, PyTorch) → int8 TFLite Micro | Full control |
| D-005 | 2026-10-01 | Firmware: ESP-IDF, C/C++ | Timing control, DMA, TFLite Micro |
| D-004 | 2026-10-01 | Parts: ESP32-S3 N16R8, ADS131M04 + 8.192 MHz oscillator, SM-24 geophone, ADXL355 over I2C, brass piezo discs, RJ45 head ports, USB-C, microSD | See master plan |
| D-003 | 2026-10-01 | Year 1 order: footstep-id → fall → appliance | Footstep ID is the novel core; fall shares hardware |
| D-002 | 2026-10-01 | Platform: one node, self-identifying heads, packs that declare their needs | Many applications, one hardware |
| D-001 | 2026-10-01 | Name: **Rezonating**, one name for project, brand and repo | Domains available |
