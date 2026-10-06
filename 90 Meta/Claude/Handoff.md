---
type: handoff
updated: 2026-10-06
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-10-06)
- **Company PC (pc-10) is ready** ([[Workstations]]): Python 3.12, ruff, `ml[dev,export]`, ESP-IDF v6.0 (`firmware/` builds from PowerShell), hooks and tests pass. The esp-idf MCP server connects.
- **Prototype changed (Kaszti + boss):** no breadboard; boards are wired directly. ADC = [[ADC 15 Click board]] (ADS131M02, 2 channels, LTC6903 clock) from Farnell, proposed as [[D-015 Prototype ADC on ADC 15 Click]] (accept in Obsidian). The ADS131M04 returns on our PCB. Oscillator, breadboard kit, microSD breakout and card are already in the lab (`have`). The TSSOP and oscillator adapters are not needed (in `00 Inbox`).
- **LTC6903 clock is only 0.5 % typ / 1.1 % max accurate:** the firmware must measure the real sample rate (count DRDY against the ESP32 timer) and write it to the sidecar.
- **ORD-001 not placed yet.** Remaining lines: ESP32-S3 boards, ADC 15 Click (Farnell, price/stock to check, buy 2 if possible), 2 × SM-24, EVAL-ADXL355Z, passives, flux pen.
- **Study library:** https://claude.ai/artifact/RNLzHhbCq3iyigThGJJnCC = the guide (`docs/study-guide.html`, unchanged apart from a library link bar) + chapter A1 (`docs/study-library/adc15-click.html`). New material goes in new chapter pages; don't edit the guide's content.
- Earlier the same day: kill test dropped, dates recounted on Mon/Tue, CLAUDE.md rules for vision changes and work days.

## Next up
| Who | What |
| --- | --- |
| Kaszti | Accept or reject D-015; check the EVAL-ADXL355Z header table in UG-1030 (search "SCL"/"ASEL"); place [[ORD-001 First rig]] at Farnell |
| Kaszti + Viktor | Study guide + chapter A1; the design questions below |
| Viktor | [[FootprintID dataset loader]] (2026-10-20); [[Wire the first rig]] once parts arrive |
| Claude | [[Run the first agent eval baseline]]; [[Check pin map against ADS131M04 datasheet]] (now: Click + ADXL355 + microSD, no GPIO 33–37) |

## Open questions (F-261006-a681)
- ADC anti-aliasing at 1 kSPS: the sinc filter gives only −4.4 dB at Nyquist; proposal: record at 4 kSPS and decimate with an FIR in firmware (changes the footstep pack's rate).
- ADXL355 at 2000 Hz over I²C: does it fit (1 MHz / 3.4 MHz bus), or lower the ODR, or SPI?
- CLAUDE.md says PSRAM takes GPIO 35–37; the datasheet says 33–37. Fixing CLAUDE.md needs a person's OK.
- License for open source (backlog); which GPU the home desktop has.

## Open flags
- F-261006-a681 (L4, team): the questions above.
- F-261006-646c (note): the researcher may only write in `60 Research`; part-note edits go through vault-keeper or the main session. For `/retro` on 2026-10-13.

## Watch out
- `idf.py` refuses Git Bash (MSYS); build from PowerShell or the EIM shortcut.
- Git Bash on pc-10 sometimes crashes at start-up ("add_item … errno 1") while agents run; retry.
- Hooks call `python`: Python must be on PATH on every machine.
- Due dates Claude set are proposals; adjust freely.
