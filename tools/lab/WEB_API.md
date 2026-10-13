# Rezonating Lab web API (phases 2 to 6)

The contract between `rzlab serve` (`src/rezonating_lab/server/`) and the browser UI (Svelte + Vite + uPlot, built
in a later run). Everything the UI needs is here. The server is the only thing that talks to the node; the UI
talks to the server over **REST** (commands, history views) and **one WebSocket** (live samples and events).

Interactive reference generated from the code: `http://127.0.0.1:8765/api/docs` (OpenAPI at `/api/openapi.json`).

Contents: 1 Basics, 2 Errors, 3 REST commands, 4 WebSocket, 5 View requests (scroll-back, PSD, spectrogram,
levels), 6 Unit and time rules, 7 Flows, 8 Limits, **9 Recorder and live labels (phase 3)**, **10 Protocol runner
(phase 4)**, **11 Rig checks (phase 4)**, **12 Review and SD import (phase 4)**, **13 Datasets and the manifest (phase 6)**.

## 1. Basics

- **Base URL:** `http://127.0.0.1:8765` (`rzlab serve --port` changes it). Loopback only. Use relative URLs
  (`/api/...`, `ws://${location.host}/ws`) so the page works on `127.0.0.1`, `localhost` and `[::1]`.
- **Host and Origin are checked** on every HTTP request and on the WebSocket handshake. Allowed `Host`:
  `127.0.0.1:PORT`, `localhost:PORT`, `[::1]:PORT` (PORT = the server port; **5173** only when the server runs with
  `rzlab serve --dev`). Allowed `Origin` (when the request has one): `http://127.0.0.1:PORT`, `http://localhost:PORT`,
  `http://[::1]:PORT` for the same ports. Anything else: HTTP 403 with `error.code` `bad_host` or `bad_origin`; a WebSocket handshake is closed
  before it is accepted: uvicorn answers the handshake with HTTP 403, so `new WebSocket()` fires `error` then
  `close`, never `open`. There is no CORS: do not call the server from another origin.
- **Dev server.** Start the server with `rzlab serve --dev` (without it, port 5173 is a foreign origin and gets 403, so
  another local project on 5173 cannot call the API). Run `npm run dev` (Vite, port 5173) and proxy `/api` and `/ws` to `http://127.0.0.1:8765`
  (`server.proxy` with `ws: true`, `changeOrigin: false`). The Vite page then talks to the server through the
  proxy and passes both checks. Production build: `vite build` with `build.outDir = '../src/rezonating_lab/static'`
  and `emptyOutDir: true` (this is what `rzlab build-ui` expects); the server serves it at `/` with a fallback to
  `index.html` for unknown non-`/api` paths (client-side routes like `/live`, `/device`).
- **JSON** everywhere. Numbers that are NaN or infinite are sent as `null`. Timestamps `t` are the server's
  Unix time in seconds (float). Device timestamps `t_dev_us` are the node's microsecond clock.
- **Stream ids:** `0 adc_raw` (2 ch, 2000 Hz nominal), `1 adc_dec` (2 ch, 1000 Hz), `2 accel` (3 ch, 2000 Hz).
  The node's `hello` event is authoritative. Anywhere a stream is named in a request, the name (`"adc_raw"`) or
  the id (`0`, or `"0"` in a query string) is accepted.
- **Sample indices** are the node's 64-bit per-stream indices (PROTOCOL.md 4.3). Treat them as JavaScript numbers
  (safe up to 2^53, which is thousands of years at 2 kSPS). Time on screen is `index / fs_hz` (section 6).
- **Counts, volts, g.** Samples travel as raw int32 **codes**. The `config` event carries `scale` (code to unit)
  and `units` per channel; the UI shows counts, V or g by multiplying. Gain and range change only while idle.

## 2. Errors

Every non-2xx REST answer has this shape, whatever went wrong:

```json
{ "error": { "code": "busy", "message": "The node is busy (ERR 5): adc.gain.0 is not allowed while it is acquiring. Stop acquisition on adc_raw and adc_dec first, then change the gain.", "node_code": 5, "event_id": 12 } }
```

`message` is written for the user and can go straight into a toast. `node_code` is the node's `ERR` code
(PROTOCOL.md 4.7) when the node refused. `event_id` is set when the same error was also pushed as a WebSocket
`error` event (field `id`): show one toast per id, not two.

| `code` | HTTP | Meaning |
| --- | --- | --- |
| `invalid_request` | 400 / 422 | Bad body or query (422 carries `details: [{loc, msg}]`), bad serial URL, bad key, unknown stream name in a request body |
| `not_connected` | 409 | Command needs a connected node |
| `busy` | 409 | Node `ERR 5`: gain / range cannot change while that sensor is acquiring |
| `bad_value` | 400 | Node `ERR 4`: value not allowed (gain must be 1, 2, 4 ... 128; range 2, 4, 8) |
| `unknown_key` | 400 | Node `ERR 3`, or a key the UI may not set |
| `not_authorised` | 403 | Node `ERR 6` (wrong or missing pairing key) |
| `node_error` | 502 | Any other node `ERR` |
| `connect_failed` | 502 | Could not open the TCP connection or serial port |
| `session_failed` | 502 | Connected, but no `HELLO`/`CONFIG` within 3 s, or the node refused the session |
| `link_lost` | 502 | The transport died during a command |
| `timeout` | 504 | No `ACK` for START (2 s), STOP (3 s) or SET (2 s) |
| `no_stream` | 404 | View request for a stream that is not known (not connected yet, or a wrong name) |
| `not_found` | 404 | No such endpoint |
| `bad_host`, `bad_origin` | 403 | Security guard (section 1) |
| `http_<status>` | | Any other framework error |

## 3. REST commands

All bodies are `application/json`. Commands run on the server's single device thread, one at a time; `connect`
can take up to about 5 s (handshake 3 s + clean-up STOP 2 s), so show a spinner.

### `GET /api/state`
The latest event of each kind, as a snapshot (what a WebSocket client also gets on connect):

```json
{ "type": "state", "clients": 1,
  "connection": { ... }, "hello": { ... }, "config": { ... }, "status": { ... } }
```
`hello`, `config` and `status` are missing until a node has connected. The objects are exactly the WebSocket
events of the same name (section 4.3).

### `GET /api/ports`
Serial ports from pyserial; the ESP32-S3 USB-Serial/JTAG (VID:PID `303A:1001`) sorts first and has `is_node: true`.
```json
{ "ports": [ { "device": "COM9", "description": "USB Serial Device (COM9)", "hwid": "USB VID:PID=303A:1001 SER=...",
               "manufacturer": "Espressif", "serial_number": "A1B2C3", "vid_pid": "303A:1001", "is_node": true },
             { "device": "COM1", "description": "Communications Port (COM1)", "hwid": "ACPI\\PNP0501\\2",
               "manufacturer": "(Standard port types)", "serial_number": null, "vid_pid": null, "is_node": false } ] }
```

### `POST /api/connect`
Disconnects the current node (politely: STOP, then close), then connects. Fresh accounting and empty ring buffers.

| Field | Type | Notes |
| --- | --- | --- |
| `kind` | `"sim"` \| `"tcp"` \| `"serial"` | required |
| `host`, `port` | string, int | `tcp` (port default 7350); `sim` uses `127.0.0.1` and `port` (default 7350) |
| `url` | string | `serial`: `COM5`, `/dev/ttyACM0` or `socket://127.0.0.1:7350`. Nothing else is accepted |
| `key` | string | pairing key, 32 hex digits. With a key the session starts with `AUTH` (Wi-Fi nodes), otherwise with `GET_INFO` (USB, simulator) |

`kind: "sim"` is TCP to the simulator at `127.0.0.1:7350`. If nothing listens there the server starts an
in-process simulator on that port (unless started with `--no-embedded-sim`); the `connection` event then has
`embedded_sim: true`.

Response `200`: `{ "state": "connected", "node_id": "rzn-sim001" }`. Errors: `connect_failed`, `session_failed`,
`not_authorised`, `invalid_request`. After success the connection is idle: nothing streams until `acquisition`.

### `POST /api/disconnect`
Stops running streams (STOP with a 1.5 s wait), closes the transport. The ring buffers and the last accounting stay
viewable. `200 { "state": "disconnected" }`.

### `POST /api/acquisition`
```json
{ "action": "start", "streams": ["adc_raw", "accel"] }
```
`action`: `"start"` or `"stop"`. `streams`: names or ids; omit (or `[]`) for every stream the node has. A stream that
starts from idle gets a new ring epoch and its indices restart at 0 (a `stream_reset` event announces it).
`200`: `{ "started": 5 }` or `{ "stopped": 7 }` (the stream mask). `stop` returns after the node drained its queue and
sent the final `STATUS`: the loss numbers of the stopped streams are then final (`loss.final: true`).

### `POST /api/set`
```json
{ "key": "adc.gain.0", "value": 16 }
```
`key`: `adc.gain.0`, `adc.gain.1` (value 1, 2, 4, 8, 16, 32, 64, 128) or `accel.range_g` (2, 4, 8).
`value` must be a JSON integer. `200`: `{ "set": "adc.gain.0", "value": 16 }`, and a new `config` event follows
(the answer is sent after it arrived, so `/api/state` is already up to date). `409 recording_active` while a recording
runs (the sidecar's gain and scale are those at the start).
**While that sensor is acquiring the node answers `ERR 5` and the server returns `409 busy`** (section 2);
`adc.gain.*` is blocked while `adc_raw` or `adc_dec` runs, `accel.range_g` while `accel` runs. Show the message and
offer "Stop acquisition".

### `GET /api/logs?limit=200`
The last up to 500 log lines (node `LOG` frames and host messages), oldest first: `{ "logs": [ <log event>, ... ] }`.

### `GET /api/health`
`{ "ok": true, "version": "0.1.0" }`.

View requests (`/api/view/...`) are in section 5.

## 4. WebSocket `/ws`

One socket for everything live. Open it with `new WebSocket(`ws://${location.host}/ws`)` and set
`ws.binaryType = 'arraybuffer'`.

- **Query:** `?streams=0,1,2` limits the binary frames to those stream ids (default all). The device page can use
  `?streams=` with an id that does not exist, e.g. `?streams=99`, to receive events only. JSON events are never filtered.
  A non-numeric value is refused.
- **Direction.** Server to client only, except two optional text messages from the client:
  `{"op":"snapshot"}` (the server re-sends `connection`, `hello`, `config`, `status`, `recording`, `runner`) and
  `{"op":"streams","streams":[0,2]}` (change the filter; `null` = all).
- **On connect** the server sends, in this order, whichever exist: `connection`, `hello`, `config`, `status`,
  `recording` (section 9.4), `runner` (section 10.3) (JSON text). Binary frames then contain only samples that arrive **after** the socket opened. Use the view requests
  (section 5) to fill the screen with history.
- **Rate:** binary frames are produced about 20 times per second. Per tick and stream there is one message per
  contiguous run of new samples (normally exactly one; about 100 samples for `adc_raw`, 50 for `adc_dec`, 100 for
  `accel` at the simulator's 1x speed; proportionally more at higher speed). `status` events come about once per
  second.
- **Slow client.** If the browser stops reading and its queue (600 messages) fills up, the server closes the socket
  with code 1013. Reconnect (and reload history).
- **Reconnect.** The server keeps running without the browser. On reconnect, send nothing; just handle the snapshot
  and refetch history through the view requests.

### 4.1 Binary sample frame

A WebSocket **binary** message, little-endian, a 20-byte header and then the samples. 20 is a multiple of 4, so the
samples can be read with an `Int32Array` view directly on the received `ArrayBuffer`.

| Offset | Size | Type | Field | Meaning |
| --- | --- | --- | --- | --- |
| 0 | 1 | u8 | `msg_type` | `1` = samples (the only one in v0; ignore other values) |
| 1 | 1 | u8 | `stream` | stream id (0 `adc_raw`, 1 `adc_dec`, 2 `accel`) |
| 2 | 1 | u8 | `n_ch` | channels in this stream (2, 2, 3) |
| 3 | 1 | u8 | `dtype` | `0` = int32 codes (the only one in v0). `1` is reserved for float32 |
| 4 | 2 | u16 | `epoch` | ring epoch modulo 65536. A change means the stream's indices restarted: clear that stream's display |
| 6 | 2 | u16 | `flags` | reserved, 0 |
| 8 | 8 | u64 | `first_sample` | sample index of the first frame in this message |
| 16 | 4 | u32 | `n` | sample frames in this message (at most 8192) |
| 20 | `n * n_ch * 4` | i32[] | `samples` | frame-major: `s0.ch0, s0.ch1, ..., s1.ch0, ...` |

Total length is exactly `20 + 4 * n * n_ch`. Decoding:

```ts
const dv = new DataView(buf);
const stream = dv.getUint8(1), nCh = dv.getUint8(2), epoch = dv.getUint16(4, true);
const first = Number(dv.getBigUint64(8, true)), n = dv.getUint32(16, true);
const codes = new Int32Array(buf, 20, n * nCh);        // codes[i * nCh + ch]
```

**Gaps are never filled.** Lost samples (node drops, link drops, corrupted frames) are not sent. After a hole the
next message's `first_sample` is greater than `previous.first_sample + previous.n`. Draw that as a gap (uPlot: `null`
values for the missing indices, or `spanGaps: false`); never shift later samples left. Messages of one stream are in
order of increasing `first_sample` within an epoch.

### 4.2 Keeping a live window

Per stream keep `epoch`, `nextIndex` and a ring of the last N seconds, indexed by `first_sample`. On a message:
if `epoch` differs from the stored one, clear the stream; otherwise fill the skipped indices
(`nextIndex ... first_sample - 1`) with `NaN`; then append. The x value of sample `i` is `i / fs_hz`, with `fs_hz`
from the stream's latest `status` (`rate_hz_fit ?? rate_hz_status ?? nominal_hz`).

### 4.3 JSON events

Text messages, each `{"type": ..., "t": <server unix seconds>, ...}`.

**`connection`**: sent on every change.
```json
{ "type": "connection", "state": "connected", "link": "serial", "target": "socket://127.0.0.1:7350",
  "embedded_sim": false, "error": null, "t": 1791794837.64 }
```
`state`: `disconnected` | `connecting` | `connected` | `disconnecting`. `link`: `tcp` | `serial` | `sim` | `null`.
`error`: text of the last failure (`connect failed`, `connection lost: ...`) while `disconnected`, else `null`.

**`hello`**: the node, once per connection.
```json
{ "type": "hello", "proto": 0, "fw_version": "0.1.0-sim", "node_id": "rzn-sim001", "t_dev_us": 5000000,
  "streams": [
    { "id": 0, "name": "adc_raw", "n_ch": 2, "nominal_hz": 2000, "bits": 24, "full_scale": 8388608, "clock": "ltc6903", "fir_taps": 0, "fir_delay": 0 },
    { "id": 1, "name": "adc_dec", "n_ch": 2, "nominal_hz": 1000, "bits": 24, "full_scale": 8388608, "clock": "ltc6903", "fir_taps": 1, "fir_delay": 0 },
    { "id": 2, "name": "accel", "n_ch": 3, "nominal_hz": 2000, "bits": 20, "full_scale": 524288, "clock": "adxl355", "fir_taps": 0, "fir_delay": 0 } ],
  "heads": [ { "port": 1, "descriptor": { "...": "head descriptor JSON, or null if unreadable" } } ],
  "t": 1791794837.7 }
```
`full_scale` is `2^(bits-1)`: a code `>= full_scale - 1` or `<= -full_scale` is clipped.

**`config`**: gains, scales and units; resent after every `SET`.
```json
{ "type": "config",
  "streams": [
    { "id": 0, "name": "adc_raw", "channels": [ { "gain": 8, "scale": 1.7881394e-08, "units": "V" }, { "gain": 8, "scale": 1.7881394e-08, "units": "V" } ] },
    { "id": 1, "name": "adc_dec", "channels": [ { "gain": 8, "scale": 1.7881394e-08, "units": "V" }, { "gain": 8, "scale": 1.7881394e-08, "units": "V" } ] },
    { "id": 2, "name": "accel", "channels": [ { "gain": 1, "scale": 3.9062502e-06, "units": "g" }, { "gain": 1, "scale": 3.9062502e-06, "units": "g" }, { "gain": 1, "scale": 3.9062502e-06, "units": "g" } ] } ],
  "accel_range_g": 2, "status_period_ms": 1000, "t": 1791794837.7 }
```
`units`: `counts` | `V` | `g`. `value = code * scale`. ADC: volts at the ADC input (divide by the head's sensitivity to
get m/s^2 etc.).

**`status`**: about once per second, plus right after connect, START and STOP.
```json
{ "type": "status", "state": "connected",
  "node": { "node_id": "rzn-sim001", "fw_version": "0.1.0-sim", "proto": 0 },
  "link": { "type": "sim", "target": "127.0.0.1:7350", "rtt_ms": 0.83, "bad_frames": 0, "lost_frames": 0, "resyncs": 0,
            "unknown_types": 0, "frames_ok": 116, "bytes_in": 56107, "rx_bytes_per_s": 48289.6,
            "last_rx_age_s": 0.04, "stale": false },
  "health": { "queue_fill": 0, "heap_free": 181156, "temp_c": 41.1, "rssi_dbm": null, "sd_state": 1, "sd_free_mb": 14000, "t_dev_us": 17031000 },
  "streams": [
    { "id": 0, "name": "adc_raw", "n_ch": 2, "nominal_hz": 2000, "running": true,
      "rate_hz_status": 2015.625, "rate_hz_fit": 2015.97, "offset_pct_status": 0.78, "offset_pct_fit": 0.80,
      "produced": 2016, "node_device_dropped": 0, "node_clipped": 0, "packets": 26, "samples": 2097, "timing_flags": 0,
      "loss": { "device": 0, "link": 0, "host": 0, "host_exact": true, "host_max": 0, "pending": 0, "received": 2016,
                "missing": 0, "window": 2016, "win_first": 0, "win_end": 2016, "final": false, "incomplete": false, "protocol_bug": false },
      "levels": [ { "mean": 1.8e-05, "rms": 1.66e-04, "std": 1.65e-04, "peak": 1.29e-03, "clipped": 0, "n": 2015, "units": "V" },
                  { "mean": 1.4e-05, "rms": 9.2e-05, "std": 9.1e-05, "peak": 7.2e-04, "clipped": 0, "n": 2015, "units": "V" } ],
      "epoch": 1, "head": 2097 } ],
  "acquiring": true, "recording": false, "t": 1791794840.1 }
```
Field notes:
- `state`, `node`, `link`: `node` is `null` before the first connect. `link.rtt_ms` is the PING/PONG round trip; `stale: true` when no frame has come from the node for 3 s. After the link is lost, `link` keeps only `type` and `target`.
- `health` is `null` until the first node `STATUS`. `rssi_dbm` is `null` when Wi-Fi is off. `sd_state`: 0 none, 1 ready, 2 recording, 3 error. `queue_fill` is the node's send-queue fill in percent.
- Per stream: `rate_hz_status` is the node's own measurement (10 s window), `rate_hz_fit` the server's fit of `t_dev_us` against the sample index. `offset_pct_*` is the offset against `nominal_hz` in percent (the LTC6903 clock is typically +0.5 %). Either rate can be `null` for the first seconds.
- **Loss counters (the three numbers to show):** `loss.device` (lost on the node), `loss.link` (lost between node and server: queue full, write errors), `loss.host` (sent but never arrived: corrupted or lost frames). `loss` is `null` until the stream's START is acknowledged. **When `host_exact` is `false` the live `host` value is a lower bound: show it as `host+` (for example `12+`)**; `host_max` is the upper bound. `pending` samples are still in flight and are not counted as lost. `final: true` means the stream was stopped and its last `STATUS` has arrived, so the numbers are exact. `incomplete: true` means the session ended without a final `STATUS` (everything unattributed counts as host). `protocol_bug: true` means `host` came out negative (a bug in the node or the lab; show an error).
- `levels` (last 1 s of the ring, in the channel's unit): `rms` about zero, `std` about the mean, `peak` = max |value|, `clipped` = samples at full scale in that second. `null` while the ring is empty. `node_clipped` is the node's own cumulative count since acquisition started.
- `epoch` and `head` mirror the ring buffer (see section 5): `head` is one past the newest stored index.
- `recording` is `true` while a recording runs (section 9). `acquiring` is true when any stream is running.

**`log`**: node `LOG` frames and host messages.
```json
{ "type": "log", "source": "node", "level": 3, "level_name": "info", "t_dev_us": 17031000, "tag": "ads131", "msg": "drdy ok", "t": 1791794840.2 }
{ "type": "log", "source": "host", "level": 3, "level_name": "info", "t_dev_us": null, "tag": "lab",
  "msg": "no simulator was listening: started an embedded one on 127.0.0.1:7350", "t": 1791794830.0 }
```
`level`: 1 error, 2 warn, 3 info, 4 debug, 5 verbose.

**`error`**: a command failed or the link broke. Same fields as the REST error, plus `id` and `command`.
```json
{ "type": "error", "id": 12, "command": "set adc.gain.0", "code": "busy", "node_code": 5, "event_id": 12,
  "message": "The node is busy (ERR 5): adc.gain.0 is not allowed while it is acquiring. Stop acquisition on adc_raw and adc_dec first, then change the gain.", "t": 1791794841.0 }
```
`command` is `connect`, `start`, `stop`, `set <key>`, `link` (transport died) or `command`. A stray node `ERR` that no
command waited for is only logged (`log`, level 2).

**`stream_reset`**: a stream's indices restarted; its ring is empty.
```json
{ "type": "stream_reset", "stream": 0, "name": "adc_raw", "epoch": 3, "t": 1791794839.9 }
```
Clear that stream's display. The same `epoch` (mod 65536) is in the following binary frames.

## 5. View requests (history, PSD, spectrogram, levels)

The server keeps **at least the last 10 minutes** of each stream (`600 s x nominal_hz x 1.02` samples) in ring
buffers, indexed by sample index; missing samples are gaps. The server does the display maths (`core/view.py`);
the browser only draws. All are `GET`, JSON, and run off the event loop. After a reconnect or disconnect the data
of the last window stays available until the next connect.

**Common query parameters**

| Parameter | Default | Notes |
| --- | --- | --- |
| `stream` | required | name or id |
| `window_s` | 10 (levels: 1) | window length in seconds, 0 < x <= 900, converted to samples with the measured `fs_hz` |
| `end` | newest | sample index of the right edge (exclusive); omit for "now", pass a smaller value to scroll back. Clipped to what the ring holds |

**Common response fields**
```json
{ "stream": 0, "name": "adc_raw", "n_ch": 2, "epoch": 1, "fs_hz": 2015.99, "fs_source": "fit", "nominal_hz": 2000,
  "scale": [1.788e-08, 1.788e-08], "units": ["V", "V"], "lo": 16370, "hi": 26450, "head": 26450, "oldest": 0 }
```
`lo`/`hi` are the sample indices actually returned (`[lo, hi)`); `head` is the newest index + 1 and `oldest` the
lowest still held (`null` when empty). `fs_hz` is the rate the maths used: `fs_source` `fit` (from timestamps),
`status` (node's measurement) or `nominal`. If a request returns fewer samples than asked, the ring did not hold more.
A stream the node does not have, or nothing connected yet: `404 no_stream`.

### `GET /api/view/envelope`: scope and scroll-back
Min/max per pixel column, so a wide window never needs more than `columns` points and a one-sample spike never
disappears.

Extra parameter: `columns` (1..4000, default 1000; use the plot's pixel width). Response (plus the common fields):
```json
{ "columns": 8, "samples_per_column": 1260.0,
  "min": [[-49646, -61614, -48470, ...], [-26448, ...]],
  "max": [[54527, 68363, 53028, ...],   [29824, ...]],
  "gap": [0, 0, 0, 0, 0, 0, 0, 0], "valid_samples": 10080 }
```
- `min` and `max` are `[channel][column]` **integer codes** (multiply by `scale[ch]` for volts / g). `null` in a
  column where no valid sample exists (a gap).
- `gap[c]` is `1` for such a column. `valid_samples` counts the non-gap samples in `[lo, hi)`.
- `columns` in the answer is `min(requested, hi - lo)`. Column `c` covers the sample indices
  `[lo + floor(c * (hi - lo) / columns), lo + floor((c + 1) * (hi - lo) / columns))`, so its x position is
  `(lo + c * (hi - lo) / columns) / fs_hz`.
- Draw each column as a vertical bar from `min` to `max` (or uPlot band series with `min` and `max`).
- Live scrolling at 20 Hz uses the WebSocket frames; use this request when the window is wider than the live buffer,
  when the user pans or zooms back, and on (re)connect.

### `GET /api/view/psd`: spectrum
Welch PSD (Hann window, 50 % overlap, constant detrend, density scaling, one-sided) of the window, computed on the
scaled values. Segments that touch a gap are skipped.

Extra parameter: `nperseg` (64..16384, default 1024; frequency resolution is `fs_hz / nperseg`). Response (plus common):
```json
{ "nperseg": 1024, "n_segments": 38, "freq_hz": [0.0, 1.9688, 3.9375, ...],
  "psd": [[1.2e-14, 3.4e-15, ...], [..], [..]], "psd_units": ["g^2/Hz", "g^2/Hz", "g^2/Hz"] }
```
`psd[ch][bin]` is in `units^2/Hz` (`null` when no segment was usable); `freq_hz` has `nperseg/2 + 1` values up to
`fs_hz / 2`. Plot dB as `10 * log10(psd)` on the client. `nperseg` shrinks to the data length for short windows
(read `nperseg` from the answer).

### `GET /api/view/spectrogram`: scrolling spectrogram
STFT columns of **one channel** (Hann window, density scaling, in dB).

| Parameter | Default | Notes |
| --- | --- | --- |
| `channel` | 0 | 0..n_ch-1 (`400 invalid_request` otherwise) |
| `nfft` | 256 | 32..4096; bins = `nfft/2 + 1` |
| `hop` | auto | samples between columns. Omitted: `max(nfft/2, ceil((hi-lo) / max_columns))`. **Pass the `hop` from the first answer on every later request** so columns stay on the same grid |
| `max_columns` | 300 | 1..1000; only the newest `max_columns` columns are returned |
| `since` | none | only columns whose `center_index` is greater than this (incremental update) |

Response (plus common):
```json
{ "channel": 0, "nfft": 256, "hop": 128, "freq_hz": [0.0, 7.875, ...],
  "center_index": [16512, 16640, ...], "db": [[-142.3, -150.1, ...], [..]],
  "db_units": "dB re V^2/Hz" }
```
`db[col][bin]` (`null` for a column whose window touches a gap), `center_index[col]` is the sample index at the
middle of the column (x = `center_index / fs_hz`). Columns lie on a grid: window start = multiple of `hop`, so
`center_index = k * hop + nfft/2`, and a request with `since = last center_index` returns exactly the next columns.
**Scrolling pattern:** first request with `window_s` = the visible span; remember `hop` and the last `center_index`;
every 0.5-1 s request `?hop=<hop>&since=<last>&window_s=<span>` and append the new columns, dropping old ones.
Bandwidth: 300 columns x 129 bins is about 250 kB as JSON; an incremental update is a few kB.

### `GET /api/view/levels`: RMS, peak, clipping
Same parameters (default `window_s` 1). Response (plus common):
```json
{ "channels": [ { "n": 2016, "mean": 1.8e-05, "rms": 1.66e-04, "std": 1.65e-04, "peak": 1.29e-03, "clipped": 0, "units": "V" }, ... ] }
```
Values are in the channel's unit (`code * scale`); `clipped` counts samples at full scale in the window; NaN becomes
`null` when the window is empty. The same numbers for the last second are already in every `status` event.

## 6. Unit and time rules

- **x axis:** time of sample `i` is `i / fs_hz` seconds since the stream's index 0 (since the stream was started
  from idle). Use the stream's measured `fs_hz`, not the nominal one: the LTC6903 clock is 0.5 % typ off (the
  simulator defaults to +0.8 %), which would stretch every frequency by that much. Streams have different clocks;
  align them on the device clock only if needed (phase 3).
- **adc_dec** is delayed by `fir_delay` raw samples against `adc_raw` (from `hello`); the simulator reports 1 tap and 0 delay.
- **y axis:** codes -> `value = code * scale[ch]`, label with `units[ch]`. Offer a "counts" toggle.
- **Clipping:** a code with `code >= full_scale - 1 || code <= -full_scale` is clipped; mark the samples or show the counter.

## 7. Flows

**Live page.** `GET /api/state` (render connection, hello, config) -> open `/ws` -> if the node is connected and idle,
`POST /api/acquisition {"action":"start"}` -> for the scope, call `/api/view/envelope?stream=...&window_s=10&columns=<width>` once
for history, then append WebSocket frames (section 4.2) -> PSD every 1 s with `/api/view/psd` -> spectrogram with
`/api/view/spectrogram` using `hop` + `since`. On a `stream_reset` or `epoch` change, clear and refetch.

**Device page.** `GET /api/ports` for the port list (offer the `is_node` one first), a form for `tcp` host/port/key,
a "Simulator" button (`kind: "sim"`); show `status.link` (type, rtt, bad/lost frames, rx rate), `status.health`
(heap, temperature, RSSI, queue fill), the three loss counters per stream, the measured rate with `offset_pct`, and the
`log` list (`GET /api/logs` once, then `log` events). Gain and range selectors call `POST /api/set`; on `busy` show the
message with a "Stop acquisition" button.

**Switching transport.** Just `POST /api/connect` again with the other kind. The server stops the old session,
resets the rings (you get `stream_reset` events and new `hello` / `config`), and counts from zero.

## 8. Limits

- One node connection at a time. One session on the node at a time (a second client gets `ERR 5`).
- Ring buffers: 600 s at the nominal rate (+2 %), 8 + 8 + 12 bytes per frame of the three streams, plus one validity byte, about 33 MB in total.
- WebSocket: ~20 binary messages/s/stream, at most 8192 frames per message, client queue 600 messages (then close 1013).
- View requests: `window_s` up to 900 (more than the ring holds is simply clipped), `columns` up to 4000,
  spectrogram `max_columns` up to 1000. Each request is computed on the server in a worker thread.
- Recording, labelling and file output are section 9.

## 9. Recorder and live labels (phase 3)

Everything the Record page needs. Files are written by the server; the browser only sends a form, key events and
reads progress. Nothing in this section changes sections 1 to 8 except that `status.recording` is now real and four
commands are refused while a recording runs (below).

Contents: 9.1 Rules, 9.2 Setup (options, data root), 9.3 Start and stop, 9.4 Progress event, 9.5 Labels (keyboard),
9.6 Phone marker and QR, 9.7 Result, 9.8 Error codes, 9.9 Flow, 9.10 Files and `rzlab validate`.

### 9.1 Rules

- **One recording at a time.** It records `adc_raw` (2 kSPS, 2 ch) and `accel` (2 kSPS, 3 ch) to two WAV files, each
  with a v1 sidecar (D-019, D-020). `adc_dec` is never recorded. Start sends STOP to the node first (clean slate), then START
  for the recorded streams, so indices restart at 0 and the Live page's rings are reset (`stream_reset` events).
- **While recording** `POST /api/connect`, `/api/disconnect` and `/api/acquisition` answer `409 recording_active`.
  The Live page keeps working (rings, WebSocket, view requests). `status.recording` is `true`.
- **People are pseudonyms** `P1`, `P2`, ... (regex `^P\d+$`). Anything else is `422`; the rejected text is not echoed.
- **Time stamps come from the server.** The browser never sends a time with a mark (section 9.5).
- Recordings are written to local staging while recording, then moved to the **data root** (a folder outside the git
  repository, normally on the shared drive). Only validated sidecars are copied to the repository's `data/`.

### 9.2 Setup

#### `GET /api/record/options`
Call it when the Record page opens and after a connect. `can_start` is `false` while `blockers` is not empty.
```json
{ "state": "idle",
  "data_root": { "configured": true, "ok": true, "path": "D:\\recordings", "source": "env", "config_file": "C:\\Users\\me\\AppData\\Roaming\\rzlab\\config.toml", "free_gb": 812.4, "error": null },
  "protocols": ["walk-pass-v1"], "default_protocol": "walk-pass-v1",
  "person_pattern": "^P\\d+$",
  "node": { "node_id": "rzn-sim001", "fw_version": "0.1.0-sim", "link": "tcp", "simulated": true,
    "streams": [
      { "name": "adc_raw", "n_ch": 2, "nominal_hz": 2000, "clock": "ltc6903", "recordable": true,
        "channels": [ { "ch": 0, "units": "V", "gain": 8, "scale": 1.788e-08, "defaults": { "head": "geophone/sm24", "serial": "G-0001", "port": 1, "mount": "spike" } },
                      { "ch": 1, "units": "V", "gain": 8, "scale": 1.788e-08, "defaults": { "head": "piezo/disc35", "serial": "PZ-0001", "port": 2 } } ] },
      { "name": "adc_dec", "n_ch": 2, "nominal_hz": 1000, "clock": "ltc6903", "recordable": false, "channels": [ "..." ] },
      { "name": "accel", "n_ch": 3, "nominal_hz": 2000, "clock": "adxl355", "recordable": true, "channels": [ "..." ] } ] },
  "label_state": { "label": "walk", "person": null, "pace": null, "shoes": null },
  "marker": { "bind": "192.168.1.23", "port": 0, "hosts": ["192.168.1.23", "10.8.0.2"] },
  "can_start": true,
  "blockers": [ { "code": "not_connected", "message": "Connect to a node first (Device page)." } ] }
```
`protocols` are the machine-readable protocols, `docs/protocols/*.yaml` of the checkout (default first); a protocol
that only has a `.md` write-up (e.g. the dropped `kill-test-phone`) is not offered. `GET /api/record/protocols/{name}`
shows one (section 10.2).
`node` is `null` when no node is connected. `defaults` are what the node's head descriptors suggest for the form
(the user may override `head`, `serial`, `port`, `mount` per channel). `simulated: true` means the firmware string ends
in `-sim`; show a "simulated" badge, such sessions are not copied to the repository's `data/` by default.
`marker` is what the phone marker would do: `hosts` are the addresses the person may choose from **before** starting (this PC's
IPv4 LAN addresses, best guess first; plus the configured bind when it is a concrete address, or `127.0.0.1` when the PC has none;
empty only when the config binds `0.0.0.0`), `bind` is the default pick (the first LAN address for `auto`, the configured address,
or `0.0.0.0` when the config says so), `port` the configured port (`0` = any free one). Show a picker over `hosts` preselecting
`bind` when `hosts` has more than one entry (VPN, WSL/Hyper-V, Ethernet plus Wi-Fi: the first one is not always the phone's network)
and send the choice as `marker_host` in the start request.

Blocker codes: `no_data_root`, `data_root_relative`, `data_root_in_repo`, `data_root_missing`, `data_root_not_writable`,
`not_connected`, `recording_active`, `no_schema`.

#### `GET /api/record/data-root`
The same `data_root` object as above, freshly checked (it also test-writes a temporary file there). Fields: `configured`
(a path is set), `ok` (usable), `path`, `source` (`"env"` | `"config"` | `null`), `config_file`, `free_gb`, and `error`
`{code, message}` when not ok. `message` is written for the user. With no data root: `error.code = "no_data_root"` and
the message names `RZ_DATA_ROOT` and the config file. The server never creates the folder.

#### `PUT /api/record/data-root`
`{ "path": "D:\\recordings" }` writes `data_root` into the user's `config.toml` (other keys are kept) and returns the new
`data_root` object. Errors (`409` unless noted): `data_root_from_env` (the `RZ_DATA_ROOT` environment variable wins; the page
cannot change it), `data_root_relative` (a full path is needed), `data_root_in_repo` (inside the git checkout: refused),
`data_root_missing`, `data_root_not_writable`, `recording_active`. The path must already exist.

### 9.3 Start and stop

#### `POST /api/record/start`
Body (the session form). Unknown fields are refused.

| Field | Type | Notes |
| --- | --- | --- |
| `site` | string, 1-64 | required. Becomes a slug `[a-z0-9-]+` in the session name (`Home A` -> `home-a`); needs at least one letter or digit |
| `room` | string, 1-64 | required, same rule |
| `floor` | string, max 40 | optional; no `;` or line breaks. Goes into the sidecar `notes` as `rzlab: floor=...` (the schema has no field) |
| `surface` | string, max 120 | optional; written to every channel's `surface` |
| `persons` | string[] | pseudonyms, each `^P\d+$`, unique, at most 12. Stored in `notes` as `persons=P1,P2`. If non-empty, marks may only use these |
| `protocol` | string | default `walk-pass-v1`; must be one of `options.protocols` |
| `streams` | `("adc_raw"\|"accel")[]` | default both (those the node has) |
| `sensors` | object[] | where each recorded channel sits; see below |
| `notes` | string, max 500 | free text, no names; a line may not start with `rzlab:` |
| `marker` | bool | default `true`: start the phone marker listener (9.6) |
| `marker_host` | string, max 64 | optional: the one address the marker listens on and the QR code names; must be one of `options.marker.hosts` or `127.0.0.1`, otherwise `422 bad_marker_host` (`details: [{loc: ["marker_host"], msg}]`, nothing reserved). An IPv6 address gets the same error with a message that says IPv6 is not supported (the marker is IPv4 only). Omit = `options.marker.bind`. `0.0.0.0` cannot be requested here, only set in the config |
| `runner` | bool | default `false`: start the protocol runner (section 10) with this `protocol` and `persons` when the recording starts. The protocol file must load (`422`, `loc: ["protocol"]`, one detail per problem) and a per-person protocol needs at least one person (`422`, `loc: ["persons"]`); both are checked before anything is reserved. The Record page sends `true` unless the person unticks "run it step by step" |

`sensors[]` entries: `{ "stream": "adc_raw", "ch": 0, "position_m": [x, y(, z)], "port"?: 1-4, "head"?: "geophone/sm24", "serial"?: "G-0001", "mount"?: "spike" }`.
`position_m` is required (metres, 2 or 3 numbers). Every channel of every recorded stream needs a position: either one entry per
`ch`, or one entry **without** `ch` that covers all channels of that stream with no entry of their own (use it for the
3-axis accelerometer). Omitted `head`, `serial`, `port`, `mount` take the node's `defaults`.

Response `200`: the `recording` event (9.4) with `state: "recording"`. The call takes up to about 5 s (clean-up STOP, START).
The session name `YYYY-MM-DD_<site>_<room>_<nn>` is reserved when this succeeds (`nn` is the lowest free number, so two
labs starting together get different names). A refused start reserves nothing.
Errors: `422 invalid_request` with `details: [{loc, msg}]` (form errors, e.g. `loc: ["body","persons"]`, or
`["sensors"]` for a missing position), `422 bad_marker_host` (see `marker_host`), `409` with a code from 9.8.

#### `POST /api/record/stop`
No body. Returns when the node has drained, the files are closed, the sidecars are written and validated and the
session is moved to the data root: usually 1-3 s, longer for long sessions on a slow share. Response: the **result** (9.7).
The same result is in `recording.last` afterwards. If the link died during the recording the same finishing steps ran on
their own (`ended_by: "link_lost"`); calling stop then returns that result. Errors: `409 not_recording`.

### 9.4 Progress: the `recording` event

WebSocket JSON event (also `GET /api/record/state`, and part of `GET /api/state`; a new socket gets the latest one in its
snapshot). Sent on every state change and **once per second** while recording.
```json
{ "type": "recording", "state": "recording", "session": "2026-10-13_home-a_kitchen_01", "protocol": "walk-pass-v1",
  "elapsed_s": 42.3,
  "streams": [
    { "stream": "adc_raw", "file": "2026-10-13_home-a_kitchen_01.adc.wav", "frames_written": 84200, "frames_received": 85011,
      "queue_depth": 3, "overflow_packets": 0, "rejected_packets": 0, "error": null,
      "loss": { "device": 0, "link": 0, "host": 0, "host_exact": true, "host_max": 0, "pending": 0, "received": 85011, "missing": 0, "window": 85011,
                "win_first": 0, "win_end": 85011, "final": false, "incomplete": false, "protocol_bug": false } },
    { "stream": "accel", "...": "..." } ],
  "n_labels": 12, "marking": false, "label_state": { "label": "walk", "person": "P1", "pace": "normal", "shoes": true },
  "marker": { "active": true, "port": 51234 }, "marker_error": null, "last": null, "t": 1791794840.1 }
```
- `state`: `idle` | `starting` | `recording` | `stopping` | `finalizing`. `idle` with `last` set means a recording just finished.
- `elapsed_s` is `null` unless recording.
- **Live loss counters** are `streams[].loss`, the same object as in the `status` event (section 4.3): show `device`, `link` and
  `host`, with `host+` when `host_exact` is `false`. They are `null` for the first second (until the node reports its window).
- `frames_written` is what is on disk; `frames_received` what has arrived (`frames_received - frames_written` is the writer's
  small backlog; `queue_depth` is that backlog in packets). `overflow_packets > 0` or `error != null` means the disk
  cannot keep up or failed: show it prominently (the samples this recorder dropped are zeros in the file and are added to `loss.host` in the sidecar when the recording
  ends, with `recorder_dropped_samples=N` in its notes).
- `marker` is `null` when no listener runs; `marker_error` has the reason when the form asked for one that could not start
  (the recording runs anyway).
- `last` is the result of the previous recording (9.7), kept until the next one starts.

### 9.5 Labels (keyboard)

The page keeps the label form; **Space starts and ends a mark**. The browser sends only the event; the server stamps its arrival
on its own clock and converts the stamp to sample indices at the end of the recording (through the PING/PONG clock map and
each stream's timestamp fit, PROTOCOL.md section 7). A browser clock is never used.

#### `GET /api/record/current-label` / `PUT /api/record/current-label`
The default fields for the next mark: `{ "label": "walk", "person": "P1" | null, "pace": "slow"|"normal"|"fast"|null, "shoes": true|false|null }`.
`label` is 1-40 characters `[a-z0-9 _.-]` (lower-cased; e.g. `walk`, `silence`). `person` is a pseudonym and, during a
recording, one of the form's `persons`. `PUT` replaces the whole object; the answer is the stored object. Change it between
marks; a mark takes a snapshot when it starts.

#### `POST /api/record/mark`
`{ "edge": "toggle" }` where `edge` is `"toggle"` (default: start if no mark is open, else end), `"start"` or `"end"`.
Optional `label`, `person`, `pace`, `shoes` override the current label state **for this mark** (only meaningful with a start).
Send it from the `keydown` handler (ignore `event.repeat`, and ignore Space while a text field has focus). Response:
```json
{ "action": "start", "mark": { "id": 7, "state": "open", "label": "walk", "person": "P1", "pace": "normal", "shoes": true,
                                "src": "key", "start_s": 61.204, "end_s": null, "rtt_ms": null } }
```
`start_s` / `end_s` are provisional seconds since the recording started (server clock) for the list on screen; the exact
sample indices (`i0`, `i1`) and times (`t0 = i0 / sample_rate`) are computed when the recording ends and go into both
sidecars, each in its own index base (indices count from the first frame of that WAV). Only one mark can be open at a time,
whether it was started from the keyboard or the phone. A mark still open at stop is closed at the stop.
Errors: `409 not_recording`, `409 mark_open`, `409 no_open_mark`, `422` for a bad pseudonym or label. The label must be one of
the session protocol's fixed list (10.1, `labels_allowed` in the options and the recording event); any other is
`422 invalid_label`. The same holds for `PUT /api/record/current-label` (the label form; before a session it is checked
against the default protocol's list, and a label of another list is reset to `walk` or the list's first one at start) and
for phone marks (refused with the same code).
While the protocol runner is active, the label fields come from its current step instead of the current-label state, and
the runner's errors apply (`countdown_running`, `runner_finished`, `runner_owns_label`; section 10.5). Phone marks follow the same rules.

#### `GET /api/record/labels`
`{ "labels": [ <mark>, ... ], "marking": false }` in order of start. `<mark>` is the object above; `state` is `open` or `closed`.
Marks of the recording that is running (empty when idle).

#### `DELETE /api/record/labels/{id}`
Removes a mark (a mistaken press) while recording: `{ "deleted": 7 }`. `404 not_found` for an unknown id.

#### `label` event (WebSocket)
`{ "type": "label", "action": "start"|"end"|"delete", "mark": { ...the mark view, or {"id": 7} for delete }, "n_labels": 13, "t": ... }`
after every change from the keyboard **or the phone**. Update the list from it.

**Uncertainty.** Each label in the sidecar has `unc_ms`: an **estimate** of the label error, not a bound. It is the
uncertainty of the node clock mapping (from the PING/PONG pairs) + an allowance for the loopback request and event loop
+ half a sample period; phone marks use a different allowance and add half the phone's measured round trip. The
allowances are calibrated so that about **95 %** of the edges of the acceptance run (simulated clock drift and timestamp
jitter, injected asymmetric phone latency) fall inside it; the other 5 % can be outside, by a few milliseconds for the
keyboard. The acceptance run (README) prints the fraction and fails below 95 %. Last result (5 min, simulated drift 60 ppm and 150 us timestamp noise, seed 7, 58 edges per source and stream): keyboard errors p95 8.8 ms, max 9.4 ms against an `unc_ms` of 12.5 ms (58/58 inside); phone errors p95 34 ms, max 42 ms against 61 ms (58/58 inside). On a heavily loaded PC the keyboard error was seen up to 12.5 ms. Use `unc_ms` as a typical error, and
never as a guarantee: a phone on a badly behaved Wi-Fi (power save, spikes) can be worse, because half the round trip only
corrects a symmetric delay. The phone page fires on `pointerdown` (the touch itself, not its release).

### 9.6 Phone marker and QR code

A phone cannot reach the Lab server (loopback only, no login). While a recording runs and the form asked for it
(`marker: true`), the server also starts a **separate listener** on the LAN (own port, own HTTP server, bound to **exactly one address**: `marker_host` of the start request, else this PC's first LAN address (`RZ_MARKER_BIND=auto`);
`0.0.0.0` only if you set it in the config; port from `marker_port` or any free one). The address is chosen before the recording
starts and cannot change while it runs, and the URL and QR code always name that address. It serves one URL space only: `GET /m/<token>` (a one-button page) and its
WebSocket `/m/<token>/ws`. Every other path, a wrong, unknown or expired token, and every other method give the same
`404 Not Found`; there is no `/api`, `/ws`, static files, docs or OpenAPI on it. The token is 160 random bits, is compared in constant time, and
dies when the recording ends (the listener is closed then). Windows asks once whether Python may accept connections on the
private network: say yes for the private network only (README).

#### `GET /api/record/marker[?host=192.168.1.23]`
Loopback API only (it contains the token).
```json
{ "active": true, "host": "192.168.1.23", "port": 51234, "url": "http://192.168.1.23:51234/m/Zk3...", "hosts": ["192.168.1.23"], "qr_svg": "<svg ...>...</svg>" }
```
or `{ "active": false, "reason": "..." }`. `host` is the address the listener is bound to, and `url` and `qr_svg` always use it.
`hosts` is `[host]` (one entry: there is nothing else to pick while recording; the choice was `marker_host` in the start request).
The optional `host` query must be absent or equal to `host`; anything else gives `400 bad_marker_host` (message names the bound
address, and the server logs a warning), because a QR code for an address that nothing listens on cannot work. Only when the
config binds `0.0.0.0` (`RZ_MARKER_BIND=0.0.0.0`) is `hosts` the PC's LAN addresses (plus the config's `marker_host`), `host` the
first of them or the config's `marker_host`, and `?host=` may pick another one of `hosts`; the listener then really answers on all of them.
Show `url` as text and `qr_svg` inline (it is a complete `<svg>` element; put it in a container with a light background and set its width,
it scales). The same QR code as an image: `GET /api/record/marker/qr.svg` (`image/svg+xml`, same optional `host`; `404 no_marker` when none runs,
`400 bad_marker_host` as above).

#### What the phone page does (for reference, not for the UI)
Opens the WebSocket, sends `{"op":"ping","id":n}` every second and measures the round trip to the server's `{"op":"pong","id":n}`,
and on a tap sends `{"op":"mark","edge":"start"|"end","rtt_ms":<median of the last 7 round trips>}`. The server stamps the arrival itself
and subtracts `rtt_ms / 2`. A mark without a round trip in 0-2000 ms is refused (`rtt_required`). The server pushes
`{"op":"state","recording":bool,"marking":bool,"n_labels":n}` so the button shows start or end; that is all the phone can learn.
Messages are limited to 2 KiB and 20 per second; at most 4 phones at once. The phone's label text and person come from the page's
`current-label` state on the Lab side.

### 9.7 Result of a recording

Returned by `POST /api/record/stop` and kept in `recording.last`.
```json
{ "ok": true, "session": "2026-10-13_home-a_kitchen_01", "ended_by": "stop", "stored": "data_root",
  "path": "D:\\recordings\\2026-10-13_home-a_kitchen_01",
  "streams": [ { "stream": "adc_raw", "wav": "...adc.wav", "sidecar": "...adc.json", "frames": 604800, "duration_s": 300.0,
                 "sample_rate": 2016, "sample_rate_measured": 2015.9999, "rate_source": "fit", "first_sample": 0,
                 "loss": { "device": 0, "link": 0, "host": 0 }, "incomplete": false, "labels": 60, "problems": [] },
               { "stream": "accel", "...": "..." } ],
  "n_labels": 60, "runner": null,
  "sidecars_copied": ["C:\\work\\Rezonating\\data\\2026-10-13_home-a_kitchen_01\\...adc.json", "..."],
  "sidecars_copy_skipped": null, "validation": { "ok": true, "problems": [] }, "problems": [] }
```
- `ok` is `false` when anything is wrong: a problem, a validation failure, or `incomplete` (no final STATUS: the sidecars say
  `rzlab: loss=incomplete` in `notes`). Show `problems` verbatim.
- `stored`: `data_root` (the normal case) or `staging` (moving to the data root failed; the files are safe at `path` in local staging and `problems` says why).
- `sidecars_copied` lists the files copied to the repository's `data/<session>/` (only validated `.json` sidecars, never a WAV);
  `sidecars_copy_skipped` says why not (`simulated session: ...`, `the session did not validate`, `no sidecar_dir is configured`).
- `rate_source`: `fit` (from the DATA timestamps; normal), `status` or `nominal`. `sample_rate` is `round(sample_rate_measured)`.
- `runner`: `null` when the protocol runner was not used; else what its last run did, the same counters as the `runner` event:
  `{ "protocol": "walk-pass-v1", "finished": true, "overall": {"done": 180, "target": 180}, "per_person": {"P1": {"done": 90, "target": 90}, ...},
  "steps": [ {"key": "silence", "done": 1, "target": 1, "status": "done"}, {"key": "P1/normal-shoes-on", ...}, ... ] }`. Show the steps
  with `done < target` (a session that is short of passes).

### 9.8 Error codes of this section

Same envelope as section 2. New codes:

| `code` | HTTP | Meaning |
| --- | --- | --- |
| `recording_active` | 409 | A recording is running (start, connect, disconnect, acquisition, data-root change) |
| `not_recording` | 409 | Mark, label delete or stop without a running recording |
| `mark_open` / `no_open_mark` | 409 | `start` while a mark is open / `end` with none open |
| `no_data_root`, `data_root_relative`, `data_root_in_repo`, `data_root_missing`, `data_root_not_writable` | 409 (PUT: 409/400) | Data root problems (9.2); the message tells the user what to do |
| `data_root_from_env` | 409 | `RZ_DATA_ROOT` is set and wins over the config file |
| `not_connected` | 409 | No node connected |
| `session_name` | 409 | All 99 numbers of that day, site and room are taken |
| `no_schema` | 409 | `schemas/sidecar.schema.json` not found (run from a checkout or set `RZ_REPO_ROOT`) |
| `start_failed`, `timeout` | 502 / 504 | The node did not start streaming |
| `stop_failed`, `finalize_failed` | 502 / 500 | Stopping or finishing failed; the files may be in staging |
| `invalid_request` | 422 | Form errors with `details` |
| `bad_marker_host` | 422 (start) / 400 (marker, qr.svg) | The start form named an address that is not one of `options.marker.hosts` / the marker query named an address the listener is not bound to |
| `no_marker`, `not_found` | 404 | No marker running / no such label |

### 9.9 Flow

**Record page.** `GET /api/record/options` (show blockers; if the data root is missing offer `PUT /api/record/data-root`) -> fill the form
(site, room, floor, surface, persons, a position per channel from `node.streams[].channels`, the marker address from `options.marker.hosts`) -> `POST /api/record/start` -> keep the WebSocket
open: `recording` events drive the timer, file sizes and loss counters; `label` events drive the mark list -> show `GET /api/record/marker`
(URL + QR) -> Space calls `POST /api/record/mark` (and the label form calls `PUT /api/record/current-label` between marks) ->
`POST /api/record/stop` -> show the result (9.7). On a `recording` event with `state: "idle"` and a new `last` that nobody asked for
(link lost), show the result too.

### 9.10 Files and `rzlab validate`

Per session, in the data root: `<root>/<session>/<session>.adc.wav|json` and `<session>.accel.wav|json`. WAV: 32-bit integer PCM, header
rate `sample_rate`, samples are the node's codes (24-bit ADC codes sign-extended, 20-bit accelerometer codes); lost samples are zeros
at their place. Sidecar: schema v1; floor, persons, frame count and bookkeeping are in `notes` as `rzlab: key=value; ...` lines.
`rzlab validate <data root>` re-checks every session (folder names, sidecars against the schema, WAV header against the sidecar,
labels inside the file) and exits non-zero on any failure; `--sidecars-only` checks a folder of sidecars without WAVs (the repository's `data/`).

## 10. Protocol runner (phase 4)

The runner walks a recording through a protocol, step by step, so the person at the Lab does not set person, pace and
shoes by hand for every pass. **The server owns its state**: a reload, a second tab or a phone sees the same step and
counters (the `runner` event is in every WebSocket snapshot). It exists only inside a running recording.

Contents: 10.1 Protocol files, 10.2 Protocols, 10.3 The `runner` event, 10.4 Commands, 10.5 Marks while the runner
runs, 10.6 Error codes, 10.7 Flow.

### 10.1 Protocol files

`docs/protocols/<name>.yaml`, the machine-readable twin of `<name>.md` (format in the header of
`docs/protocols/walk-pass-v1.yaml`; loader and checks: `src/rezonating_lab/recorder/protocol.py`). A protocol is a list
of steps run top to bottom; `for_each_person` repeats a block of steps for every person of the session (form order).

| Step key | Meaning |
| --- | --- |
| `id` | `[a-z0-9-]`, 1-40, unique in the file |
| `kind` | `timed`: one label lasting `duration_s` (a countdown), or `passes`: `passes` labels, one per pass |
| `label` | the label text (`labels[].label` in the sidecar), e.g. `silence`, `walk` |
| `passes` / `duration_s` | 1-1000 passes (`passes` steps only) / seconds, more than 0 and at most 3600 (`timed` steps only) |
| `fills` | the label fields the step sets: `person: $person` (only inside `for_each_person`, and required there; never a fixed pseudonym), `pace: slow\|normal\|fast`, `shoes: true\|false` |
| `instructions` | one line shown with the step |

Top-level `labels` (required): the protocol's **fixed list of label texts** (decision of 2026-10-13). Every step's `label`
must be in it; the lab adds the shared list `noise`, `other`, `bad` to every protocol. Live marks (Space and phone), the runner,
the label form and the Review page's add and retag accept only these labels (`422 invalid_label` otherwise), and the UI offers
a select, not free text. `GET /api/record/protocols/{name}` returns the list as `labels`.

walk-pass-v1: `labels: [silence, walk]` (plus `noise`, `other`, `bad`); `silence` (timed, 60 s, no person), then per person `normal-shoes-on` 50, `normal-shoes-off` 20,
`slow-shoes-on` 10, `fast-shoes-on` 10: 90 passes per person. Unknown keys, a duplicate key, a wrong type or a
`protocol` name that is not the file name are refused with every problem listed.

### 10.2 Protocols

#### `GET /api/record/protocols/{name}`
`name` must be one of `options.protocols`. Answer:
```json
{ "protocol": "walk-pass-v1", "title": "Walk passes for footstep-id", "pack": "footstep-id", "doc": "walk-pass-v1.md",
  "passes_per_person": 90,
  "blocks": [
    { "for_each_person": false, "steps": [
      { "id": "silence", "kind": "timed", "label": "silence", "passes": 1, "duration_s": 60.0, "fills": [], "pace": null, "shoes": null,
        "instructions": "Nobody moves or walks. ..." } ] },
    { "for_each_person": true, "steps": [
      { "id": "normal-shoes-on", "kind": "passes", "label": "walk", "passes": 50, "duration_s": null, "fills": ["person", "pace", "shoes"],
        "pace": "normal", "shoes": true, "instructions": "Normal pace, shoes on. ..." }, "..." ] } ] }
```
Errors: `404 not_found` (not offered), `422 bad_protocol` (the file does not load; `details: [{loc: ["protocol"], msg}]`, one per problem).

### 10.3 The `runner` event

WebSocket JSON event, also the answer of `GET /api/record/runner` and of every command in 10.4. Sent on every change (a mark that
starts or ends, a counted pass, a step change, a delete) and **once per second while a countdown runs**; a new socket gets the latest
one in its snapshot.
```json
{ "type": "runner", "active": true, "protocol": "walk-pass-v1", "title": "Walk passes for footstep-id", "persons": ["P1", "P2"],
  "state": "ready", "current": 1, "open_mark": null, "countdown": null,
  "overall": { "done": 12, "target": 180 },
  "per_person": { "P1": { "done": 12, "target": 90 }, "P2": { "done": 0, "target": 90 } },
  "steps": [
    { "index": 0, "key": "silence", "id": "silence", "kind": "timed", "label": "silence", "person": null, "pace": null, "shoes": null,
      "target": 1, "done": 1, "duration_s": 60.0, "status": "done", "instructions": "..." },
    { "index": 1, "key": "P1/normal-shoes-on", "id": "normal-shoes-on", "kind": "passes", "label": "walk", "person": "P1",
      "pace": "normal", "shoes": true, "target": 50, "done": 12, "duration_s": null, "status": "active", "instructions": "..." },
    "..." ],
  "t": 1791794840.1 }
```
- `active: false` (with `state: "off"`, `current: null`, `steps: []`) when no runner runs: before a recording, after it, or after
  `stop`. The marks then take the current-label state (9.5).
- `state`: `ready` (waiting for the next mark), `marking` (a pass is open), `countdown` (a timed step runs), `finished` (every step was
  left or completed; `current` is `null`), `off`.
- `current` is the index into `steps`. `steps[].done` counts the closed labels of that step, `target` what the protocol asks for
  (1 for a timed step). `overall` and `per_person` add up the `passes` steps only (the silence is not a pass).
- `steps[].status`: `pending` (not reached), `active` (current), `done` (`done >= target`), `incomplete` (left with fewer), `skipped`
  (left with Skip).
- Runner events are built and published under the recorder's lock, so they reach the sockets in the order the state changed (the
  once-per-second countdown event can never arrive after the event that ended the countdown).
- `countdown` while a timed step runs: `{ "duration_s": 60.0, "remaining_s": 47.2, "mark": 1 }`. `remaining_s` is the server's
  value when the event was sent: count it down locally from the moment the event arrived (no browser wall clock), and take the next
  event's value when it comes.

### 10.4 Commands

All `POST` without a body unless noted; each answers the new runner view (10.3). All need a running recording (`409 not_recording`);
all except `start` need an active runner (`409 runner_off`).

| Endpoint | What it does |
| --- | --- |
| `POST /api/record/runner/start` | Body `{ "protocol"?: "walk-pass-v1" }` (omit = the session's protocol). Starts at step 0 with the session's persons. Only the session's own protocol (`form.protocol`) can run: another name is `409 protocol_mismatch` (the sidecar's `protocol` would not match the labels). `409 runner_active` if one runs, `409 mark_open` if a mark is open, `422` like the form's `runner` field |
| `POST /api/record/runner/stop` | Leaves the runner (marks take the current-label state again). The result of the recording still reports the run |
| `POST /api/record/runner/next` | Next step; the current one becomes `done` or `incomplete`. On the last step: `finished` |
| `POST /api/record/runner/back` | Previous step (from `finished`: the last step); the current one becomes `done`, `incomplete` or `pending` (nothing marked). `409 runner_first_step` on step 0 |
| `POST /api/record/runner/skip` | Next step; the current one becomes `skipped` (or `done` if complete). Its labels stay |
| `POST /api/record/runner/goto` | Body `{ "index": 3 }`: jump to a step (the step list's Go button). `404 not_found` for an index outside `steps` |
| `POST /api/record/runner/cancel` | Cancels a running countdown: its open label is **deleted** (a `label` delete event follows) and the step can start again. `409 no_countdown` |

`stop`, `next`, `back`, `skip` and `goto` are refused while a pass is open (`409 mark_open`: end it with Space) or a countdown runs
(`409 countdown_running`: wait, or `cancel`). `next`/`skip` on a finished run: `409 runner_finished`. Going back to a step lets more
labels be added to it (to redo a pass after deleting a mistaken one); when it reaches its target the runner moves to the step after it.

### 10.5 Marks while the runner runs

Marks are still `POST /api/record/mark` (Space) or the phone (9.6); the browser and the phone send nothing new.

- **Start** of a mark: `label`, `person`, `pace` and `shoes` come from the current step (the sidecar's `labels[]` fields). Overrides in
  the request may only repeat them: a different value is `409 runner_owns_label`. On a `finished` run a start is `409 runner_finished`.
  On a step that already has its target (reached again with Back or Go) a start is `409 step_complete`: delete one of its labels to
  redo a pass, or go to another step. The runner card says so while such a step is current.
- **End** of a mark on a `passes` step: the label counts as one pass of the step. When `done` reaches `target` the runner moves to the
  next step by itself (and to `finished` after the last).
- **Timed step** (the silence): the mark's start starts the countdown (`duration_s`). The **server** ends the label when the time is
  over, stamped on its own clock (no human latency at the end; the label's `src` is that of its start). Ending it early by Space or the
  phone is `409 countdown_running`: cancel it instead (10.4). The Live labels card shows "the countdown ends it" and offers no End
  button meanwhile; Space sends nothing. A recording stopped during a countdown keeps the shorter label
  (`open_mark_closed_at_stop` in the sidecar notes).
- **Delete** (`DELETE /api/record/labels/{id}`): a counted label is taken off its step's `done` (a completed step that is no longer
  complete becomes `incomplete`); deleting the open countdown label cancels the countdown.
- A mark that was open when the runner started is not counted (the runner refuses to start while one is open).

What the sidecar holds: every label has `label`, `person`, `pace`, `shoes` from its step (the silence has none of the last three);
`protocol` is the session's protocol. The step id (`normal-shoes-off`) and the pass number have **no field in the sidecar schema v1**;
they follow from the tags and the label order.

### 10.6 Error codes

Same envelope as section 2.

| `code` | HTTP | Meaning |
| --- | --- | --- |
| `runner_off` | 409 | A runner command without an active runner |
| `runner_active` | 409 | `start` while a runner runs |
| `runner_finished` | 409 | A mark start, `next` or `skip` after the last step |
| `runner_first_step` | 409 | `back` on step 0 |
| `runner_owns_label` | 409 | A mark override that differs from the current step's tags |
| `protocol_mismatch` | 409 | `start` with a protocol that is not the session's |
| `step_complete` | 409 | A mark start on a step that already has its target |
| `countdown_running` | 409 | Ending a countdown's label by hand, or moving while it runs |
| `no_countdown` | 409 | `cancel` without a running countdown |
| `mark_open` | 409 | Moving, stopping or starting the runner while a pass is open |
| `bad_protocol` | 422 | `GET /api/record/protocols/{name}`: the file does not load |
| `not_found` | 404 | No such protocol, or `goto` outside `steps` |

### 10.7 Flow

**Record page.** The form's protocol picker shows `GET /api/record/protocols/{name}` as one line (silence 60 s · per person: 4 steps, 90
passes) and a "run it step by step" box (`runner: true`) -> `POST /api/record/start` -> the `runner` event drives the runner card: the
current step (person · pace · shoes, `pass n of target`, the instructions), overall and per-person counters, Back / Next / Skip, the step
list with Go buttons, and for the silence a countdown (Space starts it; Cancel). Space and the phone work as in 9.5; the label form is
greyed out while the runner sets the fields. After Stop the result shows the run and the steps that are short of passes.

## 11. Rig checks (phase 4)

Guided checks for a freshly wired node ([[Wire the first rig]]): each gives pass/fail with the measured numbers. **The
server owns the state** (`server/rigcheck.py`): one worker thread runs the checks through the device manager, and the
`rigcheck` event (in every WebSocket snapshot) carries the whole view. Thresholds are named constants in that module and
are also sent as `thresholds`.

Contents: 11.1 Checks, 11.2 The `rigcheck` event, 11.3 Commands, 11.4 Report, 11.5 Error codes, 11.6 Flow.

### 11.1 Checks

Run in this order by "run all". ADC channels are named CH0 and CH1 (the ADC channel numbers of PROTOCOL.md).

| `id` | Measures | Pass when | Person step |
| --- | --- | --- | --- |
| `adc` | HELLO lists `adc_raw`; START it and count samples | >= `adc_answer_min_samples` (100) within `adc_answer_timeout_s` (3 s) | none |
| `rate` | least-squares fit of DATA `t_dev_us` against `first_sample` over `rate_check_s` (60 s) of **device** time; STATUS rate shown too | abs(rate / nominal - 1) <= `rate_tolerance_pct` (1.1 %) | none |
| `noise` | after 0.1 s settling, `noise_check_s` (5 s) of samples: RMS (mean removed) per channel in counts and in input-referred uV (`counts * scale`, CONFIG) | every channel <= `noise_limit_uv_rms` (15 uV, provisional) | short CH0 and CH1 to AGND |
| `tap` | per channel asked: 0.3 s baseline (mean, RMS), prompt "Tap the sensor at CHn", first sample above max(20 x RMS, 5 mV) on any channel, then the peak per channel (input volts) from 20 ms before to 150 ms after it | the asked channel has the larger peak and >= `tap_min_ratio` (2) x the other, for CH0 and CH1 | connect the heads; tap when asked (20 s each) |
| `accel` | mean of `accel_check_s` (2 s) of x, y, z in g (CONFIG scale) | `accel_z_min_g` <= z <= `accel_z_max_g` (0.9 to 1.1 g), abs x and abs y <= `accel_xy_max_g` (0.1 g) | sensor flat, z up |

Why 1.1 %: the LTC6903 is 0.5 % typical, 1.1 % max at 25 degC, 1.65 % max over temperature. The check runs at room
temperature, so a clock outside the 25 degC maximum is out of spec or misprogrammed; +1.65 % fails. `t_dev_us` comes from
the ESP32 crystal (tens of ppm), so it does not limit the measurement.

A person step sets `awaiting_confirm: true` and waits for `POST /api/rigcheck/confirm` (gives up after 15 min). On a
simulator (`fw_version` ends in `-sim`) person steps are skipped and the tap is injected with the simulator-only
`SET sim.tap <channel>` (README, `rzlab sim`). Streams that the checks START are STOPped at the end; streams that were
running stay running. While checks run, connect, disconnect, START/STOP and SET answer 409 `rigcheck_running`; if a
recording starts or the link drops, the running check ends in `error`.

### 11.2 The `rigcheck` event

Sent on every change (state, prompt, result) and in every snapshot; `GET /api/rigcheck` and every command answer with
the same body.
```json
{ "type": "rigcheck", "running": true, "current": "tap", "awaiting_confirm": false, "sim": true,
  "node": { "node_id": "rzn-sim001", "fw_version": "0.1.0-sim", "link": "tcp", "target": "127.0.0.1:7350" },
  "session_started": "2026-10-13T14:02:11+02:00", "report_path": null, "report_error": null,
  "checks": [
    { "id": "rate", "title": "Sample rate", "guide": ["Leave the node running; nothing to touch.", "..."],
      "state": "pass", "prompt": null,
      "detail": "2016.00 Hz vs 2000 Hz nominal: +0.800 % over 60.0 s (1501 packets); STATUS 2016.0 Hz",
      "limit": "within +/-1.1 % of nominal (LTC6903 max at 25 degC)",
      "numbers": { "nominal_hz": 2000.0, "measured_hz": 2016.0, "error_pct": 0.8, "span_s": 60.0, "samples": 120960,
                   "packets": 1501, "status_hz": 2016.0, "limit_pct": 1.1 },
      "started": 1791915000.1, "finished": 1791915060.3 },
    { "id": "tap", "title": "Tap test (channel map)", "state": "running", "prompt": "Tap the sensor at CH1.", "...": "..." }
  ],
  "thresholds": { "rate_tolerance_pct": 1.1, "noise_limit_uv_rms": 15.0, "...": "..." } }
```
`checks` always lists all five in order. `state`: `idle` (not run in this report) | `running` | `waiting` (person step) |
`pass` | `fail` (measured, outside the limit) | `error` (could not measure: link lost, timeout, refused) | `cancelled`.
`detail` is the measured line the report uses; `numbers` per check:

| `id` | `numbers` |
| --- | --- |
| `adc` | `present`, `clock`, `nominal_hz`, `samples`, `waited_s` |
| `rate` | `nominal_hz`, `measured_hz`, `error_pct`, `span_s`, `samples`, `packets`, `status_hz`, `limit_pct` |
| `noise` | `rms_counts[]`, `rms_uv[]` (null without a volt scale), `mean_counts[]`, `gain[]`, `samples`, `confirmed` (`person` or `auto (simulator)`) |
| `tap` | `taps[]` of `{asked, detected, peak_v[], ratio, ok}` (`detected: null` = no tap in 20 s), `confirmed`, `injected` |
| `accel` | `mean_g[x,y,z]`, `std_g[]`, `samples` |

### 11.3 Commands

| Request | Body | Answer |
| --- | --- | --- |
| `GET /api/rigcheck` | | the view |
| `POST /api/rigcheck/run` | `{ "checks": ["rate"] }` or `{}` for all; optional `"rate_s"` (1 to 600, default 60) | the view, `running: true` |
| `POST /api/rigcheck/confirm` | `{}` | the view (the waiting step goes on) |
| `POST /api/rigcheck/cancel` | `{}` | the view; the running check ends `cancelled`, later ones too |
| `GET /api/rigcheck/report` | | `text/markdown` attachment, `rigcheck_<YYYYMMDD-HHMMSS>_<node>.md` |

"Run all" (no `checks`), or a run on another node, starts a new report and clears earlier results; a run of single checks
replaces only their results.

### 11.4 Report

Plain markdown for the build note: a heading with the date, then date, node, firmware (marked `(simulator)`), link, Lab
version and "n of m checks passed", then one table row per check: Check, Verdict (PASS, FAIL, ERROR, cancelled, not run),
Measured (`detail`), Limit. After every run the server writes it to `<data root>/rigchecks/` (the data root of section 9;
never the repo) and sets `report_path`; without a usable data root `report_error` says why and the download still works.

### 11.5 Error codes

| `code` | HTTP | Meaning |
| --- | --- | --- |
| `not_connected` | 409 | `run` without a connected node |
| `recording_active` | 409 | `run` while a recording runs |
| `rigcheck_running` | 409 | `run` while checks run; connect, disconnect, acquisition or set while checks run |
| `rigcheck_idle` | 409 | `cancel` when nothing runs |
| `no_prompt` | 409 | `confirm` when no step waits |
| `no_results` | 404 | `report` before any check ran |
| `not_found` | 404 | unknown check id in `checks` |

### 11.6 Flow

**Device page, Rig checks card.** One row per check (title, state chip, Steps to show the guide, Run), Run all / Cancel,
Copy report and Download report. The running check's prompt is shown above the list, with **Continue** when it waits for
the person. Results show `detail` and `limit`; the saved report path is shown under the list. Buttons are disabled while
not connected, while a recording runs and while checks run.

## 12. Review and SD import (phase 4)

The Review page opens a finished session of the data root, draws it and lets a person fix its labels; the SD import brings sessions
recorded on a node's SD card into the data root. Code: `src/rezonating_lab/recorder/review.py`, `recorder/sdimport.py`,
`server/review_routes.py`. Recordings are read only through `rezonating_ml.io`; the display maths is `core/view.py` (display only,
D-017). Every endpoint needs a usable data root (`409 no_data_root` and the other data-root codes of 9.2 otherwise).

Contents: 12.1 Sessions, 12.2 Views, 12.3 Label edits, 12.4 Save, 12.5 Error codes, 12.6 SD import, 12.7 Flow.

### 12.1 Sessions

#### `GET /api/review/sessions`
Every `<root>/<session>/` folder with at least one sidecar (empty reservations are left out), newest name first. Reads sidecars only.
```json
{ "root": "D:\\rezonating-recordings",
  "sessions": [ { "name": "2026-10-12_home-a_kitchen_01", "repo_copy": true,
                  "streams": [ { "stream": "adc_raw", "wav": true, "labels": 181, "sample_rate": 2016, "duration_s": 1834.2 } ] } ] }
```
`repo_copy`: the repository's `data/<session>/` exists (`sidecar_dir`, 9.10). A stream whose sidecar cannot be read has `error`.

#### `GET /api/review/sessions/{name}`
`name` must be a session name in the data root (`404 not_found` otherwise; no path can leave the root).
```json
{ "name": "2026-10-12_home-a_kitchen_01", "persons": ["P1", "P2"], "protocol": "walk-pass-v1", "repo_copy": true,
  "streams": { "adc_raw": { "stream": "adc_raw", "sidecar": "<name>.adc.json", "wav": "<name>.adc.wav", "frames": 3697920,
    "sample_rate": 2016, "n_ch": 2, "channels": [ { "ch": 0, "units": "V", "scale": 2.98e-7, "head": "geophone/sm24" } ],
    "labels": [ { "t0": 0.0, "t1": 60.0, "i0": 0, "i1": 120960, "src": "key", "unc_ms": 14.2, "label": "silence" } ],
    "version": "3f9a0c2b7d1e4a55", "backup": false, "labels_off_list": [] } } }
```
`version` is a hash of the sidecar's bytes; a save names it (12.4). `persons` come from the sidecar notes (`rzlab: persons=...`).
`labels_allowed` is the session protocol's fixed label list (10.1). A protocol without a usable YAML (an older session such as
`kill-test-phone`, which has only a `.md`) gets the **shared list** `noise`, `other`, `bad`, with `labels_note` saying why; `null`
(with `labels_note`) only when the sidecar names no protocol (then add, retag and save are refused with `422 no_label_list`).
`labels_off_list` (per stream): the positions of labels whose text is not in `labels_allowed`, as older sessions may hold. They are
shown marked on the page, and **a save needs them retagged** (or deleted) first: a save checks every label (`422 invalid_label`). A session folder that is a symbolic link or resolves outside the
data root is `404 not_found` and is left out of the list. A sidecar that cannot be read is `422 invalid_sidecar`.

### 12.2 Views

Both compute from the WAV (cached server-side: the last two files read) and answer in the channels' units (`codes * scale`).
`i0`/`i1` select `[i0, i1)` in samples (default: the whole file); outside `0 <= i0 < i1 <= frames` is `422 out_of_bounds`.

#### `GET /api/review/sessions/{name}/envelope?stream=adc_raw&i0=&i1=&columns=1200`
Exact min/max per pixel column (`columns` 1-4000; fewer samples than columns: one column per sample).
`{ frames, sample_rate, i0, i1, edges: [columns + 1 sample indices], units: [...], min: [[per channel]], max: [[...]] }`.

#### `GET /api/review/sessions/{name}/spectrogram?stream=adc_raw&ch=0&i0=&i1=&columns=600&nfft=256`
STFT of one channel (Hann, density, dB); the hop grows so at most `columns` (1-2000) columns come back, so a long range is sampled,
not averaged. `{ frames, sample_rate, i0, i1, ch, units, nfft, hop, freq_hz: [...], center_index: [...], power_db: [[bins] per column] }`.
`422 invalid_request` for a channel the stream does not have.

### 12.3 Label edits

Labels are edited in **sample indices** of one stream (`i0`, `i1`); the server recomputes `t0 = i0 / sample_rate` and
`t1 = i1 / sample_rate` and keeps the list sorted by `(i0, i1)`. The page holds the list and the undo history; the server applies one
edit at a time and checks every label each time (bounds `0 <= i0 <= i1 <= frames`, label text, pseudonym of the session, pace, shoes).
The label text of an `add` or a `retag` must be in the protocol's list (`labels_allowed`, 10.1); a save checks every label against it.

#### `POST /api/review/sessions/{name}/edit`
Body `{ "stream": "adc_raw", "labels": [...current list...], "op": {...} }` -> `{ "labels": [...new list...] }`. Nothing is written.

| `op.kind` | Fields | Result |
| --- | --- | --- |
| `move` | `n`, `edge: "start"\|"end"`, `i` | one edge to sample `i`; it may not pass the other edge (`bad_edit`) |
| `split` | `n`, `i` | `[i0, i)` and `[i, i1)` with the same tags; needs `i0 < i < i1` |
| `merge` | `n` | label `n` and the next one become one (first start to later end) with the tags and src of `n` |
| `retag` | `n`, `set: { label?, person?, pace?, shoes? }` | `null` removes a field (not `label`) |
| `delete` | `n` | |
| `add` | `i0`, `i1`, `label`, `person?`, `pace?`, `shoes?` | a new label with `src: "review"` |

**`src` of an edited label.** The sidecar schema v1 allows `key`, `phone`, `review` and `auto`, not `edit`, and the schema is Tier 1, so
a live label edited by hand **keeps its `src`**; a label added on the Review page gets `review`. When an index moves (move, split,
merge) the label's `unc_ms` is dropped: it described the live mark's timing. A retag keeps both.

#### `POST /api/review/sessions/{name}/check`
Body `{ "stream", "labels" }` (a `version` is accepted and ignored), nothing saved: `{ "labels": [...] }` checked (as a save checks
them, label list included) and normalised, or the error.

### 12.4 Save

#### `PUT /api/review/sessions/{name}/labels`
Body `{ "stream": "adc_raw", "labels": [...], "version": "3f9a0c2b7d1e4a55", "peer_version": "77c0d1e2f3a4b5c6" }`. `version`
(the edited stream's sidecar) is required (`422` without it); `peer_version` (the other stream's) is required when the session has
both streams. Only `labels` change, **in both sidecars** (decision of 2026-10-13: the two streams' labels stay in sync).

1. `version` and `peer_version` must be the sidecars' current ones (`409 changed_on_disk` otherwise: reload). The labels are
   checked as in 12.3, label list included.
2. The other stream's list is derived through the shared **device clock**: frame `i` of a sidecar lies at device time
   `t_dev_us + i * 1e6 / sample_rate_measured` (`first_sample`/`t_dev_us` and the measured rate the recorder wrote; it placed
   each live mark into both files on the same clock; a sidecar without `sample_rate_measured` or `t_dev_us` is
   `422 invalid_sidecar`). Each label keeps its tags and src. A label that was **not edited** (identical to one on disk, `unc_ms`
   included) keeps the other stream's own copy when one with the same tags lies within 10 ms of the mapped place (its own
   `unc_ms`); an **edited** label is always mapped afresh, however small the edit (an edge moved by 1 sample reaches the other
   file). Indices are kept inside the file; a label that lies **entirely outside** the other file is not copied there (it would
   be a zero-length label at the edge): `peer.labels_dropped` counts them and `warnings` says so.
3. Both new sidecars are checked: `rezonating_ml.io.check_pair` (schema, WAV header, labels inside the file, `t = i / sample_rate`)
   plus the schema check of `tools/validate.py`. On any problem in either **nothing is written**: `{ "saved": false, "problems":
   [...] }` (each problem starts with its sidecar's name).
4. Each previous sidecar is kept as `<sidecar>.json.bak` next to it (one generation; `rzlab validate` accepts it there), then both
   are written through `rezonating_ml.io.save_sidecar` (each atomic). The two are written **as a pair**: when the second write
   fails, the first is put back from its `.bak` (atomic copy) and the save answers `500 write_failed`, whose message says what is
   on disk (normally: both sidecars unchanged; if putting one back failed too, which file holds the new labels).
5. The session folder is validated again (`rzlab validate`'s checks, both streams). The repository copies
   `data/<session>/<sidecar>` are replaced (temp file and `os.replace`) **only** when that folder exists and the session validates.

```json
{ "saved": true, "stream": "adc_raw", "sidecar": "<name>.adc.json", "problems": [], "backup": "<name>.adc.json.bak",
  "version": "a1b2c3d4e5f60718", "labels": [...],
  "validation": { "ok": true, "problems": [], "warnings": [] },
  "peer": { "stream": "accel", "sidecar": "<name>.accel.json", "backup": "<name>.accel.json.bak", "version": "...", "labels": [...] },
  "repo_copy": { "updated": true, "path": "C:\\work\\Rezonating\\data\\<name>\\<name>.adc.json", "paths": ["...adc.json", "...accel.json"] } }
```
`repo_copy` without a copy or after a failed validation: `{ "updated": false, "reason": "..." }`; when copying the second file to
`data/<session>/` fails, the first copy is put back as it was and `reason` says so (the data root is saved either way).
`peer.labels_dropped` and `warnings` (a list, only when something was dropped) are described in step 2. `note` says when `tools/validate.py`
could not be found (the `rezonating_ml` schema check still ran). `peer` is missing for a session with one stream. `rzlab validate`
warns (not fails) when a session's two label lists differ in count or tags; one save on the Review page brings them in step.

### 12.5 Error codes

| `code` | HTTP | Meaning |
| --- | --- | --- |
| `not_found` | 404 | No such session in the data root (or not a session name), or no SD folder |
| `no_stream` | 404 | The session has no WAV + sidecar for that stream |
| `out_of_bounds` | 422 | An index or a view range outside the file |
| `bad_edit` | 422 | An edit that does not fit (no label `n`, split outside the label, merge without a neighbour, an edge past the other) |
| `invalid_label` | 422 | A bad label text, a label not in the protocol's list, a name instead of a pseudonym, a person not in the session, a bad pace/shoes/src, unknown fields |
| `no_label_list` | 422 | The session's protocol gives no label list, so no label can be set or saved |
| `invalid_sidecar` | 422 | A sidecar (or its WAV) cannot be read, or lacks `t_dev_us` / a measured rate for the sync |
| `changed_on_disk` | 409 | A sidecar changed since it was opened |
| `write_failed` | 500 | Writing a sidecar of the pair failed; the message says what is on disk (12.4 step 4) |
| `recording_active` | 409 | `import-sd` while a recording runs |
| `no_data_root`, ... | 409 | The data root is not usable (9.2) |
| `no_schema` | 409 | `schemas/sidecar.schema.json` not found |

### 12.6 SD import

#### `POST /api/review/import-sd`, and `rzlab import-sd <folder>`
Body `{ "path": "E:\\RZ" }` (a full path: the server is local). The folder, or any folder up to 4 levels below it, named like a session
(`YYYY-MM-DD_<site>_<room>_<nn>`) is a session in the recorder's layout (`<session>.adc.wav|json`, `<session>.accel.wav|json`). Per session:

1. validated where it lies (the `rzlab validate` checks); an **invalid** one is reported with its problems and not imported;
2. **skipped** when the data root already has a folder of that name (never overwritten);
3. its recording files (only those) are copied to a fresh folder in staging and validated again;
4. moved into a new `<root>/<session>/` (created exclusively), recordings first and sidecars last; when a move fails, what
   arrived and the folder are removed again, so a later import tries the session afresh;
5. its sidecars (never a WAV) are copied to the repository's `data/<session>/` when `sidecar_dir` is set, with the recorder's
   rules: not for a simulated session (`rzlab: source=sim`) unless `copy_sim_sidecars`, and never over an existing
   `data/<session>/` (the result's `note` says it was left unchanged). When this copy fails, the session is still **imported**
   (it is in the data root): `note` says the copy failed and the partial `data/<session>/` is removed again.

Labels whose text is not in the session protocol's list (12.1; the shared list for a protocol without a YAML) are a **warning**
in `warnings`, not a reason to refuse: the session is imported, and the Review page needs them retagged before it saves.
`rzlab validate` prints the same warning (when it finds the checkout).

Symbolic links are not followed: a linked session folder or recording file is skipped. The import is refused while a recording
runs (`409 recording_active`).

```json
{ "summary": { "imported": 2, "skipped": 1, "invalid": 1, "failed": 0 },
  "results": [ { "session": "2026-10-12_home-a_kitchen_01", "source": "E:\\RZ\\2026-10-12_home-a_kitchen_01", "status": "imported",
                 "problems": [], "path": "D:\\rezonating-recordings\\2026-10-12_home-a_kitchen_01", "sidecars_copied": ["..."], "note": null, "warnings": [] } ] }
```
`failed`: the copy itself went wrong (disk full, a copy that does not validate); nothing is left in the data root. Errors: `422` for a
relative path or a folder inside the data root, `404 not_found` for a folder that does not exist. The CLI prints one line per session
and exits 0 (nothing invalid or failed), 1 (something was) or 2 (bad folder, no data root, no schema).

### 12.7 Flow

**Review page** (rail entry "Review"). Left: the session list (`GET /api/review/sessions`) and the "Import from SD" card (a path field ->
`POST /api/review/import-sd`, the per-session result, then the list refreshes). Right, after a session is opened
(`GET /api/review/sessions/{name}`): a stream switch (adc_raw / accel), the waveform (envelope, one lane per channel) over the
spectrogram of the chosen channel, both for the visible range (`envelope`, `spectrogram`; wheel or the buttons zoom, drag pans, a click
sets the cursor, arrow keys move it; Zoom in/out and `+`/`-` centre on the selected label, else on the cursor, while the wheel keeps
the sample under the pointer; clicking a label or grabbing one of its edges selects it, puts the cursor at its start and loads its label, person, pace and
shoes into the fields; a label outside the protocol's list is marked "!" and listed above the save result, a click there selects it), and under them the label lane: spans with draggable edges (arrow keys move a focused edge by one
sample, Shift by 0.1 s). Buttons: Undo / Redo (Ctrl+Z, Ctrl+Shift+Z; kept in the page), Add at cursor, Split at cursor, Merge with
next, Delete, and the side fields (label, person, pace, shoes) with "Apply to selected" (retag). Each edit is one `edit` call. A chip
shows "unsaved changes" until Save (`PUT .../labels`), whose result (written or not, the problems, the validation, the data/ copy)
is shown under the editor. The label field is a select of the protocol's list. Leaving with unsaved changes asks first: closing
or reloading the tab, opening another session, switching stream, another rail page, or the browser's Back.

## 13. Datasets and the manifest (phase 6)

The Datasets page lists every session and builds `data/manifest.json`. Code: `src/rezonating_lab/datasets.py`,
`server/dataset_routes.py`. Every per-recording field (validity and its errors, people, duration, loss, ...) comes from
`rezonating_ml.manifest.build_manifest` (format v1, `ml/README.md` "Dataset manifest"); the lab only groups its entries by
session, caches them and filters them.

Contents: 13.1 Index and cache, 13.2 Sessions, 13.3 Manifest, 13.4 Error codes, 13.5 Flow.

### 13.1 Index and cache

- **Sources.** The repository's sidecars `data/<session>/<session>[.adc|.adcdec|.accel].json` (`sidecar_dir`, 9.10) and the
  WAVs on the data root `<root>/<session>/*.wav`. A session with no sidecar in the repository is read from the sidecars next to
  its WAVs (`<root>/<session>/<session>.adc.json`, ...): simulated sessions are kept there but not copied to `data/` (9.10
  `copy_sim_sidecars`). They are validated the same way and marked `in_repo: false`, `sidecar_source: "data_root"`; once
  the repository has a sidecar for the session, that one is used. Only folders named like a session are opened (never
  `data/raw`, `data/private`). Without a usable data root the list still works and every WAV shows as missing.
- **Cache.** One SQLite file per machine: `index_db` in `config.toml` or `RZ_INDEX_DB`; default
  `%LOCALAPPDATA%\rzlab\datasets.sqlite` on Windows, `$XDG_CACHE_HOME/rzlab/datasets.sqlite` (`~/.cache/...`) elsewhere. A
  path inside the repository is refused (`index_in_repo`). It holds one manifest entry per sidecar, keyed by the sidecar's and
  the WAV's `(mtime, size)`. Every list request stats the files and re-reads only sessions whose key changed (a new, edited or
  deleted sidecar or WAV). A change of data root, `sidecar_dir`, sidecar schema, manifest version or index logic version
  (`INDEX_LOGIC_VERSION`, bumped by hand when the stored rows change) drops the cache. Deleting the file is safe:
  it is rebuilt from the sidecars.
- **SHA-256** is never computed while indexing (the index reads WAV headers only). It is computed when a manifest is built,
  or for one session on request (13.2), and kept under the WAV's `(mtime, size)`: a changed WAV shows `sha256: null` again.

### 13.2 Sessions

#### `GET /api/datasets/sessions?protocol=&floor=&person=&valid=&wav=&simulated=&date_from=&date_to=`
Refreshes the index, then answers the sessions that match every given filter, newest name first. `valid` and `simulated`:
`true`/`false`; `wav`: `present` (every listed WAV is there) or `missing`; `person`: a pseudonym (`P3`; anything else is `422`);
`date_from`/`date_to`: `YYYY-MM-DD`, inclusive, on the date in the session name.
```json
{ "all": 42,
  "facets": { "protocols": ["walk-pass-v1"], "floors": ["2", "laminate"], "people": ["P1", "P2"] },
  "totals": { "sessions": 3, "hours": 1.52, "labels": 412, "invalid": 1, "wav_missing": 1, "simulated": 0,
              "per_person": [ { "person": "P1", "sessions": 3, "hours": 1.52 } ] },
  "index": { "db": "C:\\Users\\me\\AppData\\Local\\rzlab\\datasets.sqlite",
             "refresh": { "sidecars": 51, "sessions_rebuilt": 1, "sidecars_reused": 50, "sidecars_removed": 0,
                          "sidecars_data_root": 0, "cache_dropped": false, "seconds": 0.21, "at": 1792000000.0 },
             "data_root": { "ok": true, "path": "D:\\rezonating-recordings", "error": null, "...": "as 9.2" },
             "manifest": { "path": "data/manifest.json", "exists": true } },
  "sessions": [ {
    "session": "2026-10-12_home-a_kitchen_01", "date": "2026-10-12", "site": "home-a", "room": "kitchen", "take": "01",
    "floor": "2", "protocol": "walk-pass-v1", "people": ["P1", "P2"], "surface": ["laminate on concrete slab"],
    "duration_s": 1834.2, "label_count": 181, "streams_n": 2,
    "valid": true, "errors": [], "warnings": [],
    "wav_present": true, "wav_missing": 0, "simulated": false, "incomplete": false,
    "loss": { "device": 0, "link": 3, "host": 0 },
    "in_repo": true, "sidecar_source": "repo", "on_data_root": true, "unmatched_wavs": [], "size_bytes": 29634000,
    "streams": [ { "...": "one rezonating_ml manifest entry per sidecar (sha256 null until hashed)" } ] } ] }
```
`totals` cover the shown (filtered) sessions; `all` counts every session. Per session: `duration_s` is the longest stream's,
`label_count` the ADC stream's, `loss` the sum over streams; `valid` only when every stream is valid; `errors` are the manifest
entries' errors prefixed with the stream. `sidecar_source`: `repo`, `data_root` (no repository copy; the stream's `sidecar`
is then relative to the data root) or `null`. A data-root folder with WAVs but no sidecar anywhere is a row with
`in_repo: false`, `sidecar_source: null`, `valid: false`, `wav_present: true` and its WAVs in `unmatched_wavs`; a WAV
without a sidecar next to sidecars of the same session is listed in `warnings` and does not make the session invalid. `on_data_root`: the folder exists on the data root
(only then can the Review page open it). People are pseudonyms only (the manifest drops anything else).

#### `GET /api/datasets/sessions/{name}`
One row as above (`404 not_found` when neither root has it).

#### `POST /api/datasets/sessions/{name}/hash`
Computes the SHA-256 of the session's WAVs now (reads them in full) and keeps it: `{ "session": "...", "wavs": [ { "wav":
"<session>/<session>.adc.wav", "sha256": "64 hex" | null } ] }` (`null`: the WAV is missing). Needs a usable data root.

#### `POST /api/datasets/rebuild`
"Rebuild index": drops the cache and reads every sidecar again. `{ "refresh": {...}, "index": {...} }`.

### 13.3 Manifest

Both requests take the same body. Give `sessions` (names; an unknown one is `404`) **or** `filters` (the fields of the list
query); neither = every session. Then, by default, **simulated** and **invalid** sessions are left out, and a session without a
sidecar in the repository always is: with no sidecar at all it has nothing to list, and a data-root sidecar cannot be named
in format v1 (`sidecar` is relative to the repository), so it is left out as "sidecar not in repo; import or copy first"
(a simulated one says "simulated" unless `include_simulated`). Each left-out session is named with its reason.
```json
{ "sessions": ["2026-10-12_home-a_kitchen_01"], "filters": null, "include_simulated": false, "include_invalid": false }
```

#### `POST /api/datasets/manifest/preview`
From the index only; nothing is hashed or written.
```json
{ "sessions": ["2026-10-12_home-a_kitchen_01"], "entries": 2, "hours": 0.51, "bytes_to_hash": 29634000, "wav_missing": 0,
  "excluded": [ { "session": "2026-10-15_lab_bench_02", "reason": "simulated" },
                { "session": "2026-10-14_lab_bench_01", "reason": "invalid: adc_raw: wav: missing on the data root" } ],
  "include_simulated": false, "include_invalid": false, "out": "data/manifest.json", "exists": true }
```

#### `POST /api/datasets/manifest`
Builds the manifest of the planned sessions with `rezonating_ml.manifest.build_manifest` (hashes every listed WAV: about
58 MB per hour of recording), writes it to `data/manifest.json` (`sidecar_dir/manifest.json`) through `write_manifest`
(validated, deterministic, atomic) and reads it back with `read_manifest`. An entry that became simulated or invalid since the
preview is dropped and listed in `excluded` with "(changed since the preview)". The file is replaced whole; nothing is
written when no entry is left (`422 empty_manifest`). Paths in the file are relative (no machine path is stored).
```json
{ "written": "data/manifest.json", "created": "2026-11-17T10:00:00Z", "sessions": ["..."], "entries": 2, "hours": 0.51,
  "bytes_hashed": 29634000, "wav_missing": 0, "unmatched_wavs": [], "excluded": [ ... ], "seconds": 0.9 }
```
The file is in the repository; committing it is a person's choice.

### 13.4 Error codes

| `code` | HTTP | Meaning |
| --- | --- | --- |
| `not_found` | 404 | No such session (detail, hash) or an unknown name in `sessions` |
| `empty_manifest` | 422 | Every selected session or entry was left out: nothing written |
| `invalid_manifest` | 500 | `write_manifest` refused the manifest (a bug: report it) |
| `index_in_repo` | 409 | `index_db` lies inside the repository |
| `no_sidecar_dir` | 409 | No repository `data/` folder (`sidecar_dir`) |
| `no_schema` | 409 | `schemas/sidecar.schema.json` not found |
| `no_data_root`, ... | 409 | Hash, preview and build need a usable data root (9.2); the list does not |

### 13.5 Flow

**Datasets page** (rail entry "Datasets"). A filter bar (protocol, floor, person, valid, WAV, simulated, date range; Clear),
"Rebuild index" and "Build manifest…". Totals of the shown sessions (sessions, hours, labels, problem counts, per person).
A sortable table (session, date, site / room, floor, people, duration, labels, protocol, loss device / link / host, state
badges: valid / invalid, WAV missing, simulated, incomplete, not in repo (info: sidecars read from the data root), no sidecar) with a checkbox per row; clicking a session
name shows its errors, warnings and streams (with "Compute SHA-256"). **Open in Review** goes to `/review?session=<name>`;
the Review page opens that session when it loads. **Build manifest…** opens a card: the filtered list or the selected rows,
"include simulated", "include invalid", **Preview** (13.3; what is left out and why), then **Build** (asks before
replacing an existing file) and the result.

## Pack bench (Lab phase 5)

All under `/api/bench`; errors are `{"error": {"code", "message"}}`. A source is
`{"kind": "recording" | "sim" | "live", "session"?, "root"?, "channel": 0}` (`root`: a sim-dataset folder; default the
data root; `live` reads the connected node's `adc_raw` ring). Indices are pack-rate (`k`) unless named `input_index`.

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/packs` | | `{packs_dir, packs: [{id, name, sample_rate_hz, trigger, features, model, tunable}]}` |
| GET | `/sessions?root=` | | `{root, sessions: [{name, truth}]}` (sessions with an `adc_raw` stream) |
| POST | `/run` | `{pack, source, trigger?, k0?, k1?, columns?, use_model?}` | stage view (below) |
| POST | `/train` | `{pack, sources: [source], trigger?, seed?}` | model info (in memory; replaces the previous model) |
| DELETE | `/model` | | `{ok}` |
| POST | `/trigger/preview` | `{pack, trigger}` | `{pack, trigger, diff, changed, warnings}` (nothing written) |
| POST | `/trigger/save` | `{pack, trigger}` | the same plus `saved`; 422 `invalid_pack` when validation fails (file restored) |
| POST | `/compare` | `{pack?, channel?}` | `{n_fw, n_py, matched, missing, extra, missing_idx, extra_idx, diffs: [{fw, py, diff}], range, starts_at_acquisition_start, note}` |
| POST | `/vector/create` | `{pack, source, trigger?, k0, k1, folder?, filename?}` | `{path, n, events, masked, warning}` |
| POST | `/vector/check` | `{path}` | `{path, ok, problems}` |

`trigger` holds only `sta_ms`, `lta_ms`, `ratio`, `pre_ms`, `post_ms`. Stage view: `{pack, trigger, source, fs_hz,
input_fs_hz, n, range, stage_order, stages: {name: {status, detail}}, decimated, filtered, ratio (display envelopes
{k, min, max}), threshold, n_invalid_out, counts, events: [{onset, start, end, input_index}], windows: [{onset, start,
end, n_invalid}], feature_names, features: [{onset, values[13]}] | null, model: {classes, rows: [{onset, label,
proba}]} | null, model_info, score: {tolerance_ms, n_truth, n_events, true_positives, false_positives,
false_negatives, precision, recall, onset_error_ms: {mean, median, abs_p95, min, max}} | null}`. Lists are capped at
5000 items; `counts` are complete. Live with no samples yet: `{pack, empty: true, message}`.

## 14. Experiments (phase 7)

The Experiments page evaluates a pack's features on labelled sessions with a split by session or person (never by window),
always next to the majority-class baseline, saves the run and drafts an EXP note. Code: `server/experiments.py`,
`server/experiment_routes.py`. Every number comes from `rezonating_ml` (`pipeline.run_pipeline` with the
`zero_fill_mask` valid mask, `baseline.split_by_group`, `baseline.evaluate`). Errors are `{"error": {"code", "message"}}`.

Contents: 14.1 Endpoints, 14.2 Windows and labels, 14.3 Runs and EXP drafts, 14.4 Error codes.

### 14.1 Endpoints

All under `/api/experiments`. One run at a time, in a worker thread.

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/options` | | `{packs: [{id, name, features}], splits, targets, models, runs_dir, vault_root_set, busy}` |
| POST | `/run` | `{pack, sessions: [name], split, target, model, seed, test_groups?, fraction?}` | `{job}` |
| GET | `/jobs/{job}` | | `{id, state: "running" \| "done" \| "error", done, total, stage, run_id?, result?, error?}` |
| GET | `/runs` | | `{runs: [{run_id, created, pack, split, target, model, sessions, simulated, balanced_accuracy, baseline_balanced_accuracy, beats_baseline, flags, draft}]}` (newest first) |
| GET | `/runs/{run_id}` | | the run's `results.json` (below) |
| GET | `/runs/{run_id}/confusion.svg` | | the confusion heatmap (`image/svg+xml`) |
| POST | `/runs/{run_id}/draft` | `{title}` | `{ok, id, path, deleted?, check: {ok, cli, cli_rc, errors}}` |

`/run` body: `split` `session` \| `person`; `target` `person` \| `pace` \| `shoes`; `model` `logreg` \| `rf`; `seed` an
integer >= 0; `test_groups` (session names for a split by session, pseudonyms for a split by person) or `fraction`
(0 < f < 1; neither = 0.25); at least two sessions. The session list comes from the Datasets index (13.2).

`results.json`: `{format: 1, run_id, created, config, pack: {id, version, sha256}, rezonating_ml, features, simulated,
sessions: [{session, simulated, people, protocol, floor, channel, events, windows_invalid, windows, kept, dropped: {outside_labels,
silence, no_target}, classes, cached}], dataset: {windows, dropped, classes, people}, split: {train_groups, test_groups,
train_sessions, test_sessions, train_people, test_people}, result: EvalResult.as_dict() (scores and baseline: accuracy,
balanced_accuracy, confusion, per_class, per_group), beats_baseline, per_person, flags, summary, elapsed_s, draft?}`.
`flags` start with `SIMULATED DATA: n of m sessions` when any session is simulated, then the `evaluate` flags (does not
beat the baseline, one test group, < 30 test samples, labels absent from test) and mask warnings.
`per_person` is filled for target `person` (each person's recall) and for a split by person (per test group); otherwise `{}`.

### 14.2 Windows and labels

Per session: the `adc_raw` WAV, the channel of the pack's head type (else 0) in volts (codes x `scale`, float32), at the
nominal input rate, through `run_pipeline`. A feature window takes the sidecar label whose `[i0, i1)` holds its onset
(mapped back with `Pipeline.to_input_index`, `2k - 30` when decimating). Windows outside every label, in a `silence`
label, or in a label without the target field are dropped and counted (`dropped`); windows with lost samples are skipped
by the pipeline and counted (`windows_invalid`). `shoes` gives the classes `shoes` / `no_shoes`; only pseudonyms are
used as persons. Features are cached per session and pack hash in `RZ_FEATURE_CACHE`, default `features/` next to the
Datasets index (never in the repository).

### 14.3 Runs and EXP drafts

- **Runs**: `<runs>/<YYYY-MM-DD_HHMMSS>_<pack>_<split>[_n]/` with `config.json`, `results.json`, `confusion.svg`. `<runs>`
  is `RZ_RUNS_DIR`, default `tools/lab/runs/` (gitignored). A run is never overwritten.
- **Draft EXP note** writes `<vault>/50 Experiments/EXP-### <title>.md` (`<vault>`: `RZ_VAULT_ROOT`, default the
  repository root). The id is one after the highest `EXP-###` in `50 Experiments/` and `00 Inbox/` (file names and `id:`).
  The frontmatter is the `experiment` type of the vault-conventions skill (`status: running`, `owner: claude`,
  `metric: balanced_accuracy`, `result` empty); the body holds the question, data, split, model vs baseline, the confusion
  matrix, flags and the run folder. The note is then checked with `python .claude/scripts/vault_schema.py <note>`: any
  error (or a non-zero exit) deletes it, and the answer carries `ok: false`, `deleted` and the errors. Nothing else in the
  vault is written.

### 14.4 Error codes

| `code` | HTTP | Meaning |
| --- | --- | --- |
| `person_split_for_person` | 422 | A split by person cannot evaluate target `person` (every test person unseen in training) |
| `bad_target`, `bad_split`, `bad_model`, `bad_sessions`, `bad_test` | 422 | Invalid run settings |
| `overlap` | 409 | A session (or person) on both sides of the split, e.g. a session holding a train and a test person |
| `eval_refused` | 422 | `evaluate` refused (test labels never seen in training, ...) |
| `invalid_session`, `no_adc`, `wav_missing`, `loss_mismatch`, `no_loss` | 409 | A session cannot be used |
| `no_windows`, `no_features` | 409 | No labelled feature windows, or the pack has no feature stage |
| `not_found` | 404 | Unknown session, pack, run or job |
| `busy` | 409 | A run is already in progress |
| `cache_in_repo`, `no_runs_dir`, `no_vault`, `no_exp_folder`, `no_data_root` | 409 | Folder setup |
| `bad_run`, `bad_title` | 422 | Invalid run id or note title |

Job errors are reported in the job (`state: "error"`, `error: {code, message}`), not as an HTTP error.
