---
type: decision
id: D-021
status: proposed
date: 2026-10-13
decided_by: []
tier: 1
supersedes:
---
# D-021 Pack pipeline in rezonating_ml

**Decision:** `rezonating_ml` gets the pack pipeline that the Lab's Pack bench and Experiments pages run on ([[D-017 Rezonating Lab bench tool]]):
- `build_pipeline(pack_json)`: the stages a pack names, in order: the FIR + ÷2 decimator from [[D-016 ADC records at 2 kSPS]] (63-tap linear-phase equiripple FIR, pass 0–400 Hz with ripple under ±0.001 dB, about 105 dB attenuation from 600 Hz, 31 raw samples of group delay; Kaszti chose 63 over 47 taps on 2026-10-13), the `dsp` filters, the STA/LTA trigger, the features and the model. It runs chunked and stateful, and its output is byte-identical to the batch call on the same samples.
- **STA/LTA trigger** with the parameters in `packs/footstep-id/pack.json` (`sta_ms`, `lta_ms`, `ratio`, `pre_ms`, `post_ms`); events are sample indices.
- **`footstep_v1` features**: a first, simple, documented set (time-domain energy, peak, duration and band energies from the event window).
- **Baseline classifier**: a scikit-learn model on `footstep_v1`, always reported next to a majority-class baseline, with a split by session or person and no overlap.
- **Test vectors** in `ml/tests/vectors/` for the decimator, STA/LTA and `footstep_v1`, so the firmware can match them later.

Kaszti asked Claude to write this on 2026-10-13 (Lab phases 5 and 7), ahead of [[Footstep segmentation with STA-LTA]] and [[Baseline person-ID classifier]] (both Viktor's). Viktor reviews it, and the parameters, features and model can still change.

**Why:** The Pack bench and Experiments pages need a pipeline to show, and the Lab must hold no signal maths of its own (D-017). Shared feature code in `ml/` is Tier 1, so it needs this decision.

**Rejected alternatives:** Wait for Viktor's items (the Lab phases 5 and 7 stay empty until late November). Build the stages inside the Lab (breaks D-017: two implementations of the same maths).

**Affects:** `ml/src/rezonating_ml/` (new pipeline, trigger, features, baseline, test vectors), the Lab simulator's `adc_dec` (now the real decimator), [[Lab 5 Pack bench]], [[Lab 7 Experiments page]], [[Footstep segmentation with STA-LTA]], [[Baseline person-ID classifier]]. The firmware side (the same decimator, STA/LTA and features in C) isn't written yet: until it is, one feature implementation in two languages is not met, and the test vectors are what the firmware must match. Accept in Obsidian if this is right.

**Clarification (Kaszti, 2026-10-13):** a pack `dsp` entry `highpass_hz` / `lowpass_hz` means one 2nd-order Butterworth biquad (−12 dB/octave), the same in Python and firmware (`DSP_FILTER_FAMILY`, `DSP_FILTER_ORDER` in `rezonating_ml.dsp`). Firmware builds the `dsp` and trigger code with `-ffp-contract=off` and uses 64-bit sample indices; a lost raw sample is held at the previous good value and the outputs it touches are invalid (PROTOCOL.md).

**Acceptance:** Kaszti accepted D-021 in the cloud session chat on 2026-10-13 ("I kaszti accept decision 21 … I read it and accept the decision"); he couldn't edit the file from there. Kaszti flips `status` and `decided_by` in Obsidian at the next chance.
