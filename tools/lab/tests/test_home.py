"""Home page results (server/home.py): only numbers that are logged in an experiment note, and never a made-up one."""

from __future__ import annotations

from pathlib import Path

from rezonating_lab.server.home import read_experiments, score_table

NOTE = """---
type: experiment
id: EXP-004
status: done
date: 2026-11-24
owner: claude
pack: "[[footstep-id]]"
people: 1
metric: known steps with the right side (%)
metric_value: 81.3
result: partial
---
# EXP-004 Rule C

**Takeaway:** in-sample.

| Set | Right | Same | Wrong |
| --- | --- | --- | --- |
| 08:53 left | 8 | 0 | 0 |
| 09:40 right | 3 | 4 | 1 |
| not scored | – | – | – |
| **Total** | **11** | **4** | **1** |

| Set | Right | Same | Wrong |
| --- | --- | --- | --- |
| a second table | 1 | 1 | 1 |
"""


def _vault(tmp_path: Path, **notes: str) -> Path:
    d = tmp_path / "50 Experiments"
    d.mkdir()
    for name, text in notes.items():
        (d / f"{name.replace('_', '-', 1).replace('_', ' ')}.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_reads_frontmatter_and_the_first_score_table(tmp_path: Path) -> None:
    got = read_experiments(_vault(tmp_path, EXP_004_Rule_C=NOTE))
    assert len(got) == 1
    e = got[0]
    assert (e["id"], e["title"], e["date"], e["pack"]) == ("EXP-004", "Rule C", "2026-11-24", "footstep-id")
    assert e["value"] == 81.3 and e["people"] == 1 and e["in_sample"] is True
    assert e["score"][:2] == [
        {"set": "08:53 left", "right": 8, "same": 0, "wrong": 0},
        {"set": "09:40 right", "right": 3, "same": 4, "wrong": 1},
    ]
    assert [r["set"] for r in e["score"]] == ["08:53 left", "09:40 right"]  # no dashes, no total


def test_a_running_experiment_has_no_value(tmp_path: Path) -> None:
    text = NOTE.replace("metric_value: 81.3", "metric_value:").replace("status: done", "status: running")
    e = read_experiments(_vault(tmp_path, EXP_004_Rule_C=text))[0]
    assert e["value"] is None and e["status"] == "running"


def test_broken_notes_and_other_files_are_left_out(tmp_path: Path) -> None:
    v = _vault(
        tmp_path, EXP_001_No_frontmatter="# nothing", EXP_002_Bad_yaml="---\ntype: [\n---\nx\n", EXP_004_Rule_C=NOTE
    )
    (v / "50 Experiments" / "Experiments.md").write_text("---\ntype: hub\n---\n", encoding="utf-8")
    assert [e["id"] for e in read_experiments(v)] == ["EXP-004"]


def test_no_vault_gives_no_results(tmp_path: Path) -> None:
    assert read_experiments(None) == []
    assert read_experiments(tmp_path) == []
    assert score_table("no table") == []


def test_home_results_endpoint(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    from rezonating_lab.recorder.config import LabConfig
    from rezonating_lab.server.app import create_app
    from rezonating_lab.server.device import DeviceManager

    cfg = LabConfig(
        config_path=tmp_path / "rzlab" / "config.toml",
        staging_dir=tmp_path / "staging",
        repo_root=_vault(tmp_path, EXP_004_Rule_C=NOTE),
    )
    app = create_app(8765, manager=DeviceManager(embedded_sim=False), static_dir=tmp_path / "no-static", lab_config=cfg)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        got = c.get("/api/home/results").json()["experiments"]
        assert [e["id"] for e in got] == ["EXP-004"]
