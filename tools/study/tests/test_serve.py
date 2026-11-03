"""Tests for the study site server: progress notes, request guards, prompt building, static files."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve  # noqa: E402

STATE = {
    "v": 1,
    "lessons": {"e02": {"status": "done", "quiz": {"best": 75}}},
    "cards": {},
    "log": [{"d": "2026-11-03", "t": "x"}],
}


@pytest.fixture()
def study_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(serve, "STUDY_DIR", tmp_path / "Study")
    return tmp_path / "Study"


def test_progress_roundtrip(study_dir):
    summary = {
        "lessons_done": 1, "lessons_total": 28, "quiz_avg": 75, "cards_known": 2, "cards_due": 3,
        "cases_solved": 1, "parts_seen": 4, "last_lesson": "E02 Ohm's law",
        "rows": [{"track": "electronics", "title": "E02 Ohm", "status": "done", "quiz": 75, "date": "2026-11-03"}],
        "recent": ["2026-11-03: finished E02"],
    }  # fmt: skip
    p = serve.write_progress("viktor", STATE, summary, today="2026-11-03")
    assert p == study_dir / "Viktor.md"
    text = p.read_text(encoding="utf-8")
    assert text.startswith("---\ntype: study\nperson: viktor\nupdated: 2026-11-03\n")
    assert "quiz_avg: 75\n" in text and 'last_lesson: "E02 Ohm\'s law"' in text
    assert "| electronics | E02 Ohm | done | 75 % | 2026-11-03 |" in text
    assert serve.read_state("viktor") == STATE


def test_missing_note_gives_empty_state(study_dir):
    assert serve.read_state("kaszti") == {}


def test_note_text_is_sanitised(study_dir):
    summary = {"last_lesson": "a\nb|c <% evil", "quiz_avg": 250, "lessons_done": True, "rows": [{"title": "x|y\nz"}]}
    text = serve.render_note("kaszti", {}, summary, "2026-11-03")
    assert "<%" not in text
    assert "quiz_avg: 100\n" in text  # clamped
    assert "lessons_done: \n" in text  # booleans are not numbers
    assert "| x y z |" in text


def test_build_question_modes():
    q = serve.build_question({"mode": "define", "question": "LSB", "lang": "hu", "person": "kaszti"})
    assert "Answer in Hungarian." in q and "Kaszti" in q and '"LSB"' in q
    q = serve.build_question(
        {"mode": "ask", "question": "why?", "excerpt": "page", "history": [{"q": "a", "a": "b"}] * 9}
    )
    assert "Answer in English." in q and "<page>" in q and q.count("Earlier question") == 4


def test_claude_command_models(monkeypatch):
    monkeypatch.setattr(serve.shutil, "which", lambda _: "claude")
    cmd = serve.claude_command("ask")
    assert cmd[cmd.index("--model") + 1] == "sonnet" and cmd[cmd.index("--effort") + 1] == "medium"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--effort" not in serve.claude_command("define")


@pytest.fixture()
def server(study_dir):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _req(url, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h), timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_http_progress_and_guards(server):
    code, _ = _req(f"{server}/api/progress/kaszti", "PUT", {"state": STATE, "summary": {}})
    assert code == 200
    code, body = _req(f"{server}/api/progress/kaszti")
    assert code == 200 and json.loads(body)["state"] == STATE
    assert _req(f"{server}/api/progress/bob")[0] == 404
    assert _req(f"{server}/api/progress/kaszti", "PUT", {"nope": 1})[0] == 400
    # another web page must not reach the API
    assert _req(f"{server}/api/progress/kaszti", headers={"Origin": "http://evil.example"})[0] == 403
    assert _req(f"{server}/api/ask", "POST", {"question": "x"}, {"Origin": "http://evil.example"})[0] == 403
    assert _req(f"{server}/api/ask", "POST", {"question": "  "})[0] == 400


def test_static_files(server):
    code, body = _req(f"{server}/")
    assert code == 200 and b"Rezonating Study" in body
    assert _req(f"{server}/content/curriculum.json")[0] == 200
    assert _req(f"{server}/../serve.py")[0] == 404
    assert _req(f"{server}/nope.js")[0] == 404


def test_content_references_resolve():
    import check_content

    assert check_content.check() == []
