# Rezonating

Camera-free sensing from vibration. One sensing node, swappable sensor heads
(geophone, accelerometer, piezo) and software **packs** that decide what the
node detects: who is walking, a fall, a failing washing machine.

> Status: Year 1, pre-hardware. Private during development; planned to go
> open source.

## How it works

1. **Heads identify themselves.** Each head carries a small EEPROM with a
   descriptor (type, model, sensitivity, mount). See
   [`schemas/head-descriptor.schema.json`](schemas/head-descriptor.schema.json).
2. **Packs declare what they need.** A pack is a folder with `pack.json`, an
   optional model and thresholds. See
   [`schemas/pack-manifest.schema.json`](schemas/pack-manifest.schema.json).
3. **The node matches them.** A pack runs only when the attached heads satisfy
   it. Several packs can share one sensor stream.
4. **Every recording follows one format:** multichannel WAV + JSON sidecar. See
   [`schemas/sidecar.schema.json`](schemas/sidecar.schema.json).

## Year 1 packs

| Pack | Head | Status |
| --- | --- | --- |
| `footstep-id` — who is walking | Geophone | Starter |
| `fall` — a person fell | Geophone | Next, same hardware |
| `appliance` — machine running abnormally | ADXL355 | After footstep ID works |

## Repo layout

```
docs/        decisions, recording protocols, first order
schemas/     head descriptor, pack manifest, sidecar   (Tier 1)
firmware/    ESP-IDF project for the ESP32-S3 node     (core = Tier 1)
packs/       one folder per pack
ml/          Python: features, training, export to TFLite Micro
tools/       validators, recorder, labeling helpers
hardware/    node and head designs, pinouts
data/        dataset manifest + sidecars only; WAV files live outside git
scratch/     Tier 3 experiments: never imported by anything else
```

## Quality tiers

- **Tier 1 (load-bearing, change only with a decision entry):** `schemas/`,
  firmware core (acquire, buffer, timestamps, pack loader), shared feature code.
- **Tier 2 (replaceable):** packs, models, training scripts, tools, PCBs.
- **Tier 3 (throwaway):** `scratch/`, breadboard rigs, test enclosures.

## Getting started

```bash
# Validate schemas, examples and pack manifests
pip install -r tools/requirements.txt
python tools/validate.py

# Build the firmware (ESP-IDF v5.3+)
cd firmware
idf.py set-target esp32s3
idf.py build flash monitor
```

## Team

- Kaszti Benedek — design, management
- Szabó Viktor — firmware and code
