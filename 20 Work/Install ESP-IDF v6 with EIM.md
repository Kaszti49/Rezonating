---
type: work
status: done
owner: viktor
priority: p1
area: firmware
due: 2026-10-06
pack:
created: 2026-10-03
done: 2026-11-02
---
# Install ESP-IDF v6 with EIM

**Goal:** Build the firmware locally and let the agents build it too.

## Done when
- [x] ESP-IDF v6.0+ installed with the ESP-IDF Installation Manager, `mcp` feature on
- [x] `eim run "idf.py -C firmware build"` succeeds in the repo
- [ ] `/mcp` in Claude Code shows the esp-idf server connected

## Notes
Machines: the company PC first, Viktor's own PC if he uses it.

## Log
- 2026-10-03 created by Claude with the agent system (due date is a proposal)
- 2026-11-15 Claude: done (logged late). v6.0 is on pc-10 and EP-LAPTOP (`C:\esp\v6.0`) and v6.1-beta1 on desktop-o8pjtu7; the firmware was built and flashed on 2026-11-02. Open: the esp-idf MCP server doesn't connect in Claude Code (the third box), and the gate skips idf-build when IDF is reachable only through the EIM profile (F-261101-b2c0).
