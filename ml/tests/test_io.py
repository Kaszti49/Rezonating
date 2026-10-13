"""WAV and sidecar round trips for rezonating_ml.io. WAV files live in tmp_path only (never in the repo)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from rezonating_ml import io

HERE = Path(__file__).resolve().parent
SCHEMA = io.find_schema(HERE)
EXAMPLES = SCHEMA.parent / "examples"


def codes(n: int, ch: int, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).integers(-(2**23), 2**23, size=(n, ch), dtype=np.int32)


# ------------------------------------------------------------------------------------------------ WAV


@pytest.mark.parametrize("n_ch", [1, 2, 3])
def test_wav_round_trip_is_exact(tmp_path: Path, n_ch: int) -> None:
    x = codes(5000, n_ch)
    io.write_wav(tmp_path / "a.wav", x, 2016)
    y, fs = io.read_wav(tmp_path / "a.wav")
    assert fs == 2016
    assert y.dtype == np.int32 and y.shape == (5000, n_ch)
    assert np.array_equal(x, y)


def test_wav_int32_extremes_are_not_scaled(tmp_path: Path) -> None:
    lim = np.iinfo(np.int32)
    x = np.array([[lim.min, lim.max], [0, -1], [1, lim.min + 1], [lim.max - 1, 12345]], dtype=np.int32)
    io.write_wav(tmp_path / "e.wav", x, 1000)
    y, _ = io.read_wav(tmp_path / "e.wav")
    assert np.array_equal(x, y)


def test_wav_24_bit_codes_keep_their_values(tmp_path: Path) -> None:
    x = np.array([[-(2**23)], [2**23 - 1], [-1], [1]], dtype=np.int32)  # ADC full scale, sign-extended
    io.write_wav(tmp_path / "c.wav", x, 2000)
    y, _ = io.read_wav(tmp_path / "c.wav")
    assert y.ravel().tolist() == [-8388608, 8388607, -1, 1]


def test_wav_empty_and_single_frame(tmp_path: Path) -> None:
    io.write_wav(tmp_path / "z.wav", np.zeros((0, 2), dtype=np.int32), 2000)
    info = io.wav_info(tmp_path / "z.wav")
    assert (info.frames, info.channels, info.fs_hz, info.subtype) == (0, 2, 2000, "PCM_32")
    y, fs = io.read_wav(tmp_path / "z.wav")
    assert y.shape == (0, 2) and fs == 2000
    io.write_wav(tmp_path / "o.wav", np.array([[7, -7, 9]], dtype=np.int32), 1)
    y, fs = io.read_wav(tmp_path / "o.wav")
    assert y.tolist() == [[7, -7, 9]] and fs == 1


def test_wav_writer_streams_blocks_and_zeros(tmp_path: Path) -> None:
    a, b = codes(300, 2, 1), codes(200, 2, 2)
    with io.WavWriter(tmp_path / "s.wav", 2, 2000) as w:
        w.write(a)
        w.flush()
        assert io.wav_info(tmp_path / "s.wav").frames == 300  # header updated by flush: a crash keeps the data
        w.write_zeros(100_000)
        w.write(b)
        assert w.frames_written == 300 + 100_000 + 200
    y, _ = io.read_wav(tmp_path / "s.wav")
    assert y.shape == (100_500, 2)
    assert np.array_equal(y[:300], a) and not y[300:100_300].any() and np.array_equal(y[100_300:], b)


@pytest.mark.parametrize("n_ch", [1, 2, 3])
def test_set_wav_sample_rate_changes_only_the_header(tmp_path: Path, n_ch: int) -> None:
    x = codes(3000, n_ch)
    io.write_wav(tmp_path / "r.wav", x, 2000)
    io.set_wav_sample_rate(tmp_path / "r.wav", 2016)
    y, fs = io.read_wav(tmp_path / "r.wav")
    assert fs == 2016 and np.array_equal(x, y)
    assert io.wav_info(tmp_path / "r.wav").frames == 3000
    (tmp_path / "junk.wav").write_bytes(b"x" * 100)
    with pytest.raises(ValueError):
        io.set_wav_sample_rate(tmp_path / "junk.wav", 1000)


def test_iter_wav_blocks_matches_read(tmp_path: Path) -> None:
    x = codes(10_001, 3)
    io.write_wav(tmp_path / "b.wav", x, 2000)
    blocks = list(io.iter_wav_blocks(tmp_path / "b.wav", 4096))
    assert [len(b) for b in blocks] == [4096, 4096, 1809]
    assert np.array_equal(np.concatenate(blocks), x)


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((4, 2), dtype=np.float32),
        np.zeros((4, 2), dtype=np.int16),
        np.zeros(4, dtype=np.int32),
        np.zeros((4, 0), dtype=np.int32),
        [[1, 2]],
    ],
)
def test_write_refuses_wrong_shape_or_dtype(tmp_path: Path, bad) -> None:
    with pytest.raises(ValueError):
        io.write_wav(tmp_path / "x.wav", bad, 1000)


def test_write_refuses_bad_rate_and_writer_checks_channels(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        io.write_wav(tmp_path / "x.wav", codes(4, 2), 0)
    with pytest.raises(ValueError):
        io.write_wav(tmp_path / "x.wav", codes(4, 2), 2016.5)  # type: ignore[arg-type]
    with io.WavWriter(tmp_path / "y.wav", 2, 1000) as w, pytest.raises(ValueError):
        w.write(codes(4, 3))


def test_read_refuses_non_32_bit_wav(tmp_path: Path) -> None:
    import soundfile as sf

    sf.write(str(tmp_path / "p.wav"), np.zeros((10, 1), dtype=np.int16), 1000, subtype="PCM_16")
    with pytest.raises(ValueError, match="32-bit"):
        io.read_wav(tmp_path / "p.wav")
    with pytest.raises(ValueError, match="32-bit"):
        next(io.iter_wav_blocks(tmp_path / "p.wav"))


# --------------------------------------------------------------------------------------------- sidecar


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["sidecar.walk-pass.json", "sidecar.walk-pass-v1.json", "sidecar.accel-v1.json"])
def test_examples_validate_and_round_trip(tmp_path: Path, name: str) -> None:
    doc = example(name)
    assert io.validate_sidecar(doc, SCHEMA) == []
    io.save_sidecar(tmp_path / "s.json", doc, SCHEMA)
    assert io.load_sidecar(tmp_path / "s.json", SCHEMA) == doc
    assert list(tmp_path.glob("*.tmp")) == []  # the atomic write leaves no temp file


def test_v0_has_no_v1_fields_and_v1_needs_them() -> None:
    v0 = example("sidecar.walk-pass.json")
    assert v0["schema"] == 0
    v0["loss"] = {"device": 0, "link": 0, "host": 0}
    assert io.validate_sidecar(v0, SCHEMA)  # v0 may not carry v1 fields
    v1 = example("sidecar.walk-pass-v1.json")
    del v1["loss"]
    assert any("loss" in m for m in io.validate_sidecar(v1, SCHEMA))


def test_save_refuses_invalid_sidecar_and_writes_nothing(tmp_path: Path) -> None:
    doc = example("sidecar.walk-pass-v1.json")
    doc["session"] = "Not A Session"
    with pytest.raises(ValueError, match="invalid sidecar"):
        io.save_sidecar(tmp_path / "s.json", doc, SCHEMA)
    assert list(tmp_path.iterdir()) == []


def test_label_person_must_be_a_pseudonym() -> None:
    doc = example("sidecar.walk-pass-v1.json")
    doc["labels"][1]["person"] = "Alice"
    assert any("person" in m for m in io.validate_sidecar(doc, SCHEMA))


def test_find_schema_walks_up_and_fails_cleanly(tmp_path: Path) -> None:
    assert io.find_schema(HERE) == SCHEMA.resolve()
    with pytest.raises(FileNotFoundError):
        io.find_schema(tmp_path)


def test_rzlab_notes_round_trip() -> None:
    text = io.format_rzlab_notes({"floor": "2", "frames": "600000"})
    assert text == "rzlab: floor=2; frames=600000"
    assert io.parse_rzlab_notes("hello\n" + text + "\nrzlab: loss=incomplete") == {
        "floor": "2",
        "frames": "600000",
        "loss": "incomplete",
    }
    assert io.parse_rzlab_notes(None) == {} and io.format_rzlab_notes({}) == ""
    with pytest.raises(ValueError):
        io.format_rzlab_notes({"a": "b;c"})


# ----------------------------------------------------------------------------------------- the pair


def make_pair(tmp_path: Path, n: int = 4000) -> tuple[Path, dict]:
    doc = example("sidecar.walk-pass-v1.json")
    doc["notes"] = f"rzlab: frames={n}"
    wav = tmp_path / f"{doc['session']}.adc.wav"
    io.write_wav(wav, codes(n, 2), doc["sample_rate"])
    return wav, doc


def test_pair_consistent(tmp_path: Path) -> None:
    wav, doc = make_pair(tmp_path, 200_000)
    assert io.check_pair(wav, doc, SCHEMA) == []


def test_pair_flags_channels_rate_frames_and_labels(tmp_path: Path) -> None:
    wav, doc = make_pair(tmp_path, 4000)
    bad = copy.deepcopy(doc)
    bad["channels"] = bad["channels"][:1]
    assert any("channels" in m for m in io.check_pair(wav, bad, SCHEMA))
    bad = copy.deepcopy(doc)
    bad["sample_rate"], bad["sample_rate_measured"] = 2000, 2000.2
    assert any("header rate" in m for m in io.check_pair(wav, bad, SCHEMA))
    bad = copy.deepcopy(doc)
    bad["sample_rate_measured"] = 2010.0
    assert any("round(sample_rate_measured" in m for m in io.check_pair(wav, bad, SCHEMA))
    bad = copy.deepcopy(doc)
    bad["notes"] = "rzlab: frames=3999"
    assert any("frames" in m for m in io.check_pair(wav, bad, SCHEMA))
    # the example's labels run to 160776, far past the 4000-frame file
    problems = io.check_pair(wav, doc, SCHEMA)
    assert sum("after the end of the file" in m for m in problems) == 2
    bad = copy.deepcopy(doc)
    bad["labels"] = [{"t0": 0.5, "t1": 1.0, "i0": 1008, "i1": 2016, "src": "key", "label": "walk"}]
    assert io.check_pair(wav, bad, SCHEMA) == []
    bad["labels"][0]["t0"] = 0.4
    assert any("is not index" in m for m in io.check_pair(wav, bad, SCHEMA))
    bad["labels"][0].update(t0=0.5, i1=900)
    assert any("before i0" in m for m in io.check_pair(wav, bad, SCHEMA))


def test_pair_flags_name_mismatch_and_unreadable_wav(tmp_path: Path) -> None:
    wav, doc = make_pair(tmp_path, 100)
    other = tmp_path / "2026-01-01_x_y_01.adc.wav"
    wav.rename(other)
    assert any("does not start with" in m for m in io.check_pair(other, doc, SCHEMA))
    junk = tmp_path / f"{doc['session']}.accel.wav"
    junk.write_bytes(b"not a wav")
    assert any(m.startswith("wav: cannot read") for m in io.check_pair(junk, doc, SCHEMA))
