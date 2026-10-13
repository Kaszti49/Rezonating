---
type: work
status: done
owner: claude
priority: p1
area: data
due: 2026-11-03
pack:
created: 2026-10-12
done: 2026-10-13
---
# Lab 3 Recorder and live labels

**Goal:** Record sessions to WAV + sidecar and mark labels live.

## Done when
- [x] `rezonating_ml.io` WAV + sidecar round-trip
- [x] simulated 5-min session passes `tools/validate.py`
- [x] keyboard marks have label error < 20 ms against ground truth
- [x] phone marks have label error < 150 ms against ground truth

## Notes
- Sidecar fields (`loss`, `sample_rate_measured`, `labels[].src`, `unc_ms`): [[D-019 Sidecar v1]].
- Recordings go to the shared data root, never into git ([[D-017 Rezonating Lab bench tool]]).

## State on 2026-10-13 (paused by Kaszti)
**Built (backend, uncommitted):** `rezonating_ml.io` (WAV int32 + sidecar), recorder (`tools/lab/src/rezonating_lab/recorder/`), `/api/record/*` routes, server-stamped labels, phone marker listener (`/m/<token>`, QR), `rzlab validate`. API in `tools/lab/WEB_API.md` §9.

**Shown to work (before the last, stopped retry):** 483 tests pass; 5-min sim session passes `tools/validate.py` and `rzlab validate`; with 60 ppm clock drift keyboard label error max 9.4 ms, phone max 42 ms (phone latency simulated); marker gives the same 404 for bad and expired tokens; 10-min soak at 3× has zero host gaps.

**Still wrong / to fix:**
1. **Marker address (med):** the listener binds one LAN address, but the API can hand the phone a URL/QR for another one. Chosen fix: pick the address on the Record form before the session starts; the listener binds only that one and the QR always shows it. Retry 2 was editing this when it was stopped: its changes are **unverified** (files: `recorder/marker.py`, `recording.py`, `config.py`, `forms.py`, `server/record_routes.py`, `core/monitor.py`, `PROTOCOL.md`, `README.md`, `WEB_API.md`, tests). Run the full test suite first.
2. Link lost before the first STATUS: zero-filled gaps counted in no loss counter (`recording.py`, set `loss.host = zeros_in_file`).
3. `PROTOCOL.md` §6: say that `loss.host` also holds samples the recorder dropped.
4. `SessionMonitor.close_gate()` is dead code.
5. `accept_record.py` leaves WAVs in `%TEMP%\rz-accept-*`.
6. Not done at all: the **Record page** in the UI (also fix the stale port-5173 comment in `web/vite.config.ts`; dev now needs `rzlab serve --dev`).
7. Never tried: marking from a **real phone** over Wi-Fi. `unc_ms` is an estimate (about 95 % coverage in the sim), not a hard bound.
8. Install: `rezonating-ml` is not on PyPI; install with `pip install -e ml -e "tools/lab[dev]"`.

## Log
- 2026-10-12 created
- 2026-10-13 backend built by ml-dev (2 runs, hit the turn limit twice); verifier FLAG (name in the server log via `/mark`, recorder drops not counted, `unc_ms` not a bound, flaky slow test) → retry 1 fixed all → re-verify FLAG (marker address, 4 lows) → retry 2 stopped by Kaszti before its tests ran. Paused to talk it over
- 2026-10-13 resumed on Opus 5.5: retry 2 finished (marker binds one address, chosen on the form; 491 tests) → verifier PASS (follow-ups: reject IPv6 `marker_bind` in config). Record page built (check 0/0, smoke 30/30); UI verifier running. Lab started for the team at http://127.0.0.1:8765 with the simulator, data root `C:\Users\benedek.kaszti\rzlab-data`. Items 1–6 of the list above are done; 7 (real phone) and 8 stay open
- 2026-10-13 done: Record page verifier PASS (Space released from dropdowns after a pick, fixed by Claude). Done-when items met in the simulator. Still open, tracked in the Handoff: a real-phone marker test, rejecting IPv6 `marker_bind`, `kill-test-phone` still listed as a protocol
