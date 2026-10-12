---
type: decision
id: D-019
status: accepted
date: 2026-10-12
decided_by:
  - kaszti
  - viktor
tier: 1
supersedes:
---
# D-019 Sidecar v1

**Decision:** Bump the recording sidecar schema (`schemas/sidecar.schema.json`) from v0 to **v1** and add the fields that "count every sample" and the LTC6903 clock need. Everything already in v0 stays.

| Field | Type | Meaning |
| --- | --- | --- |
| `sample_rate` | integer (unchanged) | Rate written in the WAV header: `round(sample_rate_measured)` |
| `sample_rate_nominal` | integer | What the node was set to, e.g. 2000 |
| `sample_rate_measured` | number | Measured rate in Hz (DRDY counted against the ESP32 timer), e.g. 2016.13 |
| `stream` | enum `adc_raw`, `adc_dec`, `accel` | Which node stream this WAV holds ([[D-018 Node link protocol v0]]) |
| `clock` | enum `ltc6903`, `adxl355`, `crystal` | What clocks the samples |
| `first_sample` | integer | The node's sample index of the WAV's first frame |
| `t_dev_us` | integer | Device µs timestamp of the first frame (used to line up streams) |
| `loss` | object `{device, link, host}` | Samples lost in acquisition, in the node's send queue, and as gaps seen on the PC. Missing samples are written as zeros at their place, so time stays true |
| `link` | enum `usb`, `wifi`, `sd` | How the samples reached the PC |
| `labels[].i0`, `labels[].i1` | integer | Label start and end as sample indices (`t0`/`t1` stay, in seconds = index ÷ `sample_rate`) |
| `labels[].src` | enum `key`, `phone`, `review`, `auto` | Where the mark came from |
| `labels[].unc_ms` | number | Timing uncertainty of a live mark |

One session folder holds one WAV + sidecar per stream: `<session>.adc.wav|json` and `<session>.accel.wav|json`. The `session` field and its pattern don't change.

**Why:**
- The LTC6903 clock is only 0.5 % typ accurate (up to 1.65 % over temperature), so v0's single integer `sample_rate` can't record the real rate. Over a 30-minute session, a 1.65 % error moves labels by about 30 s.
- v0 has nowhere to record lost samples, which breaks the "count every sample" rule.
- The ADC and the ADXL355 run on different clocks and need separate WAVs, plus a way to line them up.
- The Handoff has listed the measured-rate field as an open question since 2026-10-06. [[D-016 ADC records at 2 kSPS]] already says to record the measured rate.
- Until this is accepted, [[D-017 Rezonating Lab bench tool]] writes v0-valid sidecars, with the extra values in `notes` (`rzlab: key=value; …`).

**Rejected alternatives:**
- Only make `sample_rate` a number: still no loss counts and no stream id.
- Keep the extras in a separate lab file: splits one recording's facts over two files.
- One WAV per session resampled to a common rate: changes the raw data.

**Affects:** `schemas/sidecar.schema.json` (v1, `$id` `/v1`, `"schema": {"const": 1}`), `schemas/examples/`, `tools/validate.py` (accepts v0 and v1), `rezonating_ml.io`, the lab recorder, [[WAV and sidecar writer on microSD]] (the firmware writes the same fields). Should be accepted before the first rig records (2026-11-17). Accept in Obsidian if this is right.
