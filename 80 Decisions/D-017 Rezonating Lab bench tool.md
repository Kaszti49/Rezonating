---
type: decision
id: D-017
status: accepted
date: 2026-10-12
decided_by:
  - kaszti
  - viktor
tier: 2
supersedes:
---
# D-017 Rezonating Lab bench tool

**Decision:** We build **Rezonating Lab**, a local web app that is the team's bench environment. It lives in `tools/lab/`: a Python server (FastAPI) that reuses `rezonating_ml`, and a browser UI in Svelte + TypeScript + Vite + uPlot. It runs on any team PC, Windows first. It covers four areas: live view and device health, recording and labelling, the pack bench, and experiments and datasets. A simulator node speaks the same link protocol as the real node ([[D-018 Node link protocol v0]]), so the lab works before the hardware arrives. Obsidian stays the project manager. The lab is where the signal work happens.

**Scope:** The lab is an **internal tool** for Kaszti, Viktor and Claude. It is **not** the product "own app" that the [[Charter]] keeps out of Year 1 and that [[D-007 Home Assistant via MQTT]] leaves for later. End users still get Home Assistant over MQTT. The Charter does not change.

**Rules it follows:**
- The lab contains no signal maths that affects a pack. Filters, decimation, triggers, features, models and WAV/sidecar I/O all come from `rezonating_ml`, which keeps "one feature implementation, two languages" true.
- It counts every sample. Device drops, link drops and host gaps are shown separately and written with each recording.
- Recordings go to a data root on the shared drive, never into git. Only validated sidecars are copied to `data/`.

**Why:** Kaszti asked on 2026-10-12 for one environment for testing, live data and everything else the project needs while the parts are on their way. Today there is no viewer, recorder or labelling tool, and the walk-pass protocol requires start and end marks to be made live. Kaszti chose a local web app (over a native desktop app or notebooks), USB and Wi-Fi from day one, all four feature areas in v1, Svelte for the UI, and any team PC as the target.

**Rejected alternatives:**
- Native Qt/pyqtgraph app: harder to make clean and to share.
- Notebooks and scripts: too weak for live data and guided recording.
- React: more boilerplate for the same result.
- A plain-JS UI with no build step: gets messy beyond a few pages.

**Affects:** `tools/lab/` (new, Tier 2), `rezonating_ml` (needs an `io` module and a chunked pipeline API), `docs/protocols/walk-pass-v1.yaml` (machine-readable protocol), `.gitignore`, [[D-018 Node link protocol v0]], [[D-019 Sidecar v1]]. Phases: the `Lab 0`–`Lab 7` work notes in `20 Work`, starting with [[Lab 0 Decisions and link spec]]. Accept in Obsidian if this is right.
