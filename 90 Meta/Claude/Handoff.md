---
type: handoff
updated: 2026-10-12
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-10-12)
- **Rezonating Lab started** ([[D-017 Rezonating Lab bench tool]], accepted). It is a local web app in `tools/lab/` (FastAPI + Svelte) for live data, recording, labelling, the pack bench and experiments. **Copy-paste prompts for every remaining phase: [[Lab build prompts]].**
- **Phase 1 done** (commit `734b59b`):
  - link protocol spec `tools/lab/PROTOCOL.md` ([[D-018 Node link protocol v0]], accepted);
  - codec, 56 golden vectors, loss accounting;
  - simulator `rzlab sim` and the connection test `rzlab tail`;
  - 280 tests, verifier PASS.
  - **No browser UI yet:** that is phase 2 ([[Lab 2 Live and Device pages]], due 2026-10-27).
- **Sidecar schema v1** ([[D-019 Sidecar v1]], accepted): measured rate, loss counters, stream, clock, label sample indices. v0 files stay valid.
- [[D-020 Recordings keep the 2 kSPS ADC stream]] is proposed. Kaszti chose `adc_raw` in chat.
- Hardware is unchanged since 2026-10-06: ADC 15 Click (ADS131M02) at 2 kSPS, ADXL355 on I²C at 2000 Hz. **[[ORD-001 First rig]] is still not placed, and there are no ESP32 boards yet.**

## Next up
| Who | What |
| --- | --- |
| Kaszti | Accept or reject D-020 (and D-016 if still open); place ORD-001 |
| Claude | Lab phase 2: paste the phase 2 prompt from [[Lab build prompts]] |
| Viktor | [[FootprintID dataset loader]] (2026-10-20); STA/LTA by 2026-11-03 (the pack bench needs it) |

## Open questions
- Push to GitHub: commits up to `f654b7b` and later are local only; nobody has said to push.
- License for open source (backlog); which GPU the home desktop has.

## Watch out
- Git Bash on pc-10 has no coreutils or python on PATH. Use full paths: Python `C:\Users\benedek.kaszti\AppData\Local\Programs\Python\Python312\python.exe`, git `C:\Program Files\Git\cmd\git.exe`. Or use PowerShell.
- `idf.py` refuses Git Bash (MSYS); build from PowerShell or the EIM shortcut.
- Accepted decisions are hook-locked. To change one, propose a new decision with `supersedes`.
- Two things only the real board can confirm: that ROM print output can be switched off on USB-Serial/JTAG, and that the node can't see a USB port close.
