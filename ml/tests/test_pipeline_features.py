"""Features and model stages of the pack pipeline (D-021 part 3), and the single-channel count-only warning."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pytest

from rezonating_ml.baseline import train_baseline_model
from rezonating_ml.features import N_FEATURES, event_features
from rezonating_ml.pipeline import (
    NOT_AVAILABLE,
    ModelOutput,
    build_pipeline,
    concat_outputs,
    run_pipeline,
    valid_from_zero_fill,
    zero_fill_mask,
)
from rezonating_ml.vectors import synthetic_footstep_clip

FOOTSTEP = Path(__file__).resolve().parents[2] / "packs" / "footstep-id" / "pack.json"


def _chunked(x, valid=None, sizes=(1, 7, 333, 1024), model=None):
    pipe = build_pipeline(FOOTSTEP, model=model)
    outs, i, k = [], 0, 0
    while i < x.size:
        n = sizes[k % len(sizes)]
        outs.append(pipe.process(x[i : i + n], None if valid is None else valid[i : i + n]))
        i, k = i + n, k + 1
    outs.append(pipe.finish())
    return pipe, concat_outputs(outs)


def _assert_features_same(a, b):
    assert a.feature_windows == b.feature_windows
    assert a.features.dtype == b.features.dtype == np.float32
    assert a.features.tobytes() == b.features.tobytes()
    assert a.model == b.model


def _lose_in(x, pipe, k):
    """Mark the raw sample that reaches decimated index ``k`` lost (zero-filled)."""
    raw = int(pipe.to_input_index(k)) + 30
    valid = np.ones(x.size, dtype=bool)
    valid[raw] = False
    x2 = x.copy()
    x2[raw] = 0.0
    return x2, valid


def _tiny_model(seed=0):
    """A logreg on fixed synthetic footstep_v1-shaped rows: three classes, deterministic for the seed."""
    rng = np.random.default_rng(123)
    X = rng.normal(0.0, 1.0, (60, N_FEATURES)).astype(np.float32)
    y = np.array(["P1", "P2", "P3"] * 20)
    X[y == "P2", 0] += 3.0
    X[y == "P3", 12] += 3.0
    return train_baseline_model(X, y, seed=seed)


def test_features_are_footstep_v1_on_the_complete_valid_windows():
    x, _ = synthetic_footstep_clip()
    out = run_pipeline(FOOTSTEP, x)
    assert out.stage("features").status == "ok"
    ref, kept = event_features(out.filtered, out.events, 1000.0)  # batch filtered signal, the reference
    assert len(kept) >= 3
    assert [(e.onset, e.start, e.end) for e in out.feature_windows] == [(e.onset, e.start, e.end) for e in kept]
    assert all(w.n_invalid == 0 for w in out.feature_windows)
    assert out.features.shape == (len(kept), N_FEATURES) and out.features.dtype == np.float32
    assert out.features.tobytes() == ref.tobytes()


def test_invalid_windows_are_skipped_and_counted():
    x, _ = synthetic_footstep_clip()
    clean = run_pipeline(FOOTSTEP, x)
    target = clean.feature_windows[1]
    pipe = build_pipeline(FOOTSTEP)
    x2, valid = _lose_in(x, pipe, target.onset + 50)
    out = concat_outputs([pipe.process(x2, valid), pipe.finish()])
    assert target.onset not in [w.onset for w in out.feature_windows]
    assert len(out.feature_windows) == len(clean.feature_windows) - 1
    assert pipe.n_windows_skipped_invalid == pipe.n_windows_invalid >= 1
    assert pipe.n_windows_featured + pipe.n_windows_skipped_invalid == pipe.n_windows == pipe.n_events
    # the loss also shifts the filter state after it, so the reference is this run's own filtered signal
    keep = [e for e in out.windows if e.n_invalid == 0]
    ref, _ = event_features(out.filtered, keep, 1000.0)
    assert out.features.tobytes() == ref.tobytes()


def test_window_cut_by_the_end_of_the_stream_is_skipped_and_counted():
    x, _ = synthetic_footstep_clip()
    clean = run_pipeline(FOOTSTEP, x)
    last = clean.feature_windows[-1]
    n_raw = int(build_pipeline(FOOTSTEP).to_input_index(last.onset + 100)) + 30  # stop inside the post window
    pipe = build_pipeline(FOOTSTEP)
    pipe.process(x[:n_raw])
    end = pipe.finish()
    assert [w.onset for w in end.windows] == [last.onset] and end.windows[0].n_invalid > 0
    assert end.features.shape == (0, N_FEATURES) and end.feature_windows == ()
    assert pipe.n_windows_skipped_invalid == pipe.n_windows_cut == 1


@pytest.mark.parametrize("sizes", [(1,), (7, 333), (1024, 1, 5000)])
def test_chunked_features_are_byte_identical_to_batch(sizes):
    x, _ = synthetic_footstep_clip()
    pipe0 = build_pipeline(FOOTSTEP)
    x2, valid = _lose_in(x, pipe0, run_pipeline(FOOTSTEP, x).feature_windows[0].onset + 20)
    batch = run_pipeline(FOOTSTEP, x2, valid=valid)
    pipe, chunked = _chunked(x2, valid, sizes)
    _assert_features_same(chunked, batch)
    assert pipe.n_windows_skipped_invalid == 1
    assert pipe._hist.size == 0  # finish() drops the history


def test_filtered_history_stays_bounded():
    x, _ = synthetic_footstep_clip()
    pipe = build_pipeline(FOOTSTEP)
    longest = 0
    for i in range(0, x.size, 100):
        pipe.process(x[i : i + 100])
        longest = max(longest, pipe._hist.size)
    n_win = pipe._trigger.n_pre + pipe._trigger.n_post
    assert longest <= n_win + 100  # one open window plus one chunk, never the whole stream


def test_model_stage_without_a_model_is_not_available():
    out = run_pipeline(FOOTSTEP, synthetic_footstep_clip()[0])
    st = out.stage("model")
    assert st.status == NOT_AVAILABLE
    assert st.detail == "no model loaded (pack names model.tflite; TFLite export comes later)"
    assert out.model is None and out.features is not None


def test_model_stage_gives_deterministic_labels_and_probabilities():
    x, _ = synthetic_footstep_clip()
    model = _tiny_model()
    out = run_pipeline(FOOTSTEP, x, model=model)
    assert out.stage("model").status == "ok" and "P1" in out.stage("model").detail
    m = out.model
    assert isinstance(m, ModelOutput) and m.classes == ("P1", "P2", "P3")
    assert len(m.labels) == len(out.feature_windows) == m.proba.shape[0] >= 3
    assert m.proba.dtype == np.float32 and m.proba.shape[1] == 3
    np.testing.assert_allclose(m.proba.sum(axis=1), 1.0, rtol=1e-6)
    expected = model.predict_proba(out.features).astype(np.float32)
    np.testing.assert_allclose(m.proba, expected, rtol=1e-6, atol=1e-7)
    assert list(m.labels) == [str(v) for v in model.predict(out.features)]
    # same seed, same data: the same model and byte-identical outputs; chunked as well
    again = run_pipeline(FOOTSTEP, x, model=_tiny_model())
    assert again.model == m
    _, chunked = _chunked(x, model=model)
    _assert_features_same(chunked, out)


def test_model_needs_the_classifier_interface_and_13_features():
    with pytest.raises(TypeError, match="predict_proba"):
        build_pipeline(FOOTSTEP, model=object())
    rng = np.random.default_rng(0)
    narrow = train_baseline_model(rng.normal(size=(20, 5)), np.array(["a", "b"] * 10), seed=0)
    with pytest.raises(ValueError, match="takes 5 features"):
        build_pipeline(FOOTSTEP, model=narrow)


def test_model_without_features_is_not_available():
    pack = json.loads(FOOTSTEP.read_text(encoding="utf-8"))
    out = run_pipeline({**pack, "features": "other_v1"}, synthetic_footstep_clip()[0], model=_tiny_model())
    assert out.stage("model").status == NOT_AVAILABLE and out.model is None


def test_train_baseline_model_is_deterministic_and_checks_inputs():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(40, N_FEATURES)).astype(np.float32)
    y = np.array(["P1", "P2"] * 20)
    a = train_baseline_model(X, y, seed=3, model="rf")
    b = train_baseline_model(X, y, seed=3, model="rf")
    assert a.predict_proba(X).tobytes() == b.predict_proba(X).tobytes()
    assert list(a.classes_) == ["P1", "P2"]
    with pytest.raises(ValueError, match="2 classes"):
        train_baseline_model(X, np.array(["P1"] * 40), seed=0)
    with pytest.raises(ValueError, match="need X"):
        train_baseline_model(X[:, 0], y, seed=0)
    with pytest.raises(ValueError, match="model must be"):
        train_baseline_model(X, y, seed=0, model="svm")


# ------------------------------------------------------------- single channel: count-only masks warn


def _one_channel_count_only():
    rng = np.random.default_rng(6)
    ch = np.round(rng.normal(0, 20.0, 40_000)).astype(np.int32)  # isolated chance zeros
    ch[10_000:10_040] = 0  # a 40-frame loss
    return ch


def test_single_channel_count_only_mask_warns():
    ch = _one_channel_count_only()
    with pytest.warns(UserWarning, match="covers_all_lost is False") as rec:
        m = zero_fill_mask(ch, expected_lost=40)
    assert not m.covers_all_lost and rec[0].filename == __file__  # points at the caller
    with pytest.warns(UserWarning, match="backed by the count only") as rec:
        valid = valid_from_zero_fill(ch, expected_lost=40)
    assert rec[0].filename == __file__
    assert valid.tobytes() == m.valid.tobytes()


def test_covering_single_channel_mask_does_not_warn():
    ch = _one_channel_count_only()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        m = zero_fill_mask(ch, min_run=1, expected_lost=40)
        zero_fill_mask(ch, expected_lost=0)
    assert m.covers_all_lost
