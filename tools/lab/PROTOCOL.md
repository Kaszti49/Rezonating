# Rezonating node link protocol v0

Status: **v0, accepted with decision D-018 (2026-10-12)**. It may still change until the first
firmware ships. This file is the contract between the node firmware (`firmware/components/link/`)
and the PC (`tools/lab/src/rezonating_lab/link/`). Both sides test against the same golden
vectors (`tools/lab/tests/vectors/link-v0.json`). A change here needs the matching change on the
other side and new vectors in the same commit.

## 1. Transports and sessions

The byte stream is identical on every transport.

| Transport | Details |
| --- | --- |
| USB | ESP32-S3 native USB-Serial/JTAG (VID:PID `303A:1001`). Baud rate is ignored. The PC opens the port with DTR and RTS **de-asserted** (pyserial: set `dtr=False, rts=False` *before* `open()`), because asserting RTS resets the chip through the USB-Serial/JTAG reset logic. After a reboot the PC finds the port again by VID:PID. |
| Wi-Fi | TCP, node listens on port **7350**. Advertised over mDNS as `_rezonating._tcp` with TXT `node=<node id>`, `proto=0`. One client at a time; a second connection is refused while a session is live. |
| Simulator | Same as Wi-Fi on `127.0.0.1:7350` (`rzlab sim`). The PC can also open it as a serial port through pyserial's `socket://127.0.0.1:7350` URL. The simulator follows the **USB** session rules by default (`GET_INFO` starts the session, `AUTH` optional); with `--auth` it follows the TCP rules. |

**Session.** The node can't see a COM port being opened, so the PC always starts the session:
- **Opening:** the PC writes one `0x00` before its first frame, to flush any stale bytes on the node.
- **Before a session**, the node silently ignores every frame except the session start (`GET_INFO` on USB, `AUTH` on TCP).
- **Left-over USB session:** on USB the node can't see the port close, so a PC that reconnects within 5 s lands in the old session. Its `GET_INFO` only re-sends `HELLO` + `CONFIG`, and the streams may still be running with an old window. So after `HELLO` the PC always sends `STOP` for all streams and waits for its ACK (up to 2 s) before its first `START`.
- **Accounting gate:** frames arrive in order, so the PC uses a stream's `STATUS` windows only after the ACK of its own `START`. If that ACK is lost, a `STATUS` with `running = 1` arms the stream, but only if a `STOP` was acknowledged since `HELLO`. If the clean-up `STOP` ACK never arrives, the PC carries on with accounting reset, so a stale window shows up as host gap rather than being hidden.
- **Start:** the session starts with `GET_INFO` on USB, or `AUTH` on TCP. In reply the node writes exactly, with no ACK:
  1. one `0x00` byte;
  2. `HELLO` with seq 0;
  3. `CONFIG` with seq 1.
  After that it sends `STATUS` every `status.period_ms` (default 1000 ms) until the session ends.
- **Seq reset:** the node resets its send `seq` to 0 every time it sends `HELLO`, including in reply to a later `GET_INFO`. The PC resets its expected `seq` whenever it receives a `HELLO`.
- **One session at a time across all transports.** While a session is live, a session start on the other transport gets `ERR 5` (busy), and on TCP the connection is then closed.
- **TCP authentication:** the client must send `AUTH` within 2 s of connecting. Otherwise, or with a wrong key, the node sends `ERR 6` (with node seq 0, and `cmd_seq` = the AUTH frame's seq, or `0xFFFF` on a timeout) and closes the connection.
- **Liveness:** the PC sends `PING` at least once per second. The node ends the session when it has received no valid PC frame for 5 s; on TCP it also closes the socket. "Valid" means it passed COBS and CRC, even if the command is then answered with `ERR`.
- **USB close:** when the USB port closes, the session and its streams keep running until the liveness timeout. DATA the node can't write counts in `win_link`.
- **Session end:** all link streams stop (an implicit `STOP` of every stream, without the drain) and the send queue is cleared. Samples still in the queue count in `win_link`. Acquisition keeps running if `SD_RECORD` still needs it (section 4.3, acquisition).

**Console.** With `link` active, no text may reach the USB stream:
- `sdkconfig.defaults` sets `CONFIG_ESP_CONSOLE_UART_DEFAULT=y` and `CONFIG_ESP_CONSOLE_SECONDARY_NONE=y`. The default secondary console mirrors every log line onto USB-Serial/JTAG, and each line would destroy the next frame.
- On the ESP32-S3 the ROM print functions (`esp_rom_printf`, early and DRAM logs) also write to USB-Serial/JTAG. So when `link` starts, the firmware must switch that ROM output off (for example with `esp_rom_install_channel_putc(2, NULL)`). This must be **confirmed on the board** in the first `link` test.
- Log lines travel as `LOG` frames instead (section 4.6).
- Text from the ROM and the 2nd-stage bootloader at boot is harmless: the session-start `0x00` separates it from `HELLO`.
- Any stray text that still appears costs one frame. It shows up in `bad_frames` and, if that frame was DATA, as a host gap.

## 2. Framing

```
raw frame   = header (4 B) | payload (0..4096 B) | crc16 (2 B)       ≤ 4102 B
wire frame  = COBS(raw frame) | 0x00                                   ≤ 4120 B
```

- **Header**: `u8 ver` (= 0), `u8 type`, `u16 seq`.
- **seq** counts frames per direction, starting at 0 at session start and wrapping at 65535. A
  jump in `seq` means frames were lost. The receiver counts them (`lost_frames`); it does not ask
  for a resend. With `jump = (seq − expected) mod 65536`:
  - `jump = 0`: in order.
  - `jump > 32768`, or `seq < 16` with `jump > 1024`, or a repeated `seq`: the numbering restarted (for example a lost `HELLO`). The receiver counts one `resyncs`, no lost frames, and expects `seq + 1` next.
  - Otherwise `jump` frames were lost.
  A real loss of more than 1024 frames in a row can't happen within the 5 s liveness limit. `seq`, the CRC and the COBS encoding are applied when the frame is written to the
  transport, not when it is queued. So a frame dropped from a queue never gets a `seq`, and
  control frames that overtake queued DATA don't show up as lost frames.
- **crc16** is CRC-16/CCITT-FALSE: poly `0x1021`, init `0xFFFF`, not reflected, xorout `0`. The
  check value for ASCII `123456789` is `0x29B1`. It covers header + payload and is stored
  little-endian.
- **COBS** encoding, pinned exactly so that both encoders produce the same bytes:
  - The raw frame is split into blocks at each `0x00`, and also after every run of 254 non-zero bytes.
  - Each block is written as a code byte (block length + 1) followed by the block's non-zero bytes.
  - A block that ends at a `0x00` uses the zero as its terminator. A block of exactly 254 non-zero bytes has code `0xFF` and no implied zero.
  - **No extra code byte is written after a final 254-byte block.** So 254 × `0x01` encodes to 255 bytes (`FF 01 … 01`).
  - A frame that ends in `0x00` gets a final empty block, written as `01`. For example, `01 00` encodes to `02 01 01`. This happens about once every 256 frames, whenever the CRC's last byte is 0.
  - An empty raw frame never occurs (minimum 6 bytes).
  - Worst case is 4102 + ⌈4102 / 254⌉ = 4119 bytes, plus the delimiter.
- **Delimiters:** a sender may write extra `0x00` bytes between frames. The node writes one before `HELLO` at every session start. Receivers silently ignore empty chunks.
- **Receiver rules:**
  - Collect bytes up to each `0x00`. If more than 4119 bytes pile up without a `0x00`, count one `bad_frames` and discard everything up to and including the next `0x00`, however long that run is.
  - Also drop a chunk and count one `bad_frames` when: COBS decoding fails, the decoded length is under 6 or over 4102, the CRC is wrong, or `ver` ≠ 0. Then go on with the next chunk.
- **Forward compatibility:** receivers ignore payload bytes after the fields they know. New fields
  are only ever appended. Any other change bumps `ver`.
- Everything is **little-endian**. Floats are IEEE 754 binary32; "no value" is the quiet NaN
  `0x7FC00000`.
- **String and blob types:**
  - `str8` = `u8 length` + UTF-8 bytes. `str16` = `u16 length` + UTF-8 bytes. A sender truncates a longer string on a UTF-8 code point boundary.
  - `blob16` = `u16 length` + raw bytes.

## 3. Frame types

| Type | Name | Direction |
| --- | --- | --- |
| `0x01` | HELLO | node → PC |
| `0x02` | DATA | node → PC |
| `0x03` | STATUS | node → PC |
| `0x04` | EVENT | node → PC |
| `0x05` | LOG | node → PC |
| `0x06` | ACK | node → PC |
| `0x07` | ERR | node → PC |
| `0x08` | PONG | node → PC |
| `0x09` | CONFIG | node → PC |
| `0x81` | GET_INFO | PC → node |
| `0x82` | START | PC → node |
| `0x83` | STOP | PC → node |
| `0x84` | SET | PC → node |
| `0x85` | SD_RECORD | PC → node |
| `0x86` | PING | PC → node |
| `0x87` | REBOOT | PC → node |
| `0x88` | AUTH | PC → node |

Replies to PC → node frames:
- `GET_INFO` → `HELLO` + `CONFIG` (no ACK)
- `AUTH` (TCP session start) → `HELLO` + `CONFIG` (no ACK)
- `PING` → `PONG`
- `SET` → `ACK` then a new `CONFIG`; on failure `ERR` only
- `START`, `STOP`, `SD_RECORD`, `REBOOT` → `ACK` or `ERR`
- an unknown PC → node type → `ERR 1`

`ACK` and `ERR` carry the command's `seq` in `cmd_seq`. `HELLO`, `CONFIG` and `PONG` are matched by
type and order (the node handles commands strictly in order); `PONG` also echoes `host_t_us`. The
PC ignores unknown node → PC types and counts them.

## 4. Node → PC

### 4.1 HELLO (`0x01`)

| Field | Type | Notes |
| --- | --- | --- |
| proto | u8 | 0 |
| fw_version | str8 | e.g. `0.1.0` |
| node_id | str8 | e.g. `rzn-a1b2c3` (from the MAC) |
| t_dev_us | u64 | node µs clock (`esp_timer_get_time`) now |
| n_streams | u8 | |
| streams[] | | per stream: `u8 id`, `u8 n_ch`, `u32 nominal_hz`, `u8 bits`, `u8 clock`, `u16 fir_taps`, `u16 fir_delay` (both 0 except `adc_dec`) |
| n_heads | u8 | |
| heads[] | | per head: `u8 port` (1–4, as in the sidecar), `blob16 descriptor` (minified UTF-8 JSON that passes `schemas/head-descriptor.schema.json`, at most 900 B, so HELLO always fits in 4096 B) |

**Stream ids:**

| id | Name | Channels | Nominal rate | Bits | Clock |
| --- | --- | --- | --- | --- | --- |
| 0 | `adc_raw` | 2 (ADS131M02) | 2000 | 24 | 0 = LTC6903 |
| 1 | `adc_dec` | 2 | 1000 (FIR + ÷2, D-016) | 24 | 0 = LTC6903 |
| 2 | `accel` | 3 (ADXL355 x, y, z) | 2000 | 20 | 1 = ADXL355 |

Clock codes: 0 `ltc6903`, 1 `adxl355`, 2 `crystal`.

### 4.2 CONFIG (`0x09`)

Reports the current settings, so the PC can fill the sidecar (`gain`, `scale`, `units`) and
convert codes after any reconnect.

| Field | Type | Notes |
| --- | --- | --- |
| n_streams | u8 | |
| streams[] | | per stream: `u8 id`, `u8 n_ch`, then per channel: `u8 gain` (ADC PGA 1–128; 1 for accel), `f32 scale`, `u8 units` |
| accel_range_g | u8 | 2, 4 or 8 |
| status_period_ms | u16 | |

- `scale` multiplies a code to get the unit given by `units` (0 `counts`, 1 `V`, 2 `g`).
- ADC: `scale = 1.2 V / gain / 2^23`, in V at the ADC input.
- Accel: `scale = 1 / (LSB per g at the current range)`, in g.
- Converting volts to m/s uses the head descriptor's sensitivity on the PC.
- Gain and range can't change during acquisition, so one `scale` holds for a whole recording. A `SET adc.gain.*` while ADC acquisition runs, or a `SET accel.range_g` while accel acquisition runs, gets `ERR 5` (busy).

### 4.3 DATA (`0x02`)

| Field | Type | Notes |
| --- | --- | --- |
| stream | u8 | stream id |
| n_ch | u8 | must match HELLO |
| n | u16 | sample frames in this packet (≥ 1) |
| first_sample | u64 | index of the first frame in this packet |
| t_dev_us | u64 | node µs clock at the first frame (see below) |
| samples | i32 × n × n_ch | frame-major: `s0.ch0, s0.ch1, s1.ch0, …` |

- **Indices are contiguous inside a packet** (`first_sample … first_sample + n − 1`). A lost
  sample is **never sent**, not even as a placeholder. A drop ends the current packet, and the
  next packet starts after the gap.
- **Size:** the node aims for about 25 DATA frames per second per stream (an `adc_raw` packet
  carries about 80 frames, 640 B). The payload must stay ≤ 4096 B, so at most 509 frames for
  2 channels or 339 for 3.
- **`adc_raw` index and time:**
  - Index 0 is the first DRDY after ADC acquisition starts.
  - Every sample interval gets the next index, even when its sample is lost. To catch DRDY edges the ISR missed, the node compares the `esp_timer` time between consecutive DRDY ISRs with the measured period. A gap of g periods (rounded) means g − 1 indices were skipped, and each of them is counted in `device_dropped` (and in `win_device` while sending is on).
  - `t_dev_us` is the DRDY ISR time of the first frame.
  - Samples are the ADC's 24-bit two's-complement codes, sign-extended to int32.
- **`adc_dec` index and time:**
  - Decimated sample k is the FIR output computed after raw sample `2k + 1`. Its `t_dev_us` is that raw sample's DRDY time.
  - The FIR delays the signal by `fir_delay` raw samples (from HELLO, `(fir_taps − 1) / 2` for a symmetric FIR). The PC subtracts this delay when lining `adc_dec` up with `adc_raw`.
  - Values are in the same LSB as raw codes: rounded to nearest (halves away from zero) and saturated to the 24-bit range.
  - `fir_taps` must be odd, so `fir_delay = (fir_taps − 1) / 2` is a whole number.
  - When acquisition starts, the filter history is all zeros, so the first outputs are sent normally and include the start-up transient.
  - If any raw sample inside the FIR window of output k was lost, output k counts as `device_dropped` for `adc_dec` and is not sent. Inside the filter, a lost raw sample is replaced by the previous good one, or by 0 if there is none yet.
- **`accel` samples** are the ADXL355's 20-bit two's-complement values, right-justified (the
  3-byte register value shifted right by 4) and sign-extended to int32.
- **Acquisition lifecycle**, the same rule for both sensors:
  - The ADC (streams 0 and 1) and the accelerometer (stream 2) each acquire while at least one consumer needs them: a link stream that is started, or an `SD_RECORD` that includes the stream.
  - When a sensor's acquisition starts from fully idle, its indices restart at 0. Otherwise nothing is reset: a link `START` during an SD recording, or starting `adc_dec` while `adc_raw` runs, only turns sending on.
  - The 2:1 mapping between `adc_raw` and `adc_dec` is fixed for the whole acquisition.
- **`accel` index and time:**
  - The node reads the ADXL355 FIFO in batches. A read at node time `t_read` (µs) returning `m` samples gives them consecutive indices. The newest gets the highest index, and sample j (0 = oldest) has time `t_read − (m − 1 − j) × 10^6 / rate`, where `rate` is the measured rate in Hz.
  - If the ADXL355 reports FIFO overflow, the samples lost since the previous read (at `t_prev`) are estimated as `round((t_read − t_prev) × rate / 10^6) − m`. That many indices are skipped and counted in `device_dropped`.
- **The PC cross-checks the timing:** it fits `t_dev_us` against `first_sample` per stream, and
  flags a packet whose residual is more than 0.5 sample periods for the ADC streams, or more than
  1.5 periods for `accel` (whose timestamps are estimated).

### 4.4 STATUS (`0x03`)

Sent every `status_period_ms` during a session.

| Field | Type | Notes |
| --- | --- | --- |
| t_dev_us | u64 | |
| queue_fill | u8 | send queue fill, % |
| sd_state | u8 | 0 none, 1 ready, 2 recording, 3 error |
| sd_free_mb | u32 | |
| rssi_dbm | i8 | 0 when Wi-Fi is off |
| heap_free | u32 | bytes, internal RAM |
| temp_c_x10 | i16 | die temperature × 10 |
| n_streams | u8 | |
| streams[] | | per stream (below) |

| Per-stream field | Type | Notes |
| --- | --- | --- |
| id | u8 | |
| running | u8 | 0 or 1 (sending to the link) |
| produced | u64 | next index to be assigned (= indices assigned since acquisition started) |
| device_dropped | u64 | all indices lost in acquisition since acquisition started (missed DRDY, failed read, ring buffer full, FIFO overflow, FIR window rule); for health display |
| rate_mhz | u32 | measured rate in mHz over the last 10 s: indices assigned counted against the ESP32 µs clock (`adc_dec` reports the raw rate ÷ 2) |
| clipped | u32 | sample frames with at least one channel at full scale, since acquisition started |
| win_first | u64 | sending window: `produced` at the moment sending was last turned on by `START` |
| win_end | u64 | `produced` now while sending is on; frozen at the moment `STOP` turned it off |
| win_device | u64 | indices in `[win_first, win_end)` lost in acquisition |
| win_link | u64 | indices in `[win_first, win_end)` never fully handed to the transport (queue full, write error or timeout, queue cleared at session end) |

The window fields reset when `START` turns sending on. Before any `START`, they are all 0.

### 4.5 EVENT (`0x04`)

The simulator sends one EVENT per `footstep-id` trigger onset (`stream` 1, `sample` = the `adc_dec` index,
`kind` 0, `pack` `footstep-id`, `key` `step`, `value` = the STA/LTA ratio at the onset, `label` empty), computed
with `rezonating_ml` on its own `adc_raw` channel 0 (README, phase 1).

| Field | Type | Notes |
| --- | --- | --- |
| stream | u8 | stream the event refers to |
| sample | u64 | sample index of the event (trigger onset) |
| kind | u8 | 0 trigger, 1 pack output |
| pack | str8 | pack id, empty for a bare trigger |
| key | str8 | output key from `pack.json` `outputs[]`, e.g. `person` |
| value | f32 | score or probability, `0x7FC00000` if none |
| label | str8 | label value, e.g. `P2`, may be empty |

### 4.6 LOG (`0x05`)

| Field | Type | Notes |
| --- | --- | --- |
| level | u8 | 1 error, 2 warn, 3 info, 4 debug, 5 verbose (ESP-IDF order) |
| t_dev_us | u64 | |
| tag | str8 | |
| msg | str16 | without trailing newline, at most 1024 B |

### 4.7 ACK (`0x06`), ERR (`0x07`), PONG (`0x08`)

- **ACK:** `u16 cmd_seq`.
- **ERR:** `u16 cmd_seq`, `u16 code`, `str8 msg`. Codes: 1 unknown command, 2 bad payload, 3 unknown SET key, 4 bad value, 5 busy, 6 not authorised, 7 SD error.
- **PONG:** `u64 host_t_us` (echoed from PING), `u64 t_dev_us` (captured when the PING frame was decoded). The PC uses PING/PONG to measure round-trip time and to map the node clock to its own.

### 4.8 Send queue

- **Two queues:** control frames (HELLO, CONFIG, STATUS, EVENT, LOG, ACK, ERR, PONG) go in a small queue that is always sent first. DATA goes in the big PSRAM queue (about 10 s).
- **When the DATA queue is full,** the new DATA frame is dropped and its samples are added to `win_link`. Older data already queued is kept.
- **When the control queue is full,** LOG frames are dropped first, then periodic STATUS frames, and the count is reported in the next LOG line. The final STATUS of a `STOP` is never dropped. A full queue never blocks acquisition.

## 5. PC → node

| Frame | Payload |
| --- | --- |
| GET_INFO `0x81` | none |
| START `0x82` | `u8 stream_mask` (bit n = stream id n). Starting a stream that is already running is a no-op (ACK, no index reset). |
| STOP `0x83` | `u8 stream_mask`. The node freezes `win_end` for those streams. It then finishes every index below `win_end`: it waits for pending reads and FIR outputs, closes the current packet and queues it. Then it drains the DATA queue for those streams, sends a final `STATUS` (never dropped; STOP waits for queue space), and sends the ACK. During the drain `running` stays 1 in periodic STATUS frames; it reads 0 for the first time in the final STATUS. |
| SET `0x84` | `str8 key`, `u8 type` (0 i32, 1 f32, 2 str8, 3 blob16), value |
| SD_RECORD `0x85` | `u8 action` (0 stop, 1 start), `u8 stream_mask`, `str8 session` |
| PING `0x86` | `u64 host_t_us` |
| REBOOT `0x87` | none; the node ACKs, then reboots |
| AUTH `0x88` | `blob16 key`, length 16 (wire: `10 00` + 16 bytes). Starts a TCP session; on USB it is accepted and ignored. |

**SET keys (v0):**

| Key | Type | Values |
| --- | --- | --- |
| `adc.gain.0`, `adc.gain.1` | i32 | 1, 2, 4, …, 128 |
| `accel.range_g` | i32 | 2, 4, 8 |
| `wifi.ssid`, `wifi.pass` | str8 | USB only; stored in NVS |
| `pair.key` | blob16 | 16 bytes; USB only; stored in NVS |
| `status.period_ms` | i32 | 200 to 10000, default 1000 |

A `wifi.*` or `pair.key` SET over TCP gets `ERR 6`.

Keys starting with `sim.` (e.g. `sim.tap`) are reserved for the simulator (`rzlab sim`); real firmware never implements them and answers `ERR 3`.

**Error rules** (the firmware must match the simulator):
- A known command whose payload is too short gets `ERR 2`.
- A stream mask of 0 or with unknown bits, in `START`, `STOP` or `SD_RECORD` start, gets `ERR 4`. `SD_RECORD` stop with mask 0 means "stop all".
- `SET` checks run in this order, and the first failure is the answer: unknown key (`ERR 3`), USB-only key over TCP (`ERR 6`), wrong value type or out of range (`ERR 4`), busy (`ERR 5`).
- A PC frame with a bad CRC gets no reply; it only counts as a bad frame.

The pairing key travels in plain text and can be replayed by anyone on the same network. That is
acceptable for a bench tool on the lab network; it is not a security boundary.

## 6. Loss accounting on the PC

A recording over the link covers one sending window per stream, from `START` to `STOP`. The
final `STATUS` that `STOP` produces gives the numbers:

- `missing = (win_end − win_first) − samples received with index in [win_first, win_end)`
- `device = win_device`
- `link = win_link`
- `host_gap = missing − device − link`

`host_gap` counts samples that were sent but never arrived: corrupted or lost frames. It is never
negative; a negative value is a protocol bug and the lab says so. The sidecar's `loss.host` is `host_gap` plus the samples the
recorder itself dropped (writer queue overflow, rejected packets, write errors), and all zero-filled samples when no `STATUS` arrived. Each lost sample sits in
exactly one of the three counters, and `missing` is their sum.

- **While recording,** the live view uses the latest `STATUS`. Samples between the last index
  received and `win_end` are shown as pending, not as lost. The live `host_gap` is therefore a
  lower bound (shown as `12+`) whenever device or link losses may sit in the pending tail. The
  final numbers are exact.
- **Sidecar:** the three counters are written as `loss.device`, `loss.link` and `loss.host` (D-019).
- **Missing samples:** the recorder writes zeros at their place, so time stays true.
- **Which STATUS counts as final:** a STATUS that arrives after the PC sent `STOP`, shows `running = 0` for the stream, and is followed by the STOP's ACK. Only the ACK proves the drain finished. A STOP whose final STATUS or ACK is lost is handled as incomplete (see the next item).
- **If the session ends without a final `STATUS`** (disconnect, liveness timeout), the PC uses the
  last `STATUS` it got: that STATUS's `win_first` and `win_end` define the window. Everything it
  can't attribute counts as `host_gap`, and the recorder adds `rzlab: loss=incomplete` to the
  sidecar's `notes`.

## 7. Timing

- `t_dev_us` in DATA lets the PC measure each stream's rate itself (cross-checking `rate_mhz`)
  and put all streams on one device time base.
- The PC timestamps a keyboard label mark when it arrives and converts it to a sample index
  through the PING/PONG clock map and the per-stream fit. Phone marks get half the measured
  round-trip time as their uncertainty.

## 8. Golden vectors

`tools/lab/tests/vectors/link-v0.json` lists named cases with the decoded fields and the exact
wire bytes in hex. It covers:
- every frame type;
- a DATA frame for each stream;
- a payload containing `0x00` bytes;
- runs of exactly 253, 254 and 255 non-zero bytes;
- a 254-byte run followed by `0x00`;
- a 254-byte run that ends exactly at the end of the frame;
- a frame whose last byte (the CRC's high byte) is `0x00`;
- a session start: `00`, HELLO with seq 0, CONFIG with seq 1;
- the largest legal frame;
- oversize runs of 4120 and 4121 bytes without a `0x00` (each gives exactly one bad frame);
- a corrupted CRC;
- a stream that starts with boot text, then `0x00` and `HELLO`.

The Python codec must reproduce each case's bytes exactly. The firmware's host-side unit test,
generated from the same JSON, must too.
