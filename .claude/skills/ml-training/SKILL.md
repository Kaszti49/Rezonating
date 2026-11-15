---
name: ml-training
description: Playbook for ml/, tools/ and data/ manifests (Python signal processing, dataset loaders, segmentation, features shared with firmware, test vectors, training, evaluation, export, experiment logging). Load before writing Python in ml/ or tools/, designing an experiment, or reporting a model result.
---

# Playbook: ML and tools

## Working rules
1. Write the task's **Done when** first. Shared feature code is Tier 1: name the accepted `D-###`,
   otherwise stop and propose the decision.
2. Test first when the behaviour is clear (`ml/tests/`, pytest), with synthetic signals that have
   known answers (impulse train for steps, sine for spectral features).
3. Reproducible maths: fixed seeds, float32 where firmware uses float32, units in names (`fs_hz`,
   `win_s`), no hidden global state, no notebooks under `src/`.
4. A feature change regenerates its test vectors and says firmware must follow (two languages, one
   implementation). The fall features' reference is the C++ core in `firmware/hackathon-rezon/`
   (`tools/replay` prints them per event).
5. Never read or write `data/raw/`, `data/private/` or WAV contents into notes or git.
6. Finish with `ruff check` and `python -m pytest -q ml/tests` (the stop gate repeats them), then
   the `verify` playbook. Report dataset, split, metric, baseline and what the number doesn't show.

Code lives in `ml/` (package `rezonating_ml`). Each pack (`packs/<id>/pack.json`) names its head,
sample rate, trigger and model; the training code reads the same file, so firmware and Python can't drift.

## Data
- Recordings: WAV + JSON sidecar (D-008). Sidecars and `data/manifest*` are in git; WAVs and the
  pseudonym list (`data/private/`) never are.
- People are pseudonyms (P1, P2, …). Never write a real name next to a pseudonym anywhere.
- Public data first: FootprintID and the 2025 structural-vibration gait dataset (see `60 Research/`).

## Splits (the most common way to fool yourself)
- Person identification: split **by session or day**, never by window from the same walk.
- Report the split explicitly: train people/sessions, test people/sessions.
- Always report a baseline next to the model (majority class, or nearest-centroid on simple features).

## Pipeline shape
1. Load → resample to the pack's rate → high-pass (remove drift).
2. Segment: STA/LTA trigger (work note `20 Work/Footstep segmentation with STA-LTA.md`) → fixed windows around each event.
3. Features: implemented in `rezonating_ml.features` **and** firmware `components/features`.
   Every feature has test vectors (convention: `ml/tests/vectors/<feature>.json` with input,
   expected output and tolerance) that both sides must pass. float32 everywhere the firmware uses float32.
4. Model: start with scikit-learn (logistic regression, random forest, SVM). A neural net only when
   the simple model plateaus and the data justifies it.
5. Export (later): TFLite Micro int8, with the representative dataset recorded in the experiment.

## Logging a result
Every training run that matters becomes (or updates) an experiment note `50 Experiments/EXP-###`:
dataset + split, features, model, metric (`metric_value`), baseline, and what the number doesn't show.
Update the pack note's `best_value` only for a result on our own floor.

## Commands
```bash
pip install -e "ml[dev]"
python -m pytest -q ml/tests
ruff check ml tools
```
