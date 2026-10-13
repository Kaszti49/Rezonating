# ML

Python package for features, training, evaluation and export to TFLite Micro.

```bash
cd ml
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
```

## First tasks (before hardware arrives)

1. Download the public [FootprintID dataset](https://zenodo.org/records/4691144)
   (10 people, 5 geophones, 8 walking speeds) into `data/raw/` (git-ignored).
2. Write a loader that turns it into WAV + sidecar files in our own format.
3. Footstep segmentation (STA/LTA) and a first feature set `footstep_v1`.
4. Baseline classifier (scikit-learn), evaluated with a split by session,
   never by random clip.

## Dataset manifest (`data/manifest.json`)

`rezonating_ml.manifest` lists every recording file of a dataset with its SHA-256, so a result
can name exactly what it was trained on and anyone can check their copy of the WAVs. It is built
from the sidecars in the repo (`data/<session>/<session>.adc.json|accel.json`) and the WAVs on the
data root (the shared drive: `<data_root>/<session>/<session>.adc.wav|accel.wav`).

```bash
python -m rezonating_ml.manifest build --data-root D:/rezonating-recordings   # writes data/manifest.json
python -m rezonating_ml.manifest verify data/manifest.json --data-root D:/rezonating-recordings
```

`--data-root` defaults to `RZ_DATA_ROOT`. `build` takes `--session` (repeatable) and `--strict`
(exit 1 if any entry is invalid). `verify` exits 1 if a WAV is missing, changed or was never hashed.

In Python, `build_manifest(..., hash_wavs=False)` reads WAV headers only (the lab's Datasets index
uses it): `sha256` and `size_bytes` stay `null`, `valid` and `errors` are the same as with hashing,
and `write_manifest` refuses such a result while any WAV is present.

Format v1. The module docstring describes every field, and `MANIFEST_SCHEMA` in the module
enforces them; it is not in `schemas/`. One entry:

```json
{
  "session": "2026-11-17_lab_bench_01", "stream": "adc_raw",
  "wav": "2026-11-17_lab_bench_01/2026-11-17_lab_bench_01.adc.wav",
  "sidecar": "data/2026-11-17_lab_bench_01/2026-11-17_lab_bench_01.adc.json",
  "wav_present": true, "sha256": "9f2c…", "size_bytes": 2419244,
  "frames": 604800, "channels": 2, "fs_header_hz": 2016, "fs_measured_hz": 2016.13,
  "duration_s": 299.980656, "start_utc": "2026-11-17T09:14:02.000Z", "protocol": "walk-pass-v1",
  "floor": "2", "surface": ["laminate on concrete slab"], "people": ["P2", "P10"], "label_count": 14,
  "loss": {"device": 0, "link": 0, "host": 0}, "simulated": false, "incomplete": false,
  "valid": true, "errors": []
}
```

- Paths are relative: `wav` is `<session>/<file>.wav` on the data root, and `sidecar` is
  `data/<session>/<file>.json` in the repo. An absolute path, `..`, or a WAV outside its own session
  folder is refused. Only `<session>.json` and `<session>.<adc|adcdec|accel>.json` are read as sidecars.
- `valid` means the WAV is present, the sidecar meets its schema and `io.check_pair` finds no
  problem; `errors` says why not. A malformed sidecar becomes an invalid entry; it never stops the build.
- `errors` never repeats a string from the sidecar (names, session text, notes, field names). Only
  numeric details are kept.
- `people` holds pseudonyms only. Any other value is left out and reported without its text.
  `protocol`, `floor` and `surface` are copied from the sidecar as they are.
- The output is deterministic: entries are sorted by `wav`, keys come in a fixed order, and the file
  uses LF line endings. Only `created` changes between two builds of the same files.
- Top level: `format`, `version`, `created`, `data_root` (a fixed note, never a path), `entries`,
  `unmatched_wavs` (WAVs on the drive with no sidecar in the repo).

## Pack pipeline (D-021)

`build_pipeline(pack_json)` runs the stages a `pack.json` names on one channel, chunked and
stateful: the chunk outputs plus the `finish()` output, concatenated, are byte-identical to the batch
call `run_pipeline`.

```python
from rezonating_ml.baseline import train_baseline_model
from rezonating_ml.pipeline import build_pipeline, run_pipeline, sidecar_lost_total, zero_fill_mask

pipe = build_pipeline("packs/footstep-id/pack.json")  # input 2000 Hz adc_raw (D-020)
out = pipe.process(chunk)  # .decimated .valid .filtered .ratio .events .windows (pack-rate indices), .stages
out.features, out.feature_windows  # (k, 13) float32 footstep_v1 rows, one per window with n_invalid == 0
out.model  # None: no model loaded (the pack names model.tflite; TFLite export comes later)
last = pipe.finish()  # end of stream: .windows = the windows still open, cut (n_invalid > 0, so skipped)
pipe.n_windows_featured, pipe.n_windows_skipped_invalid  # every reported window is one or the other

# An in-memory model (anything with predict, predict_proba and classes_), run once per feature window:
model = train_baseline_model(X, y, seed=0)  # fits make_model("logreg"); results still come from evaluate()
out = run_pipeline("packs/footstep-id/pack.json", x, model=model)
out.model.classes, out.model.labels, out.model.proba  # proba: (k, n_classes) float32, aligned with feature_windows

# Lost samples: one bool per input sample (False = lost). Recordings store them as whole frames of zeros
# and the sidecar keeps only the counts. Rebuild the mask from the whole WAV (frames: (n_frames, n_channels)
# int32) and the sidecar total; it raises LostSampleMismatch when it can't back the mask.
m = zero_fill_mask(frames, expected_lost=sidecar_lost_total(sidecar["loss"]))
m.covers_all_lost, m.n_surplus  # every lost frame is marked; real all-zero frames marked lost too
out = run_pipeline("packs/footstep-id/pack.json", frames[:, 0], valid=m.valid)
```

**Lost-sample mask contract.** A mask must mark every lost sample. A lost sample left valid runs
through the high-pass as a step and can trigger a false event; a good sample marked lost only costs
data (the outputs it reaches are invalid, a window over it is skipped and counted). The node's mask is
exact. For a recording, `zero_fill_mask` works from two facts in `tools/lab/PROTOCOL.md` section 6:
every lost frame is zeros on every channel, and the sidecar total `E` is the number of lost frames. So
with `Z` all-zero frames in the file: `E = 0` marks nothing (exact); `E = Z` marks them all (exact);
`0 < E < Z` marks every all-zero frame when `min_run` allows it (the default with two or more channels)
and reports the real ones as `n_surplus`, since sidecar v1 stores no gap positions. A single channel
(default `min_run` 8) falls back to runs that must total exactly `E`. `E > Z` or a count that differs
raises.
**Always check `m.covers_all_lost` before trusting a mask**: when it is `False` (a single channel backed by
the count only warns with a `UserWarning`, also through `valid_from_zero_fill`), a short loss may be unmarked.

**Every event is accounted for.** `events` arrive with their onset; `windows` repeats each event once
with `n_invalid`: when `[start, end)` is complete, or from `finish()` when the stream ends first
(samples before 0 or past the end count as invalid). `n_events == n_windows + n_windows_pending`;
`n_windows_invalid` counts the skipped windows, `n_windows_cut` those the end of the stream cut.

| Stage | Module | What it does |
| --- | --- | --- |
| `decimate` | `rezonating_ml.dsp.Decimator2` | D-016 63-tap equiripple FIR, keep odd raw indices: 2000 → 1000 Hz. Pass 0–400 Hz within +0.0001/−0.00001 dB, ≥ 104.5 dB down from 600 Hz. Decimated `k` describes raw index `2k − 30` (31 samples of group delay). `bypassed` when the input already runs at the pack rate. Lost raw samples are held at the previous good value inside the FIR; an output whose window held one is invalid (as `adc_dec` in `tools/lab/PROTOCOL.md`). `to_adc_dec_codes` gives the int32 link values (round half away from zero, saturate to 24 bits). |
| `dsp` | `rezonating_ml.dsp.FilterChain` | Each `highpass_hz` / `lowpass_hz` entry is one biquad of `DSP_FILTER_FAMILY` / `DSP_FILTER_ORDER` (Butterworth, 2nd order: our convention, the pack names only the cutoff). float32, transposed direct form II; invalid samples are skipped. |
| `trigger` | `rezonating_ml.trigger.StaLta` | Recursive STA/LTA on `x²`; warm-up of `lta_ms`, re-arm only after the ratio dips below `ratio`, refractory `post_ms`; events `[onset − pre, onset + post)`. Invalid samples are skipped. `windows` gives each event once with `n_invalid` (`trigger.window_n_invalid`). The features stage skips windows with `n_invalid > 0` and counts them (`Pipeline.n_windows_invalid`); firmware does the same, including the windows open when a stream stops. |
| `features` | `rezonating_ml.features.footstep_v1` | `ok` for `features: "footstep_v1"`: 13 float32 features on `filtered[start:end]` of each reported window with `n_invalid == 0`, from filtered history the pipeline keeps for open windows (so chunked == batch). Windows with `n_invalid > 0` are skipped and counted (`n_windows_skipped_invalid`). Another feature set name, or no trigger, is `not_available`. |
| `model` | `build_pipeline(..., model=)` | `ok` when a fitted classifier is passed (`baseline.train_baseline_model`): labels and float32 probabilities per feature window, one window per call as on the node. Without one: `not_available`, "no model loaded (pack names model.tflite; TFLite export comes later)". |

The exact float32 recurrences and edge rules are in each module's docstring; the firmware must follow
them, with 64-bit sample indices (as in D-018), and **build the dsp and trigger sources with
`-ffp-contract=off`** (Xtensa GCC otherwise fuses multiply-adds into `madd.s`). Each vector tolerance
is 10x the measured error of an FMA emulation or a float64 reference, whichever is larger. Test
vectors for the firmware live in `tests/vectors/` (`decimator_fir.json`, `dsp_biquads.json`,
`sta_lta.json`, from a seeded synthetic clip). Each holds lost samples: a `valid` mask on the decimator
input, and a `masked` case in the other two, with runs of 1 to 7 samples, one at index 0, and (in
`sta_lta.json`) the expected `windows` with `n_invalid`, one of them cut by the end of the stream:

```bash
python -m rezonating_ml.vectors --write   # regenerate after changing a stage, then tell firmware
python -m rezonating_ml.vectors --check
```

## Rules

- Feature code lives in `src/rezonating_ml/features/` and is mirrored in
  `firmware/components/features/`. Changing one means changing both and
  regenerating test vectors (Tier 1).
- Models export as int8 TFLite into the pack folder: `packs/<id>/model.tflite`.
