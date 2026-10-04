#!/usr/bin/env python3
"""Minimal Ollama client for Rezonating's local helpers (standard library only).

  python tools/local/ollama_client.py --check          # exit 0 if Ollama runs and the model is pulled
  python tools/local/ollama_client.py "your prompt"    # one answer to stdout

Local models only do cheap first drafts (summaries, triage suggestions). Their output is always
marked as a draft and checked by a person or by Claude; it never edits notes on its own.
Everything fails open: without Ollama the helpers fall back to plain, model-free output.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

CONFIG = Path(__file__).with_name("config.json")


def config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _post(path: str, payload: dict, timeout: float) -> dict:
    cfg = config()
    req = urllib.request.Request(
        cfg.get("host", "http://localhost:11434").rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def status() -> tuple[bool, str]:
    cfg = config()
    host = cfg.get("host", "http://localhost:11434").rstrip("/")
    want = cfg.get("model", "")
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=2) as r:
            names = [m.get("name", "") for m in json.loads(r.read().decode("utf-8")).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return False, f"Ollama is not answering at {host} (start the Ollama app)"
    if not any(n == want or n.split(":")[0] == want for n in names):
        return False, f"Ollama runs, but model {want!r} isn't pulled: ollama pull {want}"
    return True, f"Ollama OK at {host}, model {want}"


def chat(prompt: str, system: str = "", json_mode: bool = False, model: str = "") -> str | None:
    """One completion, or None when no local model is available."""
    ok, _ = status()
    if not ok:
        return None
    cfg = config()
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    payload = {
        "model": model or cfg.get("model"),
        "messages": msgs,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_ctx": int(cfg.get("num_ctx", 16384))},
    }
    if json_mode:
        payload["format"] = "json"
    timeout = float(cfg.get("timeout_s", 180))
    try:
        data = _post("/api/chat", payload, timeout)
    except urllib.error.HTTPError as e:
        if e.code != 400:
            return None
        payload.pop("think", None)  # models without a thinking switch reject the field
        try:
            data = _post("/api/chat", payload, timeout)
        except (urllib.error.URLError, OSError, ValueError):
            return None
    except (urllib.error.URLError, OSError, ValueError):
        return None
    text = (data.get("message") or {}).get("content", "")
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def model_name() -> str:
    return config().get("model", "local model")


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        ok, msg = status()
        print(msg)
        sys.exit(0 if ok else 1)
    if len(sys.argv) > 1:
        out = chat(" ".join(sys.argv[1:]))
        print(out if out is not None else status()[1])
        sys.exit(0 if out is not None else 1)
    print(__doc__)
