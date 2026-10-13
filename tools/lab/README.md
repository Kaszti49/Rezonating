# Rezonating Lab (phases 1 to 3)

Bench tool for the node link: protocol v0 codec, a simulated node, a text monitor (phase 1) and the web
server `rzlab serve` for the browser UI (phase 2).
Spec: `PROTOCOL.md`. Web API for the UI: `WEB_API.md`. Golden vectors for the firmware: `tests/vectors/link-v0.json`.

## Install

```bash
pip install -e ml -e "tools/lab[dev]"   # gives the `rzlab` command; Python 3.10+, numpy, pyserial, fastapi, uvicorn, segno
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

`rzlab tail` prints measured rate (from STATUS and from its own `t_dev_us` fit) with the offset against
nominal, then received / dev / link / gap (host gap) / bad_frames / lost_frames. Ctrl+C sends STOP and
prints the final per-stream loss summary.

Regenerate the vectors after a protocol change: `python -m rezonating_lab.link.vectors --write`.
`adc_dec` in the simulator is a placeholder (every 2nd raw sample, no FIR).

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
2. **New session**: site and room (required), floor, surface, protocol, persons as pseudonyms only (`P1`, `P2` ...; anything
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
Other settings: `RZ_STAGING_DIR` (WAV files are written there, so a folder inside the repository is refused too), `RZ_MARKER_PORT`, `RZ_MARKER_BIND` (default `auto`: the phone marker listens on one address, the first LAN address of this PC, never every interface; the Record page lets you pick another interface before the recording starts, e.g. with a VPN; set `0.0.0.0` if you want every interface), `RZ_MARKER_HOST` (only used with `RZ_MARKER_BIND=0.0.0.0`: the address in the QR code; otherwise the QR code always names the address the marker listens on), `RZ_REPO_ROOT`. `sidecar_dir` is meant to be in the repository (`data/`): only validated `.json` sidecars are ever copied there.

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
