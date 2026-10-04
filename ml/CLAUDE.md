# ml/ — context for Claude

Python package `rezonating_ml` (`src/` layout, Python 3.10+): loaders, segmentation, features,
training, evaluation and export for packs. The method is in the `ml-training` skill.

## Layout (grows as code lands)
- `src/rezonating_ml/` — importable code only; no notebooks, no data, no hard-coded paths.
- `tests/` — pytest; synthetic signals with known answers; `tests/vectors/` for feature test
  vectors shared with firmware.
- Notebooks and one-off scripts go in `scratch/` at the repo root (throwaway; never imported).

## Code style
- `ruff format` (the edit hook applies it) and `ruff check` clean.
- Type hints on public functions; NumPy arrays documented with shape and dtype, e.g.
  `x: np.ndarray  # (n_samples,), float32, volts`.
- Units in names: `fs_hz`, `win_s`, `f_lo_hz`. Seeds passed in, never global.
- Paths come from arguments or `data/manifest*`, never from a person's machine.

## Data rules
- Never open, copy or print `data/raw/`, `data/private/` or real names behind pseudonyms.
- Results without the split (by person or session) and a baseline are not results.

## Commands
```bash
pip install -e "ml[dev]"
python -m pytest -q ml/tests
ruff check ml tools
```
