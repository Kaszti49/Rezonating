---
type: handoff
updated: 2026-10-06
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-10-06)
- **Company PC (pc-10) is ready** ([[Workstations]]): Python 3.12, ruff, `ml[dev,export]`, ESP-IDF v6.0 (`firmware/` builds from PowerShell), hooks and tests pass. The esp-idf MCP server connects.
- **Prototype changed (Kaszti + boss):** no breadboard; boards are wired directly. ADC = [[ADC 15 Click board]] (ADS131M02, 2 channels, LTC6903 clock) from Farnell, [[D-015 Prototype ADC on ADC 15 Click]] accepted. The ADC records at 2 kSPS, FIR + decimation to 1 kSPS ([[D-016 ADC records at 2 kSPS]], proposed); ADXL355 on I²C at 2000 Hz. The ADS131M04 returns on our PCB. Oscillator, breadboard kit, microSD breakout and card are already in the lab (`have`). The TSSOP and oscillator adapters are not needed (in `00 Inbox`).
- **LTC6903 clock is only 0.5 % typ accurate (1.1 % max at 25 °C, up to 1.65 % over temperature):** the firmware must measure the real sample rate (count DRDY against the ESP32 timer) and record it (sidecar field still to add).
- **ORD-001 not placed yet.** Remaining lines: ESP32-S3 boards, ADC 15 Click (Farnell, price/stock to check, buy 2 if possible), 2 × SM-24, EVAL-ADXL355Z, passives, flux pen.
- **Study library:** https://claude.ai/artifact/RNLzHhbCq3iyigThGJJnCC = the guide (`docs/study-guide.html`, unchanged apart from a library link bar) + chapters A1 (ADC 15 Click) and A2 (2 kSPS, ADXL355 at 2000 Hz) in `docs/study-library/`. New material goes in new chapter pages; don't edit the guide's content.
- Earlier the same day: kill test dropped, dates recounted on Mon/Tue, CLAUDE.md rules for vision changes and work days.

## Next up
| Who | What |
| --- | --- |
| Kaszti | Accept D-016; place [[ORD-001 First rig]] at Farnell (D-015 accepted, ADXL355 I²C confirmed) |
| Kaszti + Viktor | Study guide + chapters A1 and A2; the open questions below |
| Viktor | [[FootprintID dataset loader]] (2026-10-20); [[Wire the first rig]] once parts arrive |
| Claude | [[Run the first agent eval baseline]]; [[Check pin map against ADS131M04 datasheet]] (now: Click + ADXL355 + microSD, no GPIO 33–37) |

## Open questions
- Accept or reject [[D-016 ADC records at 2 kSPS]] in Obsidian (Kaszti chose 2 kSPS in chat).
- The measured sample rate needs a field in the sidecar schema (`sample_rate` is one integer today): Tier 1, needs a decision.
- Which stream goes to the microSD: 2 kSPS raw or 1 kSPS decimated?
- License for open source (backlog); which GPU the home desktop has.

## Open flags
- F-261006-646c (note): the researcher may only write in `60 Research`; part-note edits go through vault-keeper or the main session. For `/retro` on 2026-10-13.

## Watch out
- `idf.py` refuses Git Bash (MSYS); build from PowerShell or the EIM shortcut.
- Git Bash on pc-10 sometimes crashes at start-up ("add_item … errno 1") while agents run; retry.
- Hooks call `python`: Python must be on PATH on every machine.
- Due dates Claude set are proposals; adjust freely.
