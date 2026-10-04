#!/usr/bin/env python3
"""Start the ESP-IDF Tools MCP server for this repo's firmware/ (used by .mcp.json).

Needs ESP-IDF v6.0+ installed with the EIM "mcp" feature. Claude Code sets CLAUDE_PROJECT_DIR in
the server's environment; this wrapper turns that into the absolute firmware path the server
needs and passes stdin/stdout straight through. Without ESP-IDF it exits with a clear message,
and /mcp shows the server as failed: nothing else breaks.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
firmware = root / "firmware"
env = dict(os.environ, IDF_MCP_WORKSPACE_FOLDER=str(firmware))

if os.environ.get("IDF_PATH") and shutil.which("idf.py"):
    cmd = [shutil.which("idf.py"), "-C", str(firmware), "mcp-server"]
elif shutil.which("eim"):
    cmd = [shutil.which("eim"), "run", f'idf.py -C "{firmware}" mcp-server']
else:
    sys.stderr.write("ESP-IDF not found: install ESP-IDF v6.0+ with EIM (enable the 'mcp' feature).\n")
    sys.exit(1)

sys.exit(subprocess.call(cmd, env=env, cwd=str(firmware)))
