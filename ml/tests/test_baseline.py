"""Baseline classifier and evaluation: group splits without overlap, majority baseline, determinism (D-021)."""

from __future__ import annotations

import numpy as np
import pytest

from rezonating_ml import baseline as B


def _dataset(seed: int, sep: float, n_sessions: int = 4, n_per: int = 20, n_people: int = 3):
    """``n_people`` classes, each walking in every session; class means ``sep`` apart in 4 features.

    Session ids are ``S1..Sn`` and shared by all people (a session = one recording day).
    """
    rng = np.random.default_rng(seed)
    X, y, sess, person = [], [], [], []
    for p in range(n_people):
        for s in range(n_sessions):
            mean = np.zeros(4)
            mean[p % 4] = sep
            X.append(rng.normal(mean, 1.0, size=(n_per, 4)))
            y += [f"P{p + 1}"] * n_per
            sess += [f"S{s + 1}"] * n_per
            person += [f"P{p + 1}"] * n_per
    return np.vstack(X).astype(np.float32), np.array(y), np.array(sess), np.array(person)


def test_split_has_no_overlap_and_covers_all() -> None:
    g = np.repeat(["a", "b", "c", "d", "e"], 7)
    tr, te = B.split_by_group(g, fraction=0.4, seed=3)
    assert set(g[tr]).isdisjoint(g[te])
    assert sorted(np.concatenate([tr, te]).tolist()) == list(range(g.size))
    assert len(set(g[te])) == 2


def test_split_explicit_groups_and_seed() -> None:
    g = np.repeat(["S1", "S2", "S3"], 4)
    tr, te = B.split_by_group(g, test_groups=["S2"])
    assert set(g[te]) == {"S2"} and set(g[tr]) == {"S1", "S3"}
    a = B.split_by_group(np.repeat(list("abcdefgh"), 3), fraction=0.5, seed=11)
    b = B.split_by_group(np.repeat(list("abcdefgh"), 3), fraction=0.5, seed=11)
    assert all(np.array_equal(u, v) for u, v in zip(a, b, strict=True))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"test_groups": ["S9"]},  # unknown group
        {"test_groups": ["S1", "S2"]},  # nothing left to train on
        {"fraction": 1.0},
        {"fraction": 0.0},
        {},  # neither
        {"test_groups": ["S1"], "fraction": 0.5},  # both
    ],
)
def test_split_refuses(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        B.split_by_group(np.repeat(["S1", "S2"], 3), **kwargs)


@pytest.mark.parametrize(
    ("groups", "test_groups"),
    [
        (["S1", "S2", "S3"], ["S10"]),  # longer than every id: a cast to <U2 would make it "S1"
        (["P1", "P2", "P3"], ["P1x"]),  # would become "P1"
        ([1, 2, 3], [1.7]),  # a cast to int would make it 1
        (["S1", "S2", "S3"], ["S2", "S10"]),  # one known id does not excuse an unknown one
    ],
)
def test_split_refuses_ids_that_only_match_after_a_cast(groups: list, test_groups: list) -> None:
    with pytest.raises(ValueError, match="not in groups"):
        B.split_by_group(np.repeat(groups, 3), test_groups=test_groups)


def test_split_accepts_equal_ids_of_another_type() -> None:
    """Equal values match (numpy scalars, 2.0 for group 2); only truncation or rounding is refused."""
    _, te = B.split_by_group(np.repeat([1, 2, 3], 2), test_groups=[2.0, np.int64(3)])
    assert te.tolist() == [2, 3, 4, 5]
    _, te = B.split_by_group(np.repeat(["S1", "S2", "S10"], 2), test_groups=iter([np.str_("S10")]))
    assert te.tolist() == [4, 5]


def test_split_refuses_single_group() -> None:
    with pytest.raises(ValueError):
        B.split_by_group(["S1"] * 5, fraction=0.5)


def test_result_refuses_overlap_or_missing_baseline() -> None:
    s = B.Scores(1.0, 1.0, [[1]], {}, {})
    common = dict(split="session", model="logreg", seed=0, labels=["P1"], n_train=1, n_test=1, scores=s)
    with pytest.raises(ValueError):
        B.EvalResult(**common, train_groups=["S1"], test_groups=["S1"], baseline=s)
    with pytest.raises(ValueError):
        B.EvalResult(**common, train_groups=["S1"], test_groups=["S2"], baseline=None)


@pytest.mark.parametrize("model", B.MODELS)
def test_separable_classes_beat_baseline(model: str) -> None:
    X, y, sess, person = _dataset(seed=1, sep=6.0)
    r = B.evaluate(X, y, {"session": sess, "person": person}, split="session", seed=0, model=model, test_groups=["S4"])
    assert r.test_groups == ["S4"] and r.train_groups == ["S1", "S2", "S3"]
    assert r.n_test == 60 and r.n_train == 180
    assert r.scores.accuracy > 0.95 and r.scores.balanced_accuracy > 0.95
    assert r.baseline.accuracy == pytest.approx(1 / 3) and r.baseline.balanced_accuracy == pytest.approx(1 / 3)
    assert r.beats_baseline
    assert r.flags == ["only one test session: no spread across sessions"]
    cm = np.array(r.scores.confusion)
    assert cm.shape == (3, 3) and cm.sum() == 60 and np.trace(cm) == round(60 * r.scores.accuracy)
    assert r.labels == ["P1", "P2", "P3"] and set(r.scores.per_class) == {"P1", "P2", "P3"}
    assert r.scores.per_class["P2"]["support"] == 20
    assert set(r.scores.per_group) == {"S4"}
    assert "majority baseline" in r.summary()
    d = r.as_dict()
    assert d["baseline"]["accuracy"] == pytest.approx(1 / 3) and d["beats_baseline"] is True


def test_uninformative_features_do_not_beat_baseline_and_are_flagged() -> None:
    """Constant features: the model can only predict one class, so it ties the majority baseline at best."""
    _, y, sess, _ = _dataset(seed=2, sep=0.0, n_sessions=6)
    y = np.where(np.arange(y.size) % 4 == 0, "P2", "P1")  # 75 % P1 in every session
    X = np.ones((y.size, 4), dtype=np.float32)
    r = B.evaluate(X, y, sess, split="session", seed=0, model="logreg", test_groups=["S1", "S2"])
    assert r.baseline.accuracy == pytest.approx(0.75) and r.baseline.balanced_accuracy == pytest.approx(0.5)
    assert not r.beats_baseline
    assert any("does not beat" in f for f in r.flags)


def test_deterministic_with_seed() -> None:
    X, y, sess, _ = _dataset(seed=3, sep=1.0, n_sessions=5)
    a = B.evaluate(X, y, sess, seed=5, model="rf", test_fraction=0.4)
    b = B.evaluate(X, y, sess, seed=5, model="rf", test_fraction=0.4)
    assert a.as_dict() == b.as_dict()
    assert len(a.test_groups) == 2


def test_person_split_refuses_person_labels() -> None:
    X, y, sess, person = _dataset(seed=4, sep=6.0)
    with pytest.raises(ValueError, match="never seen in training"):
        B.evaluate(X, y, {"session": sess, "person": person}, split="person", seed=0, test_groups=["P3"])


def test_person_split_for_a_non_identity_label() -> None:
    """A split by person is valid when the label is not the person (e.g. step vs not-step)."""
    X, _, sess, person = _dataset(seed=5, sep=0.0)
    y = np.where(np.arange(len(person)) % 2 == 0, "step", "other")
    X = X.copy()
    X[y == "step", 0] += 6.0
    r = B.evaluate(X, y, person, split="person", seed=0, test_groups=["P1"])
    assert r.split == "person" and r.test_groups == ["P1"] and r.beats_baseline


def test_bad_arguments() -> None:
    X, y, sess, _ = _dataset(seed=6, sep=1.0)
    with pytest.raises(ValueError):
        B.evaluate(X, y, sess, split="window")
    with pytest.raises(ValueError):
        B.evaluate(X, y, sess, model="svm")
    with pytest.raises(ValueError):
        B.evaluate(X[:-1], y, sess)
