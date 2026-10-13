"""Machine-readable recording protocols: ``docs/protocols/<name>.yaml``.

The file is a list of steps the Record page's runner walks through (format in the header of
``docs/protocols/walk-pass-v1.yaml``):

* ``kind: timed``: one label that lasts ``duration_s`` (the silence at the start of a session);
* ``kind: passes``: ``passes`` labels, one per pass, each started and ended by Space or the phone marker;
* ``for_each_person``: a block of steps repeated for every person of the session, in the form's order.

``fills`` names the label fields a step sets on every label it makes (``person``, ``pace``, ``shoes``). ``person``
is always ``$person`` (the session's pseudonym), never a fixed pseudonym: a protocol is the same for every session.

``labels`` (required) is the protocol's fixed list of label texts; every step's ``label`` must be one of them. The
shared list :data:`SHARED_LABELS` (``noise``, ``other``, ``bad``) is added to every protocol. Live marks, the runner,
the Review page and the label form accept only :attr:`Protocol.labels` (decision of 2026-10-13).

:func:`load_protocol` checks everything and raises :class:`ProtocolError` with every problem it found (with its
place in the file), so one run shows all mistakes. :meth:`Protocol.expand` turns the protocol and the session's
persons into the concrete step list the runner uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .forms import LABEL_RE, PSEUDONYM_RE

FORMAT = 1
PROTOCOL_DIR = Path("docs") / "protocols"
PERSON_VAR = "$person"
FILL_KEYS = ("person", "pace", "shoes")
PACES = ("slow", "normal", "fast")
KINDS = ("timed", "passes")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
STEP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
TOP_KEYS = {"format", "protocol", "title", "pack", "doc", "labels", "steps"}
SHARED_LABELS = ("noise", "other", "bad")  # every protocol offers these too
MAX_LABEL_LIST = 40
STEP_KEYS = {"id", "kind", "label", "passes", "duration_s", "fills", "instructions"}
MAX_PASSES = 1000
MAX_DURATION_S = 3600.0
MAX_TEXT = 300


class ProtocolError(ValueError):
    """The protocol file cannot be used. ``problems`` lists every mistake, each with its place in the file."""

    def __init__(self, name: str, problems: list[str]) -> None:
        super().__init__(f"protocol {name}: " + "; ".join(problems))
        self.name = name
        self.problems = problems


class _UniqueKeyLoader(yaml.SafeLoader):
    """``yaml.safe_load`` keeps the last of two equal keys without a word; a protocol file must not do that."""


def _mapping_no_duplicates(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(None, None, f"the key {key!r} appears twice", key_node.start_mark)
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_no_duplicates)


@dataclass(frozen=True)
class StepDef:
    """One step as written in the file."""

    id: str
    kind: str  # "timed" | "passes"
    label: str
    passes: int  # 1 for a timed step
    duration_s: float | None  # timed steps only
    pace: str | None
    shoes: bool | None
    fills_person: bool
    instructions: str
    per_person: bool

    def fills(self) -> list[str]:
        out = ["person"] if self.fills_person else []
        if self.pace is not None:
            out.append("pace")
        if self.shoes is not None:
            out.append("shoes")
        return out


@dataclass(frozen=True)
class PlanStep:
    """One concrete step of a session: a :class:`StepDef` with the person filled in."""

    index: int
    key: str  # "silence", "P1/normal-shoes-on": unique in the plan
    id: str
    kind: str
    label: str
    person: str | None
    pace: str | None
    shoes: bool | None
    target: int  # labels this step makes: passes, or 1 for a timed step
    duration_s: float | None
    instructions: str

    def tags(self) -> dict[str, Any]:
        """What every label of this step carries."""
        return {"label": self.label, "person": self.person, "pace": self.pace, "shoes": self.shoes}


@dataclass(frozen=True)
class Protocol:
    name: str
    title: str
    pack: str | None
    doc: str | None
    blocks: tuple[tuple[bool, tuple[StepDef, ...]], ...]  # (per_person, steps), in file order
    path: Path | None = field(default=None, compare=False)
    labels: tuple[str, ...] = SHARED_LABELS  # the protocol's own list, then the shared one

    @property
    def per_person(self) -> bool:
        return any(pp for pp, _ in self.blocks)

    @property
    def passes_per_person(self) -> int:
        """Pass labels each person walks (timed steps are not passes)."""
        return sum(s.passes for pp, steps in self.blocks if pp for s in steps if s.kind == "passes")

    def expand(self, persons: list[str]) -> list[PlanStep]:
        """The concrete step list for a session with these persons (form order)."""
        if self.per_person and not persons:
            raise ProtocolError(self.name, ["this protocol runs per person: add at least one pseudonym (P1, P2 ...)"])
        out: list[PlanStep] = []
        for per_person, steps in self.blocks:
            for person in persons if per_person else [None]:
                for s in steps:
                    out.append(
                        PlanStep(
                            index=len(out),
                            key=f"{person}/{s.id}" if person else s.id,
                            id=s.id,
                            kind=s.kind,
                            label=s.label,
                            person=person if s.fills_person else None,
                            pace=s.pace,
                            shoes=s.shoes,
                            target=s.passes,
                            duration_s=s.duration_s,
                            instructions=s.instructions,
                        )
                    )
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.name,
            "title": self.title,
            "pack": self.pack,
            "doc": self.doc,
            "passes_per_person": self.passes_per_person,
            "labels": list(self.labels),
            "blocks": [
                {
                    "for_each_person": pp,
                    "steps": [
                        {
                            "id": s.id,
                            "kind": s.kind,
                            "label": s.label,
                            "passes": s.passes,
                            "duration_s": s.duration_s,
                            "fills": s.fills(),
                            "pace": s.pace,
                            "shoes": s.shoes,
                            "instructions": s.instructions,
                        }
                        for s in steps
                    ],
                }
                for pp, steps in self.blocks
            ],
        }


# ------------------------------------------------------------------------------------------- loading


def protocol_dir(repo_root: Path | None) -> Path | None:
    return None if repo_root is None else repo_root / PROTOCOL_DIR


def load_named(repo_root: Path | None, name: str) -> Protocol:
    """Load ``docs/protocols/<name>.yaml`` of the checkout."""
    if not NAME_RE.match(name):
        raise ProtocolError(name, ["protocol names use letters, digits, dot, dash and underscore"])
    folder = protocol_dir(repo_root)
    if folder is None:
        raise ProtocolError(name, ["the repository checkout was not found (set RZ_REPO_ROOT)"])
    return load_protocol(folder / f"{name}.yaml")


def load_protocol(path: Path) -> Protocol:
    """Read and check one protocol file. Raises :class:`ProtocolError` with every problem found."""
    name = path.stem
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProtocolError(name, [f"cannot read {path.name}: {exc.strerror or exc}"]) from exc
    try:
        doc = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - a SafeLoader subclass
    except yaml.YAMLError as exc:
        raise ProtocolError(name, [f"not valid YAML: {exc}"]) from exc
    return parse_protocol(doc, name, path)


def parse_protocol(doc: Any, name: str, path: Path | None = None) -> Protocol:
    """Check a parsed protocol document (``name`` is the file's stem, which the ``protocol`` key must match)."""
    problems: list[str] = []
    if not isinstance(doc, dict):
        raise ProtocolError(name, ["the file must be a mapping with format, protocol and steps"])
    for k in sorted(set(doc) - TOP_KEYS, key=str):
        problems.append(f"{k}: unknown key (allowed: {', '.join(sorted(TOP_KEYS))})")
    if doc.get("format") != FORMAT:
        problems.append(f"format: must be {FORMAT}")
    proto = doc.get("protocol")
    if not isinstance(proto, str) or not NAME_RE.match(proto):
        problems.append("protocol: a name of letters, digits, dot, dash and underscore is required")
    elif proto != name:
        problems.append(f"protocol: {proto!r} does not match the file name {name!r}")
    title = _text(doc.get("title"), "title", problems, required=False) or name
    pack = _text(doc.get("pack"), "pack", problems, required=False)
    ref = _text(doc.get("doc"), "doc", problems, required=False)
    declared = _label_list(doc.get("labels"), problems)
    blocks: list[tuple[bool, tuple[StepDef, ...]]] = []
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        problems.append("steps: a non-empty list is required")
        steps = []
    top: list[StepDef] = []
    seen_ids: set[str] = set()
    for i, item in enumerate(steps):
        where = f"steps[{i}]"
        if isinstance(item, dict) and "for_each_person" in item:
            if set(item) != {"for_each_person"}:
                problems.append(f"{where}: for_each_person stands alone (no other keys next to it)")
            inner = item["for_each_person"]
            if not isinstance(inner, list) or not inner:
                problems.append(f"{where}.for_each_person: a non-empty list of steps is required")
                continue
            if top:
                blocks.append((False, tuple(top)))
                top = []
            block: list[StepDef] = []
            for j, s in enumerate(inner):
                st = _step(s, f"{where}.for_each_person[{j}]", True, seen_ids, problems)
                if st is not None:
                    block.append(st)
            blocks.append((True, tuple(block)))
        else:
            st = _step(item, where, False, seen_ids, problems)
            if st is not None:
                top.append(st)
    if top:
        blocks.append((False, tuple(top)))
    if declared is not None:
        for _pp, block_steps in blocks:
            for st in block_steps:
                if st.label not in declared and st.label not in SHARED_LABELS:
                    problems.append(f"step {st.id}: label {st.label!r} is not in labels ({', '.join(declared)})")
    if problems:
        raise ProtocolError(name, problems)
    labels = tuple(dict.fromkeys([*(declared or []), *SHARED_LABELS]))
    return Protocol(name=name, title=title, pack=pack, doc=ref, blocks=tuple(blocks), path=path, labels=labels)


def _label_list(v: Any, problems: list[str]) -> list[str] | None:
    if not isinstance(v, list) or not v:
        problems.append("labels: a non-empty list of the protocol's label texts is required (e.g. [silence, walk])")
        return None
    if len(v) > MAX_LABEL_LIST:
        problems.append(f"labels: at most {MAX_LABEL_LIST}")
    out: list[str] = []
    for i, lab in enumerate(v):
        if not isinstance(lab, str) or not LABEL_RE.match(lab):
            problems.append(f"labels[{i}]: 1-40 characters, lower-case letters, digits, space, dot, dash, underscore")
        elif lab in out:
            problems.append(f"labels[{i}]: {lab!r} is listed twice")
        else:
            out.append(lab)
    return out


def check_listed(label: str, allowed: tuple[str, ...] | list[str], protocol: str | None) -> str:
    """``label`` when it is one of ``allowed``; else ``ValueError`` naming the list (WEB_API answers 422)."""
    if label not in allowed:
        raise ValueError(f"label {label!r} is not one of protocol {protocol or '?'}'s labels: {', '.join(allowed)}")
    return label


def _text(v: Any, where: str, problems: list[str], required: bool = True) -> str | None:
    if v is None:
        if required:
            problems.append(f"{where}: required")
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > MAX_TEXT or any(c in v for c in "\r\n"):
        problems.append(f"{where}: one line of text, at most {MAX_TEXT} characters")
        return None
    return v.strip()


def _step(s: Any, where: str, per_person: bool, seen_ids: set[str], problems: list[str]) -> StepDef | None:
    if not isinstance(s, dict):
        problems.append(f"{where}: a step must be a mapping (id, kind, label, ...)")
        return None
    n0 = len(problems)
    if "for_each_person" in s:
        problems.append(f"{where}: for_each_person cannot be nested")
        return None
    for k in sorted(set(s) - STEP_KEYS, key=str):
        problems.append(f"{where}.{k}: unknown key (allowed: {', '.join(sorted(STEP_KEYS))})")
    sid = s.get("id")
    if not isinstance(sid, str) or not STEP_ID_RE.match(sid):
        problems.append(f"{where}.id: 1-40 characters, lower-case letters, digits and dashes")
        sid = None
    elif sid in seen_ids:
        problems.append(f"{where}.id: {sid!r} is used twice")
    else:
        seen_ids.add(sid)
    kind = s.get("kind")
    if kind not in KINDS:
        problems.append(f"{where}.kind: one of {', '.join(KINDS)}")
    label = s.get("label")
    if not isinstance(label, str) or not LABEL_RE.match(label):
        problems.append(f"{where}.label: 1-40 characters, lower-case letters, digits, space, dot, dash, underscore")
    passes: int = 1
    duration: float | None = None
    raw_passes, raw_duration = s.get("passes"), s.get("duration_s")
    if kind == "passes":
        if isinstance(raw_passes, bool) or not isinstance(raw_passes, int) or not 1 <= raw_passes <= MAX_PASSES:
            problems.append(f"{where}.passes: a whole number from 1 to {MAX_PASSES}")
        else:
            passes = raw_passes
        if raw_duration is not None:
            problems.append(f"{where}.duration_s: only for kind: timed")
    elif kind == "timed":
        if (
            isinstance(raw_duration, bool)
            or not isinstance(raw_duration, (int, float))
            or not 0 < raw_duration <= MAX_DURATION_S
        ):
            problems.append(f"{where}.duration_s: seconds, more than 0 and at most {MAX_DURATION_S:g}")
        else:
            duration = float(raw_duration)
        if raw_passes is not None:
            problems.append(f"{where}.passes: only for kind: passes (a timed step makes one label)")
    fills = s.get("fills", {})
    pace: str | None = None
    shoes: bool | None = None
    fills_person = False
    if fills is None:
        fills = {}
    if not isinstance(fills, dict):
        problems.append(f"{where}.fills: a mapping of person, pace, shoes")
        fills = {}
    for k in sorted(set(fills) - set(FILL_KEYS), key=str):
        problems.append(f"{where}.fills.{k}: unknown field (allowed: {', '.join(FILL_KEYS)})")
    if "person" in fills:
        p = fills["person"]
        if p != PERSON_VAR:
            if isinstance(p, str) and PSEUDONYM_RE.match(p):
                problems.append(f"{where}.fills.person: use {PERSON_VAR}, never a fixed pseudonym")
            else:
                problems.append(f"{where}.fills.person: must be {PERSON_VAR}")
        elif not per_person:
            problems.append(f"{where}.fills.person: {PERSON_VAR} only inside for_each_person")
        else:
            fills_person = True
    if per_person and "person" not in fills:
        problems.append(f"{where}.fills.person: a step inside for_each_person must fill person: {PERSON_VAR}")
    if "pace" in fills:
        if fills["pace"] not in PACES:
            problems.append(f"{where}.fills.pace: one of {', '.join(PACES)}")
        else:
            pace = fills["pace"]
    if "shoes" in fills:
        if not isinstance(fills["shoes"], bool):
            problems.append(f"{where}.fills.shoes: true or false")
        else:
            shoes = fills["shoes"]
    instructions = s.get("instructions", "")
    if instructions is None:
        instructions = ""
    if not isinstance(instructions, str) or len(instructions) > MAX_TEXT:
        problems.append(f"{where}.instructions: text, at most {MAX_TEXT} characters")
        instructions = ""
    if len(problems) != n0:
        return None
    assert isinstance(sid, str) and isinstance(kind, str) and isinstance(label, str)
    return StepDef(
        id=sid,
        kind=kind,
        label=label,
        passes=passes,
        duration_s=duration,
        pace=pace,
        shoes=shoes,
        fills_person=fills_person,
        instructions=instructions.strip(),
        per_person=per_person,
    )
