# Rezonating Lab web API (phases 2 and 3)

The contract between `rzlab serve` (`src/rezonating_lab/server/`) and the browser UI (Svelte + Vite + uPlot, built
in a later run). Everything the UI needs is here. The server is the only thing that talks to the node; the UI
talks to the server over **REST** (commands, history views) and **one WebSocket** (live samples and events).

Interactive reference generated from the code: `http://127.0.0.1:8765/api/docs` (OpenAPI at `/api/openapi.json`).

Contents: 1 Basics, 2 Errors, 3 REST commands, 4 WebSocket, 5 View requests (scroll-back, PSD, spectrogram,
levels), 6 Unit and time rules, 7 Flows, 8 Limits, **9 Recorder and live labels (phase 3)**.

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
  `{"op":"snapshot"}` (the server re-sends `connection`, `hello`, `config`, `status`) and
  `{"op":"streams","streams":[0,2]}` (change the filter; `null` = all).
- **On connect** the server sends, in this order, whichever exist: `connection`, `hello`, `config`, `status` (JSON
  text). Binary frames then contain only samples that arrive **after** the socket opened. Use the view requests
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
  "protocols": ["walk-pass-v1", "kill-test-phone"], "default_protocol": "walk-pass-v1",
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
| `marker_host` | string, max 64 | optional: the one address the marker listens on and the QR code names; must be one of `options.marker.hosts` or `127.0.0.1`, otherwise `422 bad_marker_host` (`details: [{loc: ["marker_host"], msg}]`, nothing reserved). Omit = `options.marker.bind`. `0.0.0.0` cannot be requested here, only set in the config |

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
Errors: `409 not_recording`, `409 mark_open`, `409 no_open_mark`, `422` for a bad pseudonym or label.

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
  "n_labels": 60, "sidecars_copied": ["C:\\work\\Rezonating\\data\\2026-10-13_home-a_kitchen_01\\...adc.json", "..."],
  "sidecars_copy_skipped": null, "validation": { "ok": true, "problems": [] }, "problems": [] }
```
- `ok` is `false` when anything is wrong: a problem, a validation failure, or `incomplete` (no final STATUS: the sidecars say
  `rzlab: loss=incomplete` in `notes`). Show `problems` verbatim.
- `stored`: `data_root` (the normal case) or `staging` (moving to the data root failed; the files are safe at `path` in local staging and `problems` says why).
- `sidecars_copied` lists the files copied to the repository's `data/<session>/` (only validated `.json` sidecars, never a WAV);
  `sidecars_copy_skipped` says why not (`simulated session: ...`, `the session did not validate`, `no sidecar_dir is configured`).
- `rate_source`: `fit` (from the DATA timestamps; normal), `status` or `nominal`. `sample_rate` is `round(sample_rate_measured)`.

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
