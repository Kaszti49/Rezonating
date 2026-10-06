---
type: log
---
# Session log

Append-only. Newest at the bottom. One entry per Claude session.

## 2026-10-01
- **Did:** master plan doc; repo scaffold (schemas, validator, packs, firmware stub, protocols); first-order list; this vault (tree, templates, dashboard, Bases, plugin settings, theme).
- **Decided with the team:** D-001 to D-012.
- **Left open:** license; repo push (needs Kaszti); Templater trigger switch on each device.
- **Next session should:** check whether the kill test happened and update EXP-001, then the EU stock check.

## 2026-10-03
- **Did:** built the agent system: orchestrator rules in `CLAUDE.md`, 8 agents, 6 skills, 7 hooks, ledger, 11 eval cases, local-model helpers, vault notes ([[Agent system]]).
- **Agents:** none run yet; hooks and scripts pass their tests (`.claude/tests`).
- **Decided with the team:** Kaszti approved the plan in chat; D-013 and D-014 written as proposals for him to accept.
- **Left open:** machine setup (company PC Monday), ESP-IDF v6, Ollama model choice, first eval baseline.
- **Next session should:** check the hooks fire cleanly on the company PC, run the vault-keeper and verifier evals, then go back to the kill test and the EU stock check.


## 2026-10-05 / 2026-10-06
- **Did:** set up the company PC (pc-10): Python 3.12, ruff 0.16.10, `tools/requirements.txt`, `ml[dev,export]`, git hooks path, ESP-IDF v6.0 through EIM (`firmware/` builds, from PowerShell only). Fixed the hook tests on short-name TEMP paths (`rzlib.py` realpath). Dropped the phone kill test (notes moved to 00 Inbox, gate removed from [[Roadmap]], [[Master plan]], [[ORD-001 First rig]]). Recounted all open due dates and Roadmap milestones on Mon/Tue work days, with Log lines. Added the ADXL355 to the first prototype. Added the vision and work-day rules to `CLAUDE.md`. The session was cut off by a shutdown on 2026-10-05 and resumed on 2026-10-06.
- **Agents:** researcher (parts, 2 attempts) → verifier FLAG (DigiKey ADC stock 0) → retry F-261006-1e98 (resolved) → L4 human F-261006-27f3 (open). The researcher's scope hook blocked part-note edits, so the orchestrator applied them (note F-261006-646c). ml-dev fixed `tools/mcp/idf_mcp.py` (gate pass, verifier PASS).
- **Decided with the team:** Kaszti: drop the kill test; ADXL355 next to 2 geophones in the first prototype; recount dates in work days; kill-test notes to the Inbox; approved the CLAUDE.md rule and the rzlib fix.
- **Left open:** ADS131M04 source (DigiKey 0 until 2027-01-04; LCSC 2,039; Mouser/Farnell unchecked); EVAL-ADXL355Z I2C header pins (UG-1030); an SMD adapter for the 3.2 × 2.5 mm oscillator; esp-idf MCP not yet confirmed inside Claude Code (`/mcp` reconnect).
- **Next session should:** check whether ORD-001 was placed and set part statuses; run the first agent eval baseline; review the pin map, including the ADXL355 I2C pins.
- **Later on 2026-10-06:** Kaszti: Chinese suppliers are fine (ADC from LCSC). The researcher verified the ADXL355 chip's I²C (Rev. 0 mirror); the EVAL board's header table is still unverified. Added [[Oscillator adapter board]]. The writer built `docs/study-guide.html` (first attempt hit the turn limit, F-261006-1028); verifier FLAG (anti-aliasing, ADXL355 data rate/noise) → writer retry fixed it (F-261006-ece9 resolved), published as an artifact. Open L4 F-261006-a681: four design questions from the datasheet review.
- **Evening 2026-10-06:** Kaszti (after talking with the boss): no breadboard; the oscillator, breadboard kit, microSD breakout and card are already in the lab (`have`); TSSOP and oscillator adapters not needed (moved to 00 Inbox); ADC becomes the MIKROE-4890 ADC 15 Click from Farnell. Research → verifier FLAG (input range at gain 32, SPI modes; F-261006-1d9f, fixed by the orchestrator). Proposed [[D-015 Prototype ADC on ADC 15 Click]]; new [[Wire the first rig]] replaces "Solder ADS131M04 on adapter". The study guide is now a library: chapter A1 (`docs/study-library/adc15-click.html`) → verifier FLAG (LTC6903 accuracy is 0.5–1.1 %, not ppm; DRDY active low; F-261006-4cb2) → writer retry → published v2. Committed and pushed at Kaszti's request.
