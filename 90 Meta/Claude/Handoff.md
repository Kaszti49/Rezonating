---
type: handoff
updated: 2026-11-26
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-11-26, pc-10, off day)
- **Locate rebuilt on real walks** ([[EXP-005 Timing first on one-side walks]]). Coin test: **ADC ch0 is the right geophone**; that's now the default in code, and *Swap left and right* is on Home and Locate (the case's placement decides). Rule: **heard first** (> 0.1 ms, |cc| ≥ 0.9), else 1.5 times louder, else front/back/far; zero point 0 ms. New step detector: each frequency against its own 3 s median, broadband score, 3 sigma, plus an energy check (1.5 times quiet). On six one-side walks: **267 of 298 sided steps right (90 %), 110 of 408 no side; the old rule got 52 %**. The limits are in-sample; one person, floor and day; distances not labelled.
- **The radar** lights the walk's side (2 of the last 3 steps), shows the walk's steps (solid = clearly first, hollow = not) and "2 of 3". Not yet looked at by a person on the board.
- **pc-10 Lab:** `.venv` (Python 3.12) and the desktop shortcut now exist. Launcher fixed: a left-over app-window Edge process used to make it stop its fresh server.
- **Recordings 2026-11-26** in `Recordings` (data root), sidecars in `data/`: walks `_01` L, `_02` R, `_05` L, `_06` R, `_07` L, `_08` R; coin taps `_03` (left geophone), `_04` (right). Sidecars `_01` to `_04` give ch0 the **left** position (written before the coin test); `_05` to `_08` are right.
- **Geophone lock:** lever and cam ring are one printed part now (`out/geo_lock_ring_lever.stl`); the printed base stays. Renders still show the old lever until the macro runs in the FreeCAD GUI.
- **OTIO Veszprém is Monday 2026-11-30, the next work day.**

## Next up
| Who | What |
| --- | --- |
| Kaszti | Look at the radar on the board and say what to change. Save the good state again (Home → Case position): the quiet level is measured differently now. Mark FRONT on the case so swap is never needed at OTIO |
| Kaszti | A labelled distance series on another day: 1, 2, 3, 4 m, left and right, 60 s each, plus front and back walks (should be "no side") |
| Kaszti + Viktor | OTIO: mats left and right, case fixed, rehearsal with other people |
| Viktor | Firmware README pin map vs the hackathon guide. Review `firmware/rig-s3` |
| Claude | Score the distance series with today's limits unchanged (the first held-out number). Ask whether to fix the `_01` to `_04` sidecar positions. Look at F-261126-77de (soak start-up losses) |

## Open flags
- New: F-261126-77de (med, soak loses host samples in its first 2 s; already 888 with the old code, 1371 and 1936 with the new detector), F-261126-8a18 (soak measures the venv stub), F-261126-c36e (re-save the good state), F-261126-26b1 (correction: I started a stale UI build).
- Older: Lab 4c, sim people, Lab 7, F-261101-b2c0, F-261102-f78b, F-261103-e4ed, F-261123-dab8. `ledger.py retro-due` says a retro is due (a correction): run `retro` at the next natural break.

## Watch out
- After a pull on any machine: `rzlab build-ui` (pc-10 served a UI older than the Home dashboard). Check the static build time against the last `tools/lab/web` commit.
- The Locate detector needs about 1.7 s of signal after a connect before it reports steps.
- `!` commands run in Git Bash: use forward slashes in paths.
- `python` on PATH is Espressif's 3.11; the Lab runs from `.venv` (launcher) or `Python312\Scripts\rzlab.exe`.
- Known Lab test failures on pc-10: two symlink tests, `test_soak_end_to_end_smoke` (also alone, see the flag), `test_runner_produces_90_labelled_passes_per_person` (flaky); `test_switching_transport_gives_fresh_accounting` failed once in a full run, passed alone 3 of 3.
- `scratch/prefboard.jpg` (7 MB) stays out of git. FreeCAD bridge token on pc-10 changed: never write it in the repo.
- Accepted decisions are hook-locked: propose a new one with `supersedes`.
