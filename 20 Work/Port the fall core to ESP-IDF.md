---
type: work
status: todo
owner: claude
priority: p1
area: firmware
due:
pack: "[[fall]]"
created: 2026-11-15
done:
---
# Port the fall core to ESP-IDF

**Goal:** The hackathon detection core runs inside the ESP-IDF node firmware as the `fall` engine and gives the same decisions as on the laptop.

## Done when
- [x] [[D-023 Year 1 order fall first]] and [[D-024 Hackathon core is the fall pack engine]] are accepted (blocker)
- [ ] `firmware/hackathon-rezon/rezon/src/core/` is compiled into an ESP-IDF component, and `idf.py -C firmware build` passes
- [ ] A host test feeds `session_2026-11-14T01-41-28.log` through the component and gets the same events and decisions as `tools/replay` (3 falls, 0 jumps flagged)
- [ ] Dropped samples are counted and reported (the CLAUDE.md rule)
- [ ] The Python twin of the feature vector in `rezonating_ml` matches the C++ test vectors
- [ ] `packs/fall/pack.json` names the engine and drops `uses_packs`; `python tools/validate.py` passes

## Notes
- Source and how to check it: `firmware/hackathon-rezon/README.md`. Results so far: [[EXP-001 Hackathon fall detector on stage]].
- The calling, speaker, button and BLE parts stay out (D-024).
- Estimate: 4–8 work days (2–4 weeks). This assumes the core ports without changes and the link and acquire paths already deliver 1 kSPS. The Python twin is about half of it.

## Log
- 2026-11-15 created after the hackathon merge
- 2026-11-15 Claude: D-023/D-024 accepted by Kaszti and Viktor; unblocked
