"""Rezonating study site: a local server for the lessons, the Claude tutor and progress notes.

    python tools/study/serve.py            # http://127.0.0.1:8790, opens the browser
    python tools/study/serve.py --port 8791 --no-browser

Standard library only. It does three things:

* serves ``tools/study/web/`` (the site itself),
* ``POST /api/ask`` runs the Claude Code CLI (``claude -p``) with the person's own subscription and
  streams the answer back as server-sent events (Haiku for quick definitions, Sonnet at medium effort
  for tutor questions, Opus for deep questions),
* ``GET/PUT /api/progress/<person>`` reads and writes ``10 Project/Study/<Person>.md``: properties the
  Obsidian Base reads, a lesson table, and the site's full state in a JSON block.

It binds to 127.0.0.1 only and refuses API calls whose Host or Origin isn't this server, so another web
page can't spend the subscription.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WEB = HERE / "web"
STUDY_DIR = ROOT / "10 Project" / "Study"
CONTEXT_FILE = HERE / "tutor_context.md"

PEOPLE = {"kaszti": "Kaszti", "viktor": "Viktor"}
MODES = {
    # mode: (model alias, effort or None)
    "define": ("haiku", None),
    "ask": ("sonnet", "medium"),
    "deep": ("opus", "high"),
}
MAX_BODY = 2 * 1024 * 1024
ASK_TIMEOUT_S = 240
MAX_PARALLEL_ASKS = 3
STATE_RE = re.compile(r"^## State\s*\n+```json\n(.*?)\n```", re.S | re.M)

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")

_ask_slots = threading.BoundedSemaphore(MAX_PARALLEL_ASKS)
_write_lock = threading.Lock()


# --------------------------------------------------------------------------------------------- progress


def note_path(person: str) -> Path:
    return STUDY_DIR / f"{PEOPLE[person]}.md"


def read_state(person: str) -> dict:
    """The JSON state block of a person's note, or {} when the note or the block is missing."""
    path = note_path(person)
    if not path.exists():
        return {}
    m = STATE_RE.search(path.read_text(encoding="utf-8"))
    if not m:
        return {}
    try:
        state = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
    return state if isinstance(state, dict) else {}


def _int(v, lo: int = 0, hi: int = 1_000_000) -> int | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return max(lo, min(hi, int(round(v))))


def _text(v, limit: int = 120) -> str:
    s = str(v or "")
    s = re.sub(r"[\r\n\t|`]+", " ", s).replace("<%", "< %").strip()
    return s[:limit]


def _yaml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # a JSON string is a valid YAML double-quoted scalar


def render_note(person: str, state: dict, summary: dict, today: str) -> str:
    """The whole note text. Properties follow the `study` type in 10 Project/Vault rules.md."""
    props = {
        "lessons_done": _int(summary.get("lessons_done")),
        "lessons_total": _int(summary.get("lessons_total")),
        "quiz_avg": _int(summary.get("quiz_avg"), 0, 100),
        "cards_known": _int(summary.get("cards_known")),
        "cards_due": _int(summary.get("cards_due")),
        "cases_solved": _int(summary.get("cases_solved")),
        "parts_seen": _int(summary.get("parts_seen")),
    }
    lines = ["---", "type: study", f"person: {person}", f"updated: {today}"]
    for k, v in props.items():
        lines.append(f"{k}: {'' if v is None else v}")
    lines.append(f"last_lesson: {_yaml_str(_text(summary.get('last_lesson')))}")
    lines += ["---", f"# {PEOPLE[person]}: study progress", ""]
    lines.append(
        "Written by the study site (`python tools/study/serve.py`). Edit nothing below by hand: the "
        "site rewrites this note every time you study."
    )
    lines += ["", "![[Study.base]]"]
    lines += ["", "## Lessons", "| Track | Lesson | Status | Quiz | Date |", "| --- | --- | --- | --- | --- |"]
    rows = summary.get("rows") if isinstance(summary.get("rows"), list) else []
    for r in rows[:200]:
        if not isinstance(r, dict):
            continue
        quiz = _int(r.get("quiz"), 0, 100)
        lines.append(
            f"| {_text(r.get('track'), 30)} | {_text(r.get('title'), 80)} | {_text(r.get('status'), 20)} | "
            f"{'' if quiz is None else f'{quiz} %'} | {_text(r.get('date'), 10)} |"
        )
    if not rows:
        lines.append("| | nothing yet | | | |")
    recent = summary.get("recent") if isinstance(summary.get("recent"), list) else []
    lines += ["", "## Recent"]
    lines += [f"- {_text(x, 200)}" for x in recent[:20]] or ["- nothing yet"]
    body = json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True)
    lines += ["", "## State", "```json", body, "```", ""]
    return "\n".join(lines)


def write_progress(person: str, state: dict, summary: dict, today: str | None = None) -> Path:
    today = today or dt.date.today().isoformat()
    text = render_note(person, state, summary, today)
    path = note_path(person)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".study-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    return path


# -------------------------------------------------------------------------------------------------- ask


def build_question(req: dict) -> str:
    lang = "Hungarian" if req.get("lang") == "hu" else "English"
    parts = [f"Answer in {lang}."]
    who = req.get("person")
    if who in PEOPLE:
        parts.append(f"The person asking is {PEOPLE[who]}.")
    lesson = req.get("lesson") or {}
    if isinstance(lesson, dict) and lesson.get("title"):
        parts.append(f"They are on the page: {_text(lesson.get('title'), 160)}.")
    excerpt = str(req.get("excerpt") or "")[:6000]
    if excerpt:
        parts.append("What the page shows them right now:\n<page>\n" + excerpt + "\n</page>")
    hist = req.get("history") if isinstance(req.get("history"), list) else []
    for h in hist[-4:]:
        if isinstance(h, dict) and h.get("q") and h.get("a"):
            parts.append(f"Earlier question: {str(h['q'])[:800]}\nYour earlier answer: {str(h['a'])[:2000]}")
    q = str(req.get("question") or "").strip()[:4000]
    if req.get("mode") == "define":
        parts.append(
            f'Explain the term "{q}" in more depth than a one-line glossary entry: 4–6 sentences, '
            "what it is, why it matters in our project, and one number from our hardware if there is one."
        )
    else:
        parts.append("Question: " + q)
    return "\n\n".join(parts)


def claude_command(mode: str) -> list[str]:
    exe = shutil.which("claude")
    if not exe:
        raise FileNotFoundError("the `claude` command isn't on PATH on this machine")
    model, effort = MODES[mode]
    cmd = [
        exe, "-p", "--model", model,
        "--tools", "",
        "--setting-sources", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--system-prompt-file", str(CONTEXT_FILE),
    ]  # fmt: skip
    if effort:
        cmd += ["--effort", effort]
    return cmd


def stream_answer(req: dict, send) -> None:
    """Run claude -p and call send(dict) for every text delta, then {"done": True} or {"error": ...}."""
    mode = req.get("mode") if req.get("mode") in MODES else "ask"
    try:
        cmd = claude_command(mode)
    except FileNotFoundError as e:
        send({"error": str(e)})
        return
    if not _ask_slots.acquire(timeout=30):
        send({"error": "too many questions at once; try again in a moment"})
        return
    proc = None
    timer = None
    try:
        with tempfile.TemporaryDirectory(prefix="rz-study-") as cwd:  # empty cwd: no project CLAUDE.md
            proc = subprocess.Popen(
                cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )  # fmt: skip
            timer = threading.Timer(ASK_TIMEOUT_S, proc.kill)
            timer.start()
            send({"model": MODES[mode][0]})
            proc.stdin.write(build_question(req))
            proc.stdin.close()
            got_text = False
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "stream_event":
                    d = (ev.get("event") or {}).get("delta") or {}
                    if d.get("type") == "text_delta" and d.get("text"):
                        got_text = True
                        send({"t": d["text"]})
                elif ev.get("type") == "result":
                    if ev.get("is_error"):
                        send({"error": _text(ev.get("result") or "Claude returned an error", 400)})
                        return
                    if not got_text and ev.get("result"):
                        send({"t": ev["result"]})
            proc.wait(timeout=10)
            if proc.returncode not in (0, None):
                err = (proc.stderr.read() or "").strip().splitlines()
                send({"error": _text(err[-1] if err else f"claude exited with {proc.returncode}", 400)})
                return
            send({"done": True})
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        pass  # the browser went away
    finally:
        if timer:
            timer.cancel()
        if proc and proc.poll() is None:
            proc.kill()
        _ask_slots.release()


# ---------------------------------------------------------------------------------------------- server


class Handler(BaseHTTPRequestHandler):
    server_version = "RezonatingStudy/1"

    def log_message(self, fmt, *args):  # quieter: only API calls and errors
        if self.path.startswith("/api/") or (args and str(args[1])[:1] in "45"):
            sys.stderr.write("[study] " + (fmt % args) + "\n")

    # --- helpers
    def _local_request(self) -> bool:
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "") not in allowed:
            return False
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc in allowed

    def _json(self, code: int, obj) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict | None:
        if "application/json" not in self.headers.get("Content-Type", ""):
            return None
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return None
        try:
            obj = json.loads(self.rfile.read(n).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return obj if isinstance(obj, dict) else None

    def _person(self) -> str | None:
        p = self.path.split("?")[0].rstrip("/").rsplit("/", 1)[-1].lower()
        return p if p in PEOPLE else None

    # --- routes
    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            if not self._local_request():
                return self._json(403, {"error": "forbidden"})
            if path == "/api/health":
                return self._json(200, {"ok": True, "claude": bool(shutil.which("claude")), "people": PEOPLE})
            if path.startswith("/api/progress/"):
                person = self._person()
                if not person:
                    return self._json(404, {"error": "unknown person"})
                return self._json(200, {"person": person, "state": read_state(person)})
            return self._json(404, {"error": "not found"})
        self._static(path)

    def do_PUT(self):
        path = urlparse(self.path).path
        if not self._local_request():
            return self._json(403, {"error": "forbidden"})
        if not path.startswith("/api/progress/"):
            return self._json(404, {"error": "not found"})
        person = self._person()
        body = self._body()
        if not person or body is None or not isinstance(body.get("state"), dict):
            return self._json(400, {"error": "expected {state, summary} for kaszti or viktor"})
        summary = body.get("summary") if isinstance(body.get("summary"), dict) else {}
        p = write_progress(person, body["state"], summary)
        return self._json(200, {"ok": True, "note": f"10 Project/Study/{p.name}"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._local_request():
            return self._json(403, {"error": "forbidden"})
        if path != "/api/ask":
            return self._json(404, {"error": "not found"})
        req = self._body()
        if req is None or not str(req.get("question") or "").strip():
            return self._json(400, {"error": "expected JSON with a question"})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        def send(obj):
            self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()

        stream_answer(req, send)
        self.close_connection = True

    def _static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        target = (WEB / rel).resolve()
        if not target.is_relative_to(WEB) or not target.is_file():
            target = WEB / "index.html" if "." not in rel.rsplit("/", 1)[-1] else None
        if target is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Rezonating study site on {url}  (Ctrl+C to stop)")
    if not shutil.which("claude"):
        print("note: `claude` isn't on PATH here, so the tutor won't answer on this machine")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
