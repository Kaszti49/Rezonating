# Packs

One folder per pack: `pack.json` (validated against
`schemas/pack-manifest.schema.json`), plus `model.tflite` and a short README
once trained. All numbers in the current manifests are starting guesses, to be
tuned on recordings.

| Pack | Engine | Head | Year 1 order |
| --- | --- | --- | --- |
| `footstep-id` | classifier | Geophone | 1 |
| `fall` | classifier + stillness rule | Geophone | 2 |
| `appliance` | anomaly | ADXL355 | 3 |
