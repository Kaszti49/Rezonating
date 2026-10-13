---
type: handoff
updated: 2026-10-13
---
# Handoff

**Read this first every session.** It's the current state in under a page. Rewrite it at the end of each session; don't append.

## Where we are (2026-10-13, evening, cloud session)
- **Rezonating Lab phases 4–7 are built** and run on the simulator. They have been tried only in the cloud container's browser, not yet on pc-10. Pages: Live, Device (+ **rig checks**), Record (+ **protocol runner**), **Review** (+ SD import), **Datasets**, **Experiments**, **Bench**. Details per phase in [[Lab 4 Protocol runner, review and rig checks]], [[Lab 5 Pack bench]], [[Lab 6 Datasets page]] (done), [[Lab 7 Experiments page]].
- **Verifier PASS:** 4a runner + `walk-pass-v1.yaml`, 4b sim faults + rig checks, 6 Datasets (+ fix round), the `rezonating_ml` pipeline (decimator, filters, STA/LTA, `footstep_v1`, baseline, manifest; part 1 needed a deep-engineer L3 escalation).
- **Verifier still running at wrap-up (results not in):** 4c Review + SD import (round 3), 5 Bench, 7 Experiments, sim people (round 2). They are committed anyway, at Kaszti's request. **Re-run the verifier on these first.**
- **New in `rezonating_ml` (Tier 1):** `dsp` (63-tap FIR ÷2, 2nd-order Butterworth biquads), `trigger` (STA/LTA, windows with `n_invalid`), `pipeline` (chunked, stateful, `finish()`, features + optional model), `features` (`footstep_v1`, 13 features), `baseline` (split by group, no overlap, majority baseline), `manifest`, `vectors` (firmware test vectors in `ml/tests/vectors/`). **Firmware side not written:** one implementation in two languages is not met yet.
- **Decisions:** [[D-021 Pack pipeline in rezonating_ml]] and [[D-022 Sidecar stores loss spans]] were accepted by Kaszti **in chat** (recorded in each note's body). Frontmatter still says `proposed`: **Kaszti flips them in Obsidian.** D-022 is not implemented yet.
- **Kaszti's choices today:**
  - pack `highpass_hz`/`lowpass_hz` = one 2nd-order Butterworth biquad;
  - Review edits keep both streams' labels in sync;
  - label text is a fixed list per protocol;
  - EXP drafts go to `50 Experiments` (status `running`).
- **Simulator:** `rzlab sim --walkers P1,P2` walks walk-pass-v1 by itself; `rzlab sim-dataset` writes labelled sim sessions (people drift per session, so a session split shows leakage). Synthetic result: balanced accuracy about 0.69 against a 0.33 baseline. This says nothing about a real floor.
- **Bench firmware unchanged since this morning:** `firmware/bringup-esp32/` still has FLAG F-261013-34f1, not flashed.

## Next up
| Who | What |
| --- | --- |
| Kaszti | Flip D-021 and D-022 to `accepted` in Obsidian. Pull, `pip install -e ml -e "tools/lab[dev]"`, `rzlab build-ui`, `rzlab serve --connect sim`, and click through the new pages. Real-phone marker test. ORD-001 status |
| Kaszti + Viktor | Is the classic ESP32 the node now, or are S3 boards coming? Is the ADXL355 in the lab? Load cell on Click CH1 or HX711? Is the per-session drift in the sim (f1 ±8 %, amplitude ±24 %) plausible? Should model classes be checked against the pack labels? |
| Viktor | Review D-021's STA/LTA parameters, the `footstep_v1` band edges and the 10 % active threshold, and the filter choice; [[FootprintID dataset loader]] (2026-10-20); confirm the bench-guide pin map |
| Claude | 1) Re-verify 4c, 5, 7 and the sim people; fix the findings. 2) Small queued fixes (list below). 3) The 11-17 dress rehearsal on `rzlab sim --walkers`. 4) D-022 loss spans (schema, validate, recorder, SD import, io, pipeline). 5) firmware-dev retry on F-261013-34f1, then flash COM22 |

## Open flags
- Lab 7 Experiments verifier FLAG (arrived after the stop): stale feature cache after ml code changes, duplicate EXP drafts from one run, per-person results missing for pace/shoes. See the ledger.
- **Stopped early (credits).** Sim people FLAG (`--out` guard bypass) and Bench FLAG (HIGH: vector create could overwrite `packs/`/`schemas/`) were fixed at wrap-up with tests added but NOT run. Bench med still open: compare mismatches when the live run starts mid-acquisition. 4c and 7 verifier results never arrived. Run `pytest tools/lab/tests` first.
- F-261013-860d/-4a62: 4c round 3 waiting on re-verify (ml-dev has used both retries; next failure goes to deep-engineer, L3).
- F-261013-02f8/-80bb: sim people round 2 waiting on re-verify.
- F-261013-34f1: bring-up firmware FIFO/DRDY order (not flashed).
- F-261013-906b, F-261013-e9b4: ml-dev and verifier turn limits (for /retro).
- F-261013-da80, F-261006-646c: orchestrator process notes (for /retro).

## Queued small fixes (verifier lows, not done)
- **Bench:** y-axis labels clipped.
- **Datasets:** add `sidecar_prefix` to the cache identity; re-wrap the datasets.py docstring and WEB_API 13 lines.
- **ml README:** "every reported window is one or the other" holds only when features are ok; list `footstep_v1.json` + `features --check` with the vectors.
- **`test_sim_people.py`:** use `out.features`.
- **`evaluate`:** returns no per-window predictions (per-person results for pace/shoes are missing).
- **`tools/lab/tests/test_runner_e2e.py::test_runner_produces_90_labelled_passes_per_person`:** fails under heavy CPU load (zero-length walk labels). Suspect the sim EVENT computation in `sim/node.py` or the 10 ms test margin.

## Watch out
- The ml/ vector files are pinned to footstep-id's trigger (`ratio 3.5`, 50/2000 ms). Retuning in the Bench warns: regenerate `ml/tests/vectors` and tell firmware.
- Sidecars store only loss counts until D-022. With any loss, the mask marks every all-zero frame (can skip many windows on quiet floors).
- Git Bash on pc-10 has no coreutils or python on PATH: use full paths or PowerShell. `idf.py` refuses Git Bash.
- Lab: `pip install -e ml -e "tools/lab[dev]"` (now needs pyyaml), `rzlab build-ui`. Data root via `RZ_DATA_ROOT` or config. The Datasets cache defaults to `%LOCALAPPDATA%\rzlab\datasets.sqlite`. Runs go to `tools/lab/runs/` (gitignored).
- Accepted decisions are hook-locked: to change one, propose a new decision with `supersedes`.
