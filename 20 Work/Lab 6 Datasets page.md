---
type: work
status: done
owner: claude
priority: p2
area: data
due: 2026-12-01
pack:
created: 2026-10-12
done: 2026-10-13
---
# Lab 6 Datasets page

**Goal:** Browse every recording and build manifests.

## Done when
- [x] index of sessions with validity and WAV presence
- [x] `data/manifest.json` builder

## Notes
- Only validated sidecars are copied to `data/` ([[D-017 Rezonating Lab bench tool]]).
- Sidecar checks: [[D-019 Sidecar v1]].

## Log
- 2026-10-12 created
- 2026-10-13 Claude (cloud session): built: Datasets page, SQLite index cache (user cache dir, rebuildable), data-root sidecars for sessions not in the repo, manifest builder via `rezonating_ml.manifest` (`hash_wavs`). Verifier PASS, fix round PASS. Not committed `data/manifest.json` (a person's call).
