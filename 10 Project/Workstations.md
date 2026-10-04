---
type: project
---
# Workstations

Where we work and what each machine has. The SessionStart hook finds this machine's row by its
name (Windows: `echo %COMPUTERNAME%`), so keep the first column exact.

| Machine | Who | Where | Role | ESP-IDF v6 | Ollama | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| desktop-db0e1qv | Kaszti | home | vault manager; only machine with local models | not yet | to set up | used rarely for project work, and that's an off-day |
| (company PC, name on Monday) | Kaszti, Viktor | company | main machine on Monday and Tuesday | Monday | no | set up 2026-10-05 |
| (Viktor's PC, if used) | Viktor | home | optional | ? | no | add a row when it's used |

## Setting up a machine
1. Git for Windows, Python 3.12 (tick "Add python.exe to PATH"), Node.js LTS, Claude Code.
2. `git clone https://github.com/Kaszti49/Rezonating.git C:\Work\Projects\Enterpartner\Rezonating`, then
   `git submodule update --init` and `git config core.hooksPath .githooks`.
3. `pip install -r tools/requirements.txt ruff`.
4. Firmware machines: ESP-IDF v6.0+ with the ESP-IDF Installation Manager (EIM), with the `mcp` feature.
5. Run `claude` in the repo folder, trust the folder, approve the two MCP servers, then `/doctor`.
6. Obsidian: open the folder as a vault; turn on Templater → "Trigger Templater on new file creation".
7. Add the machine's row above.
