# Rezonating Lab (phases 1 to 6)

Bench tool for the node link: protocol v0 codec, a simulated node, a text monitor (phase 1) and the web
server `rzlab serve` for the browser UI (phase 2).
Spec: `PROTOCOL.md`. Web API for the UI: `WEB_API.md`. Golden vectors for the firmware: `tests/vectors/link-v0.json`.

## Install

```bash
pip install -e ml -e "tools/lab[dev]"   # gives the `rzlab` command; Python 3.10+, numpy, pyserial, fastapi, uvicorn, segno, pyyaml
python -m pytest -q tools/lab/tests
```

## Run

```bash
rzlab sim                       # simulated node on 127.0.0.1:7350 (USB session rules)
rzlab sim --auth --speed 3 --corrupt-rate 0.02 --truth truth.jsonl
rzlab tail                      # connects to 127.0.0.1:7350, STARTs all streams, one line per second per stream
rzlab tail --serial COM5        # a real node; also --serial socket://127.0.0.1:7350 or --tcp HOST:PORT [--key HEX]
```

`rzlab sim` options: `--clock-error PERCENT` (default +0.8), `--device-drop-rate P` (per sample),
`--link-drop-rate P` (per DATA packet), `--corrupt-rate P` (per DATA frame, flips a byte on the wire),
`--speed X`, `--seed N`, `--truth FILE.jsonl` (ground-truth footstep times).
Rig faults for the rig checks: `--swap-channels` (ADC ch0/ch1 swapped), `--no-gravity` (ADXL355 z shows no 1 g),
`--no-adc` (the ADC never answers), and the bench mode `--shorted-inputs` (ADC inputs read only noise, no footsteps).
The simulator also accepts `SET sim.tap <0|1>` (`sim.*` keys are reserved for the simulator, PROTOCOL.md 5): a 50 mV tap on that physical
ADC channel 50 ms after the last produced sample, 15 % crosstalk on the other; `--swap-channels` moves it like any
other signal. Real firmware answers it with ERR 3 (unknown key).

`rzlab tail` prints measured rate (from STATUS and from its own `t_dev_us` fit) with the offset against
nominal, then received / dev / link / gap (host gap) / bad_frames / lost_frames. Ctrl+C sends STOP and
prints the final per-stream loss summary.

Regenerate the vectors after a protocol change: `python -m rezonating_lab.link.vectors --write`.
`adc_dec` in the simulator is the real D-016 decimator from `rezonating_ml` (`Decimator2` + `to_adc_dec_codes`,
HELLO `fir_taps = 63`, `fir_delay = 31`; a lost raw sample is held inside the FIR and every output whose window held
one is `device_dropped`). The simulator also sends EVENT frames (PROTOCOL.md 4.5) for the `footstep-id` trigger,
computed with `rezonating_ml.build_pipeline` on ADC channel 0 of its own `adc_raw` samples (in blocks of 512 raw
samples). It plays the firmware's part: until real firmware exists, the bench's firmware-vs-Python compare against
the simulator compares Python with Python (it checks indices, chunking and loss handling, not a second
implementation). `SimConfig(events=False)` turns them off.

## Phase 2: serve

`rzlab serve` is the server behind the browser UI: FastAPI + uvicorn, one owner of the node connection,
ring buffers with the last 10 minutes of every stream, one WebSocket (`/ws`) for live samples and events, and
REST for commands and the scope / PSD / spectrogram views. The exact contract the UI is built against is
`WEB_API.md`.

```bash
pip install -e "tools/lab[dev]"            # adds fastapi, uvicorn; dev adds httpx, psutil, scipy for tests and soak
rzlab sim                                   # terminal 1: simulated node on 127.0.0.1:7350 (optional, see below)
rzlab serve                                 # terminal 2: http://127.0.0.1:8765/
rzlab serve --connect sim                   # connect at start-up (also tcp:HOST:PORT, serial:COM5, serial:socket://127.0.0.1:7350)
rzlab build-ui                              # npm ci + npm run build in tools/lab/web/ -> src/rezonating_lab/static/
```

- **Loopback only.** `--host` accepts only `127.0.0.1`, `::1` or `localhost`; anything else is refused. The server
  also checks the `Host` header (`127.0.0.1:PORT`, `localhost:PORT`, `[::1]:PORT`) and the `Origin` header (same
  origins). `rzlab serve --dev` also lets in the Vite dev server on `localhost:5173` / `127.0.0.1:5173`; without
  it any other local project on port 5173 is a foreign origin. A foreign `Origin` gets 403, and a WebSocket
  handshake with one is closed before it is accepted.
- **The "Simulator" connection** is TCP to `127.0.0.1:7350`, the same as `rzlab sim`. If nothing listens there, the
  server starts an in-process simulator (speed 1x, default settings) on that port and stops it when the server
  stops. Use `--no-embedded-sim` to turn that off. For the soak, or to try faults and `--speed`, run `rzlab sim`
  yourself first.
- **UI not built yet?** `GET /` shows a plain page that says to run `rzlab build-ui`. `build-ui` needs Node.js and
  npm. The built UI (`src/rezonating_lab/static/`) and `node_modules/` are git-ignored.

### Browser UI (`web/`)

Svelte 5 + TypeScript + Vite + uPlot, everything bundled (no CDN, no web fonts). Pages: Live (scope, PSD,
spectrogram, units, pause and scroll-back), Device (connect, node info, gain, health graphs, log) and Record (below).
The later pages (Label, Bench, Experiments, Datasets) are greyed out in the rail.

```bash
cd tools/lab/web
npm ci                  # install the pinned dependencies (package-lock.json is committed)
npm run dev             # Vite on http://127.0.0.1:5173, proxies /api and /ws to 127.0.0.1:8765 (run `rzlab serve --dev` first)
npm run check           # svelte-check + tsc, must report 0 errors and 0 warnings
npm run build           # writes ../src/rezonating_lab/static/
rzlab build-ui          # the same as `npm ci` + `npm run build`, from anywhere
```

The dev server passes `Host` and `Origin` through unchanged; the lab server accepts port 5173 for that only when it
was started with `--dev` (WEB_API.md section 1). The theme, unit and window choices are kept in `localStorage` (optional: the page works
without it). The live scope keeps about 65 s per stream in the browser; older data and scroll-back come from the
server's 10-minute rings through the `/api/view/*` requests.
- **Switching transport** (Wi-Fi to USB, or to the simulator): connecting again closes the old session politely
  (STOP, then close), resets the ring buffers and starts a fresh `SessionMonitor`, then runs the clean-up STOP of
  PROTOCOL.md section 1 before anything starts. A window left over on the node is never counted; if the clean-up
  STOP cannot be confirmed, the first START is forced and the log says so.
- **Display maths** (`core/view.py`: envelope, Welch PSD, STFT) is for drawing only and is never used by a pack
  (D-017).

### Soak

```bash
rzlab soak --minutes 10 --speed 3          # needs psutil (dev extra); exit code 1 on any problem
```

It starts `rzlab sim --speed 3` and `rzlab serve` as separate processes, STARTs all streams and consumes the
WebSocket like a browser would (checking sample index continuity per frame), while polling the view endpoints
like a UI. Every 5 s it records the server's CPU % (of one core), RSS, WebSocket frames/s and kB/s. The report
gives per-stream device / link / host loss, CPU and RSS (start, min, max, end), RSS growth (middle quarter against
last quarter, limit max(10 MB, 5 %)) and the WebSocket rate. It fails on any host gap, memory growth, fewer than
15 WebSocket frames/s on a stream, server CPU above the limits (median 50 %, peak 100 % of one core), a dead
process, or a final STOP that was not confirmed.

## Phase 3: recorder and live labels

`rzlab serve` records sessions to WAV + sidecar and takes live labels. Contract for the UI: `WEB_API.md` section 9.
WAV and sidecar I/O is `rezonating_ml.io` (the lab has no WAV code), so install the ml package from this repository
**first or in the same command**: `pip install -e ml -e "tools/lab[dev]"`. `rezonating-ml` is listed as a dependency, but it is
not on PyPI; installing only `tools/lab` would make pip look for that name there.

### Record page

Open `http://127.0.0.1:8765/record` (connect a node on the Device page first).

1. **Where recordings go** shows the data root and its check. If it is missing or refused (inside the repository, not
   writable), type the full path of an existing folder and **Save to config**; when `RZ_DATA_ROOT` is set, change the
   variable instead and restart the server.
2. **New session**: site and room (required), floor, surface, protocol (with "run it step by step", phase 4 below), persons as pseudonyms only (`P1`, `P2` ...; anything
   else is cleared, never kept), and x/y(/z) in metres for every recorded channel (the accelerometer takes one position
   for its three axes). Empty head, serial, port and mount take the node's defaults. With more than one network, pick
   the one the phone is on for the phone marker. Form errors from the server appear next to the fields.
3. **Start recording**. The REC dot in the status strip turns red; the page shows the elapsed time, what is on disk per
   stream, and the live loss counters (device / link / host; `N+` while host is a lower bound).
4. **Live labels**: set label, person, pace and shoes, then press **Space** to start a mark and Space again to end it (the
   server stamps the time). Space does nothing while the cursor is in a text field or a list: click on an empty part of
   the page first. A mistaken mark can be deleted from the list.
5. **Phone marker**: scan the QR code (phone on the same network as the PC); it works only for this recording.
6. **Stop recording** shows the result: session name, folder, validation, problems, and `loss=incomplete` if the node's
   final status never arrived.

The form is remembered in the browser after a successful start (optional; the page works without it).

### Where recordings go

Set the **data root** (a folder on the shared drive, never inside the git repository; the lab refuses a path inside the
checkout) with the `RZ_DATA_ROOT` environment variable (it wins) or `%APPDATA%\rzlab\config.toml`:

```toml
data_root = "D:\\rezonating-recordings"
# optional: staging_dir, sidecar_dir, marker_port = 8766, marker_host = "192.168.1.23", copy_sim_sidecars = false
```

Without a data root the Record page shows an error that says how to set one. A recording is written to local staging
(`%LOCALAPPDATA%\rzlab\staging`) and moved to `<data root>/<session>/` when it ends, with the session name
`YYYY-MM-DD_<site>_<room>_<nn>` reserved by creating its folder (so two PCs never share a name). After the files validate, **only the
sidecars** are copied to `data/<session>/` of the checkout (`sidecar_dir`, `RZ_SIDECAR_DIR`); a WAV never goes there.
Sessions recorded from the simulator are **not** copied unless `RZ_COPY_SIM_SIDECARS=1`, so test runs cannot leak into `data/`.
Other settings: `RZ_STAGING_DIR` (WAV files are written there, so a folder inside the repository is refused too), `RZ_MARKER_PORT`, `RZ_MARKER_BIND` (default `auto`: the phone marker listens on one address, the first LAN address of this PC, never every interface; the Record page lets you pick another interface before the recording starts, e.g. with a VPN; set `0.0.0.0` if you want every interface; IPv6 addresses are refused with an error, the phone marker is IPv4 only), `RZ_MARKER_HOST` (only used with `RZ_MARKER_BIND=0.0.0.0`: the address in the QR code; otherwise the QR code always names the address the marker listens on), `RZ_REPO_ROOT`. `sidecar_dir` is meant to be in the repository (`data/`): only validated `.json` sidecars are ever copied there.

### Check a data root

```bash
rzlab validate D:\rezonating-recordings       # folder names, sidecars against the schema, WAV header vs sidecar, labels inside the file
rzlab validate data --sidecars-only            # the repository's data/ (sidecars only)
```
Exit code 0 when every session is fine, 1 when any fails, 2 for a bad folder.

### Phone marker and the Windows firewall

While a recording runs the lab also listens on the LAN for a phone (own port, `/m/<token>` only; see `WEB_API.md` 9.6). The first
time, **Windows Defender Firewall asks whether python.exe may communicate on the network**: allow it on **private networks only**, or
the phone cannot connect. The page needs the phone and the PC on the same network (not a guest Wi-Fi with client isolation). The marker listens on one address of this PC (the QR code names exactly that address); if the PC has several networks (VPN, WSL, Ethernet and Wi-Fi), choose the phone's network on the Record page before you start. The
token is random per recording and the listener is closed when the recording ends. Everything else in the lab stays on loopback.

### Acceptance run

```bash
python tools/lab/tests/accept_record.py --minutes 5 --out result.json
```
Records 5 minutes in real time from the simulator through the server, presses keyboard and phone marks (phone latency injected,
20-80 ms each way), compares the stored label indices with the simulator's own clock, and runs `rzlab validate` and `tools/validate.py`
(on a temporary copy of the repository layout) on the result. The simulator runs with a clock drift of 60 ppm and 150 us of timestamp noise (`--drift-ppm`, `--jitter-us`; `rzlab sim --clock-drift-ppm --timestamp-jitter-us` has the same options). The run fails when keyboard marks are off by 20 ms or more, phone marks by 150 ms or more, or when fewer than 95 % of the edges lie inside their `unc_ms`: `unc_ms` is an estimate calibrated to that percentile, not a bound. Phone marks fire on `pointerdown` (the touch, not the release). The real-phone test on Wi-Fi is still pending. The slow in-suite version of this run is opt-in: `RZ_SLOW=1 pytest tools/lab/tests/test_recorder_e2e.py`.

## Phase 4: protocol runner

The Record page can walk a recording through a protocol step by step. Contract: `WEB_API.md` section 10.

- **Protocols** are `docs/protocols/<name>.yaml`, the machine-readable twin of `<name>.md` (format in the header of
  `docs/protocols/walk-pass-v1.yaml`). Only protocols with a YAML file are offered in the form; `kill-test-phone` (dropped)
  has only its `.md` and is no longer listed. The loader refuses unknown keys, duplicate keys, wrong types and fixed
  pseudonyms, and lists every problem with its place in the file.
- **walk-pass-v1**: 60 s of silence, then per person normal pace with shoes 50 passes, normal without shoes 20, slow 10,
  fast 10 (90 per person).
- **Use**: leave "run it step by step" ticked and start the recording. The runner card shows the current step (person,
  pace, shoes, pass n of 50, the instructions), the counters per person and overall, Back / Next / Skip and the step list.
  **Space** (or the phone) starts and ends each pass; the label takes person, pace and shoes from the step, and the runner
  moves on when the step has all its passes. For the silence, Space starts a 60 s countdown and the server ends the label
  itself. A mistaken pass: delete it in the label list (the counter goes back) and walk it again. The state lives in the
  server, so a reload or a second tab shows the same step.
- **Stop runner** returns to the manual label form; the recording's result lists the steps that are short of passes.
- The step id has no field in the sidecar (schema v1): a pass label carries `label: walk`, `person`, `pace` and `shoes`.
- Only the session's own protocol can run (`409 protocol_mismatch` for another). A step that already has all its passes
  (reached again with Back or Go) refuses a new mark (`409 step_complete`): delete one of its labels to redo it. While the
  silence countdown runs, the Live labels card says "the countdown ends it" and Space does nothing.

## Phase 4: rig checks

The Device page has a **Rig checks** card for [[Wire the first rig]]. Contract: `WEB_API.md` section 11; code:
`src/rezonating_lab/server/rigcheck.py` (thresholds are named constants at the top).

| Check | What it measures | Pass |
| --- | --- | --- |
| ADC answers | `adc_raw` in HELLO, samples after START | >= 100 samples within 3 s |
| Sample rate | linear fit of `t_dev_us` against the sample index over 60 s of device time | within +/-1.1 % of 2000 Hz |
| Noise floor | inputs shorted to AGND: RMS per channel, counts and input-referred uV (CONFIG scale) | <= 15 uV rms (provisional) |
| Tap test | "tap the sensor at CH0", then CH1: peak per channel (input volts) after the tap | asked channel larger, >= 2x, >= 5 mV |
| ADXL355 gravity | mean of 2 s of x, y, z | z 0.9 to 1.1 g, abs x and y <= 0.1 g |

Why +/-1.1 %: the LTC6903 is 0.5 % typical, 1.1 % max at 25 degC and 1.65 % max over temperature. A rig check runs at
room temperature, so anything beyond the 25 degC maximum means a bad part or a wrong OCT/DAC word; +1.65 % fails. The
measured rate goes into the build note either way: it is the real rate of this board.

- **Use**: connect, then Run all (or Run on one check). Steps that need a person (short the inputs; connect the heads
  for the tap test) wait for **Continue**; the tap test then asks for each channel and waits up to 20 s for a tap.
  On a simulator (`fw_version` ends in `-sim`) those steps are skipped and the taps are injected with `SET sim.tap`.
  Streams the checks start are stopped afterwards; streams already running stay running. Connect, START/STOP and SET
  are refused (409 `rigcheck_running`) while checks run; the checks stop with an error if a recording starts.
- **Report**: markdown for the build note (date, node, firmware, link, each check with numbers, limit and verdict),
  written to `<data root>/rigchecks/rigcheck_<YYYYMMDD-HHMMSS>_<node>.md` after every run (never into the repo), and
  offered by Copy report / Download report. Run all starts a new report; a single Run updates the current one.
- **Try it on the simulator**: `rzlab sim --shorted-inputs` passes every check (the noise floor needs shorted inputs;
  a plain `rzlab sim` fails it on purpose: footsteps on the inputs). `--clock-error 1.65` fails the rate,
  `--swap-channels` the tap test, `--no-gravity` the ADXL355 check, `--no-adc` the ADC check.
- The noise limit and the tap amplitude are provisional until the first real rig gives numbers.

## Phase 4: Review and SD import

Contract: `WEB_API.md` section 12.

- **Review page** (rail entry "Review"): pick a session of the data root. The waveform (min/max envelope, one lane per
  channel) and the spectrogram of one channel show the visible range; the wheel or the buttons zoom, dragging pans, a
  click sets the cursor. Under them the label lane: drag an edge to move it, select a label to split it at the cursor,
  merge it with the next one, delete it or re-tag it (label, person, pace, shoes) in the fields beside; "Add at cursor"
  adds a 0.5 s label. Undo/Redo (Ctrl+Z / Ctrl+Shift+Z) live in the page; a chip shows unsaved changes.
- Edits are sample indices of one stream (adc_raw or accel); `t0`/`t1` follow from them. A live label edited by hand
  keeps its `src` (the schema has no `edit` source) and loses its `unc_ms` when an edge moves; a label added here gets
  `src: review`. The other stream's sidecar is not changed.
- **Save** writes nothing that does not validate. It keeps the previous sidecar as `<sidecar>.json.bak` (one
  generation), writes the new one through `rezonating_ml.io`, re-runs the `rzlab validate` checks and the
  `tools/validate.py` schema check, shows the result, and updates the repository copy `data/<session>/` only when that
  copy exists and the session validates.
- **SD import**: the "Import from SD" card on the Review page, or

```bash
rzlab import-sd E:\RZ          # session folders in the recorder's layout, at most 4 levels below
```

  Each session is validated on the card first (invalid ones are listed with their problems and stay there), skipped if
  the data root already has it (never overwritten), copied to staging, validated again, moved into the data root, and its
  sidecars (never the WAVs) are copied to the repository's `data/<session>/`. Exit code 0, 1 (something invalid or
  failed) or 2 (bad folder, no data root).


## Phase 6: Datasets page

The Datasets page (rail entry "Datasets") lists every session: the sidecars in the repository's `data/` plus the session
folders on the data root, with date, site / room, floor, people (pseudonyms), duration, label count, protocol, validity
(with the errors), WAV present or missing, simulated, incomplete and loss totals. Filter, sort, open a session in Review
(`/review?session=<name>`), and build `data/manifest.json` (preview first; simulated and invalid sessions are left out
unless asked for). Contract: `WEB_API.md` section 13. Code: `src/rezonating_lab/datasets.py`, `server/dataset_routes.py`.

- Every per-recording field comes from `rezonating_ml.manifest` (`ml/README.md`, "Dataset manifest"); the lab does not
  re-read sidecars itself.
- The index is cached per machine in SQLite (`index_db` / `RZ_INDEX_DB`; default `%LOCALAPPDATA%\rzlab\datasets.sqlite`,
  `~/.cache/rzlab/datasets.sqlite` elsewhere; never inside the repository). The cache is keyed by each sidecar's and WAV's
  mtime and size, so only changed sessions are read again; **Rebuild index** drops it. Deleting the file is always safe.
- WAVs are hashed (SHA-256) only when a manifest is built or when "Compute SHA-256" is pressed for one session, never
  while indexing. `build_manifest` has no switch for this yet, so the lab turns its hashing off while it indexes (under a
  lock; see the `datasets.py` docstring).

## Simulated people and datasets (phase 4 dress rehearsal, phase 7 experiments)

```bash
rzlab sim --walkers P1,P2 --protocol walk-pass-v1 --speed 10   # the node walks the protocol itself
rzlab sim-dataset --out ~/rz-sim --sessions 6 --persons P1,P2,P3 --seed 7 --days 3 --floors lab office
rzlab validate ~/rz-sim
```

- **Gait model** (`sim/people.py`): every pseudonym has a seeded centre for cadence (and its jitter), step length,
  heel-strike resonance `f1` (about 26 to 46 Hz), damping, a second mode, a toe-off burst and its delay, amplitude
  and left/right asymmetry, each drawn independently per (seed, person, parameter). Pace (slow/normal/fast) and shoes
  off (softer, about 1.4x higher `f1`, shorter) change it; each floor, each day and the position along the 4 m line
  (two sensors, 2 m apart) change the coupling; every step adds jitter. `P1` is the same walker in every session of
  one seed, but walks a little differently in each session (`SESSION_DRIFT`, per person and session: `f1` and
  cadence up to ±8 %, amplitude ±24 %, damping ±12 %, and so on; not scaled by difficulty). The ground truth records
  both (`centres` and `profiles`, the latter as walked). The waveform is plausible, not physical.
- **Difficulty** (`--difficulty`, 0..1, default 0.5) scales how far apart the persons' centres are; the per-step
  jitter and the session drift do not scale. Measured on **synthetic data only** (3 persons, 6 sessions on 2 floors
  at `--passes-scale 0.2`, about 1350 footsteps, `footstep_v1` on ch0; balanced accuracy; *by session* = mean of 3
  folds with one test session per floor, *by window* = mean of 3 random splits holding out a third of the windows):

  | seed 7, difficulty | 0 | 0.25 | 0.5 | 0.75 | 1 (chance 0.33) |
  | --- | --- | --- | --- | --- | --- |
  | logistic regression, by session / by window | 0.89 / 0.90 | 0.81 / 0.82 | 0.70 / 0.72 | 0.49 / 0.54 | 0.34 / 0.42 |
  | random forest, by session / by window | 0.89 / 0.90 | 0.80 / 0.83 | 0.64 / 0.71 | 0.46 / 0.55 | 0.35 / 0.46 |

  Over seeds 1, 2, 3, 4, 5 and 7 at difficulty 0.5, the split by session scores 0.50 to 0.70 with logistic regression (mean
  0.58) and 0.51 to 0.73 with a random forest (mean 0.60); the split by window is higher on every seed, by 0.02 to
  0.10 (logistic regression) and 0.04 to 0.13 (random forest). That gap is the leakage a split by window hides
  (at difficulty 1 it is all there is), and `tests/test_sim_people.py` checks it. Persons are drawn at random, so
  some seeds put two of them close together (seeds 1, 3 and 4 are harder than 7). These numbers describe the
  simulator, not the pack, and say nothing about real people or floors.
- **`rzlab sim --walkers`**: the walk starts `--walk-start` device seconds (default 10) after the ADC acquisition
  starts: 60 s of silence, then per person every passes step of the protocol (a pass is N steps along the line, then a
  3 s pause; 4 s between steps). After the last pass only the noise floor remains. `--truth` logs every footstep with
  `person`, `pace`, `shoes`, `pass` and its index in `adc_raw`, `adc_dec` and `accel`. Without `--walkers` nothing
  changes.
- **`rzlab sim-dataset`** writes the recorder's layout (`<session>/<session>.adc|accel.wav|json`, v1 sidecars through
  `rezonating_ml.io`), one label per pass (`src: auto`, person, pace, shoes) plus the silence, notes with
  `rzlab: source=sim` (so the Datasets page and the manifest leave them out), a measured rate per session (LTC6903
  error drawn per session), one work day (Monday or Tuesday) per session unless `--days` is smaller, and the ground
  truth in `<out>/<session>.truth.jsonl`. Every session is validated as it is written. `--passes-scale 0.2` makes
  quick sets. The accelerometer stream carries only gravity, hum and noise (no footsteps).
- **Where `--out` may go**: never inside the repository (only `*.wav` is ignored there, so truth files and sidecars
  could be committed) or the sidecar folder (`sidecar_dir`), and not inside the configured data root unless
  `--into-data-root` is given. A refused `--out` exits with code 2 and writes nothing.

## Phase 5: pack bench

The Bench page (`/bench`, REST in `WEB_API.md` "Pack bench") runs a pack (`packs/*/pack.json`) stage by stage on a
source: **live** (the connected node's `adc_raw` ring, fed to one `build_pipeline` chunk by chunk as it arrives),
**recording** (a session in the data root, read through `rezonating_ml.io`, lost frames from `zero_fill_mask` and the
sidecar's loss total) or **simulator** (a `rzlab sim-dataset` session, with its `<session>.truth.jsonl`, or the live
simulator). Every number comes from `rezonating_ml` (D-017, D-021): filtered signal, STA/LTA ratio and threshold,
events and windows (`n_invalid`), the 13 `footstep_v1` features per window, and the model output, greyed out
(`not_available`) until "train a baseline" fits `baseline.train_baseline_model` on the selected sessions' labels
(in memory only; scores on the training sessions are in-sample).

- **Trigger tuning**: sliders for `sta_ms`, `lta_ms`, `ratio`, `pre_ms`, `post_ms` re-run the pipeline. "Save to
  pack.json" shows the diff first, rewrites only the `trigger` block (layout and key order kept), validates the file
  with `tools/validate.py`'s pack schema check and puts the old file back on any error. Changing footstep-id's
  trigger invalidates `ml/tests/vectors` (regenerate with `python -m rezonating_ml.vectors --write` and tell firmware).
- **Scoring** (sim sessions with a truth file): an event matches a truth step when its onset, mapped to the `adc_raw`
  index (`Pipeline.to_input_index`), lies within **±50 ms** of the step's `sample_adc_raw` (50 samples at the 1 kHz
  pack rate); each step and event is used once, nearest first. Precision, recall and onset error (event − truth, ms;
  the STA/LTA onset is the threshold crossing, so it lags the step start).
- **Compare**: node EVENT frames vs Python events on the same `adc_dec` indices (live source; pack as saved). Matched,
  missing (node only), extra (Python only) and the index differences of near misses. The last second is left out
  (the node sends EVENTs in blocks). Against the simulator this is Python vs Python (above).
- **Test vectors**: "Create test vector from clip" writes an `sta_lta.json`-format file (input = the decimated and
  filtered clip, expected = `rezonating_ml`'s STA/LTA from a fresh state, a `masked` case when the clip holds lost
  samples) into a folder you choose (default `<data root>/bench-vectors`; `ml/tests/vectors` is refused, it belongs to
  `python -m rezonating_ml.vectors`). "Check" re-runs the current STA/LTA stage on a vector file.
