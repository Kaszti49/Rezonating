---
type: work
status: todo
owner: claude
priority: p2
area: data
due: 2026-10-27
pack:
created: 2026-10-12
done:
---
# Lab 2 Live and Device pages

**Goal:** Server, WebSocket and the first two pages of the browser UI.

## Done when
- [ ] live scope, PSD and spectrogram from the simulator
- [ ] device page shows health and log
- [ ] works over TCP and serial (`socket://`)
- [ ] 10-min soak with the simulator streaming at 3× real time: zero host gaps, bounded CPU and memory

## Notes
- Built on [[Lab 1 Link codec and simulator]]; UI stack and scope in [[D-017 Rezonating Lab bench tool]].
- Transport and health fields: [[D-018 Node link protocol v0]].
- Phase 1 leftovers (verifier PASS, low findings, 2026-10-12): add a test for the lost clean-up STOP ACK (`session.py` `force=True`). Remove or gate `SessionMonitor.begin_window` so it can't bypass the START gate. Fix the stale "proposed" docstring in `receiver.py` and the "10 lost" comment in `test_receiver.py`. Check that the sim keeps `running = 1` during the STOP drain (PROTOCOL.md §5 now says so).

## Log
- 2026-10-12 created
