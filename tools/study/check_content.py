"""Check the study site's content: every lesson, term, widget, case and part reference resolves.

python tools/study/check_content.py           # exit 1 on errors
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CONTENT = Path(__file__).resolve().parent / "web" / "content"
WIDGETS_JS = Path(__file__).resolve().parent / "web" / "js" / "widgets" / "index.js"
LAYERS = ["bench", "intuition", "engineer", "datasheet"]


def _bi(obj, where, errors, required=True):
    if obj is None:
        if required:
            errors.append(f"{where}: missing")
        return
    if not isinstance(obj, dict) or not str(obj.get("en", "")).strip() or not str(obj.get("hu", "")).strip():
        errors.append(f"{where}: needs non-empty en and hu")


def check() -> list[str]:
    errors: list[str] = []
    load = lambda name: json.loads((CONTENT / name).read_text(encoding="utf-8"))  # noqa: E731
    cur = load("curriculum.json")
    gloss = load("glossary.json")
    parts = {p["id"]: p for p in load("parts.json")["parts"]}
    cases = {c["id"]: c for c in load("cases.json")["cases"]}
    builds = load("builds.json")["builds"]
    widgets = set(re.findall(r"^\s+(\w+): \w+\.\w+,", WIDGETS_JS.read_text(encoding="utf-8"), re.M))
    terms = set(gloss) | set(parts)

    for tid, g in gloss.items():
        _bi(g.get("term"), f"glossary {tid}.term", errors)
        _bi(g.get("short"), f"glossary {tid}.short", errors)

    lesson_ids = [lesson["id"] for tr in cur["tracks"] for lesson in tr["lessons"]]
    for lid in lesson_ids:
        meta_p = CONTENT / "lessons" / f"{lid}.json"
        if not meta_p.exists():
            continue  # planned: outline only
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{lid}.json: {e}")
            continue
        if meta.get("id") != lid:
            errors.append(f"{lid}.json: id is {meta.get('id')!r}")
        _bi(meta.get("title"), f"{lid}.title", errors)
        for p in meta.get("parts", []):
            if p not in parts:
                errors.append(f"{lid}.json: unknown part {p!r}")
        for c in meta.get("cases", []):
            if c not in cases:
                errors.append(f"{lid}.json: unknown case {c!r}")
        for kind in ("predict", "quiz"):
            for i, q in enumerate(meta.get(kind, [])):
                _bi(q.get("q"), f"{lid}.{kind}[{i}].q", errors)
                opts = q.get("options", [])
                if not (2 <= len(opts) <= 6) or not (0 <= q.get("answer", -1) < len(opts)):
                    errors.append(f"{lid}.{kind}[{i}]: answer index out of range")
                for j, o in enumerate(opts):
                    _bi(o, f"{lid}.{kind}[{i}].options[{j}]", errors)
        for i, c in enumerate(meta.get("calc", [])):
            _bi(c.get("q"), f"{lid}.calc[{i}].q", errors)
            _bi(c.get("solution"), f"{lid}.calc[{i}].solution", errors)
            if not isinstance(c.get("answer"), (int, float)):
                errors.append(f"{lid}.calc[{i}]: answer must be a number")
        ids = [c.get("id") for c in meta.get("cards", [])]
        if len(set(ids)) != len(ids) or any(not str(x).startswith(f"{lid}-") for x in ids):
            errors.append(f"{lid}.cards: ids must be unique and start with '{lid}-'")
        for lang in ("en", "hu"):
            md_p = CONTENT / "lessons" / f"{lid}.{lang}.md"
            if not md_p.exists():
                errors.append(f"{lid}.{lang}.md: missing")
                continue
            md = md_p.read_text(encoding="utf-8")
            found = re.findall(r"^##\s*@(\w+)\s*$", md, re.M)
            if [x for x in found if x in LAYERS] != [x for x in LAYERS if x in found] or "bench" not in found:
                errors.append(f"{lid}.{lang}.md: sections {found} (need @bench then layers in order)")
            for kind, n in re.findall(r"\{\{(predict|calc):(\d+)\}\}", md):
                if int(n) >= len(meta.get(kind, [])):
                    errors.append(f"{lid}.{lang}.md: {{{{{kind}:{n}}}}} has no entry in the JSON")
            for w in re.findall(r"\{\{w:([\w-]+)", md):
                if w not in widgets:
                    errors.append(f"{lid}.{lang}.md: unknown widget {w!r}")
            for c in re.findall(r"\{\{case:([\w-]+)\}\}", md):
                if c not in cases:
                    errors.append(f"{lid}.{lang}.md: unknown case {c!r}")
            for p in re.findall(r"\{\{part:([\w-]+)", md):
                if p not in parts:
                    errors.append(f"{lid}.{lang}.md: unknown part {p!r}")
            for t in re.findall(r"\[\[([a-z0-9][\w-]*)(?:\|[^\]]+)?\]\]", md, re.I):
                if t.lower() not in terms:
                    errors.append(f"{lid}.{lang}.md: unknown term [[{t}]]")
    for c in cases.values():
        for k in c.get("lessons", []):
            if k not in lesson_ids:
                errors.append(f"case {c['id']}: unknown lesson {k!r}")
        if sum(1 for d in c["diagnoses"] if d.get("correct")) != 1:
            errors.append(f"case {c['id']}: needs exactly one correct diagnosis")
    for b in builds:
        inst = {i["id"] for i in b["instances"]}
        for w in b["wires"]:
            for end in (w["from"], w["to"]):
                if end[0] not in inst:
                    errors.append(f"build {b['id']} wire {w['id']}: unknown instance {end[0]!r}")
    return errors


def main() -> int:
    errors = check()
    for e in errors:
        print(e)
    print(f"{len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
