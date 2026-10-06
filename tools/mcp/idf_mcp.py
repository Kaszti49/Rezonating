#!/usr/bin/env python3
"""Start the ESP-IDF Tools MCP server for this repo's firmware/ (used by .mcp.json).

Needs ESP-IDF v6.0+ installed with the EIM "mcp" feature. Claude Code sets CLAUDE_PROJECT_DIR in
the server's environment; this wrapper turns that into the absolute firmware path the server
needs, passes stdin through and filters the server's stdout to JSON-RPC lines (everything else
goes to stderr). Without ESP-IDF it exits with a clear message,
and /mcp shows the server as failed: nothing else breaks.

stdout carries only JSON-RPC, so this wrapper never prints to it and never uses `eim run` on
Windows (it prints an activation banner on stdout and takes ~12 s, past Claude Code's 30 s
connect timeout). Instead it reads the EIM install record, asks the activation script for the
environment once (`-e`, about 2 s) and starts `<IDF venv python> idf.py mcp-server` directly.
Order of attempts:
  1. IDF_PATH set and idf.py on PATH (an already activated shell, CI, Linux/macOS)
  2. EIM-installed ESP-IDF found through eim_idf.json (Windows, direct start)
  3. `eim run` (other platforms; slow, so it is the last resort; the filter sends its banner to stderr)
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Variables set by MSYS/Git Bash. idf.py refuses to run when it sees them ("MSys/Mingw is no
# longer supported"), so the child process must not inherit them.
MSYS_VARS = (
    "MSYSTEM",
    "MSYSTEM_CARCH",
    "MSYSTEM_CHOST",
    "MSYSTEM_PREFIX",
    "MINGW_CHOST",
    "MINGW_PREFIX",
    "MINGW_PACKAGE_PREFIX",
    "MSYS",
    "MSYS2_PATH_TYPE",
)


def eprint(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def clean_env(extra):
    env = {k: v for k, v in os.environ.items() if k not in MSYS_VARS}
    env.update(extra)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def find_eim_record():
    """Return the selected IDF entry of eim_idf.json, or None."""
    candidates = []
    tools = os.environ.get("IDF_TOOLS_PATH")
    if tools:
        candidates.append(Path(tools) / "eim_idf.json")
    candidates += [
        Path("C:/Espressif/tools/eim_idf.json"),
        Path.home() / ".espressif" / "tools" / "eim_idf.json",
        Path.home() / ".espressif" / "eim_idf.json",
    ]
    for p in candidates:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entries = data.get("idfInstalled") or []
        selected = data.get("idfSelectedId")
        for e in entries:
            if e.get("id") == selected and e.get("status", "finished") == "finished":
                return e
        for e in entries:
            if e.get("status") == "finished":
                return e
    return None


def eim_env(record):
    """Environment of an EIM install, from its PowerShell activation script (`-e` prints it)."""
    script = record.get("activationScript")
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not script or not ps or not Path(script).is_file():
        return None
    try:
        out = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script, "-e"],
            capture_output=True,
            text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pairs = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if not pairs.get("IDF_PATH") or not pairs.get("PATH"):
        return None
    pairs.pop("SYSTEM_PATH", None)  # a snapshot of the PATH at install time: use the live one
    pairs["PATH"] = pairs["PATH"] + os.pathsep + os.environ.get("PATH", "")
    return pairs


root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
firmware = root / "firmware"
workspace = {"IDF_MCP_WORKSPACE_FOLDER": str(firmware)}

if os.environ.get("IDF_PATH") and shutil.which("idf.py"):
    cmd = [shutil.which("idf.py"), "-C", str(firmware), "mcp-server"]
    env = clean_env(workspace)
else:
    cmd = env = None
    record = find_eim_record() if os.name == "nt" else None
    if record:
        tool_env = eim_env(record)
        py = record.get("python")
        idf_py = Path(tool_env["IDF_PATH"]) / "tools" / "idf.py" if tool_env else None
        if tool_env and py and Path(py).is_file() and idf_py.is_file():
            cmd = [py, str(idf_py), "-C", str(firmware), "mcp-server"]
            env = clean_env({**tool_env, **workspace})
    if cmd is None and shutil.which("eim"):
        cmd = [shutil.which("eim"), "run", f'idf.py -C "{firmware}" mcp-server']
        env = clean_env(workspace)
    if cmd is None:
        eprint("ESP-IDF not found: install ESP-IDF v6.0+ with EIM (enable the 'mcp' feature).")
        sys.exit(1)


def run_filtered(cmd, env, cwd):
    """Run the server; forward only JSON lines to stdout, everything else to stderr.

    idf.py itself prints "Executing action: mcp-server" and "MCP Server running on stdio..." to
    stdout before the server starts, which would corrupt the JSON-RPC stream. MCP stdio messages
    are single-line JSON objects (or batches), so any other line is a log line. stdin and stderr
    are inherited. Bytes are copied as they are, so line endings are not translated.
    """
    proc = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=subprocess.PIPE)
    out = sys.stdout.buffer
    try:
        for line in proc.stdout:
            if line.lstrip()[:1] in (b"{", b"["):
                out.write(line)
                out.flush()
            else:
                sys.stderr.buffer.write(line)
                sys.stderr.buffer.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()
    return proc.wait()


sys.exit(run_filtered(cmd, env, str(firmware)))
