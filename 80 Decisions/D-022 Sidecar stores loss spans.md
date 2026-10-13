---
type: decision
id: D-022
status: proposed
date: 2026-10-13
decided_by: []
tier: 1
supersedes:
---
# D-022 Sidecar stores loss spans

**Decision:** The v1 sidecar gets an optional field **`loss_spans`**: a list of `[i, n]` pairs, one per run of lost samples. `i` is the WAV frame index where the run starts (0 = the WAV's first frame) and `n` is the number of frames in the run. The runs are sorted, don't overlap, and their total equals `loss.device + loss.link + loss.host`. Every frame inside a run is zeros in the WAV, as today ([[D-019 Sidecar v1]]). The Lab recorder writes it for every recording, and so does the node's microSD writer ([[WAV and sidecar writer on microSD]]). `rezonating_ml` builds the pipeline's validity mask from it when it is present. A sidecar without it stays valid, and the pipeline then keeps today's conservative zero-frame mask ([[D-021 Pack pipeline in rezonating_ml]]). The field is additive, so the schema stays at v1 (`"schema": 1`).

**Why:** v1 stores only how many samples were lost, not where. When a recording has any loss, the pipeline must treat every all-zero frame as possibly lost. On a quiet floor with two zero-mean channels, that marks real frames as invalid. The 2026-10-13 deep-engineer measurement: 1834 surplus frames in 10 min at a noise of 10 codes, which skips about 80 % of footstep windows. At 100 codes it's about 2 %. The recorder already knows each gap exactly (`recorder/capture.py` writes the zeros), so storing the positions costs a few bytes and makes the mask exact. "Count every sample" then also means "know where each one is". Kaszti asked for this proposal on 2026-10-13.

**Rejected alternatives:** Keep counts only (simple, but loses real footsteps on quiet floors whenever anything was lost). A separate gaps file next to the WAV (a second file to keep in sync, and nothing else under `data/` may be `.json`). A bitmap per frame (large and unreadable for no gain over runs).

**Affects:** `schemas/sidecar.schema.json` (optional `loss_spans`, plus an example in `schemas/examples/`), `tools/validate.py` and `rzlab validate` (the total equals the `loss` sum; runs are sorted, inside the WAV and zero-filled), the Lab recorder and SD import, `rezonating_ml.io` and `rezonating_ml.pipeline` (use the spans when present), `rezonating_ml.manifest`, the firmware microSD writer. Nothing changes until Kaszti and Viktor accept this in Obsidian.

**Acceptance:** Kaszti accepted D-022 in the cloud session chat on 2026-10-13 ("I kaszti accept Decision 022 … I accept"); he couldn't edit the file from there. Kaszti flips `status` and `decided_by` in Obsidian once the work is done.
