"""``rzlab serve`` option checks, ``rzlab build-ui`` and the soak harness."""

import subprocess
import sys

import pytest
from rezonating_lab import buildui, cli, soak


def test_serve_refuses_a_non_loopback_bind(capsys):
    for host in ("0.0.0.0", "::", "192.168.1.20"):
        assert cli.main(["serve", "--host", host]) == 2
        assert "loopback" in capsys.readouterr().err


def test_serve_rejects_a_bad_connect_value(capsys):
    assert cli.main(["serve", "--connect", "carrier-pigeon"]) == 2
    assert "--connect" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["serve", "--connect", "tcp:host", "--key", "xyz"])


def test_serve_parser_defaults():
    args = cli.build_parser().parse_args(["serve"])
    assert (args.host, args.port, args.connect, args.no_embedded_sim) == ("127.0.0.1", 8765, None, False)


# ------------------------------------------------------------------------------------------- build-ui


def test_build_ui_without_web_folder(tmp_path, capsys):
    assert buildui.build_ui(web_dir=tmp_path / "web", static_dir=tmp_path / "static") == 1
    assert "does not exist" in capsys.readouterr().err


def test_build_ui_without_npm(tmp_path, capsys, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "package.json").write_text("{}")
    monkeypatch.setattr(buildui, "find_npm", lambda: None)
    assert buildui.build_ui(web_dir=web, static_dir=tmp_path / "static") == 1
    assert "npm was not found" in capsys.readouterr().err


def test_build_ui_runs_ci_then_build_in_the_web_folder(tmp_path, monkeypatch):
    web, static = tmp_path / "web", tmp_path / "static"
    web.mkdir()
    (web / "package.json").write_text("{}")
    calls = []

    def fake_run(args, cwd=None, check=False):
        calls.append((list(args), cwd))
        if args[1:] == ["run", "build"]:
            static.mkdir()
            (static / "index.html").write_text("<html></html>")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(buildui.subprocess, "run", fake_run)
    assert buildui.build_ui(web_dir=web, static_dir=static, npm="NPM") == 0
    assert calls == [(["NPM", "ci"], web), (["NPM", "run", "build"], web)]


def test_build_ui_stops_at_the_first_failure_and_checks_the_output(tmp_path, monkeypatch, capsys):
    web, static = tmp_path / "web", tmp_path / "static"
    web.mkdir()
    (web / "package.json").write_text("{}")
    seen = []

    def failing(args, cwd=None, check=False):
        seen.append(args[1:])
        return subprocess.CompletedProcess(args, 7 if args[1] == "ci" else 0)

    monkeypatch.setattr(buildui.subprocess, "run", failing)
    assert buildui.build_ui(web_dir=web, static_dir=static, npm="NPM") == 7
    assert seen == [["ci"]] and "failed with exit code 7" in capsys.readouterr().err

    seen.clear()
    monkeypatch.setattr(
        buildui.subprocess, "run", lambda args, cwd=None, check=False: subprocess.CompletedProcess(args, 0)
    )
    assert buildui.build_ui(web_dir=web, static_dir=static, npm="NPM") == 1  # built, but no index.html where expected
    assert "outDir" in capsys.readouterr().err


def test_find_npm_prefers_npm_cmd_on_windows(monkeypatch):
    monkeypatch.setattr(buildui.sys, "platform", "win32")
    monkeypatch.setattr(buildui.shutil, "which", lambda name: {"npm.cmd": "C:/node/npm.cmd"}.get(name))
    assert buildui.find_npm() == "C:/node/npm.cmd"
    monkeypatch.setattr(buildui.sys, "platform", "linux")
    monkeypatch.setattr(buildui.shutil, "which", lambda name: {"npm": "/usr/bin/npm"}.get(name))
    assert buildui.find_npm() == "/usr/bin/npm"
    monkeypatch.setattr(buildui.shutil, "which", lambda name: None)
    assert buildui.find_npm() is None


def test_build_ui_command_is_wired():
    assert cli.build_parser().parse_args(["build-ui"]).command == "build-ui"


# ---------------------------------------------------------------------------------------------- soak


def series(values, step=5.0):
    return [{"t": i * step, "srv_rss_mb": v} for i, v in enumerate(values)]


def test_rss_growth_flat_noisy_and_leaking():
    flat = series([90 + (i % 3) * 0.2 for i in range(60)])
    assert soak.rss_growth(flat, 300.0)["ok"]
    leak = series([90 + i * 0.5 for i in range(60)])  # 6 MB per minute
    g = soak.rss_growth(leak, 300.0)
    assert not g["ok"] and g["growth_mb"] > 10 and g["slope_mb_per_min"] == pytest.approx(6.0, rel=0.05)
    warmup = series([40 + min(i, 10) * 5 for i in range(60)])  # ramps in the first quarter, then flat
    assert soak.rss_growth(warmup, 300.0)["ok"]


def test_soak_end_to_end_smoke():
    pytest.importorskip("psutil")
    rc = soak.run_soak(minutes=0.25, speed=3.0, sample_period_s=2.0, json_path=None)
    assert rc == 0


def test_soak_report_fails_on_a_host_gap(capsys):
    final = {
        "streams": [
            {
                "id": 0,
                "name": "adc_raw",
                "loss": {"host": 3, "device": 0, "link": 0, "final": True, "received": 9, "window": 12},
            }
        ],
        "link": {"bad_frames": 0, "lost_frames": 0},
    }
    tally = soak.StreamTally(frames=200, bytes=1000, samples=1, epochs={1})
    samples = [
        {
            "t": float(i),
            "srv_cpu": 5.0,
            "srv_rss_mb": 90.0,
            "sim_cpu": 5.0,
            "sim_rss_mb": 35.0,
            "host_gaps": {"adc_raw": 3},
            "ws_fps": {},
            "ws_kBps": 1.0,
        }
        for i in range(10)
    ]
    result = {
        "samples": samples,
        "tallies": {0: tally},
        "counters": {"bad_frames": 0, "events": {}, "ws_stalls": 0},
        "latency": [],
        "elapsed": 10.0,
    }
    rc = soak._report(0.2, 3.0, result, {"sim": True, "server": True}, {"stopped": 1}, final, None)
    out = capsys.readouterr().out
    assert rc == 1 and "host gap 3" in out and "FAIL" in out


def test_python_can_run_the_module_entry_point():
    r = subprocess.run(
        [sys.executable, "-m", "rezonating_lab.cli", "--version"], capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0 and "rzlab" in r.stdout
