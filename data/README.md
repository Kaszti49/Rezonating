# Data

Only sidecars (`*.json`) and `manifest.json` live in git. WAV recordings live
on the team's shared drive, in the same folder structure:

```
data/<YYYY-MM-DD>_<site>_<room>_<nn>/
  <session>.wav     # shared drive only
  <session>.json    # sidecar, in git, validated by tools/validate.py
```

- People are pseudonyms (`P1`, `P2`, …). The name list never enters the repo.
- Everyone recorded gives written consent first.
- `raw/` (public datasets, downloads) and `private/` are git-ignored.
