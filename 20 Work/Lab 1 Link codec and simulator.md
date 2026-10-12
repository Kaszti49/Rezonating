---
type: work
status: doing
owner: claude
priority: p1
area: data
due: 2026-10-20
pack:
created: 2026-10-12
done:
---
# Lab 1 Link codec and simulator

**Goal:** Python codec, golden vectors and a simulator node so the lab runs without hardware.

## Done when
- [x] codec round-trips every frame type
- [x] golden vectors in `tools/lab/tests/vectors/link-v0.json` (56 cases)
- [x] `rzlab sim` + `rzlab tail` show the measured rate and keep host gaps separate from device drops
- [ ] C header `link.h` matches the vectors (host build)

## Notes
- Protocol: [[D-018 Node link protocol v0]], spec in `tools/lab/PROTOCOL.md`.
- Part of [[D-017 Rezonating Lab bench tool]]. The C side is [[Firmware link component]].
- Try it: `pip install -e "tools/lab[dev]"`, then `rzlab sim` in one terminal and `rzlab tail` in another. Add `--corrupt-rate 0.05` or `--link-drop-rate 0.01` to see the loss counters work.
- Python side done 2026-10-12 by ml-dev: 280 tests, verifier PASS on the second round (the first round flagged a lost final STATUS and the USB-close behaviour; both fixed). Small leftovers are listed in [[Lab 2 Live and Device pages]].
- Placeholders until `rezonating_ml` has the real FIR: `adc_dec` in the simulator takes raw sample 2k+1.

## Log
- 2026-10-12 created
- 2026-10-12 Claude: Python codec, vectors, accounting, simulator and `rzlab tail` done; C header open
