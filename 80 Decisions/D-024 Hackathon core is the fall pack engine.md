---
type: decision
id: D-024
status: accepted
date: 2026-11-15
decided_by:
  - kaszti
  - viktor
tier: 1
supersedes:
---
# D-024 Hackathon core is the fall pack engine

**Decision:** The hackathon detection core (`firmware/hackathon-rezon/rezon/src/core/`, portable C++, no Arduino includes) becomes the `fall` pack's engine on the node.
- It is ported into the ESP-IDF firmware as a component (`firmware/components/engines`, fall engine) behind the normal acquire → dsp → trigger path; the Arduino sketch stays in `firmware/hackathon-rezon/` as a reference and is not developed further.
- Fall v0 keeps the hackathon's **linear fall score** (weights · features + bias, hard gates, walker tracks, got-up rule) instead of a TFLite model. This is an exception to [[D-006 Own Python training to TFLite Micro]] for `fall` only; a TFLite model can replace it later if data shows it is better.
- The feature code gets its Python twin in `rezonating_ml` with test vectors generated from `tools/replay`, so "one feature implementation, two languages" holds. The weight fit moves to Python then; the C++ `fit` tool stays as the reference until the outputs match.
- `packs/fall/pack.json` drops `uses_packs: footstep-id` (the core tracks walkers itself) and names the new engine; that is a pack-schema check with `tools/validate.py`.
- Events still go to Home Assistant over MQTT ([[D-007 Home Assistant via MQTT]]). The hackathon's phone call (SIM868), voice prompt (speaker), "I'm OK" button and BLE link are **not** part of the Year 1 node; they are parked under Later in the [[Roadmap]] until someone proposes them.

**Why:** It is the only pack logic that has worked on real hardware, and it was written to be portable. Porting the core keeps the pack architecture ([[D-002 One node with swappable heads and packs]], [[D-005 Firmware in ESP-IDF C and C++]]) and avoids rebuilding a working detector from scratch.

**Rejected alternatives:** Move the node firmware to Arduino (breaks D-005 and the IDF driver work). Retrain fall from scratch as a TFLite classifier first (no dataset that big; the linear score is explainable and already tuned). Ship the calling/speaker features in Year 1 (new hardware, new budget, not in the Charter).

**Affects:** `firmware/components/` (new engine, Tier 1 paths `features` and `packs` if touched), `ml/` (feature twin, test vectors), `packs/fall/pack.json`, [[fall]], [[Master plan]] engines table. Flip `status` to `accepted` and fill `decided_by` in Obsidian.
