---
paths:
  - "schemas/**"
  - "packs/**"
  - "tools/validate.py"
---

# Schemas and packs (Tier 1)

`schemas/` defines the head descriptor, the pack manifest and the recording sidecar. Firmware,
`ml/` and every recording depend on them, so they change only with an accepted decision note.

- A schema change needs a `D-###` decision with `status: accepted` named in the task. Without
  it, propose the decision instead of editing.
- On a breaking change bump the version (the `/v0` in `$id` and the `"schema": {"const": 0}`
  value) and update `schemas/examples/` in the same edit.
- Every `packs/*/pack.json` and every example must still pass: `python tools/validate.py`
  (the edit hook runs it when jsonschema is installed).
- JSON Schema draft 2020-12; keep `additionalProperties: false` where it is.
