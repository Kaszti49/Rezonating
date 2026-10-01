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

## Rules

- Feature code lives in `src/rezonating_ml/features/` and is mirrored in
  `firmware/components/features/`. Changing one means changing both and
  regenerating test vectors (Tier 1).
- Models export as int8 TFLite into the pack folder: `packs/<id>/model.tflite`.
