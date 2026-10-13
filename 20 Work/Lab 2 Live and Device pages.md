---
type: work
status: done
owner: claude
priority: p2
area: data
due: 2026-10-27
pack:
created: 2026-10-12
done: 2026-10-13
---
# Lab 2 Live and Device pages

**Goal:** Server, WebSocket and the first two pages of the browser UI.

## Done when
- [x] live scope, PSD and spectrogram from the simulator
- [x] device page shows health and log
- [x] works over TCP and serial (`socket://`)
- [x] 10-min soak with the simulator streaming at 3× real time: zero host gaps, bounded CPU and memory

## Notes
- Built on [[Lab 1 Link codec and simulator]]; UI stack and scope in [[D-017 Rezonating Lab bench tool]].
- Transport and health fields: [[D-018 Node link protocol v0]].
- Phase 1 leftovers (verifier PASS, low findings, 2026-10-12): add a test for the lost clean-up STOP ACK (`session.py` `force=True`). Remove or gate `SessionMonitor.begin_window` so it can't bypass the START gate. Fix the stale "proposed" docstring in `receiver.py` and the "10 lost" comment in `test_receiver.py`. Check that the sim keeps `running = 1` during the STOP drain (PROTOCOL.md §5 now says so).

## Log
- 2026-10-12 created
- 2026-10-13 built on 2026-10-12 (uncommitted, never verified then). Verifier FLAG (no 10-min soak, CPU not checked, port 5173 open in production, 4 lows) → all fixed in the Lab 3 retry; 10-min soak at 3×: host gap 0, CPU median 5.9 %, RSS flat (verifier confirmed). Not yet done: nobody has looked at the pages in a browser (screenshots), so status stays `todo`
- 2026-10-13 done: Kaszti and Viktor looked at the site in the browser ("looks clean"). All done-when items met (soak at 3x clean, foreign Origin refused, pytest/ruff/npm check pass, phase 1 leftovers fixed)
