---
type: project
---
# Lab build prompts

Copy-paste prompts for building the rest of the **Rezonating Lab** ([[D-017 Rezonating Lab bench tool]]). Start `claude` in the repo folder, paste one prompt, and let the orchestrator run it. Go in order: each phase builds on the one before. The background for all of them is in [[Lab 1 Link codec and simulator]] and the work notes `Lab 2`–`Lab 7`.

**State on 2026-10-12:** phase 1 is done (commit `734b59b`). It covers the link protocol spec `tools/lab/PROTOCOL.md`, the codec, golden vectors, loss accounting, the simulator and `rzlab sim` / `rzlab tail`, with 280 tests and verifier PASS. There is no browser UI yet.

---

## Phase 2: Live and Device pages (first visual step, due 2026-10-27)

```text
Build Lab phase 2 ([[Lab 2 Live and Device pages]]). Read D-017, D-018, tools/lab/PROTOCOL.md,
tools/lab/README.md and the Lab 2 note (including its "Phase 1 leftovers") first.

Goal: `rzlab serve` starts a local web app at http://127.0.0.1:8765 that shows live data from
the simulator (and later the real node over USB or Wi-Fi).

Server (Python, in tools/lab/src/rezonating_lab/): FastAPI + uvicorn. A device manager owns the
connection (TCP, serial incl. socket://, simulator), reusing link/, session.py and
core/monitor.py. Per-stream numpy ring buffers (10 min). One WebSocket that sends binary sample
frames to the browser at ~20 Hz plus JSON status/log events. Display-only maths (min/max
envelope, PSD, STFT spectrogram) in core/view.py, never used by packs. Bind 127.0.0.1 only and
check Host and Origin on HTTP and WebSocket. Add fastapi and uvicorn to pyproject.

Browser UI (tools/lab/web/): Svelte + TypeScript + Vite + uPlot. Clean instrument-panel look,
dark theme plus light theme, one fixed colour per channel, monospace numbers, left rail with
the pages (Live, Device; the others greyed out "coming"). A status strip that's always visible:
node, link type, measured rate per stream with % offset, the three loss counters
(device/link/host, live host gap shown as "N+" when it's a lower bound), REC dot.
- Live page: scope per channel (1–60 s window, pause and scroll back), PSD, scrolling
  spectrogram, units toggle counts/V/g, RMS, peak and clipping per channel.
- Device page: connect (serial port list, manual IP, simulator), node info and heads, gain
  settings (refused while acquiring: ERR 5), health graphs (rate over time, losses, queue
  fill), device log console.
`rzlab build-ui` runs npm ci + npm run build into src/rezonating_lab/static/ (gitignored; add
node_modules/, static/ and tools/lab/runs/ to .gitignore).

Done when: rzlab sim + rzlab serve show moving waveforms and the spectrogram in the browser;
switching transport keeps the counters right; a 10-min soak with the sim at --speed 3 has zero
host gaps and bounded CPU and memory; the WebSocket refuses a foreign Origin; pytest, ruff and
npm run check pass; also fix the phase 1 leftovers listed in the Lab 2 note.

Route: ml-dev builds it (it may take several runs; split server and UI if needed), then
verifier. Take screenshots of both pages with the run skill and show them to me. Update the Lab
2 note and today's daily note, and propose the commits.
```

## Phase 3: Recorder and live labels (due 2026-11-03)

```text
Build Lab phase 3 ([[Lab 3 Recorder and live labels]]). Read D-008, D-019, D-020,
tools/lab/PROTOCOL.md §6–7 and schemas/sidecar.schema.json (v1) first.

1. In rezonating_ml (ml/): an `io` module that reads and writes WAV (32-bit int, multichannel)
   + sidecar, round-trip tested. The lab must use it; no WAV code in the lab.
2. Lab recorder: the session form (site, room, floor, surface, sensor positions, pseudonyms P1…,
   protocol). It names the session YYYY-MM-DD_site_room_nn and reserves nn by creating the
   folder. It writes <session>.adc.wav|json (adc_raw, per D-020) and <session>.accel.wav|json
   with v1 sidecars: measured rate, loss.device/link/host, first_sample, t_dev_us, missing
   samples as zeros, "rzlab: loss=incomplete" in notes when the final STATUS is missing.
   - Data root from %APPDATA%\rzlab\config.toml or RZ_DATA_ROOT, never inside the repo.
   - Write to local staging, then move to the data root.
   - Copy validated sidecars to data/<session>/. Nothing else under data/ may be .json.
3. Live labels: Space starts/ends a mark, stamped on the server (never the browser clock) and
   stored as sample indices (i0/i1/src). A phone marker page on a separate LAN listener, one
   route /m/<token>, QR code, token dies at session end, no data access; marks corrected by
   half the round-trip time, with unc_ms.
4. A Record page in the UI.

Done when: a 5-min simulated session passes `python tools/validate.py` and `rzlab validate
<root>`; label error vs simulator ground truth < 20 ms (keyboard) and < 150 ms (phone); the
marker rejects bad or expired tokens. Route: ml-dev, then verifier. Update the notes and propose
commits.
```

## Phase 4: Protocol runner, review and rig checks (due 2026-11-10, before the first rig day 11-17)

```text
Build Lab phase 4 ([[Lab 4 Protocol runner, review and rig checks]]).
1. docs/protocols/walk-pass-v1.yaml: a machine-readable version of walk-pass-v1.md (60 s
   silence, then per person: normal/shoes on 50, normal/off 20, slow 10, fast 10). Runner on
   the Record page with a pass counter; labels fill from the current step.
2. Review page: waveform + spectrogram timeline with a label lane (drag edges, split, merge,
   re-tag person/pace/shoes). Saves to the sidecar and runs the validator.
3. Rig checks on the Device page (guided, pass/fail, saved report text for the build note of
   [[Wire the first rig]]): ADC answers, rate over 60 s vs nominal, noise floor with inputs
   shorted, tap test for channel mapping, ADXL355 ≈ 1 g on z.
4. SD import: bring in recordings the node wrote to microSD (validate on import).

Done when: the rig checks catch the simulator's faults (swapped channels, missing 1 g, +1.65 %
clock); the runner produces 90 labelled passes per person; a full dress rehearsal of the
11-17 session works on the simulator. Route: ml-dev, then verifier.
```

## Phase 5: Pack bench (due 2026-11-24)

```text
Build Lab phase 5 ([[Lab 5 Pack bench]]). Needs rezonating_ml STA/LTA ([[Footstep segmentation
with STA-LTA]]) and ideally the baseline classifier. If they don't exist yet, stop and tell me.
- In rezonating_ml: build_pipeline(pack_json), chunked and stateful, giving byte-identical
  results to the batch call (the real FIR + ÷2 decimator from D-016 lives here too). Then replace
  the simulator's adc_dec placeholder with it.
- Bench page: pick a pack + source (live, recording, simulator). Show every stage: filtered
  signal, trigger statistic with threshold, events, features, model output; grey out stages
  that don't exist yet. Trigger sliders → "save to pack.json" (validate.py runs). Compare mode:
  firmware EVENT frames vs Python on the same sample indices. Create/check
  ml/tests/vectors/*.json from a clip.
- No signal maths in the lab: everything comes from rezonating_ml.
Done when: bench output equals a direct rezonating_ml call on the same WAV; triggers are
scored against simulator ground truth. Route: ml-dev, then verifier.
```

## Phase 6: Datasets page (due 2026-12-01)

```text
Build Lab phase 6 ([[Lab 6 Datasets page]]): an index of every session (repo sidecars + WAVs on
the data root): date, floor, people, duration, label count, protocol, valid or not, WAV present
or missing. Filter and open in Review. Per-machine SQLite cache, always rebuildable from the
sidecars. A builder for data/manifest.json (paths relative to the data root + sha256; ml-dev
defines the format in ml/). Route: ml-dev, then verifier.
```

## Phase 7: Experiments page (due 2026-12-08)

```text
Build Lab phase 7 ([[Lab 7 Experiments page]]): run an evaluation (pack, sessions, split by
session or person, refuse any overlap, baseline required, seed). Show accuracy, confusion
matrix and per-person results; save runs under tools/lab/runs/ (gitignored). "Draft EXP note"
writes an EXP-### note into 00 Inbox with the exact experiment frontmatter (vault-conventions
skill), checked by `python .claude/scripts/vault_schema.py`. Route: ml-dev, then verifier.
```

## Firmware side: link component (needs an ESP32 board from [[ORD-001 First rig]])

```text
Build [[Firmware link component]]: firmware/components/link (Tier 2) implementing
tools/lab/PROTOCOL.md over USB-Serial/JTAG first, Wi-Fi TCP + mDNS later. First a host-side
unit test generated from tools/lab/tests/vectors/link-v0.json (byte-identical encoding). Set
CONFIG_ESP_CONSOLE_UART_DEFAULT=y and CONFIG_ESP_CONSOLE_SECONDARY_NONE=y, and switch off ROM
print output to USB at link start. On the board, confirm: no text on the stream, the session
survives a port close until the 5 s liveness timeout, and `rzlab tail --serial COMx` shows the
measured rate with 0 losses. Route: firmware-dev, then verifier. Flashing needs a person.
```
