# Rezonating — context for AI assistants

Read this before changing anything in the repo.

## What this is

A vibration-sensing platform built by a two-person team (Kaszti Benedek:
design and management; Szabó Viktor: code). One ESP32-S3 node reads up to four
sensor heads through an ADS131M04 ADC (plus I2C for digital heads). Software
packs, not firmware changes, decide what a node detects.

Scope is **Year 1 only**: `footstep-id`, then `fall`, then `appliance`. Do not
plan or build for later packs unless asked.

## Rules

- **Tier 1 files** (`schemas/`, `firmware/components/` core, shared feature
  code in `ml/`) change only together with an entry in `docs/decisions.md`.
- **`scratch/` is throwaway.** Nothing outside it may import from it.
- **Never commit raw recordings** (`*.wav`) or the name list behind person
  pseudonyms (P1, P2, …). Only sidecars and the dataset manifest go in git.
- **Count every sample.** Firmware must report dropped samples, never hide them.
- **One feature implementation, two languages.** Any change to feature code in
  Python needs the matching firmware change and updated test vectors.
- Run `python tools/validate.py` before committing schema, pack or sidecar
  changes.

## Hardware facts that bite

- ADS131M04 needs a continuous 8.192 MHz clock on CLKIN (no internal
  oscillator). All 4 channels share one data rate (500 SPS to 64 kSPS).
- ADS131M04 inputs survive only AGND −1.6 V to AVDD +0.3 V: piezo heads must be
  clamped and buffered.
- ADXL355 is digital (SPI/I2C) and does not go through the ADC.
- ESP32-S3-N16R8 uses octal PSRAM: GPIO 35, 36 and 37 are taken.

## Commands

```bash
python tools/validate.py                # schemas, examples, packs, sidecars
cd firmware && idf.py build             # ESP-IDF v5.3+, target esp32s3
```
