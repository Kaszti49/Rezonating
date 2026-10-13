"""The firmware test vectors in ml/tests/vectors/ match the current code (D-016, D-021)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from rezonating_ml.dsp import DECIM_FIR_TAPS
from rezonating_ml.vectors import (
    FOOTSTEP_ID_DSP,
    FOOTSTEP_ID_TRIGGER,
    VECTOR_FILES,
    check_vectors,
    default_vector_dir,
    main,
    write_vectors,
)

VEC_DIR = Path(__file__).resolve().parent / "vectors"
PACK = Path(__file__).resolve().parents[2] / "packs" / "footstep-id" / "pack.json"


def test_default_dir_is_this_folder():
    assert default_vector_dir() == VEC_DIR


def test_committed_vectors_match_the_code():
    assert check_vectors(VEC_DIR) == [], "run: python -m rezonating_ml.vectors --write (and tell firmware)"


def test_vector_files_are_self_describing():
    for name in VECTOR_FILES:
        v = json.loads((VEC_DIR / name).read_text(encoding="utf-8"))
        assert {"name", "description", "generator", "clip", "tolerance", "input", "expected"} <= set(v)
    dec = json.loads((VEC_DIR / "decimator_fir.json").read_text(encoding="utf-8"))
    assert np.array_equal(np.asarray(dec["taps"]).astype(np.float32), DECIM_FIR_TAPS)
    assert len(dec["expected"]) == len(dec["input"]) // 2 and dec["raw_offset"] == -30
    sta = json.loads((VEC_DIR / "sta_lta.json").read_text(encoding="utf-8"))
    assert len(sta["expected"]["events"]) == 4 and sta["threshold_margin_rel"] >= 1e-3


def test_vectors_use_the_pack_settings():
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    msg = "footstep-id pack was tuned: update FOOTSTEP_ID_* in rezonating_ml.vectors, regenerate, tell firmware"
    assert pack["dsp"] == FOOTSTEP_ID_DSP, msg
    assert pack["trigger"] == FOOTSTEP_ID_TRIGGER, msg


def test_regenerate_and_check_round_trip(tmp_path):
    write_vectors(tmp_path)
    assert check_vectors(tmp_path) == []
    assert main(["--check", "--dir", str(tmp_path)]) == 0
    (tmp_path / "sta_lta.json").unlink()
    assert main(["--check", "--dir", str(tmp_path)]) == 1


def test_tolerances_cover_an_fma_build_with_headroom():
    """Finding F-261013-537e: each stored tolerance is >= 10x what a fused-multiply-add build would deviate."""
    from rezonating_ml.dsp import filter_chain_from_pack
    from rezonating_ml.vectors import _biquad_alt, _fir_alt, _ratio_alt

    dec = json.loads((VEC_DIR / "decimator_fir.json").read_text(encoding="utf-8"))
    x = np.asarray(dec["input"], dtype=np.float32)
    valid = np.asarray(dec["valid"], dtype=bool)
    exp = np.asarray(dec["expected"]).astype(np.float32)
    fused, _ = _fir_alt(x, ~valid)
    assert np.max(np.abs(fused.astype(np.float64) - exp)) * 10 <= dec["tolerance"]["abs"] * 1.0001

    dsp = json.loads((VEC_DIR / "dsp_biquads.json").read_text(encoding="utf-8"))
    sec_in = np.asarray(dsp["input"]).astype(np.float32)
    for c, exp_s in zip(filter_chain_from_pack(dsp["dsp"], dsp["fs_hz"]).sections, dsp["expected"], strict=True):
        exp_s = np.asarray(exp_s).astype(np.float32)
        fused, _ = _biquad_alt(c, sec_in)
        assert np.max(np.abs(fused.astype(np.float64) - exp_s)) * 10 <= dsp["tolerance"]["abs"] * 1.0001
        sec_in = exp_s
    # The verifier's gcc -mfma -ffp-contract=fast build deviated by 0.01813; it must now sit well inside.
    assert dsp["tolerance"]["abs"] >= 10 * 0.01813

    # masked case: the skip rule means the same recurrences over the valid samples only
    valid = np.asarray(dsp["masked"]["valid"], dtype=bool)
    sec_in = np.asarray(dsp["input"]).astype(np.float32)[valid]
    for c, exp_s in zip(
        filter_chain_from_pack(dsp["dsp"], dsp["fs_hz"]).sections, dsp["masked"]["expected"], strict=True
    ):
        exp_s = np.asarray(exp_s).astype(np.float32)[valid]
        fused, _ = _biquad_alt(c, sec_in)
        assert np.max(np.abs(fused.astype(np.float64) - exp_s)) * 10 <= dsp["tolerance"]["abs"] * 1.0001
        sec_in = exp_s

    sta = json.loads((VEC_DIR / "sta_lta.json").read_text(encoding="utf-8"))
    r = np.asarray(sta["expected"]["ratio"]).astype(np.float32).astype(np.float64)
    fused, _ = _ratio_alt(np.asarray(sta["input"]).astype(np.float32), 50, 2000)
    rel = np.max(np.abs(fused - r) / np.maximum(np.abs(r), 1.0))
    assert rel * 10 <= sta["tolerance"]["rel"] * 1.0001
    assert sta["threshold_margin_rel"] >= sta["tolerance"]["rel"]
    valid = np.asarray(sta["masked"]["valid"], dtype=bool)
    r = np.asarray(sta["masked"]["expected"]["ratio"]).astype(np.float32).astype(np.float64)[valid]
    fused, _ = _ratio_alt(np.asarray(sta["input"]).astype(np.float32)[: valid.size][valid], 50, 2000)
    assert np.max(np.abs(fused - r) / np.maximum(np.abs(r), 1.0)) * 10 <= sta["tolerance"]["rel"] * 1.0001
    assert sta["masked"]["threshold_margin_rel"] >= sta["tolerance"]["rel"]


def test_vectors_state_build_flags_lost_samples_and_index_width():
    for name in VECTOR_FILES:
        v = json.loads((VEC_DIR / name).read_text(encoding="utf-8"))
        assert "-ffp-contract=off" in v["build"]
    dec = json.loads((VEC_DIR / "decimator_fir.json").read_text(encoding="utf-8"))
    assert "64-bit" in dec["description"]
    lost = ~np.asarray(dec["valid"])
    ref_invalid = [lost[max(0, 2 * k + 1 - 62) : 2 * k + 2].any() for k in range(len(dec["expected"]))]
    assert dec["expected_valid"] == [not b for b in ref_invalid]  # FIR window rule, independent of the code
    assert lost.sum() == 53 and sum(ref_invalid) == 181
    assert len(dec["expected_codes"]) == len(dec["expected"]) and all(isinstance(c, int) for c in dec["expected_codes"])
    assert all(float(v).is_integer() for v in dec["input"])  # ADC codes
    sta = json.loads((VEC_DIR / "sta_lta.json").read_text(encoding="utf-8"))
    assert "64-bit" in sta["description"] and "quiet_until" in sta["description"]


# ------------------------------------------- lost samples in every vector (verify-3 finding 3: no masks for C)


def _lost_runs(valid: list[bool]) -> list[tuple[int, int]]:
    lost = ~np.asarray(valid, dtype=bool)
    edges = np.flatnonzero(np.diff(np.concatenate([[0], lost.astype(np.int8), [0]])))
    return list(zip(edges[::2].tolist(), edges[1::2].tolist(), strict=True))


def test_decimator_vector_has_short_losses_and_one_before_the_first_good_sample():
    dec = json.loads((VEC_DIR / "decimator_fir.json").read_text(encoding="utf-8"))
    runs = _lost_runs(dec["valid"])
    lengths = {b - a for a, b in runs}
    assert runs[0][0] == 0 and {1, 2, 7, 40} <= lengths and all(n <= 7 or n == 40 for n in lengths)
    assert all(dec["input"][i] == 0 for a, b in runs for i in range(a, b))  # zeros, as a WAV stores them
    assert dec["expected_valid"][:32] == [False] * 32  # FIR windows reaching raw 0..2
    # "0 if none yet": holding the first good sample backwards instead would move those outputs far outside the
    # tolerance, so the vector tells the two apart.
    x = np.asarray(dec["input"], dtype=np.float64)
    first_good = runs[0][1]
    x_backfill = x.copy()
    x_backfill[:first_good] = x[first_good]
    h = DECIM_FIR_TAPS.astype(np.float64)
    y = np.convolve(x_backfill, h)[1 : 2 * 32 : 2]  # outputs k = 0..31 at raw 2k + 1
    exp = np.asarray(dec["expected"][:32], dtype=np.float64)
    assert np.max(np.abs(y - exp)) > 100 * dec["tolerance"]["abs"]


def test_dsp_vector_has_a_masked_case():
    dsp = json.loads((VEC_DIR / "dsp_biquads.json").read_text(encoding="utf-8"))
    valid = dsp["masked"]["valid"]
    assert len(valid) == len(dsp["input"])
    runs = _lost_runs(valid)
    assert runs[0][0] == 0 and {1, 7} <= {b - a for a, b in runs}
    for exp in dsp["masked"]["expected"]:
        assert all(exp[i] == 0 for a, b in runs for i in range(a, b))  # output 0 where skipped
    assert any(dsp["input"][i] != 0 for a, b in runs for i in range(a, b))  # the input there is ignored, not 0
    # after the first lost run the masked output differs from the unmasked one (the state skipped samples)
    assert dsp["masked"]["expected"][1][1000] != dsp["expected"][1][1000]


def test_sta_lta_vector_has_a_masked_case_with_window_n_invalid():
    sta = json.loads((VEC_DIR / "sta_lta.json").read_text(encoding="utf-8"))
    m = sta["masked"]
    n = len(m["valid"])
    runs = _lost_runs(m["valid"])
    assert runs[0][0] == 0 and {1, 3, 5, 7} <= {b - a for a, b in runs} and n < len(sta["input"])
    events, windows = m["expected"]["events"], m["expected"]["windows"]
    assert [(e["onset"], e["start"], e["end"]) for e in events] == [(w["onset"], w["start"], w["end"]) for w in windows]
    assert all("n_invalid" not in e for e in events)
    assert events[0]["onset"] != sta["expected"]["events"][0]["onset"]  # a lost run over the onset moves it
    n_invalid = [w["n_invalid"] for w in windows]
    assert 0 in n_invalid and any(0 < k < 10 for k in n_invalid)  # a clean window and ones with short losses
    assert windows[-1]["end"] > n and n_invalid[-1] >= windows[-1]["end"] - n  # cut by the end of the stream
    assert all(m["expected"]["ratio"][i] == 0 for a, b in runs for i in range(a, b))


def test_check_vectors_catches_wrong_masked_cases(tmp_path):
    write_vectors(tmp_path)
    sta = json.loads((tmp_path / "sta_lta.json").read_text(encoding="utf-8"))
    sta["masked"]["expected"]["windows"][0]["n_invalid"] += 1
    (tmp_path / "sta_lta.json").write_text(json.dumps(sta), encoding="utf-8")
    dsp = json.loads((tmp_path / "dsp_biquads.json").read_text(encoding="utf-8"))
    dsp["masked"]["expected"][0][0] = 1.0  # an invalid sample's output must stay 0
    (tmp_path / "dsp_biquads.json").write_text(json.dumps(dsp), encoding="utf-8")
    problems = check_vectors(tmp_path)
    assert any("sta_lta.json masked: windows differ" in p for p in problems)
    assert any("dsp_biquads.json masked section 0" in p for p in problems)
    del dsp["masked"]
    (tmp_path / "dsp_biquads.json").write_text(json.dumps(dsp), encoding="utf-8")
    assert "dsp_biquads.json: no masked case" in check_vectors(tmp_path)
