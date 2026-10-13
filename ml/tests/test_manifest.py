"""data/manifest.json: build, write, read, verify. WAVs are synthetic and live in tmp_path only (never in the repo)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from rezonating_ml import io, manifest

HERE = Path(__file__).resolve().parent
SCHEMA = io.find_schema(HERE)
EXAMPLES = SCHEMA.parent / "examples"
CREATED = "2026-10-13T08:00:00Z"
S1 = "2026-11-17_lab_bench_01"
S2 = "2026-11-18_home-a_kitchen_02"


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def codes(n: int, ch: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(-(2**23), 2**23, size=(n, ch), dtype=np.int32)


def adc_doc(session: str, n: int = 4032) -> dict:
    """v1 adc_raw sidecar at 2016 Hz (measured 2016.13), two labels by P2 and P10, P2 also in the notes."""
    doc = example("sidecar.walk-pass-v1.json")
    doc["session"] = session
    doc["notes"] = io.format_rzlab_notes({"frames": str(n), "rate_source": "drdy", "floor": "2", "persons": "P2,P10"})
    doc["labels"] = [
        {"t0": 0.5, "t1": 1.0, "i0": 1008, "i1": 2016, "src": "key", "label": "walk", "person": "P10"},
        {"t0": 1.0, "t1": 1.5, "i0": 2016, "i1": 3024, "src": "key", "label": "walk", "person": "P2"},
    ]
    return doc


def accel_doc(session: str, n: int = 3998) -> dict:
    doc = example("sidecar.accel-v1.json")
    doc["session"] = session
    doc["notes"] = io.format_rzlab_notes({"frames": str(n), "persons": "P1", "source": "sim"})
    return doc


def write_session(data_root: Path, sidecar_root: Path, session: str, *, wavs: bool = True, seed: int = 1) -> None:
    for suffix, doc, n_ch in (("adc", adc_doc(session), 2), ("accel", accel_doc(session), 3)):
        (sidecar_root / session).mkdir(parents=True, exist_ok=True)
        io.save_sidecar(sidecar_root / session / f"{session}.{suffix}.json", doc, SCHEMA)
        if wavs:
            (data_root / session).mkdir(parents=True, exist_ok=True)
            n = int(io.parse_rzlab_notes(doc["notes"])["frames"])
            io.write_wav(data_root / session / f"{session}.{suffix}.wav", codes(n, n_ch, seed), doc["sample_rate"])
            seed += 1


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    data_root, sidecar_root = tmp_path / "drive", tmp_path / "repo" / "data"
    data_root.mkdir()
    sidecar_root.mkdir(parents=True)
    write_session(data_root, sidecar_root, S1, seed=1)
    write_session(data_root, sidecar_root, S2, seed=10)
    return data_root, sidecar_root


def build(roots: tuple[Path, Path], **kw) -> dict:
    return manifest.build_manifest(roots[0], roots[1], schema_path=SCHEMA, created=CREATED, **kw)


def by_wav(m: dict) -> dict[str, dict]:
    return {e["wav"]: e for e in m["entries"]}


# ------------------------------------------------------------------------------------------------ build


def test_build_lists_every_recording_with_its_facts(roots: tuple[Path, Path]) -> None:
    m = build(roots)
    assert manifest.validate_manifest(m) == []
    assert (m["format"], m["version"], m["created"]) == ("rezonating-manifest", 1, CREATED)
    assert [e["wav"] for e in m["entries"]] == [
        f"{S1}/{S1}.accel.wav",
        f"{S1}/{S1}.adc.wav",
        f"{S2}/{S2}.accel.wav",
        f"{S2}/{S2}.adc.wav",
    ]
    adc = by_wav(m)[f"{S1}/{S1}.adc.wav"]
    wav_bytes = (roots[0] / S1 / f"{S1}.adc.wav").read_bytes()
    assert adc["sha256"] == hashlib.sha256(wav_bytes).hexdigest()
    assert adc["size_bytes"] == len(wav_bytes)
    assert adc["sidecar"] == f"data/{S1}/{S1}.adc.json"
    assert (adc["session"], adc["stream"], adc["channels"], adc["frames"]) == (S1, "adc_raw", 2, 4032)
    assert (adc["fs_header_hz"], adc["fs_measured_hz"]) == (2016, 2016.13)
    assert adc["duration_s"] == pytest.approx(4032 / 2016.13, abs=1e-6)  # true time uses the measured rate
    assert adc["people"] == ["P2", "P10"]  # labels + notes, unique, in number order
    assert (adc["label_count"], adc["protocol"], adc["floor"]) == (2, "walk-pass-v1", "2")
    assert adc["surface"] == ["laminate on concrete slab"]
    assert adc["loss"] == {"device": 0, "link": 0, "host": 0}
    assert (adc["simulated"], adc["incomplete"], adc["wav_present"], adc["valid"], adc["errors"]) == (
        False,
        False,
        True,
        True,
        [],
    )
    acc = by_wav(m)[f"{S1}/{S1}.accel.wav"]
    assert (acc["stream"], acc["channels"], acc["people"], acc["label_count"], acc["simulated"]) == (
        "accel",
        3,
        ["P1"],
        0,
        True,
    )
    assert acc["loss"] == {"device": 12, "link": 0, "host": 0}
    assert m["unmatched_wavs"] == []


def test_manifest_never_holds_an_absolute_path(roots: tuple[Path, Path], tmp_path: Path) -> None:
    m = build(roots)
    out = tmp_path / "manifest.json"
    manifest.write_manifest(out, m)
    text = out.read_text(encoding="utf-8")
    assert str(tmp_path) not in text and str(tmp_path).replace("\\", "/") not in text
    bad = copy.deepcopy(m)
    bad["entries"][0]["wav"] = str(roots[0] / S1 / f"{S1}.accel.wav")
    assert any("wav" in p for p in manifest.validate_manifest(bad))
    with pytest.raises(ValueError, match="invalid manifest"):
        manifest.write_manifest(tmp_path / "bad.json", bad)
    for p in ("C:/rec/x.wav", "C:\\rec\\x.wav", "../x.wav", f"{S1}/../x.wav", "\\\\server\\x.wav"):
        bad["entries"][0]["wav"] = p
        assert manifest.validate_manifest(bad), p


def test_missing_wav_is_reported_not_hashed(roots: tuple[Path, Path]) -> None:
    (roots[0] / S2 / f"{S2}.adc.wav").unlink()
    e = by_wav(build(roots))[f"{S2}/{S2}.adc.wav"]
    assert (e["wav_present"], e["sha256"], e["size_bytes"], e["valid"]) == (False, None, None, False)
    assert e["errors"] == ["wav: missing on the data root"]
    assert e["frames"] == 4032 and e["fs_header_hz"] == 2016  # from the sidecar when there is no WAV


def test_sidecar_and_wav_disagreeing_is_invalid(roots: tuple[Path, Path]) -> None:
    path = roots[1] / S1 / f"{S1}.adc.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["channels"] = doc["channels"][:1]
    path.write_text(json.dumps(doc), encoding="utf-8")
    e = by_wav(build(roots))[f"{S1}/{S1}.adc.wav"]
    assert e["valid"] is False and e["wav_present"] is True and e["sha256"]
    assert any("channels" in m for m in e["errors"])


def test_broken_sidecar_still_gets_an_entry(roots: tuple[Path, Path]) -> None:
    (roots[1] / S1 / f"{S1}.adc.json").write_text("{not json", encoding="utf-8")
    m = build(roots)
    assert manifest.validate_manifest(m) == []
    e = by_wav(m)[f"{S1}/{S1}.adc.wav"]
    assert e["valid"] is False and e["stream"] == "adc_raw"  # stream from the file name
    assert e["errors"][0].startswith("sidecar: cannot read")
    assert e["sha256"] and e["frames"] == 4032


def test_names_never_reach_the_manifest(roots: tuple[Path, Path], tmp_path: Path) -> None:
    path = roots[1] / S1 / f"{S1}.adc.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["labels"][0]["person"] = "Zsuzsanna"
    doc["notes"] = doc["notes"].replace("persons=P2,P10", "persons=P2,Gizella")
    path.write_text(json.dumps(doc), encoding="utf-8")
    m = build(roots)
    e = by_wav(m)[f"{S1}/{S1}.adc.wav"]
    assert e["people"] == ["P2"] and e["valid"] is False
    assert any("person" in msg and "not copied" in msg for msg in e["errors"])
    manifest.write_manifest(tmp_path / "m.json", m)
    text = (tmp_path / "m.json").read_text(encoding="utf-8")
    assert "Zsuzsanna" not in text and "Gizella" not in text


def test_schema_messages_do_not_echo_the_sidecar(roots: tuple[Path, Path]) -> None:
    # a v0 sidecar carrying v1 fields fails a "not" rule whose stock message repeats the whole document
    path = roots[1] / S1 / f"{S1}.adc.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["schema"] = 0
    doc["notes"] = "private free text that must stay in the sidecar"
    path.write_text(json.dumps(doc), encoding="utf-8")
    e = by_wav(build(roots))[f"{S1}/{S1}.adc.wav"]
    assert e["valid"] is False and e["errors"]
    assert not any("private free text" in msg for msg in e["errors"])


def test_v0_sidecar_without_stream_or_measured_rate(tmp_path: Path) -> None:
    data_root, sidecar_root = tmp_path / "drive", tmp_path / "data"
    doc = example("sidecar.walk-pass.json")
    doc["labels"] = [{"t0": 0.5, "t1": 1.0, "label": "walk", "person": "P3"}]
    s = doc["session"]
    (sidecar_root / s).mkdir(parents=True)
    (data_root / s).mkdir(parents=True)
    io.save_sidecar(sidecar_root / s / f"{s}.json", doc, SCHEMA)
    io.write_wav(data_root / s / f"{s}.wav", codes(2500, 1, 3), 1000)
    m = manifest.build_manifest(data_root, sidecar_root, schema_path=SCHEMA, created=CREATED)
    (e,) = m["entries"]
    assert (e["wav"], e["stream"], e["fs_measured_hz"], e["duration_s"], e["loss"]) == (
        f"{s}/{s}.wav",
        None,
        None,
        2.5,
        None,
    )
    assert e["valid"] is True and e["people"] == ["P3"]


def test_select_by_names_or_predicate(roots: tuple[Path, Path]) -> None:
    assert {e["session"] for e in build(roots, select=[S2])["entries"]} == {S2}
    assert {e["session"] for e in build(roots, select=lambda s: s.startswith("2026-11-17"))["entries"]} == {S1}
    with pytest.raises(ValueError, match="2026-12-01_x_y_01"):
        build(roots, select=[S1, "2026-12-01_x_y_01"])


def test_wavs_without_a_repo_sidecar_are_listed(roots: tuple[Path, Path]) -> None:
    s3 = "2026-11-19_lab_bench_03"
    (roots[0] / s3).mkdir()
    io.write_wav(roots[0] / s3 / f"{s3}.adc.wav", codes(10, 2, 5), 2000)
    (roots[0] / "not-a-session").mkdir()
    io.write_wav(roots[0] / "not-a-session" / "x.wav", codes(10, 1, 6), 2000)
    m = build(roots)
    assert m["unmatched_wavs"] == [f"{s3}/{s3}.adc.wav"]
    assert build(roots, select=[s3])["entries"] == []  # a session only on the drive may be selected


def test_missing_roots_are_refused(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        manifest.build_manifest(tmp_path / "nope", tmp_path, schema_path=SCHEMA)
    with pytest.raises(NotADirectoryError):
        manifest.build_manifest(tmp_path, tmp_path / "nope", schema_path=SCHEMA)


# ------------------------------------------------------------------------------------- write and read


def test_round_trip_is_exact_and_deterministic(roots: tuple[Path, Path], tmp_path: Path) -> None:
    m = build(roots)
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    manifest.write_manifest(a, m)
    assert manifest.read_manifest(a) == m
    shuffled = json.loads(json.dumps(m))
    shuffled["entries"].reverse()
    shuffled = dict(reversed(list(shuffled.items())))
    shuffled["entries"] = [dict(reversed(list(e.items()))) for e in shuffled["entries"]]
    manifest.write_manifest(b, shuffled)
    assert a.read_bytes() == b.read_bytes()  # same content, same bytes, whatever the dict order
    assert a.read_bytes().endswith(b"}\n") and b"\r\n" not in a.read_bytes()
    assert list(json.loads(a.read_text(encoding="utf-8"))) == list(manifest.TOP_KEYS)
    assert manifest.build_manifest(roots[0], roots[1], schema_path=SCHEMA, created=CREATED) == m  # rebuild = same
    assert list(tmp_path.glob("*.tmp")) == []


def test_read_refuses_an_invalid_manifest(roots: tuple[Path, Path], tmp_path: Path) -> None:
    m = build(roots)
    m["version"] = 2
    (tmp_path / "m.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        manifest.read_manifest(tmp_path / "m.json")
    m["version"] = 1
    m["entries"].append(copy.deepcopy(m["entries"][0]))
    assert any("twice" in p for p in manifest.validate_manifest(m))
    m["entries"].pop()
    m["entries"][0]["valid"] = True
    m["entries"][0]["sha256"] = None
    assert manifest.validate_manifest(m)


# ---------------------------------------------------------------------------------------------- verify


def test_verify_passes_on_untouched_files(roots: tuple[Path, Path]) -> None:
    report = manifest.verify_manifest(build(roots), roots[0])
    assert report.passed and report.checked == 4 and len(report.ok) == 4
    assert (report.missing, report.changed, report.not_hashed) == ([], [], [])


def test_verify_finds_a_changed_byte_and_a_missing_wav(roots: tuple[Path, Path]) -> None:
    m = build(roots)
    target = roots[0] / S1 / f"{S1}.adc.wav"
    raw = bytearray(target.read_bytes())
    raw[-1] ^= 0x01  # same size, one sample bit flipped
    target.write_bytes(bytes(raw))
    (roots[0] / S2 / f"{S2}.accel.wav").unlink()
    report = manifest.verify_manifest(m, roots[0])
    assert not report.passed
    assert report.missing == [f"{S2}/{S2}.accel.wav"]
    (changed,) = report.changed
    assert changed["wav"] == f"{S1}/{S1}.adc.wav"
    assert changed["expected_size"] == changed["found_size"]
    assert changed["expected_sha256"] == by_wav(m)[f"{S1}/{S1}.adc.wav"]["sha256"]
    assert changed["found_sha256"] == hashlib.sha256(bytes(raw)).hexdigest()
    assert sorted(report.ok) == [f"{S1}/{S1}.accel.wav", f"{S2}/{S2}.adc.wav"]


def test_verify_flags_entries_built_without_a_wav(roots: tuple[Path, Path]) -> None:
    (roots[0] / S2 / f"{S2}.adc.wav").rename(roots[0] / "parked.wav")
    m = build(roots)
    (roots[0] / "parked.wav").rename(roots[0] / S2 / f"{S2}.adc.wav")
    report = manifest.verify_manifest(m, roots[0])
    assert report.not_hashed == [f"{S2}/{S2}.adc.wav"] and not report.passed


# ------------------------------------------------------------------------------------------------- CLI


def test_cli_build_then_verify(roots: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    out = tmp_path / "m.json"
    args = ["--data-root", str(roots[0]), "--sidecars", str(roots[1]), "--schema", str(SCHEMA), "--out", str(out)]
    assert manifest.main(["build", *args]) == 0
    assert len(manifest.read_manifest(out)["entries"]) == 4
    assert "4 entries, 4 valid" in capsys.readouterr().out
    assert manifest.main(["verify", str(out), "--data-root", str(roots[0])]) == 0
    (roots[0] / S1 / f"{S1}.adc.wav").write_bytes(b"changed")
    assert manifest.main(["verify", str(out), "--data-root", str(roots[0])]) == 1
    assert "changed" in capsys.readouterr().out
    (roots[0] / S1 / f"{S1}.adc.wav").unlink()
    assert manifest.main(["build", *args, "--strict"]) == 1  # an invalid entry fails a strict build


# ------------------------------------------------------------------------- malformed sidecars (verifier F-261013-0fd6)


def edit_sidecar(roots: tuple[Path, Path], session: str, suffix: str, change) -> None:
    path = roots[1] / session / f"{session}.{suffix}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")  # json.dumps writes NaN as the bare token NaN


def test_malformed_sidecar_becomes_an_invalid_entry_not_a_crash(roots: tuple[Path, Path], tmp_path: Path) -> None:
    def break_it(doc: dict) -> None:
        doc["labels"].append("not a label")  # io.check_pair calls lab.get() on it
        doc["sample_rate_measured"] = float("nan")  # check_pair calls round(nan)
        doc["channels"] = 7  # not a list

    edit_sidecar(roots, S1, "adc", break_it)
    m = build(roots)
    e = by_wav(m)[f"{S1}/{S1}.adc.wav"]
    assert e["valid"] is False and e["errors"]
    assert e["fs_measured_hz"] is None and e["channels"] == 2  # channels from the WAV header
    assert e["duration_s"] == pytest.approx(4032 / 2016)  # NaN measured rate: falls back to the header rate
    assert any(msg.startswith("pair: the check stopped") for msg in e["errors"])
    manifest.write_manifest(tmp_path / "m.json", m)  # allow_nan=False: nothing non-finite got in
    assert by_wav(manifest.read_manifest(tmp_path / "m.json"))[e["wav"]] == e
    assert all(x["valid"] for x in m["entries"] if x is not e)  # the other recordings are unaffected


@pytest.mark.parametrize("rate", [float("inf"), -5.0, 0.0])
def test_non_finite_or_non_positive_measured_rate_is_dropped(roots: tuple[Path, Path], rate: float) -> None:
    edit_sidecar(roots, S1, "adc", lambda d: d.update(sample_rate_measured=rate))
    e = by_wav(build(roots))[f"{S1}/{S1}.adc.wav"]
    assert e["fs_measured_hz"] is None and e["valid"] is False


def test_errors_never_echo_sidecar_strings(roots: tuple[Path, Path], tmp_path: Path) -> None:
    secret = "Gizella Kovacs"

    def leak(doc: dict) -> None:
        doc["session"] = secret  # breaks the pattern and the file-name check of check_pair
        doc["notes"] = f"rzlab: frames={secret}\n{secret} walked twice"
        doc[secret] = 1  # an extra field named like a person
        doc["start_utc"] = secret
        doc["channels"][0]["units"] = secret  # enum

    edit_sidecar(roots, S1, "adc", leak)
    m = build(roots)
    e = by_wav(m)[f"{S1}/{S1}.adc.wav"]
    assert e["valid"] is False and len(e["errors"]) >= 4
    assert e["start_utc"] is None
    manifest.write_manifest(tmp_path / "m.json", m)
    text = (tmp_path / "m.json").read_text(encoding="utf-8")
    assert "Gizella" not in text and "Kovacs" not in text


def test_pair_lines_with_only_numbers_are_kept(roots: tuple[Path, Path]) -> None:
    edit_sidecar(roots, S1, "adc", lambda d: d.update(channels=d["channels"][:1]))
    e = by_wav(build(roots))[f"{S1}/{S1}.adc.wav"]
    assert "wav has 2 channels, the sidecar lists 1" in e["errors"]


def test_wav_paths_must_stay_in_their_session_folder(roots: tuple[Path, Path]) -> None:
    m = build(roots)
    e = m["entries"][0]
    for bad in ("raw/x.wav", "private/P1.wav", f"{S2}/{S2}.adc.wav", f"{S1}/x.wav", f"{S1}/sub/{S1}.adc.wav"):
        broken = copy.deepcopy(m)
        broken["entries"][0]["wav"] = bad
        assert manifest.validate_manifest(broken), bad
    broken = copy.deepcopy(m)
    broken["entries"][0]["sidecar"] = f"data/{S1}/{S1}.other.json"
    assert any("sidecar" in p for p in manifest.validate_manifest(broken))
    broken = copy.deepcopy(m)
    broken["unmatched_wavs"] = ["raw/x.wav"]
    assert manifest.validate_manifest(broken)
    assert e["sidecar"] == f"data/{e['session']}/{e['wav'].split('/')[1][:-4]}.json"


def test_only_sidecar_names_are_read(roots: tuple[Path, Path]) -> None:
    folder = roots[1] / S1
    (folder / "extra.json").write_text("{}", encoding="utf-8")
    (folder / f"{S1}.notes.json").write_text("{}", encoding="utf-8")
    (folder / f"{S2}.adc.json").write_text("{}", encoding="utf-8")
    assert [e["wav"] for e in build(roots)["entries"] if e["session"] == S1] == [
        f"{S1}/{S1}.accel.wav",
        f"{S1}/{S1}.adc.wav",
    ]


def test_hash_wavs_false_reads_no_wav_in_full(roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    hashed = build(roots)
    calls: list[Path] = []
    monkeypatch.setattr(manifest, "sha256_file", lambda p, *a, **k: calls.append(p))
    quick = build(roots, hash_wavs=False)
    assert calls == [], "no WAV is hashed"
    assert all(e["sha256"] is None and e["size_bytes"] is None for e in quick["entries"])
    strip = ("sha256", "size_bytes")
    same = [{k: v for k, v in e.items() if k not in strip} for e in hashed["entries"]]
    assert [{k: v for k, v in e.items() if k not in strip} for e in quick["entries"]] == same
    assert any(e["valid"] for e in quick["entries"]), "validity does not depend on hashing"
    assert manifest.validate_manifest(quick), "a present WAV without a hash is not a writable manifest"
