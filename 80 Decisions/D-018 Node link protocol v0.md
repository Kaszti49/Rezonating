---
type: decision
id: D-018
status: accepted
date: 2026-10-12
decided_by:
  - kaszti
  - viktor
tier: 2
supersedes:
---
# D-018 Node link protocol v0

**Decision:** The node and the PC talk over **one binary protocol**, which runs on both the ESP32-S3's native **USB-Serial/JTAG** port and **TCP over Wi-Fi**. The full spec is `tools/lab/PROTOCOL.md`. The short version:
- **Framing:** COBS frames ending in `0x00`, each with a CRC-16/CCITT-FALSE. The header is `{ver, type, seq}`, little-endian. The bytes are identical on both transports.
- **Node → PC:**
  - `HELLO`: firmware, node id, heads, streams.
  - `DATA`: stream, 64-bit first-sample index, device µs timestamp, int32 samples.
  - `STATUS` at 1 Hz: samples, device drops, link drops, measured rate, clipping, queue, SD, RSSI.
  - `EVENT`: trigger or pack output, with its sample index.
  - `LOG`: replaces ESP_LOG text on the stream.
  - `ACK`/`ERR`.
- **PC → node:** `GET_INFO`, `START`/`STOP`, `SET` (gain, streams, Wi-Fi credentials, pairing key), `SD_RECORD`, `PING`, `REBOOT`.
- **Streams:**
  - `adc_raw`: 2 ch × 2 kSPS.
  - `adc_dec`: 2 ch × 1 kSPS, after the firmware FIR ([[D-016 ADC records at 2 kSPS]]).
  - `accel`: ADXL355, 3 ch × 2000 Hz.
  - Each stream has its own sample counter and measured rate, because the LTC6903 and the ADXL355 run on different clocks.
- **Wi-Fi:**
  - Discovery: mDNS `_rezonating._tcp`, plus manual IP.
  - The node accepts one client, which must present a pairing key set over USB.
  - A 10 s send queue in PSRAM; a full queue never blocks acquisition and is counted as link drops.
- **Firmware:** a new Tier 2 component `link`, separate from `net` (MQTT / Home Assistant, [[D-007 Home Assistant via MQTT]]).
- **One protocol, two languages:** the Python codec (`tools/lab`) and the C header (`firmware/components/link`) are both tested against the same golden byte vectors.

**Why:**
- No host↔node protocol exists yet, and [[D-017 Rezonating Lab bench tool]] needs one for live data, device control and health.
- Kaszti asked for USB and Wi-Fi from day one (2026-10-12). One framing for both means one codec and one set of tests.
- The 64-bit sample index and the separate drop counters make "count every sample" checkable on the PC. The device timestamp lets us line up streams that run on different clocks.
- Bandwidth with every stream on is about 50 kB/s, well within full-speed USB and Wi-Fi TCP.

**Rejected alternatives:**
- Text/CSV over serial: too slow, hides lost samples, and ESP_LOG lines corrupt it.
- WebSocket on the node: more firmware code and memory for no gain, since the PC server is the only client.
- MQTT for raw samples: wrong tool for 2 kSPS streams; MQTT stays for Home Assistant events.
- Protobuf/CBOR: more dependencies on the node, and fixed little-endian structs are enough.
- UART-bridge port at 921600 baud: about 55 % load, little headroom.

**Affects:** `tools/lab/PROTOCOL.md`, `tools/lab/src/rezonating_lab/link/`, the new `firmware/components/link/`, [[ADS131M04 driver]] (it fills the drop counters and the measured rate), `firmware/README.md` (component table), `sdkconfig.defaults` (console moves off USB-Serial/JTAG once `link` lands). Accept in Obsidian if this is right.
