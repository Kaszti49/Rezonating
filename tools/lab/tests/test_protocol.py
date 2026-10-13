"""Machine-readable protocols (docs/protocols/*.yaml), the protocol runner's state machine, and the IPv6 refusal of
the phone-marker address. No node here: the runner is driven directly, with a fake clock."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from rec_helpers import REPO
from rezonating_lab.recorder import config as rconfig
from rezonating_lab.recorder import marker as mk
from rezonating_lab.recorder.protocol import ProtocolError, load_named, load_protocol, parse_protocol
from rezonating_lab.recorder.runner import ProtocolRunner, RunnerError

WALK = REPO / "docs" / "protocols" / "walk-pass-v1.yaml"


def walk_doc() -> dict:
    return yaml.safe_load(WALK.read_text(encoding="utf-8"))


def problems_of(doc: object, name: str = "walk-pass-v1") -> list[str]:
    with pytest.raises(ProtocolError) as exc:
        parse_protocol(doc, name)
    return exc.value.problems


# ------------------------------------------------------------------------------------------ loader


def test_walk_pass_v1_yaml_matches_the_written_protocol():
    p = load_protocol(WALK)
    assert p.name == "walk-pass-v1" and p.pack == "footstep-id" and p.doc == "walk-pass-v1.md"
    assert p.passes_per_person == 90
    plan = p.expand(["P1", "P2"])
    assert [s.key for s in plan[:2]] == ["silence", "P1/normal-shoes-on"]
    silence = plan[0]
    assert silence.kind == "timed" and silence.duration_s == 60.0 and silence.target == 1
    assert silence.tags() == {"label": "silence", "person": None, "pace": None, "shoes": None}
    rows = [(s.person, s.pace, s.shoes, s.target, s.label) for s in plan[1:]]
    per_person = [("normal", True, 50), ("normal", False, 20), ("slow", True, 10), ("fast", True, 10)]
    assert rows == [(p, pace, shoes, n, "walk") for p in ("P1", "P2") for pace, shoes, n in per_person]
    assert len(plan) == 1 + 4 * 2
    assert load_named(REPO, "walk-pass-v1") == p
    d = p.to_dict()
    assert d["passes_per_person"] == 90 and d["blocks"][1]["for_each_person"] is True
    assert (
        d["blocks"][1]["steps"][0]["fills"] == ["person", "pace", "shoes"] and d["blocks"][0]["steps"][0]["fills"] == []
    )


def test_per_person_protocol_needs_persons():
    with pytest.raises(ProtocolError, match="per person"):
        load_protocol(WALK).expand([])


def test_loader_reports_every_problem_with_its_place():
    doc = walk_doc()
    doc["format"] = 2
    doc["extra"] = 1
    silence = doc["steps"][0]
    silence["duration_s"] = 0
    silence["passes"] = 3
    block = doc["steps"][1]["for_each_person"]
    block[0]["passes"] = 0
    block[1]["fills"] = {"person": "P7", "pace": "jog", "shoes": "yes please", "floor": "wood"}
    block[2]["id"] = "normal-shoes-on"  # duplicate id
    block[3]["kind"] = "walk"
    block[3]["label"] = "Walk!"
    probs = problems_of(doc)
    expect = [
        "extra: unknown key",
        "format: must be 1",
        "steps[0].duration_s",
        "steps[0].passes: only for kind: passes",
        "steps[1].for_each_person[0].passes",
        "steps[1].for_each_person[1].fills.person: use $person, never a fixed pseudonym",
        "steps[1].for_each_person[1].fills.pace",
        "steps[1].for_each_person[1].fills.shoes: true or false",
        "steps[1].for_each_person[1].fills.floor: unknown field",
        "steps[1].for_each_person[2].id: 'normal-shoes-on' is used twice",
        "steps[1].for_each_person[3].kind",
        "steps[1].for_each_person[3].label",
    ]
    for e in expect:
        assert any(p.startswith(e) for p in probs), (e, probs)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d.update(protocol="other"), "does not match the file name"),
        (lambda d: d.update(steps=[]), "steps: a non-empty list"),
        (lambda d: d["steps"][0]["fills"].update(person="$person"), "$person only inside for_each_person"),
        (lambda d: d["steps"][1]["for_each_person"][0]["fills"].pop("person"), "must fill person"),
        (lambda d: d["steps"][1].update(note="x"), "for_each_person stands alone"),
        (lambda d: d["steps"][1]["for_each_person"].append({"for_each_person": []}), "cannot be nested"),
        (lambda d: d["steps"][1]["for_each_person"][0].update(duration_s=5), "only for kind: timed"),
        (lambda d: d["steps"].append("walk"), "a step must be a mapping"),
        (lambda d: d["steps"][0].update(passes=True, kind="passes", duration_s=None), "passes: a whole number"),
    ],
)
def test_loader_refuses_bad_steps(mutate, expected):
    doc = walk_doc()
    mutate(doc)
    assert any(expected in p for p in problems_of(doc)), problems_of(doc)


def test_loader_refuses_duplicate_keys_bad_yaml_and_missing_files(tmp_path: Path):
    text = WALK.read_text(encoding="utf-8").replace("format: 1\n", "format: 1\nformat: 1\n", 1)
    dup = tmp_path / "walk-pass-v1.yaml"
    dup.write_text(text, encoding="utf-8")
    with pytest.raises(ProtocolError, match="appears twice"):
        load_protocol(dup)
    bad = tmp_path / "bad.yaml"
    bad.write_text("steps: [unclosed\n", encoding="utf-8")
    with pytest.raises(ProtocolError, match="not valid YAML"):
        load_protocol(bad)
    with pytest.raises(ProtocolError, match="cannot read"):
        load_protocol(tmp_path / "missing.yaml")
    with pytest.raises(ProtocolError, match="letters, digits"):
        load_named(REPO, "../schemas/sidecar")
    with pytest.raises(ProtocolError, match="checkout"):
        load_named(None, "walk-pass-v1")
    assert problems_of([1, 2]) == ["the file must be a mapping with format, protocol and steps"]


def test_yaml_tags_cannot_run_code(tmp_path: Path):
    p = tmp_path / "evil.yaml"
    p.write_text("format: !!python/object/apply:os.system ['echo hi']\n", encoding="utf-8")
    with pytest.raises(ProtocolError, match="not valid YAML"):
        load_protocol(p)


def test_a_minimal_protocol_without_persons():
    doc = {
        "format": 1,
        "protocol": "quiet",
        "labels": ["silence"],
        "steps": [{"id": "quiet", "kind": "timed", "label": "silence", "duration_s": 5}],
    }
    p = parse_protocol(doc, "quiet")
    assert not p.per_person and p.passes_per_person == 0 and p.title == "quiet"
    assert [s.key for s in p.expand([])] == ["quiet"]
    assert p.labels == ("silence", "noise", "other", "bad")


def test_the_protocol_declares_a_fixed_label_list():
    """Decision B (2026-10-13): walk-pass-v1 offers silence, walk and the shared noise, other, bad."""
    p = load_protocol(WALK)
    assert p.labels == ("silence", "walk", "noise", "other", "bad")
    assert p.to_dict()["labels"] == list(p.labels)
    for change, msg in (
        (lambda d: d.pop("labels"), "labels: a non-empty list"),
        (lambda d: d.update(labels=["silence"]), "label 'walk' is not in labels"),
        (lambda d: d.update(labels=["silence", "walk", "walk"]), "listed twice"),
        (lambda d: d.update(labels=["silence", "walk", "Walk!"]), r"labels\[2\]"),
    ):
        doc = walk_doc()
        change(doc)
        with pytest.raises(ProtocolError, match=msg):
            parse_protocol(doc, "walk-pass-v1")


# ------------------------------------------------------------------------------------------ runner


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make_runner(persons=("P1", "P2"), scale: float = 1.0) -> tuple[ProtocolRunner, Clock]:
    clock = Clock()
    return ProtocolRunner(load_protocol(WALK), list(persons), now=clock, timed_scale=scale), clock


class Marks:
    """Stands in for the recorder's label book: ids count up."""

    def __init__(self, runner: ProtocolRunner) -> None:
        self.r = runner
        self.next_id = 1
        self.made: list[tuple[int, dict]] = []

    def start(self) -> int:
        tags = self.r.tags_for_start({})
        mid = self.next_id
        self.next_id += 1
        self.r.started(mid)
        self.made.append((mid, tags))
        return mid

    def end(self, by_timer: bool = False) -> bool:
        mid = self.r.open_mark
        assert mid is not None
        self.r.check_end(mid, by_timer)
        return self.r.ended(mid)

    def one(self) -> int:
        mid = self.start()
        self.end()
        return mid


def test_runner_silence_countdown_then_90_passes_per_person():
    r, clock = make_runner()
    m = Marks(r)
    assert r.state == "ready" and r.current == 0 and r.view()["overall"] == {"done": 0, "target": 180}
    m.start()
    assert r.state == "countdown" and r.view()["countdown"]["remaining_s"] == 60.0
    clock.t += 42.5
    assert r.view()["countdown"]["remaining_s"] == pytest.approx(17.5)
    with pytest.raises(RunnerError) as exc:
        m.end()  # Space cannot end the silence early
    assert exc.value.code == "countdown_running"
    with pytest.raises(RunnerError):
        r.next()
    assert r.countdown_due(1)
    clock.t += 17.5
    m.end(by_timer=True)
    assert r.steps[0].status == "done" and r.current == 1 and r.state == "ready"
    while not r.finished:
        m.one()
    walks = [t for _, t in m.made if t["label"] == "walk"]
    for p in ("P1", "P2"):
        mine = [t for t in walks if t["person"] == p]
        assert len(mine) == 90
        combos = {
            (pace, shoes): sum(1 for t in mine if (t["pace"], t["shoes"]) == (pace, shoes))
            for pace, shoes in [("normal", True), ("normal", False), ("slow", True), ("fast", True)]
        }
        assert combos == {("normal", True): 50, ("normal", False): 20, ("slow", True): 10, ("fast", True): 10}
    assert [t for _, t in m.made if t["label"] == "silence"] == [
        {"label": "silence", "person": None, "pace": None, "shoes": None}
    ]
    v = r.view()
    assert v["state"] == "finished" and v["current"] is None
    assert v["overall"] == {"done": 180, "target": 180} and v["per_person"]["P2"] == {"done": 90, "target": 90}
    assert all(s["status"] == "done" for s in v["steps"])
    with pytest.raises(RunnerError) as exc:
        r.tags_for_start({})
    assert exc.value.code == "runner_finished"
    assert r.summary()["finished"] is True


def test_runner_navigation_statuses_and_deletes():
    r, _ = make_runner(["P1"])
    m = Marks(r)
    r.skip()  # skip the silence
    assert r.steps[0].status == "skipped" and r.current == 1
    a = m.one()
    m.one()
    r.next()  # leave normal-shoes-on with 2 of 50
    assert r.steps[1].status == "incomplete" and r.current == 2 and r.steps[2].status == "active"
    r.back()
    assert r.current == 1 and r.steps[2].status == "pending" and r.steps[1].done == 2
    m.start()
    with pytest.raises(RunnerError) as exc:
        r.next()  # a pass is open
    assert exc.value.code == "mark_open"
    m.end()
    assert r.steps[1].done == 3
    assert r.deleted(a) and r.steps[1].done == 2
    r.goto(4)
    assert r.current == 4 and r.steps[1].status == "incomplete"
    for _ in range(10):
        m.one()
    assert r.finished and r.steps[4].status == "done"
    r.back()  # from finished to the last step
    assert r.current == 4 and r.state == "ready"
    with pytest.raises(RunnerError) as exc:
        r.goto(99)
    assert exc.value.http == 404
    r.goto(0)
    with pytest.raises(RunnerError) as exc:
        r.back()
    assert exc.value.code == "runner_first_step"


def test_runner_deleting_a_counted_pass_of_a_done_step_marks_it_incomplete():
    r, _ = make_runner(["P1"])
    m = Marks(r)
    r.goto(4)  # fast, 10 passes
    ids = [m.one() for _ in range(10)]
    assert r.steps[4].status == "done" and r.finished
    r.deleted(ids[3])
    assert r.steps[4].status == "incomplete" and r.steps[4].done == 9


def test_runner_tags_win_and_clashing_overrides_are_refused():
    r, _ = make_runner(["P1"])
    r.skip()
    assert r.tags_for_start({"person": "P1", "pace": "normal"}) == {
        "label": "walk",
        "person": "P1",
        "pace": "normal",
        "shoes": True,
    }
    with pytest.raises(RunnerError) as exc:
        r.tags_for_start({"pace": "fast"})
    assert exc.value.code == "runner_owns_label" and "pace" in exc.value.message


def test_runner_cancel_countdown_and_timed_scale():
    r, clock = make_runner(["P1"], scale=60.0)
    m = Marks(r)
    mid = m.start()
    assert r.view()["countdown"]["duration_s"] == 1.0 and r.view()["steps"][0]["duration_s"] == 1.0
    assert r.cancel_countdown() == mid and r.state == "ready" and r.steps[0].done == 0
    assert not r.countdown_due(mid)
    with pytest.raises(RunnerError) as exc:
        r.cancel_countdown()
    assert exc.value.code == "no_countdown"
    with pytest.raises(ValueError):
        ProtocolRunner(load_protocol(WALK), ["P1"], timed_scale=0)


def test_a_mark_from_before_the_runner_is_not_counted():
    r, _ = make_runner(["P1"])
    assert r.ended(77) is False and r.steps[0].done == 0


# ------------------------------------------------------------------------------------ IPv6 refusal


@pytest.mark.parametrize("addr", ["::", "::1", "[::1]", "fe80::1%eth0", "2001:db8::5"])
def test_ipv6_marker_bind_is_refused_in_the_config(tmp_path: Path, addr: str):
    env = {"RZ_CONFIG": str(tmp_path / "none.toml"), "RZ_REPO_ROOT": str(REPO), "RZ_MARKER_BIND": addr}
    with pytest.raises(rconfig.ConfigError) as exc:
        rconfig.load_config(env)
    assert exc.value.code == "bad_config" and "IPv6" in exc.value.message and "marker_bind" in exc.value.message
    cfg_file = tmp_path / "c.toml"
    cfg_file.write_text(f'marker_bind = "{addr}"\n', encoding="utf-8")
    with pytest.raises(rconfig.ConfigError, match="IPv6"):
        rconfig.load_config({"RZ_CONFIG": str(cfg_file), "RZ_REPO_ROOT": str(REPO)})
    with pytest.raises(rconfig.ConfigError, match="marker_host.*IPv6"):
        rconfig.load_config({"RZ_CONFIG": str(tmp_path / "none.toml"), "RZ_MARKER_HOST": addr})


def test_ipv4_marker_binds_still_load(tmp_path: Path):
    for addr in ("auto", "0.0.0.0", "192.168.1.23"):
        env = {"RZ_CONFIG": str(tmp_path / "none.toml"), "RZ_REPO_ROOT": str(REPO), "RZ_MARKER_BIND": addr}
        assert rconfig.load_config(env).marker_bind == addr
    assert not rconfig.is_ipv6("192.168.1.23") and not rconfig.is_ipv6("auto") and rconfig.is_ipv6("::ffff:1.2.3.4")


def test_ipv6_marker_host_in_the_form_gets_a_clear_error():
    for cfg_bind in ("auto", "0.0.0.0", "127.0.0.1"):
        with pytest.raises(mk.MarkerHostError, match="IPv6 addresses are not supported"):
            mk.choose_bind(cfg_bind, "::1")
    assert not mk.is_wildcard("::")  # no longer an accepted bind
